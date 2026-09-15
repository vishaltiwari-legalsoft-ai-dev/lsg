"""r3_email_pattern tests: learn a firm's local-part pattern from known
`contact_email` rows on its domain, apply it only to contacts with no email
at all. Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,060,070 \
        uv run pytest tests/planes/r -q
"""

from __future__ import annotations

import uuid

import pytest

from lge.planes.r import r3_email_pattern
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_contact(conn, firm_id, full_name, **cols) -> str:
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols["full_name"] = full_name
    columns = list(cols.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({', '.join(columns)}) VALUES ({placeholders}) "  # noqa: S608
            "RETURNING id",
            [cols[c] for c in columns],
        )
        return cur.fetchone()["id"]


def _insert_contact_email(conn, contact_id, email, *, status="unverified", vendor_status=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status, vendor_status) "
            "VALUES (%s, %s, %s, %s)",
            (contact_id, email, status, vendor_status),
        )


def _email_pattern_claims(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value, confidence FROM firm_attribute "
            "WHERE firm_id = %s AND attr = 'email_pattern'",
            (firm_id,),
        )
        return cur.fetchall()


def _contact_emails(conn, contact_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email, status, pattern FROM contact_email WHERE contact_id = %s", (contact_id,)
        )
        return cur.fetchall()


def test_learns_first_last_and_applies_to_site_derived_owner(db):
    firm_id = make_firm(db, domain="acmelaw.com", country="US")

    smith = _insert_contact(db, firm_id, "John Smith", source="internal_firms")
    _insert_contact_email(db, smith, "john.smith@acmelaw.com", vendor_status="verified")
    roe = _insert_contact(db, firm_id, "Jane Roe", source="internal_firms")
    _insert_contact_email(db, roe, "jane.roe@acmelaw.com", vendor_status="verified")

    owner = _insert_contact(db, firm_id, "New Owner", role="owner", source="site:llm")

    result = r3_email_pattern.run(_ctx(db))
    assert result.processed == 1
    assert result.failed == 0

    claims = _email_pattern_claims(db, firm_id)
    assert len(claims) == 1
    assert claims[0]["value"] == {"pattern": "first.last", "support": 2}
    assert float(claims[0]["confidence"]) == 0.85

    owner_emails = _contact_emails(db, owner)
    assert len(owner_emails) == 1
    assert owner_emails[0]["email"] == "new.owner@acmelaw.com"
    assert owner_emails[0]["status"] == "unverified"
    assert owner_emails[0]["pattern"] == "first.last"


def test_refuses_freemail_domain(db):
    firm_id = make_firm(db, domain="gmail.com", country="US")
    smith = _insert_contact(db, firm_id, "John Smith", source="internal_firms")
    _insert_contact_email(db, smith, "john.smith@gmail.com")
    owner = _insert_contact(db, firm_id, "New Owner", role="owner", source="site:llm")

    result = r3_email_pattern.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 1
    assert _email_pattern_claims(db, firm_id) == []
    assert _contact_emails(db, owner) == []


def test_refuses_foreign_firm(db):
    firm_id = make_firm(db, domain="foreignfirm.ca", country="CA")
    smith = _insert_contact(db, firm_id, "John Smith", source="internal_firms")
    _insert_contact_email(db, smith, "john.smith@foreignfirm.ca")
    another_smith = _insert_contact(db, firm_id, "Jane Smith", source="internal_firms")
    _insert_contact_email(db, another_smith, "jane.smith@foreignfirm.ca")
    owner = _insert_contact(db, firm_id, "New Owner", role="owner", source="site:llm")

    result = r3_email_pattern.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 1
    assert _email_pattern_claims(db, firm_id) == []
    assert _contact_emails(db, owner) == []


def test_split_evidence_needs_support_of_at_least_two(db):
    firm_id = make_firm(db, domain="splitfirm.com", country="US")
    # Three known emails, three DIFFERENT patterns -- no pattern reaches the
    # >=2 agreeing-examples bar, and there is more than one known email, so
    # the single-email exception does not apply either.
    a = _insert_contact(db, firm_id, "Alan Ames", source="internal_firms")
    _insert_contact_email(db, a, "alan.ames@splitfirm.com")  # first.last
    b = _insert_contact(db, firm_id, "Beth Bell", source="internal_firms")
    _insert_contact_email(db, b, "bbell@splitfirm.com")  # flast
    c = _insert_contact(db, firm_id, "Carl Cole", source="internal_firms")
    _insert_contact_email(db, c, "carl@splitfirm.com")  # first
    owner = _insert_contact(db, firm_id, "New Owner", role="owner", source="site:llm")

    result = r3_email_pattern.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 1
    assert _email_pattern_claims(db, firm_id) == []
    assert _contact_emails(db, owner) == []


def test_single_known_email_accepted_at_support_one(db):
    firm_id = make_firm(db, domain="soloshop.com", country="US")
    only = _insert_contact(db, firm_id, "Sam Solo", source="internal_firms")
    _insert_contact_email(db, only, "sam.solo@soloshop.com")
    owner = _insert_contact(db, firm_id, "New Owner", role="owner", source="site:llm")

    result = r3_email_pattern.run(_ctx(db))
    assert result.processed == 1

    claims = _email_pattern_claims(db, firm_id)
    assert claims[0]["value"] == {"pattern": "first.last", "support": 1}
    assert float(claims[0]["confidence"]) == 0.6

    owner_emails = _contact_emails(db, owner)
    assert owner_emails[0]["email"] == "new.owner@soloshop.com"


@pytest.mark.parametrize(
    "email,pattern",
    [
        ("john.smith@x.com", "first.last"),
        ("jsmith@x.com", "flast"),
        ("john@x.com", "first"),
        ("johns@x.com", "firstl"),
        ("smith@x.com", "last"),
        ("johnsmith@x.com", "firstlast"),
        ("john_smith@x.com", "first_last"),
        ("smithj@x.com", "lastf"),
        ("j.smith@x.com", "f.last"),
        ("smith.john@x.com", "last.first"),
        ("smithjohn@x.com", "lastfirst"),
        ("jls@x.com", "other"),
    ],
)
def test_infer_and_render_cover_the_schemes_seen_on_the_probe(email, pattern):
    from lge.planes.r.r3_email_pattern import infer_pattern, render_pattern

    assert infer_pattern("John Q. Smith", email) == pattern
    if pattern != "other":
        assert render_pattern("John Q. Smith", pattern) == email.split("@")[0]


def test_idempotent_rerun_applies_nothing_new(db):
    firm_id = make_firm(db, domain="rerunfirm.com", country="US")
    smith = _insert_contact(db, firm_id, "John Smith", source="internal_firms")
    _insert_contact_email(db, smith, "john.smith@rerunfirm.com")
    roe = _insert_contact(db, firm_id, "Jane Roe", source="internal_firms")
    _insert_contact_email(db, roe, "jane.roe@rerunfirm.com")
    owner = _insert_contact(db, firm_id, "New Owner", role="owner", source="site:llm")

    first = r3_email_pattern.run(_ctx(db))
    assert first.processed == 1
    assert len(_contact_emails(db, owner)) == 1

    second = r3_email_pattern.run(_ctx(db))
    assert second.processed == 0
    assert second.skipped == 1
    assert len(_contact_emails(db, owner)) == 1  # never re-applied / duplicated
