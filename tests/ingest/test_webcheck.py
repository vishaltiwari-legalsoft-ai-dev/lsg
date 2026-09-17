"""website_check: ok / mismatch -> corrected / missing -> searched / dead ->
found / blocked (never searched) / found domain owned by another firm ->
review, and the recheck window. The site fetch is mocked with respx, the
search with a recorder; nothing here touches the network."""

from __future__ import annotations

import httpx
import pytest
import respx

from lge.ingest import webcheck
from lge.ingest.webcheck import build_query, name_match, page_identity, pick_site
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx, make_lead

pytestmark = pytest.mark.db

UA = "TestBot/1.0 (+https://example.com/bot)"


class Recorder:
    def __init__(self, results=None):
        self.results = results or []
        self.queries: list[str] = []

    def __call__(self, query: str, max_results: int = 8):
        self.queries.append(query)
        return self.results


def _checks(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM website_check WHERE firm_id = %s ORDER BY id", (firm_id,)
        )
        return cur.fetchall()


def _firm_domain(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute("SELECT domain FROM firm WHERE id = %s", (firm_id,))
        return cur.fetchone()["domain"]


def _open_robots(host):
    respx.get(f"https://{host}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------


def test_name_match_ignores_law_words():
    assert name_match("Butler Kahn, PC", "Atlanta Personal Injury Lawyer - Butler Kahn") == 1.0
    assert name_match("Butler Kahn, PC", "Sunrise Bakery Atlanta") == 0.0
    assert name_match("Doe & Roe Law Group LLC", "Doe Roe attorneys") == 1.0
    assert name_match("Personal Injury Law Firm", "anything") == 0.5  # nothing to test


def test_pick_site_drops_directories_and_rewards_the_domain_name():
    results = [
        {"title": "Butler Kahn - Avvo", "href": "https://www.avvo.com/attorneys/butler",
         "body": ""},
        {"title": "Butler Kahn | Atlanta", "href": "https://www.lawyers.com/atlanta/butler-kahn",
         "body": ""},
        {"title": "Atlanta Injury Lawyers", "href": "https://butlerfirm.com/",
         "body": "Butler Kahn"},
        {"title": "Other Firm", "href": "https://otherfirm.com/", "body": "no match here"},
    ]
    domain, score, considered = pick_site("Butler Kahn, PC", results)
    assert domain == "butlerfirm.com" and score >= 0.5
    assert [c["domain"] for c in considered if c.get("skipped")] == ["avvo.com", "lawyers.com"]
    assert pick_site("Butler Kahn, PC", [])[0] is None


def test_page_identity_reads_title_and_jsonld():
    html = ('<html><head><title>Doe &amp; Roe | Atlanta</title>'
            '<script type="application/ld+json">{"@type":"LegalService","name":"Doe & Roe Law"}'
            '</script></head><body><p>We help injured people.</p></body></html>')
    ident = page_identity(html)
    assert ident["title"] == "Doe & Roe | Atlanta"
    assert "Doe & Roe Law" in ident["ld_names"]
    assert "injured people" in ident["text"]










def test_build_query():
    assert build_query("Doe & Roe", "Atlanta", "GA") == '"Doe & Roe" Atlanta GA law firm'
    assert build_query("Doe & Roe", None, None) == '"Doe & Roe" law firm'


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


@respx.mock
def test_site_that_names_the_firm_is_ok_and_never_searched(db):
    _open_robots("butlerfirm.com")
    respx.get("https://butlerfirm.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Butler Kahn - Atlanta "
                                              "Injury Lawyers</title></head><body></body></html>")
    )
    firm_id = make_firm(db, domain="butlerfirm.com", canonical_name="Butler Kahn, PC")
    make_lead(db, firm_id)
    search = Recorder()

    result = webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                                    default_interval_s="0")
    assert result.processed == 1 and result.failed == 0
    checks = _checks(db, firm_id)
    assert checks[-1]["outcome"] == "ok" and float(checks[-1]["name_match"]) >= 0.5
    assert search.queries == []


@respx.mock
def test_mismatch_is_corrected_from_search(db):
    _open_robots("wrongsite.com")
    respx.get("https://wrongsite.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Sunrise Bakery</title></head>"
                                              "<body>fresh bread daily</body></html>")
    )
    firm_id = make_firm(db, domain="wrongsite.com", canonical_name="Doe & Roe Law", city="Atlanta",
                        state="GA")
    make_lead(db, firm_id)
    search = Recorder([
        {"title": "Doe & Roe Law - Avvo", "href": "https://www.avvo.com/x", "body": ""},
        {"title": "Doe & Roe Law | Atlanta Injury Attorneys", "href": "https://doeroe.com/",
         "body": "Doe & Roe represents injured Georgians."},
    ])
    # the candidate is only adopted once its own homepage names the firm
    _open_robots("doeroe.com")
    respx.get("https://doeroe.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Doe & Roe Law</title></head>"
                                              "<body></body></html>")
    )

    webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                           default_interval_s="0")

    assert search.queries == ['"Doe & Roe Law" Atlanta GA law firm']
    check = _checks(db, firm_id)[-1]
    assert check["outcome"] == "corrected" and check["corrected_domain"] == "doeroe.com"
    assert check["given"] is None and check["domain"] == "wrongsite.com"
    assert check["evidence"]["results"][0]["skipped"] == "directory"
    assert _firm_domain(db, firm_id) == "doeroe.com"
    with db.cursor() as cur:
        cur.execute(
            "SELECT alias_domain, merge_rule FROM firm_alias WHERE firm_id = %s", (firm_id,)
        )
        assert cur.fetchone() == {"alias_domain": "wrongsite.com", "merge_rule": "corrected"}
        cur.execute("SELECT domain, payload FROM observation WHERE source = 'search:ddg' "
                    "AND firm_id = %s", (firm_id,))
        obs = cur.fetchone()
        assert obs["domain"] == "doeroe.com" and obs["payload"]["query"] == search.queries[0]


