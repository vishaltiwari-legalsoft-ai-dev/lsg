"""score() -- context/40-pipeline/04-scoring-engine.md's nightly full scan."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.registry import RunContext
from lge.score import score as sc
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

AT = datetime(2026, 1, 1, tzinfo=UTC)


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "QUALIFIED_A")
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


def make_signal(conn, firm_id, **cols):
    cols.setdefault("kind", "job_posting_open")
    cols.setdefault("fingerprint", "fp-" + uuid.uuid4().hex[:8])
    cols.setdefault("first_seen", AT)
    cols.setdefault("last_seen", AT)
    cols.setdefault("evidence", Jsonb({"q": "test"}))
    columns = ["firm_id", *cols.keys()]
    values = [firm_id, *cols.values()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with lge_db.writer(conn, "reconcile"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO signal ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def lead_row(conn, lead_id, *cols):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM lead WHERE id = %s", (lead_id,))  # noqa: S608
        return cur.fetchone()


def _ctx(db):
    return RunContext(db, get_settings())


def test_score_with_no_signal_null_arming_none_contest(db):
    firm_id = make_firm(db, tier="1A", fee_model="contingency", primary_practice="personal_injury")
    lead_id = make_lead(db, firm_id)
    n = sc._score_chunk(db, [lead_id], AT)
    assert n == 1
    row = lead_row(db, lead_id, "fit_score", "intent_score", "band", "contest", "arming_signal",
                    "wedge_sku", "scored_at")
    assert row["arming_signal"] is None
    assert row["contest"] == "NONE"
    assert row["intent_score"] == 0
    assert row["fit_score"] is not None and row["fit_score"] > 0
    assert row["wedge_sku"] == "demand_writer"
    assert row["scored_at"] == AT


def test_score_job_posting_open_25_days_gets_weight_40(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id)
    signal_id = make_signal(
        db, firm_id,
        kind="job_posting_open",
        first_seen=AT - timedelta(days=25),
        last_seen=AT,  # decay(0 days) == 1.0, so intent == weight exactly
    )
    sc._score_chunk(db, [lead_id], AT)
    row = lead_row(db, lead_id, "intent_score", "arming_signal", "contest")
    assert row["intent_score"] == 40
    assert row["arming_signal"] == signal_id
    assert row["contest"] == "HIGH"  # contest_level('job_posting_open')


def test_score_picks_highest_weight_times_decay_signal(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id)
    # partner_intro: weight 35, decayed to 0.70 at 10 days -> 24.5. Weaker
    # than the job posting below, so it must NOT be the arming signal --
    # even though intent_score() itself (a separate SQL function) sums
    # every open signal's contribution, arming_signal picks only the single
    # highest weight*decay signal, which is what this test is actually about.
    weak_id = make_signal(
        db, firm_id, kind="partner_intro",
        first_seen=AT - timedelta(days=10), last_seen=AT - timedelta(days=10),
    )
    # job_posting_open, 25 days old, seen today: weight 40 * decay 1.0 = 40 -- wins
    strong_id = make_signal(
        db, firm_id, kind="job_posting_open",
        first_seen=AT - timedelta(days=25), last_seen=AT,
    )
    sc._score_chunk(db, [lead_id], AT)
    row = lead_row(db, lead_id, "arming_signal", "intent_score", "contest")
    assert row["arming_signal"] == strong_id
    assert row["arming_signal"] != weak_id
    # intent_score() sums ALL open signals (24.5 + 40 = 64.5), capped at 50.
    assert row["intent_score"] == 50
    assert row["contest"] == "HIGH"  # contest_level() of the ARMING signal's kind


def test_score_ignores_closed_signals(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id)
    make_signal(
        db, firm_id, kind="job_posting_open",
        first_seen=AT - timedelta(days=25), last_seen=AT, closed_at=AT,
    )
    sc._score_chunk(db, [lead_id], AT)
    row = lead_row(db, lead_id, "arming_signal", "contest", "intent_score")
    assert row["arming_signal"] is None
    assert row["contest"] == "NONE"
    assert row["intent_score"] == 0


def test_score_ignores_closed_leads(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id, closed_at=AT, close_reason="WON")
    n = sc._score_chunk(db, [lead_id], AT)
    assert n == 0


def test_score_idempotent_rerun(db):
    firm_id = make_firm(db, tier="1A")
    lead_id = make_lead(db, firm_id)
    make_signal(
        db, firm_id, kind="job_posting_open", first_seen=AT - timedelta(days=25), last_seen=AT
    )
    sc._score_chunk(db, [lead_id], AT)
    row1 = lead_row(db, lead_id, "intent_score", "band", "arming_signal")
    sc._score_chunk(db, [lead_id], AT)
    row2 = lead_row(db, lead_id, "intent_score", "band", "arming_signal")
    assert row1 == row2


def test_score_component_via_registry(db):
    firm_id = make_firm(db, tier="1A")
    make_lead(db, firm_id)
    ctx = _ctx(db)
    result = sc.score(ctx)
    assert result.processed >= 1
    assert result.failed == 0
