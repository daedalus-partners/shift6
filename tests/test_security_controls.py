from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "backend")

from app.main import app
from app.prompt_paths import PROMPT_DIR, prompt_path, validate_client_slug
from app.security import IdempotencyRegistry


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
