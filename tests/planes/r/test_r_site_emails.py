"""r_site_emails: addresses printed on the firm's own pages -> the matching
named contact, or the firm's general/hiring inbox claims. Never guessed onto a
person, never off-domain, never re-fetched."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from lge.planes.r import r_site_emails
from lge.planes.r.r_site_emails import extract_site_emails, local_kind, match_contact
from lge.registry import RunContext
from lge.settings import get_settings
from lge.store.objects import ObjectStore
from tests.conftest import make_firm

pytestmark = pytest.mark.db

_PAGE = b"""<html><body>
<a href="mailto:Michelle@DressieLaw.com?subject=Hello">Email Michelle</a>
<p>General questions: info@dressielaw.com &middot; careers: hiring&#64;dressielaw.com</p>
<p>Jane can be reached at jdoe [at] dressielaw [dot] com</p>
<p>Not ours: someone@gmail.com, help@wixpress.com, and photo@dressielaw.com.png</p>
<script>window.cfg={"support":"ops@dressielaw.com"}</script>
</body></html>"""


def test_extract_reads_mailto_text_entities_and_at_spelling_on_domain_only():
    got = extract_site_emails(_PAGE.decode(), "dressielaw.com")
    assert got == [
        "hiring@dressielaw.com",
        "info@dressielaw.com",
        "jdoe@dressielaw.com",
        "michelle@dressielaw.com",
        "ops@dressielaw.com",
    ]
    assert extract_site_emails("", "dressielaw.com") == []


@pytest.mark.parametrize(
    "email,kind",
    [
        ("info@f.com", "general"), ("intake@f.com", "general"), ("hiring@f.com", "hiring"),
        ("careers@f.com", "hiring"), ("michelle@f.com", "person"), ("dfried@f.com", "person"),
    ],
)
def test_local_kind(email, kind):
    assert local_kind(email) == kind


def test_match_contact_needs_exactly_one_name():
    contacts = [
        {"id": "1", "full_name": "Michelle Dressie"},
        {"id": "2", "full_name": "Emanuel Dressie"},
    ]
    assert match_contact("michelle@dressielaw.com", contacts) == (contacts[0], "first")
    assert match_contact("edressie@dressielaw.com", contacts) == (contacts[1], "flast")
    # "dressie@" renders for both people under the 'last' pattern -> nobody
    assert match_contact("dressie@dressielaw.com", contacts) is None
    assert match_contact("jdoe@dressielaw.com", contacts) is None


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_document(conn, firm_id, object_key, url="https://dressielaw.com/contact-us/"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, status_code, content_hash, object_key, bytes, "
            "fetch_ok, page_kind, fetched_at) VALUES (%s, %s, 200, %s, %s, 0, true, 'contact', %s)",
            (firm_id, url, object_key, object_key, datetime(2026, 9, 15, tzinfo=UTC)),
        )


def _insert_contact(conn, firm_id, full_name, role="owner") -> str:
    cid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact (id, firm_id, full_name, role, source) "
            "VALUES (%s, %s, %s, %s, 'site:llm')",
            (cid, firm_id, full_name, role),
        )
    return cid


def _emails(conn, contact_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email, status, pattern FROM contact_email WHERE contact_id = %s ORDER BY email",
            (contact_id,),
        )
        return cur.fetchall()


def _claim(conn, firm_id, attr):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value, source, evidence FROM firm_attribute WHERE firm_id = %s AND attr = %s "
            "ORDER BY observed_at DESC LIMIT 1",
            (firm_id, attr),
        )
        return cur.fetchone()


def test_site_emails_attach_to_the_named_contact_and_inboxes_become_claims(db, tmp_path):
    store = ObjectStore(tmp_path)
    key = store.put(_PAGE)
    firm_id = make_firm(db, domain="dressielaw.com")
    _insert_document(db, firm_id, key)
    michelle = _insert_contact(db, firm_id, "Michelle Dressie")
    emanuel = _insert_contact(db, firm_id, "Emanuel Dressie")

    result = r_site_emails.run(_ctx(db), store=store)
    assert result.processed == 1
    assert result.failed == 0

    assert _emails(db, michelle) == [
        {"email": "michelle@dressielaw.com", "status": "unverified", "pattern": "first"}
    ]
    assert _emails(db, emanuel) == []  # nothing on the page renders to his name

    assert _claim(db, firm_id, "general_email")["value"] == "info@dressielaw.com"
    assert _claim(db, firm_id, "hiring_email")["value"] == "hiring@dressielaw.com"
    site = _claim(db, firm_id, "site_emails")
    assert site["source"] == "site:page"
    assert site["evidence"] == "https://dressielaw.com/contact-us/"
    assert "jdoe@dressielaw.com" in site["value"]  # kept for provenance, attached to nobody

    # Unchanged pages and people: a re-run is free.
    again = r_site_emails.run(_ctx(db), store=store)
    assert again.skipped == 1 and again.processed == 0

    # A contact added later (a new AI pass) re-runs the attach step.
    jane = _insert_contact(db, firm_id, "Jane Doe", role="admin")
    third = r_site_emails.run(_ctx(db), store=store)
    assert third.processed == 1
    assert _emails(db, jane) == [
        {"email": "jdoe@dressielaw.com", "status": "unverified", "pattern": "flast"}
    ]


def test_off_domain_pages_and_firms_without_documents_are_skipped(db, tmp_path):
    store = ObjectStore(tmp_path)
    key = store.put(b"<html><body><a href='mailto:owner@otherfirm.com'>x</a></body></html>")
    firm_id = make_firm(db, domain="thisfirm.com")
    _insert_document(db, firm_id, key, url="https://thisfirm.com/")
    _insert_contact(db, firm_id, "Owner Person")
    make_firm(db, domain="nodocs.com")

    result = r_site_emails.run(_ctx(db), store=store)
    assert result.failed == 0
    assert _claim(db, firm_id, "site_emails") is None
