"""Shape smoke tests for the endpoints not covered in more depth elsewhere:
health, today, pipeline/alerts, pipeline/gates."""

from __future__ import annotations

import pytest

from tests.conftest import make_firm

from .conftest import make_lead, sequence_ready_firm

pytestmark = pytest.mark.db


def test_health_reports_db_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert body["version"]


def test_today_on_an_empty_database(client, db):
    resp = client.get("/api/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["top_proof"] is None
    assert body["first_draft"] is None
    assert body["strike"] == []
    assert "alerts" in body["attention"]
    assert "bench" in body["attention"]
    assert body["attention"]["bench"]["skus_available"] == 0


def test_today_top_proof_is_the_highest_intent_strike_lead(client, db):
    firm_lo_id, contact_lo, signal_lo = sequence_ready_firm(
        db, make_firm, canonical_name="Lower Intent Firm"
    )
    make_lead(
        db, firm_lo_id, contact_id=contact_lo, arming_signal=signal_lo,
        band="STRIKE", intent_score=10, fit_score=20, contest="LOW",
    )
    firm_hi_id, contact_hi, signal_hi = sequence_ready_firm(
        db, make_firm, canonical_name="Higher Intent Firm"
    )
    make_lead(
        db, firm_hi_id, contact_id=contact_hi, arming_signal=signal_hi,
        band="STRIKE", intent_score=40, fit_score=20, contest="LOW",
    )

    body = client.get("/api/today").json()
    assert body["top_proof"]["firm"]["name"] == "Higher Intent Firm"
    assert len(body["strike"]) == 1
    assert body["strike"][0]["firm"]["name"] == "Lower Intent Firm"
    assert body["first_draft"] is not None
    assert "demand writer" in body["first_draft"]["body"].lower()


def test_pipeline_alerts_shape(client):
    resp = client.get("/api/pipeline/alerts")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert {"name", "label", "state", "value", "detail"} <= set(items[0].keys())


def test_pipeline_gates_only_fast_gates(client):
    resp = client.get("/api/pipeline/gates")
    assert resp.status_code == 200
    names = {g["name"] for g in resp.json()["items"]}
    assert names <= {"invariants", "g1_identity", "g3_tier_distribution", "g7_coverage"}
    assert "invariants" in names
