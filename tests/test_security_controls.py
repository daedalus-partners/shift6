from __future__ import annotations

import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")

from app.main import app
from app.prompt_paths import PROMPT_DIR, prompt_path, validate_client_slug
from app.security import IdempotencyRegistry, SecurityBoundaryMiddleware


def test_production_without_auth_remains_public(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "none")
    with TestClient(app) as client:
        response = client.get("/docs")
    assert response.status_code == 200


def test_api_key_mode_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "api_key")
    monkeypatch.setenv("SHIFT6_API_KEY", "test-secret")
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 401
        assert client.get("/docs", headers={"X-Shift6-API-Key": "test-secret"}).status_code == 200


def test_health_remains_available_for_service_monitoring(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "none")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_prompt_paths_are_slug_restricted_and_contained():
    assert validate_client_slug("acme-client") == "acme-client"
    assert validate_client_slug("UPPER") == "upper"
    assert prompt_path("acme-client").parent == PROMPT_DIR
    for value in ("../secret", "a/b", "a..b"):
        try:
            prompt_path(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe slug accepted: {value}")


@pytest.mark.asyncio
async def test_idempotency_registry_rejects_duplicate_claims():
    registry = IdempotencyRegistry()
    assert await registry.claim("principal:path:request-key")
    assert not await registry.claim("principal:path:request-key")


def test_cached_browser_can_call_expensive_route_without_idempotency_header(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "none")
    compatibility_app = FastAPI()
    compatibility_app.add_middleware(SecurityBoundaryMiddleware)

    @compatibility_app.post("/api/v1/email/summarize")
    async def summarize_fixture():
        return {"status": "accepted"}

    with TestClient(compatibility_app) as client:
        response = client.post("/api/v1/email/summarize")
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


def test_supplied_idempotency_key_still_rejects_duplicate(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "none")
    compatibility_app = FastAPI()
    compatibility_app.add_middleware(SecurityBoundaryMiddleware)

    @compatibility_app.post("/api/v1/email/summarize")
    async def summarize_fixture():
        return {"status": "accepted"}

    headers = {"Idempotency-Key": "cached-browser-test-key"}
    with TestClient(compatibility_app) as client:
        assert client.post("/api/v1/email/summarize", headers=headers).status_code == 200
        assert client.post("/api/v1/email/summarize", headers=headers).status_code == 409
