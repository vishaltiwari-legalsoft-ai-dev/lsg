"""The engine answers only its own hosts. A page elsewhere whose hostname
was re-pointed at 127.0.0.1 (DNS rebinding) arrives with its own Host
header and is refused before any route runs (security review, 28 Sep 2026)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lge.api.app import app


def test_a_foreign_host_header_is_refused():
    with TestClient(app, base_url="http://attacker.example") as c:
        r = c.get("/api/health", headers={"host": "attacker.example:5000"})
    assert r.status_code == 400


def test_our_own_hosts_are_answered(client):
    assert client.get("/api/health", headers={"host": "127.0.0.1:8100"}).status_code == 200
    assert client.get("/api/health", headers={"host": "localhost:8100"}).status_code == 200
