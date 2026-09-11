"""i1_load — CSV -> observation (source=internal_firms)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lge.norm import norm_name
from lge.planes.i.i1_firms import i1_load
from lge.registry import RunContext
from lge.settings import get_settings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "vendor_sample.csv"


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def test_reads_all_rows_and_inserts_observations(db):
    result = i1_load(_ctx(db), path=str(FIXTURE))
    assert result.processed == 15
    assert result.skipped == 0
    assert result.failed == 0
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM observation WHERE source = 'internal_firms'")
        assert cur.fetchone()["n"] == 15


def test_never_writes_firm(db):
    i1_load(_ctx(db), path=str(FIXTURE))
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm")
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT count(*) AS n FROM observation WHERE firm_id IS NOT NULL")
        assert cur.fetchone()["n"] == 0


def test_idempotent_reload_inserts_nothing_new(db):
    ctx = _ctx(db)
    first = i1_load(ctx, path=str(FIXTURE))
    assert first.processed == 15

    second = i1_load(ctx, path=str(FIXTURE))
    assert second.skipped == 1
    assert second.processed == 0

    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM observation WHERE source = 'internal_firms'")
        assert cur.fetchone()["n"] == 15


def test_domain_variants_collapse_fallback_and_no_domain(db):
    result = i1_load(_ctx(db), path=str(FIXTURE))
    with db.cursor() as cur:
        cur.execute(
            "SELECT domain, count(*) AS n FROM observation "
            "WHERE source = 'internal_firms' GROUP BY domain"
        )
        by_domain = {r["domain"]: r["n"] for r in cur.fetchall()}

    # https:// / http://www. / www....(trailing path) / bare-host variants of
    # bigfirm.com all collapse to one domain.
    assert by_domain["bigfirm.com"] == 12
    # wixsite.com is shared-host-blocked -> fell back to the firm's own email domain
    assert by_domain["janedoelaw.com"] == 1
    # .gov domain, resolved straight from Company URL
    assert by_domain["smallcountyda.gov"] == 1
    # gmail-only contact with no Company URL at all -> no domain identity
    assert by_domain[None] == 1

    assert "rows with no domain: 1" in result.notes
    assert "rows whose domain came from the email: 1" in result.notes
    assert "distinct domains: 3" in result.notes


def test_size_contradiction_reported_for_domain_with_12_contacts(db):
    result = i1_load(_ctx(db), path=str(FIXTURE))
    assert any("bigfirm.com -> 12 contacts" in note for note in result.notes)
    assert "size-contradiction domains (>10 contacts, file states 1-10 employees): 1" in (
        result.notes
    )


def test_payload_is_the_full_raw_row_and_name_stem_is_normalized(db):
    i1_load(_ctx(db), path=str(FIXTURE))
    with db.cursor() as cur:
        cur.execute(
            "SELECT payload, name_raw, name_stem FROM observation "
            "WHERE source = 'internal_firms' AND domain = 'smallcountyda.gov'"
        )
        row = cur.fetchone()

    assert row["payload"]["Job Title"] == "Assistant District Attorney"
    assert row["payload"]["Business Email"] == "info@smallcountyda.gov"
    assert row["name_raw"] == "Smallcounty District Attorney"
    assert row["name_stem"] == norm_name("Smallcounty District Attorney")


def test_city_prefers_company_city_and_falls_back_to_city(db):
    i1_load(_ctx(db), path=str(FIXTURE))
    with db.cursor() as cur:
        # Company City is blank on this row -> falls back to City="Boise"
        cur.execute(
            "SELECT city, state FROM observation WHERE source = 'internal_firms' "
            "AND payload ->> 'Business Email' = 'soloattorney@gmail.com'"
        )
        gmail_row = cur.fetchone()
        # Company City is present and used directly elsewhere
        cur.execute(
            "SELECT city FROM observation WHERE source = 'internal_firms' "
            "AND domain = 'bigfirm.com' LIMIT 1"
        )
        bigfirm_row = cur.fetchone()

    assert gmail_row["city"] == "Boise"
    assert gmail_row["state"] is None  # never embedded in City/Company City in this file
    assert bigfirm_row["city"] == "Austin"


def test_missing_path_raises(db):
    with pytest.raises(ValueError, match="path"):
        i1_load(_ctx(db))


def test_nonexistent_file_raises(db, tmp_path):
    with pytest.raises(FileNotFoundError):
        i1_load(_ctx(db), path=str(tmp_path / "does-not-exist.csv"))
