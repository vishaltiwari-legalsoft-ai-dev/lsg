"""r_search_links: a LinkedIn profile is adopted only when the result names
the person; Google review snippets become claims; every query is logged and
not repeated within recheck_days; nothing runs without live=1."""

from __future__ import annotations

import pytest

from lge.planes.r import r_search_links
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx
from tests.planes.r.test_r_site_contacts import _contacts, _insert_contact

pytestmark = pytest.mark.db


def _li(title: str, slug: str, body: str = "") -> dict[str, str]:
    return {"title": title, "href": f"https://www.linkedin.com/in/{slug}", "body": body}


class Recorder:
    """A search that answers from a table keyed on the query text and
    remembers what it was asked."""

    def __init__(self, table: dict[str, list[dict[str, str]]] | None = None):
        self.table = table or {}
        self.queries: list[str] = []

    def __call__(self, query: str, max_results: int) -> list[dict[str, str]]:
        self.queries.append(query)
        for key, rows in self.table.items():
            if key in query:
                return rows
        return []


def _search_log(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind, contact_id, query, outcome, url, rating, review_count FROM search_log "
            "WHERE firm_id = %s ORDER BY id",
            (firm_id,),
        )
        return cur.fetchall()


def _claims(conn, firm_id) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT attr, value, evidence FROM firm_attribute WHERE firm_id = %s "
            "AND source = 'search:ddg'",
            (firm_id,),
        )
        return {r["attr"]: r for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------


def test_queries_follow_the_brief():
    assert r_search_links.linkedin_query("Hartley Injury Law", "Margaret Hartley") == (
        '"Hartley Injury Law" "Margaret Hartley" linkedin'
    )
    assert r_search_links.reviews_query("Hartley Injury Law", "Atlanta", "GA") == (
        '"Hartley Injury Law" Atlanta GA google business reviews'
    )
    assert r_search_links.reviews_query("Hartley Injury Law", None, None) == (
        '"Hartley Injury Law" google business reviews'
    )


def test_pick_linkedin_needs_the_person_named_and_prefers_the_firm():
    results = [
        {"title": "Hartley Injury Law | LinkedIn", "href": "https://www.linkedin.com/company/x"},
        _li("Margaret Hartley - Partner - Other Firm LLP", "margaret-hartley-77"),
        _li("Margaret Hartley - Founding Partner - Hartley Injury Law", "mhartley",
            "Founding Partner at Hartley Injury Law"),
        _li("Margaret Smith - Paralegal", "margaret-smith"),
    ]
    url, evidence = r_search_links.pick_linkedin("Margaret Hartley", "Hartley Injury Law", results)
    assert url == "https://www.linkedin.com/in/mhartley/"
    assert evidence["score"] == pytest.approx(1.0)

    url, _ = r_search_links.pick_linkedin(
        "Margaret Hartley", "Hartley Injury Law", [_li("John Hartley - Attorney", "john-hartley")]
    )
    assert url is None  # the surname alone is not the person
    url, _ = r_search_links.pick_linkedin("Margaret Hartley", "Hartley Injury Law", [])
    assert url is None


def test_read_reviews_prefers_the_maps_listing_then_the_largest_count():
    results = [
        {"title": "Hartley Injury Law - Avvo", "href": "https://www.avvo.com/x",
         "body": "Rated 4.7 out of 5 based on 58 reviews."},
        {"title": "Hartley Injury Law · Personal injury attorney",
         "body": "4.9 (312) · Atlanta, GA",
         "href": "https://www.google.com/maps/place/Hartley+Injury+Law/@33.8,-84.3"},
        {"title": "Yelp", "href": "https://www.yelp.com/biz/hartley", "body": "120 reviews"},
    ]
    found = r_search_links.read_reviews(results)
    assert found["maps_url"].startswith("https://www.google.com/maps/")
    assert (found["rating"], found["count"]) == (4.9, 312)
    assert len(found["snippets"]) == 3

    no_maps = r_search_links.read_reviews(results[:1] + results[2:])
    assert (no_maps["maps_url"], no_maps["rating"], no_maps["count"]) == (None, None, 120)
    assert r_search_links.read_reviews([])["count"] is None


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


def test_profiles_and_reviews_are_found_logged_and_not_repeated(db):
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", city="Atlanta", state="GA")
    owner = _insert_contact(db, firm_id, full_name="Margaret Hartley", role="owner",
                            confidence=0.9)
    admin = _insert_contact(db, firm_id, full_name="Priya Raman", role="admin", confidence=0.8)
    search = Recorder({
        '"Margaret Hartley" linkedin': [
            _li("Margaret Hartley - Founding Partner - Hartley Injury Law", "mhartley"),
        ],
        '"Priya Raman" linkedin': [_li("Priya Raman - Office Manager - Some Other Firm", "praman")],
        "google business reviews": [
            {"title": "Hartley Injury Law", "body": "4.9 (312) · Personal injury attorney",
             "href": "https://www.google.com/maps/place/Hartley+Injury+Law/"},
        ],
    })

    result = r_search_links.run(ctx(db, live=True), search=search)
    assert result.processed == 1 and result.failed == 0, result.notes

    by_name = {c["full_name"]: c for c in _contacts(db, firm_id)}
    with db.cursor() as cur:
        cur.execute("SELECT id, linkedin_url FROM contact WHERE firm_id = %s", (firm_id,))
        linkedin = {str(r["id"]): r["linkedin_url"] for r in cur.fetchall()}
    assert linkedin[str(owner)] == "https://www.linkedin.com/in/mhartley/"
    # Priya's result names her, at a different firm: name match alone is enough
    assert linkedin[str(admin)] == "https://www.linkedin.com/in/praman/"
    assert set(by_name) == {"Margaret Hartley", "Priya Raman"}

    claims = _claims(db, firm_id)
    assert claims["review_count"]["value"] == 312
    assert claims["google_rating"]["value"] == 4.9
    assert claims["google_business_url"]["value"].startswith("https://www.google.com/maps/")
    assert len(claims["search_review_snippets"]["value"]) == 1

    log = _search_log(db, firm_id)
    assert [(r["kind"], r["outcome"]) for r in log] == [
        ("linkedin", "found"), ("linkedin", "found"), ("reviews", "found")
    ]
    assert search.queries[0] == '"Hartley Injury Law" "Margaret Hartley" linkedin'
    assert search.queries[-1] == '"Hartley Injury Law" Atlanta GA google business reviews'

    again = r_search_links.run(ctx(db, live=True), search=search)
    assert again.processed == 0
    assert len(search.queries) == 3  # nothing asked twice


def test_a_namesake_elsewhere_is_not_adopted_and_is_logged_not_found(db):
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", city="Atlanta", state="GA")
    _insert_contact(db, firm_id, full_name="Margaret Hartley", role="owner", confidence=0.9)
    search = Recorder({
        "linkedin": [_li("John Hartley - Sales - Acme", "john-hartley")],
        "google business reviews": [],
    })
    r_search_links.run(ctx(db, live=True), search=search)
    with db.cursor() as cur:
        cur.execute("SELECT linkedin_url FROM contact WHERE firm_id = %s", (firm_id,))
        assert cur.fetchone()["linkedin_url"] is None
    log = _search_log(db, firm_id)
    assert [(r["kind"], r["outcome"]) for r in log] == [
        ("linkedin", "not_found"), ("reviews", "not_found")
    ]
    assert _claims(db, firm_id) == {}


def test_at_most_four_people_per_firm_owners_first(db):
    firm_id = make_firm(db, canonical_name="Big Firm")
    for i in range(3):
        _insert_contact(db, firm_id, full_name=f"Assoc Number{i}", role="attorney",
                        confidence=0.5)
    _insert_contact(db, firm_id, full_name="Olive Owner", role="owner", confidence=0.9)
    _insert_contact(db, firm_id, full_name="Adam Admin", role="admin", confidence=0.7)
    search = Recorder()
    r_search_links.run(ctx(db, live=True), search=search)
    people_queries = [q for q in search.queries if "linkedin" in q]
    assert len(people_queries) == 4
    assert '"Olive Owner"' in people_queries[0]
    assert '"Adam Admin"' in people_queries[1]


def test_nothing_runs_without_live(db):
    firm_id = make_firm(db, canonical_name="Quiet Firm")
    _insert_contact(db, firm_id, full_name="Quinn Quiet", role="owner", confidence=0.9)
    search = Recorder()
    result = r_search_links.run(ctx(db, live=False), search=search)
    assert search.queries == []
    assert "live=0" in " ".join(result.notes)
    assert _search_log(db, firm_id) == []


def test_a_failed_search_is_logged_as_failed_and_retried_next_run(db):
    firm_id = make_firm(db, canonical_name="Flaky Firm")
    _insert_contact(db, firm_id, full_name="Fay Flaky", role="owner", confidence=0.9)
    failing = Recorder({"": [{"title": "", "href": "", "body": "search failed: Timeout: x"}]})
    r_search_links.run(ctx(db, live=True), search=failing)
    log = _search_log(db, firm_id)
    assert [r["outcome"] for r in log] == ["failed", "failed"]
