"""`attribution_report` -- context/40-pipeline/07-observability.md
"Attribution closes the loop": outcome (WON/LOST) x arming-signal kind x
tier."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.ops.report import attribution_report
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)


def _ctx(db):
    return RunContext(db, get_settings())


def make_signal(conn, firm_id, **cols):
    cols.setdefault("kind", "job_posting_open")
    cols.setdefault("fingerprint", "fp-" + uuid.uuid4().hex[:8])
    cols.setdefault("first_seen", NOW)
    cols.setdefault("last_seen", NOW)
    cols.setdefault("evidence", Jsonb({}))
    columns = ["firm_id", *cols.keys()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO signal ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            [firm_id, *cols.values()],
        )
        return cur.fetchone()["id"]


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "QUALIFIED_A")
    cols.setdefault("created_at", NOW)
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            [cols[c] for c in columns],
        )
        return cur.fetchone()["id"]


def test_attribution_report_prints_no_outcomes_yet_state(db):
    make_firm(db, tier="1A")  # firms alone are not outcomes
    rows = attribution_report(_ctx(db))
    assert rows == []


def test_attribution_report_groups_by_outcome_signal_kind_and_tier(db):
    firm_a = make_firm(db, tier="1A")
    firm_b = make_firm(db, tier="2")
    sig_a = make_signal(db, firm_a, kind="job_posting_open")
    sig_b = make_signal(db, firm_b, kind="job_posting_open", fingerprint="fp-b")

    # closed_at set on both -- invariant I1 (lead_open_firm_id_uidx) allows
    # only one OPEN lead per firm, and a WON/LOST lead is a closed one.
    make_lead(db, firm_a, state="WON", arming_signal=sig_a, closed_at=NOW)
    make_lead(db, firm_a, state="WON", arming_signal=sig_a, closed_at=NOW)
    make_lead(db, firm_b, state="LOST", arming_signal=sig_b, closed_at=NOW)

    rows = attribution_report(_ctx(db))
    by_key = {(r.outcome, r.signal_kind, r.tier): r.n for r in rows}
    assert by_key[("WON", "job_posting_open", "1A")] == 2
    assert by_key[("LOST", "job_posting_open", "2")] == 1


def test_attribution_report_handles_a_lead_closed_without_an_arming_signal(db):
    firm_id = make_firm(db, tier="3")
    make_lead(db, firm_id, state="LOST", arming_signal=None, closed_at=NOW)

    rows = attribution_report(_ctx(db))
    assert len(rows) == 1
    assert rows[0].outcome == "LOST"
    assert rows[0].signal_kind == "(none)"
    assert rows[0].tier == "3"


def test_attribution_report_ignores_open_leads(db):
    firm_id = make_firm(db, tier="1A")
    make_lead(db, firm_id, state="QUALIFIED_A")
    rows = attribution_report(_ctx(db))
    assert rows == []


def test_attribution_report_counts_a_ui_outcome_whose_transition_did_not_apply(db):
    """Most leads cannot legally reach HANDOFF -> WON today (I4: no bench
    inventory), so an SDR's "Won" click in the UI records a lead_outcome row
    while lead.state stays wherever it was. Attribution must still count it
    -- sql/090_ui.sql's lead_outcome is the append-only record of what the
    UI captured, independent of whether the state machine allowed the
    transition."""
    firm_id = make_firm(db, tier="1A")
    sig = make_signal(db, firm_id, kind="job_posting_open")
    lead_id = make_lead(db, firm_id, state="QUALIFIED_A", arming_signal=sig)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO lead_outcome (lead_id, action, transition_applied) "
            "VALUES (%s, 'won', false)",
            (lead_id,),
        )

    rows = attribution_report(_ctx(db))
    by_key = {(r.outcome, r.signal_kind, r.tier): r.n for r in rows}
    assert by_key[("WON", "job_posting_open", "1A")] == 1


def test_attribution_report_does_not_double_count_when_state_and_outcome_agree(db):
    """A lead whose transition DID apply (state == 'WON') and which also
    carries a lead_outcome row for the same action is one deal, not two."""
    firm_id = make_firm(db, tier="2")
    sig = make_signal(db, firm_id, kind="job_posting_open", fingerprint="fp-agree")
    lead_id = make_lead(db, firm_id, state="WON", arming_signal=sig, closed_at=NOW)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO lead_outcome (lead_id, action, transition_applied) "
            "VALUES (%s, 'won', true)",
            (lead_id,),
        )

    rows = attribution_report(_ctx(db))
    by_key = {(r.outcome, r.signal_kind, r.tier): r.n for r in rows}
    assert by_key[("WON", "job_posting_open", "2")] == 1
