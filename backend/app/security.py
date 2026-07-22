from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


logger = logging.getLogger(__name__)
PUBLIC_PATHS = {"/", "/health", "/api/v1/email/health"}
EXPENSIVE_PATHS = (
    "/generate",
    "/retrieval/",
    "/api/v1/email/summarize",
    "/api/v1/tasks/chat",
    "/api/v1/coverage/scan",
    "/api/v1/coverage/sheets/import",
    "/api/v1/search/run-due",
)
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
EXPENSIVE_RATE_LIMIT_PER_MINUTE = int(os.getenv("EXPENSIVE_RATE_LIMIT_PER_MINUTE", "12"))
MAX_EXPENSIVE_CONCURRENCY = int(os.getenv("MAX_EXPENSIVE_CONCURRENCY", "3"))
_expensive_slots = asyncio.Semaphore(MAX_EXPENSIVE_CONCURRENCY)


@dataclass(frozen=True)
class Principal:
    subject: str
    mode: str


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = 2048):
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        async with self._lock:
            events = self._events.setdefault(key, deque())
            self._events.move_to_end(key)
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            while len(self._events) > self._max_keys:
                self._events.popitem(last=False)
            return True


_limiter = SlidingWindowLimiter()
_jwks_clients: dict[str, object] = {}


class IdempotencyRegistry:
    def __init__(self, max_entries: int = 4096, ttl_seconds: int = 600):
        self._entries: OrderedDict[str, float] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds

    async def claim(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            while self._entries and next(iter(self._entries.values())) <= now - self._ttl_seconds:
                self._entries.popitem(last=False)
            if key in self._entries:
                return False
            self._entries[key] = now
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return True


_idempotency = IdempotencyRegistry()


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"prod", "production"}


def _cloudflare_principal(assertion: str) -> Principal:
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - deployment configuration failure
        raise RuntimeError("PyJWT is required for Cloudflare Access authentication") from exc

    team_domain = os.getenv("CF_ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
    audience = os.getenv("CF_ACCESS_AUDIENCE", "").strip()
    if not team_domain or not audience:
        raise RuntimeError("CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUDIENCE must be configured")
    if not team_domain.startswith("https://"):
        team_domain = f"https://{team_domain}"
    issuer = team_domain
    certs_url = f"{team_domain}/cdn-cgi/access/certs"
    client = _jwks_clients.get(certs_url)
    if client is None:
        client = jwt.PyJWKClient(certs_url, cache_keys=True, lifespan=300)
        _jwks_clients[certs_url] = client
    signing_key = client.get_signing_key_from_jwt(assertion)
    claims = jwt.decode(
        assertion,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "iat", "aud", "iss", "sub"]},
    )
    return Principal(subject=str(claims["sub"]), mode="cloudflare_access")


async def authenticate(request: Request) -> Principal | Response:
    mode = os.getenv("AUTH_MODE", "none").strip().lower()
    if request.url.path in PUBLIC_PATHS:
        return Principal(subject="public-health", mode="public")
    if mode == "none":
        if _is_production():
            logger.error("AUTH_MODE=none is prohibited in production")
            return JSONResponse({"detail": "authentication_not_configured"}, status_code=503)
        return Principal(subject="local-development", mode="none")
    if mode == "api_key":
        expected = os.getenv("SHIFT6_API_KEY", "")
        supplied = request.headers.get("x-shift6-api-key", "")
        if not expected:
            logger.error("SHIFT6_API_KEY is missing while AUTH_MODE=api_key")
            return JSONResponse({"detail": "authentication_not_configured"}, status_code=503)
        if not supplied or not secrets.compare_digest(supplied, expected):
            return JSONResponse({"detail": "authentication_required"}, status_code=401)
        return Principal(subject="api-key-user", mode="api_key")
    if mode == "cloudflare_access":
        assertion = request.headers.get("cf-access-jwt-assertion", "")
        if not assertion:
            return JSONResponse({"detail": "authentication_required"}, status_code=401)
        try:
            return await asyncio.to_thread(_cloudflare_principal, assertion)
        except Exception:
            logger.exception("Cloudflare Access token validation failed")
            return JSONResponse({"detail": "invalid_authentication"}, status_code=401)
    logger.error("Unsupported AUTH_MODE=%s", mode)
    return JSONResponse({"detail": "authentication_not_configured"}, status_code=503)


class SecurityBoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        declared_length = request.headers.get("content-length")
        if declared_length:
            try:
                if int(declared_length) > MAX_REQUEST_BYTES:
                    return JSONResponse({"detail": "request_too_large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "invalid_content_length"}, status_code=400)

        identity = await authenticate(request)
        if isinstance(identity, Response):
            return identity
        request.state.principal = identity
        peer = request.client.host if request.client else "unknown"
        expensive = request.method not in {"HEAD", "OPTIONS"} and any(
            request.url.path.startswith(prefix) for prefix in EXPENSIVE_PATHS
        )
        registry_key = None
        if expensive and request.method not in {"GET", "HEAD", "OPTIONS"}:
            idempotency_key = request.headers.get("idempotency-key", "").strip()
            if not (16 <= len(idempotency_key) <= 128):
                return JSONResponse({"detail": "valid_idempotency_key_required"}, status_code=400)
            registry_key = f"{identity.subject}:{request.url.path}:{idempotency_key}"
        limit = EXPENSIVE_RATE_LIMIT_PER_MINUTE if expensive else RATE_LIMIT_PER_MINUTE
        bucket = f"{identity.subject}:{peer}:{'expensive' if expensive else 'standard'}"
        if not await _limiter.allow(bucket, limit):
            return JSONResponse({"detail": "rate_limit_exceeded"}, status_code=429)

        if expensive:
            try:
                await asyncio.wait_for(_expensive_slots.acquire(), timeout=0.05)
            except TimeoutError:
                return JSONResponse({"detail": "server_busy"}, status_code=503)
            try:
                if registry_key and not await _idempotency.claim(registry_key):
                    return JSONResponse({"detail": "duplicate_request"}, status_code=409)
                response = await call_next(request)
            finally:
                _expensive_slots.release()
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response
