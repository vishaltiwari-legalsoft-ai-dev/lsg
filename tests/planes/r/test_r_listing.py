"""r_listing (D-062): the Google Business Profile and its reviews become
claims under the provider's tag, the lookup is logged once and not
repeated, a firm whose listing is not there is logged not_found, and
nothing runs without live=1 or without a provider."""

from __future__ import annotations

import pytest

from lge.planes.r import r_listing, r_search_links
from lge.settings import Settings, get_settings
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx
from tests.planes.r.test_r_search_links import Recorder

pytestmark = pytest.mark.db

_LISTING = {
    "name": "Hartley Injury Law, P.C.", "category": "Personal Injury Attorney",
    "address": "1 Peachtree St NE Suite 100, Atlanta, GA 30303, USA",
    "phone": "(404) 555-0100", "website": "https://www.hartleylaw.com/",
    "rating": 4.8, "review_count": 212, "url": "https://maps.google.com/?cid=42",
    "place_id": "ChIJ123", "status": "operational", "_reviews": ["private"],
}
_REVIEWS = [
    {"author": "R. Diaz", "rating": 2, "date": "2026-07-10",
     "text": "Nobody called me back for three weeks.", "url": None},
    {"author": "J. Smith", "rating": 5, "date": "2026-08-02",
     "text": "They kept me informed every step.", "url": None},
]


def _ctx(db, **over):
    base = get_settings()
    s = Settings(
        dsn=base.dsn, admin_dsn=base.admin_dsn, object_store=base.object_store,
        user_agent=base.user_agent, anthropic_api_key="", openrouter_api_key="",
        live=over.pop("live", True), **over,
    )
    c = ctx(db)
    c.settings = s
    return c


def _claims(conn, firm_id, source="listing:google_places") -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT attr, value, confidence, evidence FROM firm_attribute "
            "WHERE firm_id = %s AND source = %s",
            (firm_id, source),
        )
        return {r["attr"]: r for r in cur.fetchall()}


def _log(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind, query, outcome, url, rating, review_count, results, engine "
            "FROM search_log WHERE firm_id = %s ORDER BY id",
            (firm_id,),
        )
        return cur.fetchall()


def test_the_listing_and_its_reviews_become_claims_and_one_log_row(db):
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com",
                        city="Atlanta", state="GA")
    asked: list[str] = []

    def find(query):
        asked.append(query)
        return [{"name": "Hartley Dental", "category": "Dentist"}, dict(_LISTING)]

    result = r_listing.run(
        _ctx(db, google_places_api_key="g"), find=find, reviews=lambda lst, n: list(_REVIEWS)
    )
    assert result.processed == 1 and result.failed == 0
    assert asked == ["Hartley Injury Law Atlanta GA"]
    claims = _claims(db, firm_id)
    assert claims["business_listing"]["value"]["name"] == "Hartley Injury Law, P.C."
    assert "_reviews" not in claims["business_listing"]["value"]  # private handles never stored
    assert claims["google_rating"]["value"] == 4.8
    assert claims["review_count"]["value"] == 212
    assert float(claims["review_count"]["confidence"]) == 0.9
    assert claims["google_business_url"]["value"] == "https://maps.google.com/?cid=42"
    assert claims["phone_e164"]["value"] == "+14045550100"
    assert claims["phone_e164"]["evidence"] == "Google Business Profile: (404) 555-0100"
    address = claims["address"]["value"]
    # The same six keys as every other address claim, and never the printed
    # text: two sources printing the same office must "agree" in reconcile (D-052).
    assert set(address) == {"street_norm", "unit", "city", "state", "zip5", "addr_hash"}
    assert claims["address"]["evidence"] == (
        "Google Business Profile: 1 Peachtree St NE Suite 100, Atlanta, GA 30303, USA"
    )
    assert address["city"] == "ATLANTA" and address["state"] == "GA" and address["zip5"] == "30303"
    assert address["unit"] and address["street_norm"]
    assert claims["city"]["value"] == "ATLANTA"
    assert [r["author"] for r in claims["google_reviews"]["value"]] == ["R. Diaz", "J. Smith"]
    assert claims["google_reviews"]["evidence"] == "2 review(s) on the listing"
    (row,) = _log(db, firm_id)
    assert row["kind"] == "listing" and row["outcome"] == "found"
    assert row["engine"] == "google_places" and row["review_count"] == 212
    assert row["results"]["listing"]["name"] == "Hartley Injury Law, P.C."
    assert len(row["results"]["reviews"]) == 2
    assert "listings found 1" in result.notes[-1]

    # Fresh: the next run does not even select the firm, and asks nothing.
    again = r_listing.run(
        _ctx(db, google_places_api_key="g"), find=find, reviews=lambda lst, n: list(_REVIEWS)
    )
    assert again.processed == 0 and asked == ["Hartley Injury Law Atlanta GA"]

    # And r_search_links no longer asks its snippet query for reviews either.
    search = Recorder({})
    r_search_links.run(ctx(db, live=True), search=search, places=lambda q: None)
    assert not any("google business reviews" in q for q in search.queries)


def test_a_firm_whose_listing_is_not_there_is_logged_not_found_and_gets_no_claims(db):
    firm_id = make_firm(db, canonical_name="Smith & Jones", domain="smithjones.com")
    result = r_listing.run(
        _ctx(db, serper_api_key="s"),
        find=lambda q: [{"name": "Hartley Dental", "category": "Dentist"}],
        reviews=lambda lst, n: [],
    )
    assert result.processed == 1
    assert _claims(db, firm_id, "listing:serper") == {}
    (row,) = _log(db, firm_id)
    assert row["outcome"] == "not_found" and row["engine"] == "serper"
    assert row["results"] == [{"name": "Hartley Dental", "category": "Dentist"}]


