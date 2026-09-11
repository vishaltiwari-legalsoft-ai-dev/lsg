"""classify() -- one test per lifecycle guard in context/40-pipeline/
05-lead-lifecycle.md, plus a couple of full-cascade integration checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from lge import db as lge_db
from lge.registry import RunContext
from lge.score import classify as cl
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "DISCOVERED")
    cols.setdefault("created_at", datetime.now(UTC))
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_document_with_text(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, fetch_ok) VALUES (%s, 'https://x.test/', true) "
            "RETURNING id",
            (firm_id,),
        )
        doc_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO document_text (document_id, main_text, extractor) "
            "VALUES (%s, 'some page text', 'trafilatura:2.0')",
            (doc_id,),
        )


def make_regex_claim(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, observed_at) "
            "VALUES (%s, 'fee_model', '\"contingency\"'::jsonb, 'regex:p6', 0.9, now())",
            (firm_id,),
        )


def make_contact(conn, firm_id, *, role="owner", **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols["role"] = role
    cols.setdefault("full_name", "Jamie Test")
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_contact_email(conn, contact_id, email, status, **cols):
    cols["contact_id"] = contact_id
    cols["email"] = email
    cols["status"] = status
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO contact_email ({col_list}) VALUES ({placeholders})", values)  # noqa: S608


def suppress(conn, scope, value, reason="optout"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO suppression (scope, value, reason, added_at) VALUES (%s, %s, %s, now())",
            (scope, value, reason),
        )


def open_conflict(conn, firm_id, attr="primary_practice"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO reconcile_conflict (firm_id, attr, claims, reason) "
            "VALUES (%s, %s, '[]'::jsonb, 'test conflict')",
            (firm_id, attr),
        )


def lead_state(conn, lead_id):
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM lead WHERE id = %s", (lead_id,))
        return cur.fetchone()["state"]


# =============================================================================
# Guards, one at a time (`_next_transition` -- avoids a full cascade masking
# which specific guard is under test)
# =============================================================================


def test_profiling_to_profiled_requires_text_and_regex_claim(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id, state="PROFILING")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None  # neither document text nor regex claim yet

    make_document_with_text(db, firm_id)
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None  # text but no regex:p6 claim

    make_regex_claim(db, firm_id)
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("PROFILED", {})


def test_profiled_to_classified_when_tier_resolved_no_conflict(db):
    firm_id = make_firm(db, tier="1A", fee_model="contingency", primary_practice="personal_injury")
    lead_id = make_lead(db, firm_id, state="PROFILED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("CLASSIFIED", {})


def test_profiled_to_escalated_when_tier_unclassified(db):
    firm_id = make_firm(db, tier="UNCLASSIFIED")
    lead_id = make_lead(db, firm_id, state="PROFILED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("ESCALATED", {})


def test_profiled_to_escalated_when_open_conflict_even_with_tier_set(db):
    firm_id = make_firm(db, tier="1A")
    open_conflict(db, firm_id)
    lead_id = make_lead(db, firm_id, state="PROFILED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("ESCALATED", {})


def test_escalated_to_classified_once_conflict_resolved(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id, state="ESCALATED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("CLASSIFIED", {})


def test_classified_to_disqualified_writes_close_reason(db):
    firm_id = make_firm(db, tier="DQ_SIZE")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")
    hops = cl.advance_lead(db, lead_id)
    assert hops == 1
    with db.cursor() as cur:
        cur.execute("SELECT state, close_reason, closed_at FROM lead WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    assert row["state"] == "DISQUALIFIED"
    assert row["close_reason"] == "DQ_SIZE"
    assert row["closed_at"] is not None


def test_classified_to_contact_pending_blocked_by_suppressed_domain(db):
    firm_id = make_firm(db, tier="1A", domain="suppressed-classify.test")
    suppress(db, "domain", "suppressed-classify.test")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None


def test_classified_to_contact_pending_blocked_by_suppressed_firm_id(db):
    firm_id = make_firm(db, tier="1A")
    suppress(db, "firm_id", str(firm_id))
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None


def test_classified_to_contact_pending_when_not_suppressed(db):
    firm_id = make_firm(db, tier="1A", domain="clean-classify.test")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("CONTACT_PENDING", {})


def test_contact_pending_to_resolved_requires_owner_or_admin(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id, state="CONTACT_PENDING")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None  # no contact at all

    make_contact(db, firm_id, role="attorney")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None  # attorney is not owner/admin

    owner_id = make_contact(db, firm_id, role="owner")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("RESOLVED", {"contact_id": owner_id})


def test_resolved_to_qualified_a_requires_our_own_valid_status(db):
    firm_id = make_firm(db, tier="1A")
    contact_id = make_contact(db, firm_id, role="owner")
    lead_id = make_lead(db, firm_id, state="RESOLVED", contact_id=contact_id)

    # Purchased-dataset shape: vendor claims 'verified', OUR status is
    # 'unverified' -- must NOT reach QUALIFIED_A (R4 is a later milestone).
    make_contact_email(db, contact_id, "owner@example.test", "unverified", vendor_status="verified")
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None

    with db.cursor() as cur:
        cur.execute(
            "UPDATE contact_email SET status = 'valid' WHERE contact_id = %s", (contact_id,)
        )
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("QUALIFIED_A", {"grade": "A"})


def test_resolved_to_qualified_b_requires_catch_all_or_risky_plus_phone(db):
    firm_id = make_firm(db, tier="1A", phone_e164=None)
    contact_id = make_contact(db, firm_id, role="admin", phone_direct=None)
    lead_id = make_lead(db, firm_id, state="RESOLVED", contact_id=contact_id)
    make_contact_email(db, contact_id, "admin@example.test", "catch_all")

    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) is None  # catch_all but no phone anywhere

    with db.cursor() as cur:
        cur.execute("UPDATE firm SET phone_e164 = '+15125551234' WHERE id = %s", (firm_id,))
    lead = cl._fetch_lead(db, lead_id)
    assert cl._next_transition(db, lead) == ("QUALIFIED_B", {"grade": "B"})


# =============================================================================
# Cascade + component-level integration
# =============================================================================


def test_advance_lead_cascades_classified_all_the_way_to_qualified_a(db):
    firm_id = make_firm(db, tier="1A", domain="cascade-classify.test")
    owner_id = make_contact(db, firm_id, role="owner")
    make_contact_email(db, owner_id, "owner@cascade-classify.test", "valid")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")

    hops = cl.advance_lead(db, lead_id)
    assert hops == 3  # CLASSIFIED -> CONTACT_PENDING -> RESOLVED -> QUALIFIED_A
    assert lead_state(db, lead_id) == "QUALIFIED_A"
    with db.cursor() as cur:
        cur.execute("SELECT grade, contact_id FROM lead WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    assert row["grade"] == "A"
    assert row["contact_id"] == owner_id


def test_classify_component_advances_multiple_leads_and_is_idempotent(db):
    firm_a = make_firm(db, tier="DQ_GEO")
    lead_a = make_lead(db, firm_a, state="CLASSIFIED")

    firm_b = make_firm(db, tier="UNCLASSIFIED")
    lead_b = make_lead(db, firm_b, state="PROFILED")

    ctx = RunContext(db, get_settings())
    result1 = cl.classify(ctx)
    assert result1.failed == 0
    assert lead_state(db, lead_a) == "DISQUALIFIED"
    assert lead_state(db, lead_b) == "ESCALATED"

    # Idempotent re-run: DISQUALIFIED is closed (no further guard fires), and
    # ESCALATED with no resolved tier and no new conflict has nothing to do.
    result2 = cl.classify(ctx)
    assert result2.failed == 0
    assert lead_state(db, lead_a) == "DISQUALIFIED"
    assert lead_state(db, lead_b) == "ESCALATED"
