"""GET /api/meta/providers -- booleans only, never key values. Plus CORS."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def test_providers_never_leak_key_material(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret-openrouter-value")
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "zb-secret-value")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "places-secret-value")
    from lge.settings import get_settings

    get_settings.cache_clear()
    try:
        resp = client.get("/api/meta/providers")
        assert resp.status_code == 200
        assert "sk-secret-openrouter-value" not in resp.text
        assert "zb-secret-value" not in resp.text
        assert "places-secret-value" not in resp.text
        body = resp.json()
        assert body["ai_extraction"] is True
        assert body["email_verification"] is True
        assert body["places"] is True
        assert "crawler_identity" in body
    finally:
        get_settings.cache_clear()


def test_providers_report_inert_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ZEROBOUNCE_API_KEY", raising=False)
    monkeypatch.delenv("NEVERBOUNCE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    from lge.settings import get_settings

    get_settings.cache_clear()
    try:
        body = client.get("/api/meta/providers").json()
        assert body["ai_extraction"] is False
        assert body["email_verification"] is False
        assert body["places"] is False
    finally:
        get_settings.cache_clear()


def test_cors_allows_configured_origin(client):
    resp = client.options(
        "/api/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_other_origins(client):
    resp = client.options(
        "/api/health",
        headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
