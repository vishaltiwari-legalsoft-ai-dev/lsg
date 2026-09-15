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
