"""GET /api/firms, GET /api/firms/{id}."""

from __future__ import annotations

import pytest

from tests.conftest import make_firm

from .conftest import make_contact, make_firm_attribute

pytestmark = pytest.mark.db


def test_firm_detail_lists_each_page_once_at_its_latest_fetch(client, db):
    firm_id = make_firm(db, canonical_name="Twice Crawled")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, status_code, content_hash, bytes, word_count, "
            "fetch_ok, page_kind, fetched_at) VALUES "
            "(%s, 'https://tc.example/contact', 200, 'h1', 10, 50, true, 'contact', "
            " now() - interval '30 days'), "
            "(%s, 'https://tc.example/contact', 200, 'h2', 12, 80, true, 'contact', now()), "
            "(%s, 'https://tc.example/', 200, 'h3', 10, 400, true, 'home', now())",
            (firm_id, firm_id, firm_id),
        )
    resp = client.get(f"/api/firms/{firm_id}")
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert [d["url"] for d in docs].count("https://tc.example/contact") == 1
    contact = next(d for d in docs if d["url"] == "https://tc.example/contact")
    assert contact["words"] == 80  # the latest fetch


def test_firm_detail_lists_the_firm_contacts_with_linkedin(client, db):
    # The route looked contacts up by the path string while the query keyed
    # them by uuid: every firm page showed no contacts (found 15 Sep 2026).
    firm_id = make_firm(db, canonical_name="People Firm")
    make_contact(
        db, firm_id, full_name="Margaret Hartley", title="Founding Partner",
        role="owner", source="site:page",
        linkedin_url="https://www.linkedin.com/in/mhartley/",
    )
    make_contact(db, firm_id, full_name="Priya Raman", title="Office Manager", role="admin")

    resp = client.get(f"/api/firms/{firm_id}")
    assert resp.status_code == 200
    contacts = {c["full_name"]: c for c in resp.json()["contacts"]}
    assert set(contacts) == {"Margaret Hartley", "Priya Raman"}
    assert contacts["Margaret Hartley"]["linkedin_url"] == "https://www.linkedin.com/in/mhartley/"
    assert contacts["Margaret Hartley"]["source_label"] == "Firm website (page text)"
    assert contacts["Priya Raman"]["linkedin_url"] is None


