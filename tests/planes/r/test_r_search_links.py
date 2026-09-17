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
    remembers what it was asked. A key ending "#2" answers page two."""

    def __init__(self, table: dict[str, list[dict[str, str]]] | None = None):
        self.table = table or {}
        self.queries: list[str] = []

    def __call__(self, query: str, max_results: int, page: int = 1) -> list[dict[str, str]]:
        self.queries.append(query if page == 1 else f"{query} [page {page}]")
        for key, rows in self.table.items():
            if page > 1 and key.endswith(f"#{page}") and key[: -len(f"#{page}")] in query:
                return rows
            if page == 1 and "#" not in key and key in query:
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
    assert r_search_links.sweep_query("Hartley Injury Law") == (
        'site:linkedin.com "Hartley Injury Law"'
    )
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
        'site:linkedin.com "Hartley Injury Law"': [
            _li("Margaret Hartley - Founding Partner - Hartley Injury Law", "mhartley"),
            _li("Someone Else - Paralegal - Hartley Injury Law", "someone-else"),
            _li("Priya Raman - Office Manager - Some Other Firm", "praman"),
        ],
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
        ("linkedin", "found"), ("linkedin", "found"), ("sweep", "found"), ("reviews", "found"),
    ]
    # one sweep found both people: no query of their own was needed
    assert search.queries == [
        'site:linkedin.com "Hartley Injury Law" Atlanta',  # the city keeps namesakes apart
        '"Hartley Injury Law" Atlanta GA google business reviews',
    ]

    again = r_search_links.run(ctx(db, live=True), search=search)
    assert again.processed == 0
    assert len(search.queries) == 2  # nothing asked twice


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
        ("sweep", "not_found"), ("linkedin", "not_found"), ("reviews", "not_found")
    ]
    assert _claims(db, firm_id) == {}


def test_one_sweep_per_firm_then_a_query_for_each_decision_maker_it_missed(db):
    firm_id = make_firm(db, canonical_name="Big Firm")
    for name in ("Alan Ames", "Bea Bell", "Cal Cole"):
        _insert_contact(db, firm_id, full_name=name, role="attorney", confidence=0.5)
    _insert_contact(db, firm_id, full_name="Olive Oakes", role="owner", confidence=0.9)
    _insert_contact(db, firm_id, full_name="Adam Ashby", role="admin", confidence=0.7)
    search = Recorder({
        'site:linkedin.com "Big Firm"': [
            _li("Bea Bell - Associate - Big Firm", "bea-bell"),
            _li("Adam Ashby - Office Manager - Big Firm", "adam-ashby"),
        ],
    })
    r_search_links.run(ctx(db, live=True), search=search)
    assert search.queries[0] == 'site:linkedin.com "Big Firm"'
    people_queries = [q for q in search.queries if q.endswith('" linkedin')]
    # the owner the sweep missed gets a query; the attorneys never do
    assert people_queries == ['"Big Firm" "Olive Oakes" linkedin']
    with db.cursor() as cur:
        cur.execute("SELECT full_name, linkedin_url FROM contact WHERE firm_id = %s", (firm_id,))
        urls = {r["full_name"]: r["linkedin_url"] for r in cur.fetchall()}
    assert urls["Bea Bell"] == "https://www.linkedin.com/in/bea-bell/"
    assert urls["Adam Ashby"] == "https://www.linkedin.com/in/adam-ashby/"
    assert urls["Olive Oakes"] is None and urls["Alan Ames"] is None

    other = make_firm(db, canonical_name="Capped Firm")
    for name in ("Dee Dunn", "Eve Eames", "Fay Ford", "Gus Gale", "Hal Hart", "Ida Ives"):
        _insert_contact(db, other, full_name=name, role="unknown", confidence=0.5)
    capped = Recorder()
    r_search_links.run(ctx(db, live=True), search=capped, max_people="4")
    assert [q for q in capped.queries if "Capped Firm" in q] == [
        'site:linkedin.com "Capped Firm"', '"Capped Firm" google business reviews',
    ]


def test_a_full_first_page_with_people_still_missing_earns_a_second_page(db):
    firm_id = make_firm(db, canonical_name="Page Firm")
    for name in ("Ann Page", "Ben Page", "Cy Page"):
        _insert_contact(db, firm_id, full_name=name, role="attorney", confidence=0.5)
    first = [_li("Ann Page - Associate - Page Firm", "ann-page")] + [
        _li("Other Person - Paralegal - Page Firm", f"other-{i}") for i in range(7)
    ]
    search = Recorder({
        'site:linkedin.com "Page Firm"': first,
        'site:linkedin.com "Page Firm"#2': [_li("Ben Page - Associate - Page Firm", "ben-page")],
    })
    r_search_links.run(ctx(db, live=True), search=search)
    assert search.queries[:2] == [
        'site:linkedin.com "Page Firm"', 'site:linkedin.com "Page Firm" [page 2]',
    ]
    with db.cursor() as cur:
        cur.execute("SELECT full_name, linkedin_url FROM contact WHERE firm_id = %s", (firm_id,))
        urls = {r["full_name"]: r["linkedin_url"] for r in cur.fetchall()}
    assert urls["Ann Page"] and urls["Ben Page"] and urls["Cy Page"] is None
    assert not any('"Cy Page"' in q for q in search.queries)  # an attorney: no query of his own

    # a first page that was not full has no second page
    other = make_firm(db, canonical_name="Short Firm")
    _insert_contact(db, other, full_name="Sal Short", role="attorney", confidence=0.5)
    _insert_contact(db, other, full_name="Tia Short", role="attorney", confidence=0.5)
    short = Recorder({'site:linkedin.com "Short Firm"': [_li("Sal Short - Short Firm", "sal")]})
    r_search_links.run(ctx(db, live=True), search=short)
    assert not any("[page 2]" in q for q in short.queries)


def test_the_company_page_in_the_sweep_is_taken_and_junk_names_are_not_searched(db):
    firm_id = make_firm(db, canonical_name="Sattler Law Group PC")
    _insert_contact(db, firm_id, full_name="Sam Sattler", role="owner", confidence=0.9)
    _insert_contact(db, firm_id, full_name="About Us", role="unknown", confidence=0.4)
    search = Recorder({
        'site:linkedin.com "Sattler Law Group PC"': [
            {"title": "Sattler Law Group PC - LinkedIn", "body": "Law Practice · 2-10 employees",
             "href": "https://www.linkedin.com/company/sattler-law-group-pc"},
        ],
    })
    r_search_links.run(ctx(db, live=True), search=search)
    assert not any('"About Us"' in q for q in search.queries)
    assert not any("linkedin.com/company" in q for q in search.queries)
    claims = _claims(db, firm_id)
    assert claims["linkedin_company_url"]["value"] == (
        "https://www.linkedin.com/company/sattler-law-group-pc/"
    )
    assert claims["linkedin_headcount"]["value"] == "2-10"


def test_the_run_stops_at_its_query_budget(db):
    for name in ("Bea Budget", "Ben Bounds", "Bo Brake"):
        firm_id = make_firm(db, canonical_name=f"{name} Firm")
        _insert_contact(db, firm_id, full_name=name, role="owner", confidence=0.9)
    search = Recorder()
    result = r_search_links.run(ctx(db, live=True), search=search, max_queries="2")
    assert len(search.queries) == 2
    assert "budget" in " ".join(result.notes)


@pytest.mark.parametrize(
    "title,body,expected",
    [
        (
            "John Karpousis - Partner at Freehill Hogan & Mahar | LinkedIn",
            "Partner at Freehill Hogan & Mahar · Experience: Freehill Hogan & Mahar · "
            "Location: New York · 500+ connections on LinkedIn.",
            {"headline": "Partner at Freehill Hogan & Mahar", "company": "Freehill Hogan & Mahar",
             "location": "New York", "connections": "500+"},
        ),
        (
            "Sofia Zneimer - Lawyer at Zneimer & Zneimer p.c. | LinkedIn",
            "Lawyer at Zneimer & Zneimer p.c. · I am a passionate advocate for fair laws.",
            {"headline": "Lawyer at Zneimer & Zneimer p.c.", "company": "Zneimer & Zneimer p.c.",
             "location": None, "connections": None},
        ),
        ("Joseph Farella, Esq. - Farella Mascolo PLLC | LinkedIn", "",
         {"headline": "Farella Mascolo PLLC", "company": None, "location": None,
          "connections": None}),
        # several page titles glued together: the headline ends at the first "LinkedIn"
        ("Joseph Appio - Associate Attorney at Tanenbaum Keale LLP ...Joseph Appio posted on "
         "LinkedInTanenbaum Keale LLP associates Joseph Appio ...", "Location: Montclair",
         {"headline": "Associate Attorney at Tanenbaum Keale LLP", "company": "Tanenbaum Keale LLP",
          "location": "Montclair", "connections": None}),
    ],
)
def test_read_profile_reads_the_snippet(title, body, expected):
    assert r_search_links.read_profile({"title": title, "body": body, "href": ""}) == expected


def test_title_from_headline():
    assert r_search_links.title_from_headline("Partner at Freehill Hogan & Mahar") == "Partner"
    assert r_search_links.title_from_headline("Office Manager at Hartley Injury Law") == (
        "Office Manager"
    )
    assert r_search_links.title_from_headline("Farella Mascolo PLLC") is None
    assert r_search_links.title_from_headline("Helping firms grow") is None
    assert r_search_links.title_from_headline(None) is None


def test_the_headline_fills_a_missing_title_and_the_company_page_becomes_claims(db):
    firm_id = make_firm(db, canonical_name="Freehill Hogan & Mahar", city="New York", state="NY")
    contact_id = _insert_contact(db, firm_id, full_name="John Karpousis", role="unknown",
                                 confidence=0.5)
    search = Recorder({
        'site:linkedin.com "Freehill Hogan & Mahar"': [
            {"title": "John Karpousis - Partner at Freehill Hogan & Mahar | LinkedIn",
             "href": "https://www.linkedin.com/in/jkarpousis",
             "body": "Partner at Freehill Hogan & Mahar · Location: New York · 500+ connections"},
            {"title": "Freehill Hogan & Mahar | LinkedIn",
             "href": "https://www.linkedin.com/company/freehill-hogan-mahar",
             "body": "Freehill Hogan & Mahar · Law Practice · New York · 51-200 employees"},
        ],
    })
    result = r_search_links.run(ctx(db, live=True), search=search)
    assert result.failed == 0, result.notes
    with db.cursor() as cur:
        cur.execute("SELECT title, role, linkedin_url, linkedin_headline, linkedin_location "
                    "FROM contact WHERE id = %s", (contact_id,))
        row = cur.fetchone()
    assert row["title"] == "Partner" and row["role"] == "owner"
    assert row["linkedin_url"] == "https://www.linkedin.com/in/jkarpousis/"
    assert row["linkedin_headline"] == "Partner at Freehill Hogan & Mahar"
    assert row["linkedin_location"] == "New York"
    claims = _claims(db, firm_id)
    assert claims["linkedin_company_url"]["value"] == (
        "https://www.linkedin.com/company/freehill-hogan-mahar/"
    )
    assert claims["linkedin_headcount"]["value"] == "51-200"
    assert any(
        r["kind"] == "company" and r["outcome"] == "found" for r in _search_log(db, firm_id)
    )


def test_nothing_runs_without_live(db):
    firm_id = make_firm(db, canonical_name="Quiet Firm")
    _insert_contact(db, firm_id, full_name="Quinn Quiet", role="owner", confidence=0.9)
    search = Recorder()
    result = r_search_links.run(ctx(db, live=False), search=search)
    assert search.queries == []
    assert "live=0" in " ".join(result.notes)
    assert _search_log(db, firm_id) == []


def test_five_failures_in_a_row_stop_the_run(db):
    # Three firms, four people each: twelve queries would be asked. With the
    # network gone the run stops after five, and says so.
    dead = Recorder({"": [{"title": "", "href": "", "body": "search failed: ConnectError"}]})
    names = iter(("Ann Able", "Bob Baker", "Cam Cross", "Dan Dole", "Eli East", "Flo Fair",
                  "Gil Grant", "Hope Hill", "Ian Ingle", "Joy Jones", "Kim Kerr", "Lee Lane"))
    for i in range(3):
        firm_id = make_firm(db, canonical_name=f"Dead Firm {i}")
        for _ in range(4):
            _insert_contact(db, firm_id, full_name=next(names), role="attorney", confidence=0.5)
    result = r_search_links.run(ctx(db, live=True), search=dead)
    assert len(dead.queries) == 5
    assert "stopped early" in " ".join(result.notes)


def test_a_failed_search_is_logged_as_failed_and_retried_next_run(db):
    firm_id = make_firm(db, canonical_name="Flaky Firm")
    _insert_contact(db, firm_id, full_name="Fay Flaky", role="owner", confidence=0.9)
    failing = Recorder({"": [{"title": "", "href": "", "body": "search failed: Timeout: x"}]})
    r_search_links.run(ctx(db, live=True), search=failing)
    log = _search_log(db, firm_id)
    assert [r["outcome"] for r in log] == ["failed", "failed", "failed"]

    # a failed query is asked again next run; a found/not-found one is not
    working = Recorder({'" linkedin': [_li("Fay Flaky - Owner - Flaky Firm", "fay-flaky")]})
    r_search_links.run(ctx(db, live=True), search=working)
    assert len(working.queries) == 3
    outcomes = [r["outcome"] for r in _search_log(db, firm_id)]
    assert outcomes.count("found") == 1 and outcomes.count("not_found") == 2
    r_search_links.run(ctx(db, live=True), search=working)
    assert len(working.queries) == 3  # nothing asked a third time


def test_queries_carry_the_city_when_the_firm_has_one():
    assert r_search_links.sweep_query("Hartley Injury Law", "Atlanta") == (
        'site:linkedin.com "Hartley Injury Law" Atlanta'
    )
    assert r_search_links.linkedin_query("Hartley Injury Law", "Margaret Hartley", "Atlanta") == (
        '"Hartley Injury Law" "Margaret Hartley" Atlanta linkedin'
    )
    assert r_search_links.places_query("Hartley Injury Law", "Atlanta", "GA") == (
        "Hartley Injury Law Atlanta GA"
    )
    assert r_search_links.pick_listing("Hartley Injury Law", [
        {"name": "Hartley Dental"}, {"name": "Hartley Injury Law, P.C.", "rating": 4.9},
    ])["rating"] == 4.9
    assert r_search_links.pick_listing("Hartley Injury Law", [{"name": "Hartley Dental"}]) is None
    # a listing whose category is not a law practice is never the firm
    assert r_search_links.pick_listing("Smith Law", [
        {"name": "Smith Legal", "category": "Dentist"},
    ]) is None
    assert r_search_links.pick_listing("Hartley Injury Law", None) is None


def test_a_listing_from_the_engine_beats_the_snippets(db):
    """When the engine has a listings endpoint, the Google Business Profile is
    read from it -- rating, count, the listing's own URL -- and the snippet
    query is never asked (D-045)."""
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com",
                        city="Atlanta", state="GA")
    search = Recorder({})
    listings = [{"name": "Hartley Injury Law", "address": "1 Peachtree St, Atlanta, GA",
                 "rating": 4.8, "review_count": 212, "phone": None, "website": None,
                 "url": "https://www.google.com/maps?cid=123"}]
    asked: list[str] = []

    def places(query):
        asked.append(query)
        return listings

    result = r_search_links.run(ctx(db, live=True), search=search, places=places)
    assert result.processed == 1
    assert asked == ["Hartley Injury Law Atlanta GA"]
    assert not any("google business reviews" in q for q in search.queries)
    with db.cursor() as cur:
        cur.execute(
            "SELECT attr, value, confidence FROM firm_attribute WHERE firm_id = %s "
            "AND attr IN ('google_rating', 'review_count', 'google_business_url') ORDER BY attr",
            (firm_id,),
        )
        claims = {r["attr"]: r for r in cur.fetchall()}
        cur.execute(
            "SELECT outcome, url, rating, review_count, engine FROM search_log "
            "WHERE firm_id = %s AND kind = 'reviews'", (firm_id,),
        )
        log = cur.fetchone()
    assert claims["google_rating"]["value"] == 4.8 and claims["review_count"]["value"] == 212
    assert claims["google_business_url"]["value"] == "https://www.google.com/maps?cid=123"
    assert float(claims["review_count"]["confidence"]) == 0.85
    assert log["outcome"] == "found" and log["review_count"] == 212 and log["engine"] == "ddg"