@respx.mock
def test_missing_website_with_no_convincing_result_stays_missing(db):
    firm_id = make_firm(db, domain=None, canonical_name="Nowhere Legal Group", city="Boise",
                        state="ID")
    make_lead(db, firm_id)
    search = Recorder([{"title": "Nowhere Legal - Justia", "href": "https://www.justia.com/x",
                        "body": ""}])

    webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                           default_interval_s="0")

    check = _checks(db, firm_id)[-1]
    assert check["outcome"] == "missing" and check["corrected_domain"] is None
    assert check["search_query"] == '"Nowhere Legal Group" Boise ID law firm'
    assert _firm_domain(db, firm_id) is None


@respx.mock
def test_dead_site_is_found_by_search(db):
    respx.get("https://gone.example.com/robots.txt").mock(side_effect=httpx.ConnectError("no"))
    firm_id = make_firm(db, domain="gone.example.com", canonical_name="Harbor Injury Law")
    make_lead(db, firm_id)
    search = Recorder([{"title": "Harbor Injury Law", "href": "https://harborinjury.com/",
                        "body": "Harbor Injury Law, personal injury"}])
    _open_robots("harborinjury.com")
    respx.get("https://harborinjury.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Harbor Injury Law</title>"
                                              "</head><body></body></html>")
    )

    webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                           default_interval_s="0")
    check = _checks(db, firm_id)[-1]
    assert check["outcome"] == "corrected" and check["corrected_domain"] == "harborinjury.com"
    assert _firm_domain(db, firm_id) == "harborinjury.com"


@respx.mock
def test_a_directory_that_names_the_firm_is_never_adopted(db):
    # The first live run replaced eight real (dead) domains with aggregators
    # whose snippets mentioned the firm. A candidate must name the firm on its
    # own homepage; a directory's homepage does not.
    respx.get("https://gone.example.com/robots.txt").mock(side_effect=httpx.ConnectError("no"))
    _open_robots("somelistings.com")
    respx.get("https://somelistings.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Some Listings - find any "
                                              "business</title></head><body></body></html>")
    )
    firm_id = make_firm(db, domain="gone.example.com", canonical_name="Fiorentino Law Offices")
    make_lead(db, firm_id)
    search = Recorder([{"title": "Fiorentino Law Offices Ltd - Chicago",
                        "href": "https://somelistings.com/il/fiorentino-law-offices",
                        "body": "Fiorentino Law Offices, Chicago IL"}])

    webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                           default_interval_s="0")
    check = _checks(db, firm_id)[-1]
    assert check["outcome"] == "dead" and check["corrected_domain"] is None
    assert "not adopted" in check["note"]
    assert _firm_domain(db, firm_id) == "gone.example.com"


@respx.mock
def test_edge_blocked_site_is_recorded_and_never_searched(db):
    respx.get("https://walled.example.com/robots.txt").mock(return_value=httpx.Response(403))
    firm_id = make_firm(db, domain="walled.example.com", canonical_name="Walled Law")
    make_lead(db, firm_id)
    search = Recorder()

    webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                           default_interval_s="0")
    assert _checks(db, firm_id)[-1]["outcome"] == "blocked"
    assert search.queries == []
    assert _firm_domain(db, firm_id) == "walled.example.com"


@respx.mock
def test_found_domain_owned_by_another_firm_opens_a_review_not_a_rewrite(db):
    _open_robots("stale.example.com")
    respx.get("https://stale.example.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Parked domain for sale"
                                              "</title></head><body></body></html>")
    )
    other_id = make_firm(db, domain="realfirm.com", canonical_name="Real Firm")
    firm_id = make_firm(db, domain="stale.example.com", canonical_name="Real Firm PC")
    make_lead(db, firm_id)
    search = Recorder(
        [{"title": "Real Firm PC", "href": "https://realfirm.com/", "body": "Real Firm"}]
    )
    _open_robots("realfirm.com")
    respx.get("https://realfirm.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Real Firm PC</title></head>"
                                              "<body></body></html>")
    )

    webcheck.website_check(ctx(db, live=True, user_agent=UA), search=search,
                           default_interval_s="0")
    assert _checks(db, firm_id)[-1]["outcome"] == "unresolved"
    assert _firm_domain(db, firm_id) == "stale.example.com"
    with db.cursor() as cur:
        cur.execute("SELECT rule, left_firm_id, right_firm_id FROM identity_review "
                    "WHERE status = 'open' AND rule = 'website_check'")
        row = cur.fetchone()
    assert {str(row["left_firm_id"]), str(row["right_firm_id"])} == {str(firm_id), str(other_id)}


@respx.mock
def test_recently_checked_firms_are_skipped_unless_forced(db):
    _open_robots("butlerfirm.com")
    route = respx.get("https://butlerfirm.com/").mock(
        return_value=httpx.Response(200, html="<html><head><title>Butler Kahn</title></head>"
                                              "<body></body></html>")
    )
    firm_id = make_firm(db, domain="butlerfirm.com", canonical_name="Butler Kahn, PC")
    make_lead(db, firm_id)
    c = ctx(db, live=True, user_agent=UA)
    webcheck.website_check(c, search=Recorder(), default_interval_s="0")
    second = webcheck.website_check(c, search=Recorder(), default_interval_s="0")
    assert second.processed == 0 and "no firms to check" in second.notes[0]
    assert route.call_count == 1
    webcheck.website_check(c, search=Recorder(), default_interval_s="0", force="1")
    assert route.call_count == 2 and len(_checks(db, firm_id)) == 2
