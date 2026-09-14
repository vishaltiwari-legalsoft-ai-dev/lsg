"""JA6 stage 4+5 -- signal/sighting writes (live sources), fit-claim writes
(internal_jobs), repost detection, multi_opening, and the pure-re-run guarantee.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from lge.norm import norm_name
from tests.conftest import make_firm
from tests.planes.ja._ja6_helpers import fetch_all, fetch_one, make_posting, run_normalise

pytestmark = pytest.mark.db


def _dt(y, m, d_):
    return datetime(y, m, d_, tzinfo=UTC)


# =============================================================================
# One opening, several sources -> one signal
# =============================================================================


def test_three_sources_merge_into_one_signal_with_earliest_first_seen(db):
    firm_id = make_firm(db, city="Denver", state="CO")
    make_posting(
        db,
        source="careers",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        source_url="https://smithlaw.com/careers/1",
        board_posted_date=date(2026, 7, 1),
        fetched_at=_dt(2026, 7, 1),
        body="We need a paralegal. Apply now.",
    )
    make_posting(
        db,
        source="bar_board:co",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        source_url="https://cobar.example/job/2",
        board_posted_date=date(2026, 7, 3),
        fetched_at=_dt(2026, 7, 3),
    )
    make_posting(
        db,
        source="serp",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        source_url="https://indeed.com/job/3",
        board_posted_date=date(2026, 7, 2),
        fetched_at=_dt(2026, 7, 2),
    )

    run_normalise(db)

    signals = fetch_all(
        db,
        "SELECT * FROM signal WHERE firm_id = %s AND kind = 'job_posting_open'",
        (firm_id,),
    )
    assert len(signals) == 1
    sig = signals[0]
    assert sorted(sig["evidence"]["sources"]) == ["bar_board:co", "careers", "serp"]
    assert sig["first_seen"] == _dt(2026, 7, 1)  # our earliest fetched_at, not any board date
    # careers page preferred as the canonical url/title (context/20-signals/04,
    # "Merge policy on collision")
    assert sig["evidence"]["url"] == "https://smithlaw.com/careers/1"

    sightings = fetch_all(
        db, "SELECT source FROM signal_sighting WHERE signal_id = %s", (sig["id"],)
    )
    assert sorted(s["source"] for s in sightings) == ["bar_board:co", "careers", "serp"]


# =============================================================================
# Repost detection
# =============================================================================


def test_repost_advances_last_seen_and_bumps_repost_count_without_moving_first_seen(db):
    firm_id = make_firm(db, city="Denver", state="CO")
    make_posting(
        db,
        source="careers",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2026, 6, 1),
        fetched_at=_dt(2026, 6, 1),
    )
    run_normalise(db)
    sig1 = fetch_one(
        db, "SELECT * FROM signal WHERE firm_id = %s AND kind = 'job_posting_open'", (firm_id,)
    )
    assert sig1["repost_count"] == 0

    # the board re-lists it a month later -- same fingerprint (same firm/role/metro/
    # week-of-earliest), board_posted_date moved forward.
    make_posting(
        db,
        source="careers",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2026, 7, 1),
        fetched_at=_dt(2026, 7, 1),
    )
    run_normalise(db)
    sig2 = fetch_one(db, "SELECT * FROM signal WHERE id = %s", (sig1["id"],))

    assert sig2["repost_count"] == 1
    assert sig2["first_seen"] == sig1["first_seen"]  # immutable
    assert sig2["last_seen"] > sig1["last_seen"]


def test_second_repost_reaches_weight_bearing_count_of_two(db):
    firm_id = make_firm(db, city="Denver", state="CO")
    for month_day, fetch_day in [((6, 1), (6, 1)), ((7, 1), (7, 1)), ((8, 1), (8, 1))]:
        make_posting(
            db,
            source="careers",
            firm_id=firm_id,
            title="Paralegal",
            city="Denver",
            state="CO",
            board_posted_date=date(2026, *month_day),
            fetched_at=_dt(2026, *fetch_day),
        )
        run_normalise(db)

    sig = fetch_one(
        db, "SELECT * FROM signal WHERE firm_id = %s AND kind = 'job_posting_open'", (firm_id,)
    )
    assert sig["repost_count"] == 2


# =============================================================================
# multi_opening
# =============================================================================


def test_multi_opening_fires_for_two_concurrent_open_roles(db):
    firm_id = make_firm(db, city="Denver", state="CO")
    make_posting(
        db, source="careers", firm_id=firm_id, title="Paralegal", city="Denver", state="CO"
    )
    make_posting(
        db, source="careers", firm_id=firm_id, title="Legal Assistant", city="Denver", state="CO"
    )
    run_normalise(db)

    open_roles = fetch_all(
        db,
        "SELECT * FROM signal WHERE firm_id = %s AND kind = 'job_posting_open' "
        "AND closed_at IS NULL",
        (firm_id,),
    )
    assert len(open_roles) == 2

    multi = fetch_one(
        db, "SELECT * FROM signal WHERE firm_id = %s AND kind = 'multi_opening'", (firm_id,)
    )
    assert multi is not None
    assert multi["evidence"]["open_job_posting_count"] == 2
    # The renderer's 1C opener needs the roles themselves ("{role} and {role_2}").
    roles = {r["canonical_role"] for r in multi["evidence"]["roles"]}
    assert roles == {"paralegal", "legal_assistant"}


def test_multi_opening_evidence_renders_the_1c_opener(db):
    # Contract test across the writer (JA6) and the reader (journey renderer):
    # the evidence JA6 writes must resolve {role} and {role_2}.
    from lge.journey.tokens import role_from_evidence

    firm_id = make_firm(db, city="Denver", state="CO")
    make_posting(db, source="careers", firm_id=firm_id, title="Paralegal", city="Denver",
                 state="CO")
    make_posting(db, source="careers", firm_id=firm_id, title="Case Manager", city="Denver",
                 state="CO")
    run_normalise(db)
    multi = fetch_one(
        db, "SELECT evidence FROM signal WHERE firm_id = %s AND kind = 'multi_opening'",
        (firm_id,),
    )
    rendered = {role_from_evidence(r) for r in multi["evidence"]["roles"]}
    assert None not in rendered
    assert len(rendered) == 2


def test_multi_opening_stays_one_open_signal_across_weeks(db):
    # The live re-sweep three days later minted a second multi_opening for the
    # same two roles at BSL and Dressie, and the first never closed (D-026).
    firm_id = make_firm(db, city="Denver", state="CO")
    for day in (1, 11):
        make_posting(
            db, source="careers", firm_id=firm_id, title="Paralegal", city="Denver", state="CO",
            source_url="https://smithlaw.com/careers/", fetched_at=_dt(2026, 7, day),
        )
        make_posting(
            db, source="careers", firm_id=firm_id, title="Legal Assistant", city="Denver",
            state="CO", source_url="https://smithlaw.com/careers/", fetched_at=_dt(2026, 7, day),
        )
        run_normalise(db)

    multis = fetch_all(
        db, "SELECT * FROM signal WHERE firm_id = %s AND kind = 'multi_opening'", (firm_id,)
    )
    open_multis = [m for m in multis if m["closed_at"] is None]
    assert len(open_multis) == 1
    assert open_multis[0]["evidence"]["open_job_posting_count"] == 2

    # A pure re-run changes nothing.
    run_normalise(db)
    again = fetch_all(
        db, "SELECT id, closed_at FROM signal WHERE firm_id = %s AND kind = 'multi_opening'",
        (firm_id,),
    )
    assert [(m["id"], m["closed_at"]) for m in again] == [(m["id"], m["closed_at"]) for m in multis]


def test_multi_opening_does_not_fire_for_a_single_open_role(db):
    firm_id = make_firm(db, city="Denver", state="CO")
    make_posting(
        db, source="careers", firm_id=firm_id, title="Paralegal", city="Denver", state="CO"
    )
    run_normalise(db)
    multi = fetch_one(
        db, "SELECT 1 FROM signal WHERE firm_id = %s AND kind = 'multi_opening'", (firm_id,)
    )
    assert multi is None


# =============================================================================
# Pure re-run: identical rejects/signals/sightings, and never a forbidden UPDATE
# (if one were attempted, the I6 trigger would raise and these calls would fail
# outright rather than silently producing a different result)
# =============================================================================


def test_rerun_with_no_new_rows_writes_nothing_new(db):
    firm_id = make_firm(db, city="Denver", state="CO")
    make_posting(
        db,
        source="careers",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2026, 6, 1),
        fetched_at=_dt(2026, 6, 1),
    )
    run_normalise(db)
    sig1 = fetch_one(db, "SELECT * FROM signal WHERE firm_id = %s", (firm_id,))
    sightings1 = fetch_all(db, "SELECT id FROM signal_sighting WHERE signal_id = %s", (sig1["id"],))

    run_normalise(db)  # no new raw_posting rows at all

    sig2 = fetch_one(db, "SELECT * FROM signal WHERE firm_id = %s", (firm_id,))
    sightings2 = fetch_all(db, "SELECT id FROM signal_sighting WHERE signal_id = %s", (sig1["id"],))
    assert sig1 == sig2
    assert sightings1 == sightings2


def test_pure_rerun_over_a_mixed_dataset_is_byte_identical(db):
    firm_id = make_firm(db, city="Denver", state="CO", name_stem=norm_name("Smith Law"))
    make_posting(db, source="careers", company_name="Robert Half", title="Paralegal")
    make_posting(
        db,
        source="careers",
        firm_id=firm_id,
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2026, 6, 1),
        fetched_at=_dt(2026, 6, 1),
    )
    make_posting(
        db, source="bar_board:co", company_name="Nobody Knows This Firm", city="Nowhereville"
    )

    def snapshot():
        return (
            fetch_all(db, "SELECT * FROM job_posting_rejected ORDER BY raw_posting_id"),
            fetch_all(db, "SELECT * FROM signal ORDER BY id"),
            fetch_all(db, "SELECT * FROM signal_sighting ORDER BY id"),
            fetch_all(db, "SELECT * FROM posting_resolution ORDER BY raw_posting_id"),
            fetch_all(db, "SELECT * FROM discovery_lead ORDER BY raw_posting_id"),
        )

    run_normalise(db)
    first = snapshot()
    run_normalise(db)
    second = snapshot()
    run_normalise(db)
    third = snapshot()

    assert first == second == third


# =============================================================================
# internal_jobs -- never a signal, always the four fit claims
# =============================================================================


def _latest_attrs(conn, firm_id) -> dict[str, object]:
    rows = fetch_all(
        conn,
        "SELECT DISTINCT ON (attr) attr, value FROM firm_attribute "
        "WHERE firm_id = %s AND source = 'internal_jobs' ORDER BY attr, observed_at DESC",
        (firm_id,),
    )
    return {r["attr"]: r["value"] for r in rows}


def test_internal_jobs_never_creates_a_signal_and_writes_the_four_fit_claims(db):
    firm_id = make_firm(db, city="Denver", state="CO", name_stem=norm_name("Smith & Associates"))
    make_posting(
        db,
        source="internal_jobs",
        company_name="Smith & Associates",
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2025, 1, 1),
    )
    make_posting(
        db,
        source="internal_jobs",
        company_name="Smith & Associates",
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2025, 6, 1),
    )
    make_posting(
        db,
        source="internal_jobs",
        company_name="Smith & Associates",
        title="Legal Assistant",
        city="Denver",
        state="CO",
        board_posted_date=date(2025, 3, 1),
    )

    run_normalise(db)

    signals = fetch_all(db, "SELECT 1 FROM signal WHERE firm_id = %s", (firm_id,))
    assert signals == []

    attrs = _latest_attrs(db, firm_id)
    assert attrs["has_hired_support_roles"] is True
    assert sorted(attrs["support_roles_posted"]) == ["legal_assistant", "paralegal"]
    assert attrs["last_known_hiring_attempt"] == "2025-06-01"
    # "paralegal" posted twice, ~5 months apart -> two distinct week-fingerprints;
    # "legal_assistant" posted once -> max over roles is 2.
    assert attrs["repeat_role_count"] == 2


def test_internal_jobs_still_goes_through_the_agency_filter(db):
    raw_id = make_posting(
        db, source="internal_jobs", company_name="Robert Half", title="Paralegal"
    )
    run_normalise(db)
    rejected = fetch_one(
        db, "SELECT rule FROM job_posting_rejected WHERE raw_posting_id = %s", (raw_id,)
    )
    assert rejected["rule"] == "known_agency"


def test_internal_jobs_claims_are_idempotent_on_rerun(db):
    firm_id = make_firm(db, city="Denver", state="CO", name_stem=norm_name("Smith & Associates"))
    make_posting(
        db,
        source="internal_jobs",
        company_name="Smith & Associates",
        title="Paralegal",
        city="Denver",
        state="CO",
        board_posted_date=date(2025, 1, 1),
    )
    run_normalise(db)
    count1 = fetch_one(
        db,
        "SELECT count(*) AS n FROM firm_attribute WHERE firm_id = %s AND source = 'internal_jobs'",
        (firm_id,),
    )["n"]
    run_normalise(db)
    count2 = fetch_one(
        db,
        "SELECT count(*) AS n FROM firm_attribute WHERE firm_id = %s AND source = 'internal_jobs'",
        (firm_id,),
    )["n"]
    assert count1 == count2 == 4
