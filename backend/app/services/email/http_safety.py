from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class UnsafeUrlError(ValueError):
    pass


class ResponseTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class SafeTextResponse:
    status_code: int
    text: str
    final_url: str
    headers: Mapping[str, str]


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(str(url).strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not scheme or not host:
        raise UnsafeUrlError("URL must include a scheme and hostname")
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit(("https", netloc, path, urlencode(sorted(query)), ""))


def same_source_url(left: str, right: str) -> bool:
    try:
        return canonicalize_url(left) == canonicalize_url(right)
    except (UnsafeUrlError, ValueError):
        return False


async def resolve_addresses(host: str, port: int) -> set[str]:
    def _resolve() -> set[str]:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return {str(info[4][0]) for info in infos}

    try:
        return await asyncio.to_thread(_resolve)
    except socket.gaierror as exc:
        raise UnsafeUrlError("Hostname could not be resolved") from exc


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return bool(address.is_global)


async def validate_public_url(url: str) -> str:
    parsed = urlsplit(str(url).strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("Only HTTP and HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Credentials in URLs are not allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL must include a hostname")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise UnsafeUrlError("Local destinations are not allowed")
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    addresses = await resolve_addresses(host, port)
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise UnsafeUrlError("Destination resolves to a non-public address")
    return str(httpx.URL(url))


def _validate_peer_address(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        raise UnsafeUrlError("Connected peer address could not be verified")
    peer = stream.get_extra_info("server_addr")
    if not isinstance(peer, tuple) or not peer:
        raise UnsafeUrlError("Connected peer address could not be verified")
    if not _is_public_address(str(peer[0])):
        raise UnsafeUrlError("Connected peer is not a public address")


async def safe_get_text(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 20.0,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    client: httpx.AsyncClient | None = None,
) -> SafeTextResponse:
    current = str(url)
    owned_client = client is None
    active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False)
    try:
        for redirect_count in range(max_redirects + 1):
            current = await validate_public_url(current)
            async with active_client.stream("GET", current, headers=dict(headers or {})) as response:
                _validate_peer_address(response)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeUrlError("Redirect response omitted Location")
                    if redirect_count >= max_redirects:
                        raise UnsafeUrlError("Too many redirects")
                    current = urljoin(current, location)
                    continue

                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ResponseTooLargeError("Response exceeds configured size limit")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ResponseTooLargeError("Response exceeds configured size limit")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                body = b"".join(chunks).decode(encoding, errors="replace")
                return SafeTextResponse(response.status_code, body, current, dict(response.headers))
        raise UnsafeUrlError("Redirect limit exceeded")
    finally:
        if owned_client:
            await active_client.aclose()
