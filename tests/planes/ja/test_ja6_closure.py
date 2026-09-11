"""JA6 closure -- context/20-signals/04-dedupe-dates-and-closure.md: closed only
after two consecutive successful careers sweeps confirm absence; a failed sweep
never counts, and the firm's own careers page is authoritative over any board.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tests.conftest import make_firm
from tests.planes.ja._ja6_helpers import (
    fetch_all,
    fetch_one,
    make_careers_sweep,
    make_posting,
    run_closure,
    run_normalise,
)

pytestmark = pytest.mark.db


def _dt(y, m, d_):
    return datetime(y, m, d_, tzinfo=UTC)


def _open_signal(db, firm_id, **posting_cols):
    posting_cols.setdefault("source", "careers")
    posting_cols.setdefault("firm_id", firm_id)
    posting_cols.setdefault("title", "Paralegal")
    posting_cols.setdefault("city", "Denver")
    posting_cols.setdefault("state", "CO")
    posting_cols.setdefault("board_posted_date", date(2026, 6, 1))
    posting_cols.setdefault("fetched_at", _dt(2026, 6, 1))
    make_posting(db, **posting_cols)
    run_normalise(db)
    return fetch_one(
        db, "SELECT * FROM signal WHERE firm_id = %s AND kind = 'job_posting_open'", (firm_id,)
    )


def test_closure_requires_two_consecutive_successful_sweeps(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id)
    assert sig["closed_at"] is None

    # one successful sweep confirming absence -- not enough on its own
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 5), postings_found=0)
    result = run_closure(db)
    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is None
    assert result.skipped == 1

    # second successful sweep -- now closes
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 10), postings_found=0)
    result = run_closure(db)
    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is not None
    assert result.skipped == 0

    closing_sightings = fetch_all(
        db,
        "SELECT * FROM signal_sighting WHERE signal_id = %s AND present = false",
        (sig["id"],),
    )
    assert len(closing_sightings) == 1


def test_a_single_failed_sweep_never_closes_a_live_signal(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id)

    make_careers_sweep(db, firm_id, fetch_ok=False, swept_at=_dt(2026, 6, 5))
    run_closure(db)
    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is None


def test_failed_sweeps_do_not_reset_or_substitute_for_successful_ones(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id)

    make_careers_sweep(db, firm_id, fetch_ok=False, swept_at=_dt(2026, 6, 3))
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 5), postings_found=0)
    make_careers_sweep(db, firm_id, fetch_ok=False, swept_at=_dt(2026, 6, 7))
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 9), postings_found=0)

    run_closure(db)
    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is not None  # two successful sweeps landed regardless of the failures


def test_only_failed_sweeps_never_close_the_signal(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id)
    for day in (3, 5, 7, 9, 11):
        make_careers_sweep(db, firm_id, fetch_ok=False, swept_at=_dt(2026, 6, day))
    run_closure(db)
    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is None


def test_careers_page_is_authoritative_even_with_board_sightings(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id, source="careers")
    # also seen on a board, contributing a second sighting to the same signal
    make_posting(
        db,
        source="bar_board:co",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2026, 6, 1),
        fetched_at=_dt(2026, 6, 2),
    )
    run_normalise(db)

    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 10), postings_found=0)
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 15), postings_found=0)
    run_closure(db)

    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is not None


def test_no_careers_sweep_history_never_closes(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id, source="bar_board:co")
    result = run_closure(db)
    sig = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig["id"],))
    assert sig["closed_at"] is None
    assert result.processed == 1
    assert result.skipped == 1


def test_closure_is_idempotent(db):
    firm_id = make_firm(db)
    sig = _open_signal(db, firm_id)
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 5), postings_found=0)
    make_careers_sweep(db, firm_id, fetch_ok=True, swept_at=_dt(2026, 6, 10), postings_found=0)
    run_closure(db)
    run_closure(db)  # already closed -- no longer selected as an open signal

    sightings = fetch_all(
        db,
        "SELECT * FROM signal_sighting WHERE signal_id = %s AND present = false",
        (sig["id"],),
    )
    assert len(sightings) == 1