def test_a_failed_lookup_is_logged_failed_and_asked_again_next_run(db):
    firm_id = make_firm(db, canonical_name="Doe Law", domain="doelaw.com")
    result = r_listing.run(_ctx(db, google_places_api_key="g"), find=lambda q: None,
                           reviews=lambda lst, n: [])
    assert result.failed == 1
    assert _log(db, firm_id)[0]["outcome"] == "failed"
    calls = []
    r_listing.run(_ctx(db, google_places_api_key="g"),
                  find=lambda q: calls.append(q) or [], reviews=lambda lst, n: [])
    assert calls == ["Doe Law"]


def test_failed_reviews_keep_the_listing_and_the_reviews_already_on_file(db):
    """A refetch whose reviews call fails writes the listing's facts, logs
    the lookup failed so it is asked again, and never replaces the reviews
    already on file with an empty list."""
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com")
    first = r_listing.run(_ctx(db, google_places_api_key="g"),
                          find=lambda q: [dict(_LISTING)], reviews=lambda lst, n: list(_REVIEWS))
    assert first.processed == 1
    with db.cursor() as cur:  # make the first lookup stale so the firm is due again
        cur.execute("UPDATE search_log SET searched_at = now() - interval '40 days' "
                    "WHERE firm_id = %s", (firm_id,))
        cur.execute("UPDATE firm_attribute SET observed_at = now() - interval '40 days' "
                    "WHERE firm_id = %s", (firm_id,))
    again = r_listing.run(_ctx(db, google_places_api_key="g"),
                          find=lambda q: [dict(_LISTING)], reviews=lambda lst, n: None)
    assert again.processed == 1
    with db.cursor() as cur:
        cur.execute(
            "SELECT value FROM firm_attribute WHERE firm_id = %s AND attr = 'google_reviews' "
            "ORDER BY observed_at DESC LIMIT 1", (firm_id,),
        )
        latest = cur.fetchone()["value"]
    assert [r["author"] for r in latest] == ["R. Diaz", "J. Smith"]
    assert _log(db, firm_id)[-1]["outcome"] == "failed"
    assert _claims(db, firm_id)["google_rating"]["value"] == 4.8


def test_replay_re_derives_every_claim_from_the_stored_answer_without_a_lookup(db):
    """A matching or address-parsing fix reaches every firm already looked
    up from the answer kept in search_log, and the provider is never asked."""
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com")
    r_listing.run(_ctx(db, google_places_api_key="g"),
                  find=lambda q: [dict(_LISTING)], reviews=lambda lst, n: list(_REVIEWS))
    with db.cursor() as cur:
        cur.execute("DELETE FROM firm_attribute WHERE firm_id = %s", (firm_id,))
    calls = []
    result = r_listing.run(_ctx(db, live=False), find=lambda q: calls.append(q) or [],
                           reviews=lambda lst, n: [], replay="1")
    assert result.processed == 1 and calls == []
    claims = _claims(db, firm_id)
    assert claims["business_listing"]["value"]["name"] == "Hartley Injury Law, P.C."
    assert claims["phone_e164"]["value"] == "+14045550100"
    assert [r["author"] for r in claims["google_reviews"]["value"]] == ["R. Diaz", "J. Smith"]
    assert "replayed 1" in result.notes[-1]


def test_nothing_runs_without_live_or_without_a_provider(db):
    make_firm(db, canonical_name="Doe Law", domain="doelaw.com")
    calls = []
    off = r_listing.run(_ctx(db, live=False, google_places_api_key="g"),
                        find=lambda q: calls.append(q) or [], reviews=lambda lst, n: [])
    assert off.processed == 0 and "live=0" in off.notes[0]
    none = r_listing.run(_ctx(db), find=lambda q: calls.append(q) or [],
                         reviews=lambda lst, n: [])
    assert none.processed == 0 and "inert" in none.notes[0] and "never scraped" in none.notes[0]
    assert calls == []


def test_five_failures_in_a_row_stop_the_run(db):
    for i in range(7):
        make_firm(db, canonical_name=f"Firm {i}", domain=f"firm{i}.com")
    calls = []
    result = r_listing.run(_ctx(db, google_places_api_key="g"),
                           find=lambda q: calls.append(q), reviews=lambda lst, n: [])
    assert len(calls) == 5 and result.failed == 5
    assert any("stopped early" in n for n in result.notes)


@pytest.mark.parametrize(
    ("formatted", "expect"),
    [
        ("1 Peachtree St NE Suite 100, Atlanta, GA 30303, USA",
         {"city": "ATLANTA", "state": "GA", "zip5": "30303"}),
        ("100 Main Street, Springfield, IL 62701", {"city": "SPRINGFIELD", "state": "IL"}),
        ("Atlanta, GA, USA", None),
        (None, None),
    ],
)
def test_the_listing_address_is_parsed_only_when_it_is_a_street_address(formatted, expect):
    got = r_listing.parse_address(formatted)
    if expect is None:
        assert got is None
    else:
        assert "raw" not in got
        for k, v in expect.items():
            assert got[k] == v


def test_the_website_host_drops_www_and_scheme():
    assert r_listing.website_host("https://www.hartleylaw.com/contact") == "hartleylaw.com"
    assert r_listing.website_host("hartleylaw.com") == "hartleylaw.com"
    assert r_listing.website_host(None) is None
