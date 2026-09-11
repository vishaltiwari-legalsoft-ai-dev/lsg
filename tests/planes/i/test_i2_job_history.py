from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lge.planes.i.i2_job_history import _parse_city_state, _parse_post_date, i2_job_history_load
from lge.registry import RunContext
from lge.settings import get_settings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "job_history_sample.csv"


def ctx(db) -> RunContext:
    return RunContext(db, get_settings())


def raw_postings(db, source="internal_jobs"):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM raw_posting WHERE source = %s ORDER BY id", (source,))
        return cur.fetchall()


# =============================================================================
# City/state and date parsing -- pure helpers, no DB needed
# =============================================================================


def test_parse_city_state_only_city_comma_state():
    assert _parse_city_state("Denver, CO") == ("Denver", "CO")
    assert _parse_city_state("Grand Prairie, TX") == ("Grand Prairie", "TX")


@pytest.mark.parametrize(
    "value", ["United States", "Remote", "United States (+2 others)", "OR", "", "Colorado"]
)
def test_parse_city_state_non_city_shapes_are_null(value):
    assert _parse_city_state(value) == (None, None)


def test_parse_post_date():
    assert _parse_post_date("Jul 20, 2026") == date(2026, 7, 20)


def test_parse_post_date_unparseable_returns_none():
    assert _parse_post_date("not a date") is None


# =============================================================================
# The loader itself
# =============================================================================


def test_load_inserts_every_row_with_expected_mapping(db):
    result = i2_job_history_load(ctx(db), path=str(FIXTURE))
    rows = raw_postings(db)

    assert result.processed == 10
    assert result.failed == 0
    assert len(rows) == 10
    assert all(r["source"] == "internal_jobs" for r in rows)
    assert all(r["source_url"] is None for r in rows)
    assert all(r["fetch_ok"] for r in rows)

    denver = next(r for r in rows if r["company_name"] == "Robert Half")
    assert denver["city"] == "Denver"
    assert denver["state"] == "CO"
    assert denver["location_raw"] == "Denver, CO"
    assert denver["board_posted_date"] == date(2026, 7, 19)
    assert denver["title"] == "Personal Injury Paralegal"
    assert denver["payload"]["Company"] == "Robert Half"

    remote = next(r for r in rows if r["company_name"] == "Upwork")
    assert remote["city"] is None
    assert remote["state"] is None

    us = next(r for r in rows if r["company_name"] == "Confidential")
    assert us["city"] is None
    assert us["state"] is None

    blank_company = next(r for r in rows if r["title"] == "Demand Writer")
    assert blank_company["company_name"] is None


def test_load_is_idempotent(db):
    first = i2_job_history_load(ctx(db), path=str(FIXTURE))
    second = i2_job_history_load(ctx(db), path=str(FIXTURE))

    assert first.processed == 10
    assert second.processed == 0
    assert second.skipped == 10
    assert len(raw_postings(db)) == 10


def test_missing_file_fails_loudly_not_silently(db):
    result = i2_job_history_load(ctx(db), path="data/in/does-not-exist.csv")
    assert result.failed == 1
    assert result.processed == 0
    assert raw_postings(db) == []


def test_limit_opt_restricts_row_count(db):
    result = i2_job_history_load(ctx(db), path=str(FIXTURE), limit=3)
    assert result.processed == 3
    assert len(raw_postings(db)) == 3


def test_exact_duplicate_row_within_the_file_is_written_once(db, tmp_path):
    # Seen in the real file: 261 of its 2,730 rows are byte-identical repeats.
    # source_key = sha1(row) means every repeat hashes the same -- one insert,
    # every occurrence accounted for as skipped, never a duplicate raw_posting.
    csv_path = tmp_path / "dupes.csv"
    csv_path.write_text(
        "Job Title,Company,Practice Area,Seniority,Firm Location,Work Type,Post Date,Status\n"
        'Paralegal,Smith Law,Litigation,,"Denver, CO",In-House,"Jul 20, 2026",New\n'
        'Paralegal,Smith Law,Litigation,,"Denver, CO",In-House,"Jul 20, 2026",New\n'
        'Paralegal,Smith Law,Litigation,,"Denver, CO",In-House,"Jul 20, 2026",New\n'
        'Legal Assistant,Other Firm,IP,,"Austin, TX",In-House,"Jul 21, 2026",New\n',
        encoding="utf-8",
    )
    result = i2_job_history_load(ctx(db), path=str(csv_path))
    assert result.processed == 2  # the two distinct rows
    assert result.skipped == 2  # the two extra copies of the duplicate row
    assert result.failed == 0
    assert len(raw_postings(db)) == 2
