"""i1_contacts — resolved internal_firms observations -> contact + contact_email."""

from __future__ import annotations

from pathlib import Path

import pytest

from lge.planes.i.i1_firms import i1_contacts, i1_load
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


@pytest.fixture
def loaded(db):
    i1_load(_ctx(db), path=str(FIXTURE))
    bigfirm_id = make_firm(db, canonical_name="Bigfirm Pllc", name_stem="bigfirm")
    gov_id = make_firm(db, canonical_name="Smallcounty DA", name_stem="smallcounty da")
    janedoe_id = make_firm(db, canonical_name="Jane Doe Law", name_stem="jane doe law")
    _resolve_domain_to_firm(db, "bigfirm.com", bigfirm_id)
    _resolve_domain_to_firm(db, "smallcountyda.gov", gov_id)
    _resolve_domain_to_firm(db, "janedoelaw.com", janedoe_id)
    return {"bigfirm": bigfirm_id, "gov": gov_id, "janedoe": janedoe_id}


def test_only_resolved_observations_produce_contacts(loaded, db):
    result = i1_contacts(_ctx(db))
    # 12 bigfirm + 1 janedoe + 1 gov = 14; the gmail-only row's firm_id is still
    # NULL (never resolved) and must not produce a contact.
    assert result.processed == 14
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM contact WHERE source = 'internal_firms'")
        assert cur.fetchone()["n"] == 14
        cur.execute("SELECT count(*) AS n FROM contact_email")
        assert cur.fetchone()["n"] == 14


def test_owner_and_office_manager_role_mapping(loaded, db):
    i1_contacts(_ctx(db))
    with db.cursor() as cur:
        cur.execute(
            "SELECT full_name, title, role, confidence FROM contact WHERE firm_id = %s",
            (loaded["bigfirm"],),
        )
        by_name = {r["full_name"]: r for r in cur.fetchall()}

    assert by_name["Jane Ownerly"]["role"] == "owner"
    assert by_name["Jane Ownerly"]["title"] == "Owner"
    assert float(by_name["Jane Ownerly"]["confidence"]) == 0.9

    assert by_name["Mike Chen"]["role"] == "admin"
    assert by_name["Mike Chen"]["title"] == "Office Manager"
    assert float(by_name["Mike Chen"]["confidence"]) == 0.9


def test_email_pattern_and_vendor_status(loaded, db):
    i1_contacts(_ctx(db))
    with db.cursor() as cur:
        cur.execute(
            "SELECT c.full_name, ce.email, ce.pattern, ce.status, ce.vendor_status "
            "FROM contact c JOIN contact_email ce ON ce.contact_id = c.id "
            "WHERE c.firm_id = %s",
            (loaded["bigfirm"],),
        )
        by_name = {r["full_name"]: r for r in cur.fetchall()}

    assert by_name["Jane Ownerly"]["email"] == "jane.ownerly@bigfirm.com"
    assert by_name["Jane Ownerly"]["pattern"] == "first.last"
    assert by_name["Mike Chen"]["email"] == "mchen@bigfirm.com"
    assert by_name["Mike Chen"]["pattern"] == "flast"

    for row in by_name.values():
        # OUR verification (R4) hasn't run -- status stays 'unverified' even
        # though the vendor calls the address 'verified'.
        assert row["status"] == "unverified"
        assert row["vendor_status"] == "verified"


def test_linkedin_url_from_vendor_column(loaded, db):
    i1_contacts(_ctx(db))
    with db.cursor() as cur:
        cur.execute(
            "SELECT linkedin_url FROM contact WHERE firm_id = %s AND full_name = 'Jane Ownerly'",
            (loaded["bigfirm"],),
        )
        row = cur.fetchone()
    assert row["linkedin_url"] == "https://linkedin.com/in/jane-ownerly"


def test_idempotent_rerun_adds_nothing(loaded, db):
    ctx = _ctx(db)
    i1_contacts(ctx)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM contact")
        first_count = cur.fetchone()["n"]

    second = i1_contacts(ctx)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM contact")
        second_count = cur.fetchone()["n"]

    assert second_count == first_count
    assert second.processed == 0
    assert second.skipped == first_count
