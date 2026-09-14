"""GET /api/leads, GET/POST /api/leads/{id}[...], GET /api/leads/export.csv."""

from __future__ import annotations

import pytest

from tests.conftest import make_firm

from .conftest import (
    make_contact,
    make_contact_email,
    make_lead,
    make_suppression,
    sequence_ready_firm,
)

pytestmark = pytest.mark.db


def test_strike_sequence_nurture_views_and_counts(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm, tier="1A")
    make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id,
        band="STRIKE", contest="LOW", fit_score=45, intent_score=40,
    )

    resp = client.get("/api/leads", params={"view": "STRIKE"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["band"] == "STRIKE"
    assert body["items"][0]["firm"]["name"] == "Ready Law Firm"
    assert body["counts"]["STRIKE"] == 1
    assert body["counts"]["SEQUENCE"] == 0


def test_suppressed_firm_never_in_strike_sequence_nurture(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(
        db, make_firm, domain="blocked-lead.example.com"
    )
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")
    make_suppression(db, "domain", "blocked-lead.example.com")

    for view in ("STRIKE", "SEQUENCE", "NURTURE"):
        resp = client.get("/api/leads", params={"view": view})
        assert resp.json()["items"] == [], f"view={view}"

    excluded = client.get("/api/leads", params={"view": "EXCLUDED"}).json()
    assert len(excluded["items"]) == 1
    assert excluded["items"][0]["firm"]["domain"] == "blocked-lead.example.com"


def test_grade_b_only_in_phone(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id,
        band="SEQUENCE", grade="B",
    )

    for view in ("STRIKE", "SEQUENCE", "NURTURE", "EXCLUDED"):
        resp = client.get("/api/leads", params={"view": view})
        assert resp.json()["items"] == [], f"view={view}"

    phone = client.get("/api/leads", params={"view": "PHONE"}).json()
    assert len(phone["items"]) == 1
    assert phone["counts"]["PHONE"] == 1


def test_unscored_lead_in_unscored_view(client, db):
    firm_id = make_firm(db, canonical_name="Brand New Firm")
    make_lead(db, firm_id, band=None, grade=None, state="DISCOVERED")

    resp = client.get("/api/leads", params={"view": "UNSCORED"})
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["band"] is None
    assert body["items"][0]["firm"]["name"] == "Brand New Firm"
    assert body["counts"]["UNSCORED"] == 1


def test_never_crawled_lead_stays_unscored_after_the_nightly_scan(client, db):
    # The full scan bands every open lead, un-crawled ones HOLD on vendor fit
    # alone. Showing those as EXCLUDED told the user 21,940 firms were rejected.
    firm_id = make_firm(db, canonical_name="Not Crawled Yet")
    make_lead(db, firm_id, band="HOLD", grade=None, state="DISCOVERED")

    unscored = client.get("/api/leads", params={"view": "UNSCORED"}).json()
    assert [i["firm"]["name"] for i in unscored["items"]] == ["Not Crawled Yet"]
    assert unscored["counts"]["UNSCORED"] == 1
    assert unscored["counts"]["EXCLUDED"] == 0


def test_cursor_pagination_is_stable_and_covers_every_row(client, db):
    lead_ids = set()
    for i in range(4):
        firm_id, contact_id, signal_id = sequence_ready_firm(
            db, make_firm, canonical_name=f"Firm {i}"
        )
        lead_id = make_lead(
            db, firm_id, contact_id=contact_id, arming_signal=signal_id,
            band="STRIKE", intent_score=10 + i, fit_score=20, contest="LOW",
        )
        lead_ids.add(str(lead_id))

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"view": "STRIKE", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        resp = client.get("/api/leads", params=params)
        body = resp.json()
        assert len(body["items"]) <= 1
        if not body["items"]:
            break
        seen.append(body["items"][0]["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(lead_ids) == len(set(seen))
    assert set(seen) == lead_ids
    # highest intent_score (13) must come first -- "intent descending"
    first_full = client.get("/api/leads", params={"view": "STRIKE", "limit": 10}).json()
    assert first_full["items"][0]["intent"] == 13


def test_lead_detail_has_owner_and_admin_and_reports_missing_role(client, db):
    firm_id = make_firm(db, canonical_name="Both People Law")
    owner_id = make_contact(db, firm_id, full_name="Owner Person", role="owner")
    make_contact_email(db, owner_id, status="valid")
    lead_id = make_lead(db, firm_id, contact_id=owner_id, band="SEQUENCE", grade="A")

    resp = client.get(f"/api/leads/{lead_id}")
    assert resp.status_code == 200
    body = resp.json()
    names = {c["full_name"] for c in body["contacts"]}
    assert names == {"Owner Person"}
    assert body["missing_roles"] == ["admin"]
    assert body["contact"]["full_name"] == "Owner Person"


def test_lead_detail_owner_and_admin_both_present(client, db):
    firm_id = make_firm(db, canonical_name="Two Contacts Law")
    owner_id = make_contact(db, firm_id, full_name="Owner Person", role="owner")
    make_contact_email(db, owner_id, status="valid")
    admin_id = make_contact(db, firm_id, full_name="Admin Person", role="admin")
    make_contact_email(db, admin_id, status="valid")
    lead_id = make_lead(db, firm_id, contact_id=owner_id, band="SEQUENCE", grade="A")

    resp = client.get(f"/api/leads/{lead_id}")
    body = resp.json()
    names = {c["full_name"] for c in body["contacts"]}
    assert names == {"Owner Person", "Admin Person"}
    assert body["missing_roles"] == []


def test_lead_not_found_returns_contract_error_shape(client):
    resp = client.get("/api/leads/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]


def test_drafts_come_from_build_journey(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    lead_id = make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE"
    )

    resp = client.get(f"/api/leads/{lead_id}/drafts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["band"] == "SEQUENCE"
    assert body["excluded_reason"] is None
    touch1 = next(t for t in body["touches"] if t["step"] == 1)
    assert "demand writer" in touch1["body"].lower()


def test_drafts_sequence_missing_signal_evidence_is_excluded(client, db):
    firm_id = make_firm(
        db, canonical_name="No Pain Law", tier="1A",
        fee_model="contingency", primary_practice="personal_injury",
    )
    contact_id = make_contact(db, firm_id, full_name="Sam Owner", role="owner")
    make_contact_email(db, contact_id, status="valid")
    lead_id = make_lead(db, firm_id, contact_id=contact_id, arming_signal=None, band="SEQUENCE")

    resp = client.get(f"/api/leads/{lead_id}/drafts")
    body = resp.json()
    assert body["excluded_reason"] == "sequence_missing_signal_evidence"
    assert body["touches"] == []


def test_outcome_always_writes_lead_outcome(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    lead_id = make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id,
        band="SEQUENCE", state="QUALIFIED_A",
    )

    resp = client.post(f"/api/leads/{lead_id}/outcome", json={"action": "replied"})
    assert resp.status_code == 200
    body = resp.json()
    # QUALIFIED_A -> RESPONDED is not a whitelisted transition (never armed)
    assert body["transition_applied"] is False
    assert "bench is empty" in body["message"].lower()
    assert len(body["lead"]["outcomes"]) == 1
    assert body["lead"]["outcomes"][0]["action"] == "replied"
    assert body["lead"]["outcomes"][0]["transition_applied"] is False

    with db.cursor() as cur:
        cur.execute(
            "SELECT action, transition_applied FROM lead_outcome WHERE lead_id = %s",
            (lead_id,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["action"] == "replied"
    assert rows[0]["transition_applied"] is False


def test_outcome_applies_transition_when_whitelisted(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    lead_id = make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id,
        band="SEQUENCE", state="ENGAGED",
    )

    resp = client.post(f"/api/leads/{lead_id}/outcome", json={"action": "replied"})
    body = resp.json()
    assert body["transition_applied"] is True
    assert body["lead"]["state"] == "RESPONDED"

    with db.cursor() as cur:
        cur.execute("SELECT state FROM lead WHERE id = %s", (lead_id,))
        assert cur.fetchone()["state"] == "RESPONDED"


def test_outcome_not_now_requires_until(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    lead_id = make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE"
    )

    resp = client.post(f"/api/leads/{lead_id}/outcome", json={"action": "not_now"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_outcome_not_now_sets_cooldown(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    lead_id = make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE"
    )

    resp = client.post(
        f"/api/leads/{lead_id}/outcome",
        json={"action": "not_now", "until": "2026-12-01"},
    )
    assert resp.status_code == 200

    with db.cursor() as cur:
        cur.execute("SELECT cooldown_until FROM lead WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    assert row["cooldown_until"].date().isoformat() == "2026-12-01"


def test_outcome_opt_out_suppresses_domain(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(
        db, make_firm, domain="optout-me.example.com"
    )
    lead_id = make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id,
        band="SEQUENCE", state="QUALIFIED_A",
    )

    resp = client.post(f"/api/leads/{lead_id}/outcome", json={"action": "opt_out"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["transition_applied"] is True
    assert body["lead"]["state"] == "SUPPRESSED"

    with db.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM suppression WHERE scope = 'domain' AND value = %s",
            ("optout-me.example.com",),
        )
        assert cur.fetchone() is not None


def test_export_csv_runs_build_list_and_applies_hygiene(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")

    resp = client.get("/api/leads/export.csv", params={"view": "SEQUENCE"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Ready Law Firm" in resp.text


def test_export_csv_never_includes_grade_b(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    make_lead(
        db, firm_id, contact_id=contact_id, arming_signal=signal_id,
        band="SEQUENCE", grade="B",
    )

    resp = client.get("/api/leads/export.csv", params={"view": "SEQUENCE"})
    assert "Ready Law Firm" not in resp.text
