"""i1_claims — resolved internal_firms observations -> firm_attribute claims."""

from __future__ import annotations

from pathlib import Path

import pytest

from lge.planes.i.i1_firms import i1_claims, i1_load
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "vendor_sample.csv"


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _resolve_domain_to_firm(conn, domain: str, firm_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE observation SET firm_id = %s "
            "WHERE source = 'internal_firms' AND domain = %s",
            (firm_id, domain),
        )


def _claims(conn, firm_id: str, attr: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM firm_attribute WHERE firm_id = %s AND attr = %s",
            (firm_id, attr),
        )
        return cur.fetchall()


@pytest.fixture
def loaded(db):
    """i1_load the fixture, then simulate identity resolution: bigfirm.com's 12
    contacts, the .gov domain, and the wixsite-fallback domain each resolve to
    their own firm. The gmail-only row is left unresolved (firm_id stays NULL) --
    exactly like a real firm identity resolution can't be done on."""
    i1_load(_ctx(db), path=str(FIXTURE))
    bigfirm_id = make_firm(db, canonical_name="Bigfirm Pllc", name_stem="bigfirm")
    gov_id = make_firm(db, canonical_name="Smallcounty DA", name_stem="smallcounty da")
    janedoe_id = make_firm(db, canonical_name="Jane Doe Law", name_stem="jane doe law")
    _resolve_domain_to_firm(db, "bigfirm.com", bigfirm_id)
    _resolve_domain_to_firm(db, "smallcountyda.gov", gov_id)
    _resolve_domain_to_firm(db, "janedoelaw.com", janedoe_id)
    return {"bigfirm": bigfirm_id, "gov": gov_id, "janedoe": janedoe_id}


def test_never_writes_attorney_count(loaded, db):
    i1_claims(_ctx(db))
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm_attribute WHERE attr = 'attorney_count'")
        assert cur.fetchone()["n"] == 0


def test_ignores_unresolved_observations(loaded, db):
    # the gmail-only contact's firm_id is still NULL -- i1_claims must not crash
    # or invent a firm for it.
    result = i1_claims(_ctx(db))
    assert result.processed == 3  # bigfirm, gov, janedoe -- not the unresolved row


def test_canonical_name_and_city_claims(loaded, db):
    i1_claims(_ctx(db))
    name_rows = _claims(db, loaded["bigfirm"], "canonical_name")
    assert len(name_rows) == 1
    assert name_rows[0]["value"] == "Bigfirm Pllc"
    assert float(name_rows[0]["confidence"]) == 0.5
    assert name_rows[0]["source"] == "internal_firms"

    city_rows = _claims(db, loaded["bigfirm"], "city")
    assert city_rows[0]["value"] == "Austin"
    assert float(city_rows[0]["confidence"]) == 0.5


def test_country_claim_is_us(loaded, db):
    i1_claims(_ctx(db))
    rows = _claims(db, loaded["bigfirm"], "country")
    assert rows[0]["value"] == "US"
    assert float(rows[0]["confidence"]) == 0.7


def test_gov_entity_kind_from_gov_domain(loaded, db):
    i1_claims(_ctx(db))
    rows = _claims(db, loaded["gov"], "entity_kind")
    assert len(rows) == 1
    assert rows[0]["value"] == "gov"
    assert float(rows[0]["confidence"]) == 0.95
    assert "smallcountyda.gov" in rows[0]["evidence"]


def test_private_firm_entity_kind_from_industry(loaded, db):
    i1_claims(_ctx(db))
    rows = _claims(db, loaded["bigfirm"], "entity_kind")
    assert len(rows) == 1
    assert rows[0]["value"] == "private_firm"
    assert float(rows[0]["confidence"]) == 0.4


def test_cms_detected_from_filevine_tag(loaded, db):
    i1_claims(_ctx(db))
    rows = _claims(db, loaded["bigfirm"], "cms_detected")
    assert len(rows) == 1
    assert rows[0]["value"] == "filevine"
    assert rows[0]["evidence"] == "vendor technology tag: filevine"


def test_vendor_description_is_a_practice_hint_never_primary_practice(loaded, db):
    # Doc 02 §4: vendor practice data is coarse; it steers the crawl but never sets
    # primary_practice — a blurb-keyword read disqualified real prospects when it could.
    i1_claims(_ctx(db))
    assert _claims(db, loaded["bigfirm"], "primary_practice") == []
    assert _claims(db, loaded["bigfirm"], "practice_areas") == []

    hint_rows = _claims(db, loaded["bigfirm"], "vendor_practice_hint")
    assert hint_rows[0]["value"]["primary"] == "personal_injury"
    assert hint_rows[0]["value"]["areas"] == ["personal_injury"]
    assert float(hint_rows[0]["confidence"]) == 0.5  # min(0.5, norm_practice's 1.0)


def test_vendor_headcount_range_and_size_contradiction(loaded, db):
    i1_claims(_ctx(db))
    hc_rows = _claims(db, loaded["bigfirm"], "vendor_headcount_range")
    assert hc_rows[0]["value"] == "1 to 10"
    assert float(hc_rows[0]["confidence"]) == 0.5

    contradiction_rows = _claims(db, loaded["bigfirm"], "vendor_size_contradiction")
    assert len(contradiction_rows) == 1
    assert contradiction_rows[0]["value"] == {"contacts_in_file": 12, "stated": "1 to 10"}
    assert float(contradiction_rows[0]["confidence"]) == 0.9

    # janedoe has exactly 1 contact -- no contradiction
    assert _claims(db, loaded["janedoe"], "vendor_size_contradiction") == []


def test_idempotent_rerun_adds_no_rows(loaded, db):
    ctx = _ctx(db)
    first = i1_claims(ctx)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm_attribute")
        first_count = cur.fetchone()["n"]
    assert first_count > 0

    second = i1_claims(ctx)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm_attribute")
        second_count = cur.fetchone()["n"]

    assert second_count == first_count
    assert second.processed == first.processed
    assert second.skipped == first_count  # every attempted claim row was a duplicate
