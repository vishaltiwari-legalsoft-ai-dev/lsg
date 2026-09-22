"""GET /api/meta/providers -- booleans only, never key values. Plus CORS."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def _keys(monkeypatch, **values):
    # Set empty rather than delete: settings fall back to the project's .env
    # when a variable is absent, so deleting only passed until a real key was added.
    for name in ("OPENROUTER_API_KEY", "ZEROBOUNCE_API_KEY", "NEVERBOUNCE_API_KEY",
                 "HUNTER_API_KEY", "SERPER_API_KEY", "BRAVE_API_KEY"):
        monkeypatch.setenv(name, values.get(name, ""))
    # conftest pins the seams keyless; here they choose by key, as a real machine does
    monkeypatch.setenv("LGE_EMAIL_VERIFIER", "auto")
    monkeypatch.setenv("LGE_SEARCH_ENGINE", "auto")


def test_providers_never_leak_key_material(client, monkeypatch):
    _keys(monkeypatch, OPENROUTER_API_KEY="sk-secret-openrouter-value",
          ZEROBOUNCE_API_KEY="zb-secret-value", SERPER_API_KEY="serper-secret-value")
    from lge.settings import get_settings

    get_settings.cache_clear()
    try:
        resp = client.get("/api/meta/providers")
        assert resp.status_code == 200
        assert "sk-secret-openrouter-value" not in resp.text
        assert "zb-secret-value" not in resp.text
        assert "serper-secret-value" not in resp.text
        body = resp.json()
        assert body["ai_extraction"] is True
        assert body["email_verification"] is True
        assert body["places"] is True
        assert "crawler_identity" in body
    finally:
        get_settings.cache_clear()


def test_providers_report_inert_when_unconfigured(client, monkeypatch):
    _keys(monkeypatch)
    from lge.settings import get_settings

    get_settings.cache_clear()
    try:
        body = client.get("/api/meta/providers").json()
        assert body["ai_extraction"] is False
        assert body["email_verification"] is False
        assert body["places"] is False
    finally:
        get_settings.cache_clear()


def test_the_listing_light_follows_the_search_engine_not_a_key_nobody_reads(client, monkeypatch):
    # GOOGLE_PLACES_API_KEY was the old light's key: nothing in the engine reads it.
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "places-key")
    _keys(monkeypatch, BRAVE_API_KEY="brave-key")  # an engine, but one with no listings
    from lge.settings import get_settings

    get_settings.cache_clear()
    try:
        assert client.get("/api/meta/providers").json()["places"] is False
    finally:
        get_settings.cache_clear()


def test_cors_allows_our_own_screens(client):
    for origin in ("http://localhost:5000", "http://127.0.0.1:5000"):
        resp = client.options(
            "/api/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert resp.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example.com",
        # another project runs on 3000 on this machine; its pages must not read contacts
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
)
def test_cors_rejects_other_origins(client, origin):
    resp = client.options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
