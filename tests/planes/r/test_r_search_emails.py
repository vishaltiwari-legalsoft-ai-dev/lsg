"""r_search_emails: addresses read off search snippets attach to the named
person they render from (or the person the snippet names), general and
hiring inboxes become claims, off-domain addresses are recorded but never
attached, queries are logged once and failures retried."""

from __future__ import annotations

import pytest

from lge.planes.r import r_search_emails
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx
from tests.planes.r.test_r_search_links import Recorder
from tests.planes.r.test_r_site_contacts import _insert_contact

pytestmark = pytest.mark.db


def _emails(conn, firm_id) -> dict[str, list[tuple[str, str]]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.full_name, e.email, e.pattern FROM contact c "
            "LEFT JOIN contact_email e ON e.contact_id = c.id WHERE c.firm_id = %s "
            "ORDER BY c.full_name, e.email",
            (firm_id,),
        )
        out: dict[str, list[tuple[str, str]]] = {}
        for r in cur.fetchall():
            out.setdefault(r["full_name"], [])
            if r["email"]:
                out[r["full_name"]].append((r["email"], r["pattern"]))
        return out


def _log(conn, firm_id) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind, outcome FROM search_log WHERE firm_id = %s ORDER BY id", (firm_id,)
        )
        return [(r["kind"], r["outcome"]) for r in cur.fetchall()]


def _claims(conn, firm_id) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT attr, value, evidence FROM firm_attribute WHERE firm_id = %s "
            "AND source = 'search:ddg'",
            (firm_id,),
        )
        return {r["attr"]: r for r in cur.fetchall()}


def test_queries():
    assert r_search_emails.firm_query("hartleylaw.com") == '"@hartleylaw.com"'
    assert r_search_emails.person_query("Hartley Injury Law", "Margaret Hartley") == (
        '"Margaret Hartley" "Hartley Injury Law" email'
    )


def test_emails_in_results_splits_on_and_off_domain():
    results = [
        {"title": "Georgia Bar - Margaret Hartley", "href": "https://gabar.org/x",
         "body": "Email: margaret.hartley@hartleylaw.com Phone (404) 555-0142"},
        {"title": "Contact", "href": "https://hartleylaw.com/contact",
         "body": "info@hartleylaw.com or hartleylawatl@gmail.com; logo@2x.png"},
    ]
    on, off = r_search_emails.emails_in_results(results, "hartleylaw.com")
    assert set(on) == {"margaret.hartley@hartleylaw.com", "info@hartleylaw.com"}
    assert set(off) == {"hartleylawatl@gmail.com"}


def test_attach_for_person_by_pattern_then_by_the_snippet_naming_them():
    person = {"full_name": "Margaret Hartley"}
    by_pattern = {"mhartley@hartleylaw.com": {"title": "", "body": "", "href": ""}}
    assert r_search_emails.attach_for_person(person, by_pattern) == (
        "mhartley@hartleylaw.com", "flast"
    )
    named = {"mjh@hartleylaw.com": {"title": "Margaret Hartley | Avvo", "body": "", "href": ""}}
    assert r_search_emails.attach_for_person(person, named) == ("mjh@hartleylaw.com", "other")
    someone_else = {"jdoe@hartleylaw.com": {"title": "John Doe", "body": "", "href": ""}}
    assert r_search_emails.attach_for_person(person, someone_else) is None


def test_search_finds_attaches_claims_and_logs(db):
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com")
    _insert_contact(db, firm_id, full_name="Margaret Hartley", role="owner", confidence=0.9)
    _insert_contact(db, firm_id, full_name="Priya Raman", role="admin", confidence=0.8)
    _insert_contact(db, firm_id, full_name="Tom Becker", role="attorney", confidence=0.6)
    search = Recorder({
        '"@hartleylaw.com"': [
            {"title": "Hartley Injury Law - Justia", "href": "https://justia.com/h",
             "body": "info@hartleylaw.com · careers@hartleylaw.com · tbecker@hartleylaw.com"},
            {"title": "Some Blog", "href": "https://blog.example/",
             "body": "reach hartley.injury@gmail.com"},
        ],
        '"Margaret Hartley"': [
            {"title": "Margaret Hartley - State Bar of Georgia", "href": "https://gabar.org/m",
             "body": "Email margaret.hartley@hartleylaw.com"},
        ],
        '"Priya Raman"': [
            {"title": "Priya Raman - Office Manager", "href": "https://avvo.com/p",
             "body": "Priya Raman can be reached at pr@hartleylaw.com"},
        ],
    })

    result = r_search_emails.run(ctx(db, live=True), search=search)
    assert result.processed == 1 and result.failed == 0, result.notes

    emails = _emails(db, firm_id)
    assert emails["Margaret Hartley"] == [("margaret.hartley@hartleylaw.com", "first.last")]
    assert emails["Priya Raman"] == [("pr@hartleylaw.com", "other")]  # named beside it
    assert emails["Tom Becker"] == [("tbecker@hartleylaw.com", "flast")]  # from the firm query

    claims = _claims(db, firm_id)
    assert claims["general_email"]["value"] == "info@hartleylaw.com"
    assert claims["hiring_email"]["value"] == "careers@hartleylaw.com"
    entries = {e["email"]: e for e in claims["search_emails"]["value"]}
    assert entries["hartley.injury@gmail.com"]["on_domain"] is False
    assert entries["tbecker@hartleylaw.com"]["on_domain"] is True

    log = _log(db, firm_id)
    assert log[0] == ("emails", "found")
    assert ("person_email", "found") in log
    assert search.queries[0] == '"@hartleylaw.com"'
    assert search.queries[1] == '"Margaret Hartley" "Hartley Injury Law" email'  # owner first

    again = r_search_emails.run(ctx(db, live=True), search=search)
    assert again.processed == 0
    assert len(search.queries) == 3  # Tom got his address from the firm query: never searched


def test_off_domain_addresses_are_never_attached(db):
    firm_id = make_firm(db, canonical_name="Solo Law", domain="sololaw.com")
    _insert_contact(db, firm_id, full_name="Sam Solo", role="owner", confidence=0.9)
    search = Recorder({
        "": [{"title": "Sam Solo", "href": "https://x/", "body": "Sam Solo samsolo@gmail.com"}],
    })
    r_search_emails.run(ctx(db, live=True), search=search)
    assert _emails(db, firm_id)["Sam Solo"] == []
    assert _claims(db, firm_id)["search_emails"]["value"][0]["on_domain"] is False


def test_failed_queries_are_retried_and_nothing_runs_without_live(db):
    firm_id = make_firm(db, canonical_name="Flaky", domain="flaky.com")
    _insert_contact(db, firm_id, full_name="Fay Flaky", role="owner", confidence=0.9)
    off = r_search_emails.run(ctx(db, live=False), search=Recorder())
    assert "live=0" in " ".join(off.notes) and _log(db, firm_id) == []

    failing = Recorder({"": [{"title": "", "href": "", "body": "search failed: Timeout"}]})
    r_search_emails.run(ctx(db, live=True), search=failing)
    assert _log(db, firm_id) == [("emails", "failed"), ("person_email", "failed")]

    working = Recorder()
    r_search_emails.run(ctx(db, live=True), search=working)
    assert len(working.queries) == 2
    r_search_emails.run(ctx(db, live=True), search=working)
    assert len(working.queries) == 2
