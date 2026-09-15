"""px_site_facts component: the fixture site's pages become site:page claims
(phone, address, people, testimonials, posts, links, gaps); a soft-404 page is
never read; a re-run over unchanged pages is a no-op."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lge.planes.p import px_site_facts
from lge.store.objects import ObjectStore
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx, insert_document, make_lead

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"
_BASE = "https://hartleylaw.com/"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _claims(conn, firm_id) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT attr, value, source, confidence, evidence, observed_at FROM firm_attribute "
            "WHERE firm_id = %s AND source = 'site:page'",
            (firm_id,),
        )
        return {r["attr"]: r for r in cur.fetchall()}


def _site(db, store, *, with_news=True, with_careers=False) -> str:
    firm_id = make_firm(db, domain="hartleylaw.com")
    make_lead(db, firm_id)
    home = (
        "<html><body><h1>Hartley Injury Law</h1><p>Atlanta personal injury attorneys.</p>"
        "<a href='/contact/'>Contact</a><footer>&copy; 2026</footer></body></html>"
    )
    insert_document(db, store, firm_id, home, url=_BASE, page_kind="home")
    insert_document(db, store, firm_id, _fixture("site_contact_page.html"),
                    url=_BASE + "contact/", page_kind="contact")
    insert_document(db, store, firm_id, _fixture("site_team_page.html"),
                    url=_BASE + "our-team/", page_kind="team")
    insert_document(db, store, firm_id, _fixture("site_testimonials_page.html"),
                    url=_BASE + "reviews/", page_kind="testimonials")
    if with_news:
        insert_document(db, store, firm_id, _fixture("site_news_page.html"),
                        url=_BASE + "news/", page_kind="news")
    if with_careers:
        insert_document(db, store, firm_id, "<html><body><h1>Careers</h1></body></html>",
                        url=_BASE + "careers/", page_kind="careers")
    return firm_id


def test_the_site_becomes_claims(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = _site(db, store)

    result = px_site_facts.run(ctx(db), store=store)
    assert result.processed == 1 and result.failed == 0, result.notes

    claims = _claims(db, firm_id)
    assert claims["phone_e164"]["value"] == "+14045550142"
    assert claims["phone_e164"]["evidence"] == "+1-404-555-0142"
    assert claims["address"]["value"]["street_norm"] == "3350 PEACHTREE RD NE"
    assert claims["address"]["value"]["zip5"] == "30326"
    assert claims["city"]["value"] == "ATLANTA"
    assert claims["office_count"]["value"] == 2
    assert [o["city"] for o in claims["office_locations"]["value"]] == ["ATLANTA", "MARIETTA"]

    people = {p["name"]: p for p in claims["site_people"]["value"]}
    assert people["Dana Whitfield"]["title"] == "Senior Litigation Paralegal"
    assert people["Margaret Hartley"]["url"] == _BASE + "our-team/margaret-hartley/"
    assert claims["staff_listed"]["value"] == {
        "attorneys": 2, "support": 2, "other": 1, "total": 5
    }

    assert len(claims["testimonials"]["value"]) == 3
    assert claims["site_review_summary"]["value"]["count"] == 312
    assert set(claims["social_links"]["value"]) == {"facebook", "linkedin"}
    assert set(claims["review_profiles"]["value"]) == {"avvo", "yelp"}
    assert claims["google_maps_url"]["value"].startswith("https://www.google.com/maps/")

    assert claims["latest_post_date"]["value"] == "2026-08-12"
    assert len(claims["recent_posts"]["value"]) == 3
    assert [g["cue"] for g in claims["growth_news"]["value"]] == [
        "opens new marietta office", "joins"
    ]

    assert claims["live_chat_vendor"]["value"] == "Intaker"
    assert claims["online_intake_form"]["value"] is True
    assert claims["copyright_year"]["value"] == 2026  # the newest footer wins

    gaps = {g["gap"] for g in claims["site_gaps"]["value"]}
    assert gaps == {"no_careers_page"}
    assert all(c["source"] == "site:page" for c in claims.values())


def test_a_bare_name_on_the_attorneys_page_is_an_attorney(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="listed.example")
    make_lead(db, firm_id)
    page = (
        "<html><body><h1>Our Attorneys</h1>"
        "<a href='/attorneys/christopher-hall/'><h3>Christopher B. Hall</h3></a>"
        "<a href='/attorneys/andrew-lampros/'><h3>Andrew Lampros</h3></a>"
        "<h3>Practice Areas</h3></body></html>"
    )
    insert_document(db, store, firm_id, page, url="https://listed.example/attorneys/",
                    page_kind="attorneys")
    px_site_facts.run(ctx(db), store=store)
    people = {p["name"]: p for p in _claims(db, firm_id)["site_people"]["value"]}
    assert set(people) == {"Christopher B. Hall", "Andrew Lampros"}
    assert people["Andrew Lampros"]["title"] == "Attorney"
    assert people["Andrew Lampros"]["title_inferred"] is True
    assert _claims(db, firm_id)["staff_listed"]["value"]["attorneys"] == 2


def test_gaps_name_what_the_pages_read_lack(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="quiet.example")
    make_lead(db, firm_id)
    home = (
        "<html><body><h1>Quiet Law</h1><p>Call 404-555-0100.</p>"
        "<p>&copy; 2021 Quiet Law</p></body></html>"
    )
    insert_document(db, store, firm_id, home, url="https://quiet.example/", page_kind="home")
    team = (
        "<html><body><h2>Sam Quiet</h2><p class='title'>Attorney at Law</p></body></html>"
    )
    insert_document(db, store, firm_id, team, url="https://quiet.example/team/",
                    page_kind="team")

    px_site_facts.run(ctx(db), store=store)
    claims = _claims(db, firm_id)
    gaps = {g["gap"] for g in claims["site_gaps"]["value"]}
    assert gaps == {
        "no_careers_page", "no_online_intake", "no_live_chat", "no_spanish", "stale_copyright",
        "no_testimonials", "no_news", "no_support_staff_listed", "no_social_presence",
        "no_review_link",
    }
    assert claims["online_intake_form"]["value"] is False
    assert claims["phone_e164"]["value"] == "+14045550100"


def test_no_gap_list_without_pages_and_soft_404s_are_not_read(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="gone.example")
    make_lead(db, firm_id)
    doc_id = insert_document(
        db, store, firm_id, _fixture("site_contact_page.html"),
        url="https://gone.example/contact/", page_kind="contact",
    )
    with db.cursor() as cur:
        cur.execute("UPDATE document SET soft_404 = true WHERE id = %s", (doc_id,))

    result = px_site_facts.run(ctx(db), store=store)
    assert result.processed == 0 and result.skipped == 1
    assert _claims(db, firm_id) == {}


def test_rerun_over_unchanged_pages_is_a_no_op(db, tmp_path):
    store = ObjectStore(tmp_path)
    _site(db, store, with_careers=True)
    first = px_site_facts.run(ctx(db), store=store)
    assert first.processed == 1
    second = px_site_facts.run(ctx(db), store=store)
    assert second.processed == 0 and second.skipped == 1


def test_claims_carry_the_page_fetch_time(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = _site(db, store)
    when = datetime(2026, 5, 1, tzinfo=UTC)
    with db.cursor() as cur:
        cur.execute("UPDATE document SET fetched_at = %s WHERE firm_id = %s", (when, firm_id))
    px_site_facts.run(ctx(db), store=store)
    claims = _claims(db, firm_id)
    assert claims["phone_e164"]["observed_at"] == when
    assert claims["site_gaps"]["observed_at"] == when
