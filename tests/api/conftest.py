from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.api.app import app
from lge.api.deps import get_conn

NOW = datetime(2026, 9, 11, tzinfo=UTC)


@pytest.fixture
def client(db):
    """A TestClient wired to the SAME connection/transaction the `db`
    fixture gives the test -- writes made with `db` are visible to the API
    (and vice versa) without a commit, and the whole test rolls back
    together at teardown (tests/conftest.py's `db` fixture)."""

    def _override():
        yield db

    app.dependency_overrides[get_conn] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# Factories -- mirrors tests/export/test_list.py's local helpers so a lead
# built here behaves identically under list hygiene.
# ---------------------------------------------------------------------------


def make_signal(conn, firm_id, **cols):
    cols.setdefault("kind", "job_posting_open")
    cols.setdefault("fingerprint", "fp-" + uuid.uuid4().hex[:10])
    cols.setdefault("first_seen", NOW - timedelta(days=25))
    cols.setdefault("last_seen", NOW - timedelta(days=1))
    if "evidence" in cols and not isinstance(cols["evidence"], Jsonb):
        cols["evidence"] = Jsonb(cols["evidence"])
    cols.setdefault("evidence", Jsonb({"title": "Paralegal", "canonical_role": "paralegal"}))
    columns = ["firm_id", *cols.keys()]
    values = [firm_id, *cols.values()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO signal ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_contact(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("full_name", "Jane Doe")
    cols.setdefault("title", "Managing Partner")
    cols.setdefault("role", "owner")
    cols.setdefault("source", "site:jsonld")
    columns = list(cols.keys())
    values = [cols[c] for c in columns]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_contact_email(conn, contact_id, **cols):
    cols.setdefault("email", f"{uuid.uuid4().hex[:10]}@example.com")
    cols.setdefault("status", "valid")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status, vendor_status) "
            "VALUES (%s, %s, %s, %s)",
            (contact_id, cols["email"], cols["status"], cols.get("vendor_status")),
        )
    return cols["email"]


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "QUALIFIED_A")
    cols.setdefault("grade", "A")
    cols.setdefault("band", "SEQUENCE")
    cols.setdefault("created_at", NOW)
    columns = list(cols.keys())
    values = [cols[c] for c in columns]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_suppression(conn, scope, value, reason="optout"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO suppression (scope, value, reason, added_at) VALUES (%s, %s, %s, %s)",
            (scope, value, reason, NOW),
        )


def make_firm_attribute(conn, firm_id, attr, value, source, **cols):
    cols.setdefault("confidence", 0.9)
    cols.setdefault("observed_at", NOW)
    cols.setdefault("evidence", None)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, "
            "evidence, observed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                firm_id, attr, Jsonb(value), source, cols["confidence"],
                cols["evidence"], cols["observed_at"],
            ),
        )


def sequence_ready_firm(conn, make_firm, **firm_kwargs):
    """A firm/contact/signal combination that passes every hygiene filter
    and renders a full SEQUENCE journey -- mirrors
    tests/export/test_list.py's `_sequence_ready_firm`."""
    firm_kwargs.setdefault("canonical_name", "Ready Law Firm")
    firm_kwargs.setdefault("domain", f"{uuid.uuid4().hex[:8]}.example.com")
    firm_kwargs.setdefault("city", "Austin")
    firm_kwargs.setdefault("state", "TX")
    firm_kwargs.setdefault("tier", "1A")
    firm_kwargs.setdefault("fee_model", "contingency")
    firm_kwargs.setdefault("primary_practice", "personal_injury")
    firm_kwargs.setdefault("cms_detected", "filevine")
    firm_id = make_firm(conn, **firm_kwargs)
    contact_id = make_contact(conn, firm_id, full_name="John Smith", role="owner")
    make_contact_email(conn, contact_id, status="valid")
    signal_id = make_signal(
        conn, firm_id,
        evidence=Jsonb({"title": "Demand Writer", "canonical_role": "demand_writer"}),
    )
    return firm_id, contact_id, signal_id
