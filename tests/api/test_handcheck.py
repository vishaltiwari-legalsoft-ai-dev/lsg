"""GET /api/handcheck, POST /api/handcheck/{firm_id}/{attr} -- gate G2."""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import make_firm

from .conftest import NOW, make_firm_attribute

pytestmark = pytest.mark.db


def make_document(conn, firm_id, **cols):
    cols.setdefault("url", f"https://example.com/{uuid.uuid4().hex[:8]}")
    cols.setdefault("fetch_ok", True)
    cols.setdefault("page_kind", "home")
    cols.setdefault("status_code", 200)
    cols.setdefault("fetched_at", NOW)
    columns = ["firm_id", *cols.keys()]
    values = [firm_id, *cols.values()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO document ({col_list}) VALUES ({placeholders})",  # noqa: S608
            values,
        )


def test_handcheck_sample_is_stable_across_calls(client, db):
    firm_ids = []
    for i in range(3):
        firm_id = make_firm(db, canonical_name=f"Probe Firm {i}")
        make_document(db, firm_id)
        make_firm_attribute(db, firm_id, "fee_model", "contingency", "regex:p6")
        firm_ids.append(str(firm_id))

    first = client.get("/api/handcheck").json()
    second = client.get("/api/handcheck").json()

    first_ids = [f["firm_id"] for f in first["sample"]]
    second_ids = [f["firm_id"] for f in second["sample"]]
    assert first_ids == second_ids
    assert set(firm_ids) <= set(first_ids)
    assert first["gate"]["needed"] == 50


def test_handcheck_gate_fails_when_not_fully_reviewed(client, db):
    firm_id = make_firm(db, canonical_name="Unreviewed Firm")
    make_document(db, firm_id)
    make_firm_attribute(db, firm_id, "fee_model", "contingency", "regex:p6")

    body = client.get("/api/handcheck").json()
    assert body["gate"]["passed"] is False
    assert "rule" in body["gate"] and body["gate"]["rule"]


def test_handcheck_decision_is_recorded_and_reflected(client, db):
    firm_id = make_firm(db, canonical_name="Reviewed Firm")
    make_document(db, firm_id)
    make_firm_attribute(db, firm_id, "fee_model", "contingency", "regex:p6")

    resp = client.post(
        f"/api/handcheck/{firm_id}/fee_model", json={"correct": True}
    )
    assert resp.status_code == 204

    body = client.get("/api/handcheck").json()
    row = next(f for f in body["sample"] if f["firm_id"] == str(firm_id))
    assert row["reviews"]["fee_model"]["correct"] is True


def test_handcheck_decision_upsert_overwrites_previous_review(client, db):
    firm_id = make_firm(db, canonical_name="Re-reviewed Firm")
    make_document(db, firm_id)
    make_firm_attribute(db, firm_id, "fee_model", "contingency", "regex:p6")

    client.post(
        f"/api/handcheck/{firm_id}/fee_model",
        json={"correct": False, "corrected_value": "hourly"},
    )
    resp2 = client.post(f"/api/handcheck/{firm_id}/fee_model", json={"correct": True})
    assert resp2.status_code == 204

    with db.cursor() as cur:
        cur.execute(
            "SELECT correct, corrected_value FROM handcheck_result "
            "WHERE firm_id = %s AND attr = %s",
            (firm_id, "fee_model"),
        )
        row = cur.fetchone()
    assert row["correct"] is True