def test_list_firms_search_by_name_and_domain(client, db):
    make_firm(db, canonical_name="Findable Law Group", domain="findable-law.example.com")
    make_firm(db, canonical_name="Someone Else PLLC", domain="someoneelse.example.com")

    resp = client.get("/api/firms", params={"q": "Findable"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Findable Law Group"

    resp2 = client.get("/api/firms", params={"q": "someoneelse.example.com"})
    assert resp2.json()["total"] == 1
    assert resp2.json()["items"][0]["name"] == "Someone Else PLLC"


def test_firm_not_found(client):
    resp = client.get("/api/firms/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_firm_record_marks_the_winning_claim(client, db):
    # cms_detected's precedence (config/precedence.yml) is rules:p7 >
    # internal_firms, and it is not tier-determining, so a disagreement
    # resolves to a clean precedence winner rather than a P9-escalation
    # conflict (unlike fee_model/primary_practice/attorney_count).
    firm_id = make_firm(db, canonical_name="CMS Firm", cms_detected="filevine")
    make_firm_attribute(
        db, firm_id, "cms_detected", "filevine", "rules:p7",
        confidence=0.9, evidence="powered by Filevine",
    )
    make_firm_attribute(
        db, firm_id, "cms_detected", "clio", "internal_firms", confidence=0.5,
    )

    resp = client.get(f"/api/firms/{firm_id}")
    assert resp.status_code == 200
    body = resp.json()
    cms_row = next(a for a in body["attributes"] if a["attr"] == "cms_detected")
    assert cms_row["display"] == "Filevine"
    assert cms_row["state"] == "resolved"

    by_source = {c["source_label"]: c for c in cms_row["claims"]}
    winners = [c for c in cms_row["claims"] if c["won"]]
    assert len(winners) == 1
    assert winners[0]["display"] == "Filevine"
    assert by_source["Firm website (page code)"]["won"] is True
    assert by_source["Purchased firm list"]["won"] is False


def test_firm_unknown_attribute_shows_not_guessed(client, db):
    firm_id = make_firm(db, canonical_name="Unknown Practice Firm")
    make_firm_attribute(db, firm_id, "primary_practice", "unknown", "llm:p8:v1", confidence=0.5)

    resp = client.get(f"/api/firms/{firm_id}")
    body = resp.json()
    row = next(a for a in body["attributes"] if a["attr"] == "primary_practice")
    assert row["display"] == "Unknown — not guessed"
    assert row["state"] == "unknown"


def test_firm_conflict_state_when_open_reconcile_conflict_exists(client, db):
    firm_id = make_firm(db, canonical_name="Conflicted Firm", attorney_count=None)
    make_firm_attribute(db, firm_id, "attorney_count", 5, "llm:p8:v1", confidence=0.4)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO reconcile_conflict (firm_id, attr, claims, reason) "
            "VALUES (%s, 'attorney_count', '[]'::jsonb, 'test conflict')",
            (firm_id,),
        )

    resp = client.get(f"/api/firms/{firm_id}")
    body = resp.json()
    row = next(a for a in body["attributes"] if a["attr"] == "attorney_count")
    assert row["state"] == "conflict"


def test_firm_informational_attribute_included_with_clear_label(client, db):
    firm_id = make_firm(db, canonical_name="Vendor Hint Firm")
    make_firm_attribute(
        db, firm_id, "vendor_practice_hint", "immigration", "internal_firms", confidence=0.5
    )

    resp = client.get(f"/api/firms/{firm_id}")
    body = resp.json()
    row = next(a for a in body["attributes"] if a["attr"] == "vendor_practice_hint")
    assert "not used for tier" in row["label"].lower()


def test_the_google_listing_and_its_reviews_are_their_own_section_on_the_firm(client, db):
    """r_listing (D-062): the profile and the reviews come back typed, never
    as a wall of JSON, and a firm without a listing says so with null."""
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com")
    before = client.get(f"/api/firms/{firm_id}").json()
    assert before["listing"] is None
    assert before["listing_note"].startswith("Not looked up yet.")
    assert "Google Places key" in before["listing_note"]  # no provider on a keyless machine
    make_firm_attribute(
        db, firm_id, "business_listing",
        {"name": "Hartley Injury Law, P.C.", "category": "Personal Injury Attorney",
         "address": "1 Peachtree St NE, Atlanta, GA 30303, USA", "phone": "(404) 555-0100",
         "website": "https://hartleylaw.com/", "rating": 4.8, "review_count": 212,
         "url": "https://maps.google.com/?cid=42", "status": "operational"},
        "listing:google_places", confidence=0.9,
    )
    make_firm_attribute(
        db, firm_id, "google_reviews",
        [{"author": "R. Diaz", "rating": 2, "date": "2026-07-10",
          "text": "Nobody called me back for three weeks.", "url": None},
         {"author": "x", "rating": 4, "date": None, "text": "", "url": None}],
        "listing:google_places", confidence=0.9,
    )
    body = client.get(f"/api/firms/{firm_id}").json()
    listing = body["listing"]
    assert body["listing_note"] is None
    assert listing["name"] == "Hartley Injury Law, P.C."
    assert listing["notes"] == []
    assert listing["rating"] == 4.8 and listing["review_count"] == 212
    assert listing["phone"] == "(404) 555-0100"
    assert listing["source_label"] == "Google Business Profile (Google Places API)"
    assert body["reviews"] == [{
        "author": "R. Diaz", "rating": 2, "date": "2026-07-10",
        "text": "Nobody called me back for three weeks.", "url": None,
    }]
    # and the claims table shows the profile in words, not JSON
    row = next(a for a in body["attributes"] if a["attr"] == "business_listing")
    assert row["label"] == "Google Business Profile"
    assert row["display"].startswith("Hartley Injury Law, P.C.; Personal Injury Attorney")
    reviews_row = next(a for a in body["attributes"] if a["attr"] == "google_reviews")
    assert reviews_row["display"].startswith("2 review(s); latest: Nobody called")


def test_the_listing_says_where_it_disagrees_with_the_firm_and_why_there_is_none(client, db):
    """A website that is not the firm's domain and an address the site does
    not print are said on the screen (D-062); a looked-up firm with no match
    says so instead of showing nothing."""
    firm_id = make_firm(db, canonical_name="Duron Law", domain="duronlaw.com")
    make_firm_attribute(
        db, firm_id, "address",
        {"street_norm": "100 W MADISON ST", "unit": None, "city": "CHICAGO", "state": "IL",
         "zip5": "60602", "addr_hash": "abc"},
        "site:page", confidence=0.8, evidence="100 W Madison St, Chicago, IL 60602",
    )
    make_firm_attribute(
        db, firm_id, "business_listing",
        {"name": "Duron Law", "address": "1 Wall St, New York, NY 10005, USA",
         "website": "https://www.duron-legal.com/", "rating": 4.0, "review_count": 3},
        "listing:serper", confidence=0.9,
    )
    listing = client.get(f"/api/firms/{firm_id}").json()["listing"]
    assert listing["notes"] == [
        "The listing's website (duron-legal.com) is not the firm's domain (duronlaw.com).",
        "The site prints a different address: 100 W Madison St, Chicago, IL 60602.",
    ]

    other = make_firm(db, canonical_name="Nobody Law", domain="nobodylaw.com")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO search_log (firm_id, kind, query, outcome, results, engine) "
            "VALUES (%s, 'listing', 'Nobody Law', 'not_found', '[]', 'serper')", (other,),
        )
    body = client.get(f"/api/firms/{other}").json()
    assert body["listing"] is None
    assert body["listing_note"] == "No Google listing matched this firm's name and place."
