"""The listings seam (D-062): each provider maps its own answer onto the
one listing and review shape, a rate limit is a block, the settings choose
the provider by key, and the matcher adopts the firm and not its namesake.
No test reaches a real provider."""

from __future__ import annotations

import httpx
import pytest
import respx

import lge.listings as seam
from lge.listings.base import SearchBlocked
from lge.listings.google_places import SEARCH_URL as GOOGLE_URL
from lge.listings.google_places import GooglePlacesProvider
from lge.listings.match import listing_query, pick_listing
from lge.listings.serper import PLACES_URL, REVIEWS_URL, SerperListingProvider
from lge.search.pace import Pace, Pacer
from lge.settings import Settings

_GOOGLE_ANSWER = {
    "places": [
        {
            "id": "ChIJ123",
            "displayName": {"text": "Hartley Injury Law, P.C.", "languageCode": "en"},
            "formattedAddress": "1 Peachtree St NE Suite 100, Atlanta, GA 30303, USA",
            "nationalPhoneNumber": "(404) 555-0100",
            "websiteUri": "https://hartleylaw.com/",
            "primaryType": "personal_injury_attorney",
            "primaryTypeDisplayName": {"text": "Personal Injury Attorney"},
            "googleMapsUri": "https://maps.google.com/?cid=42",
            "rating": 4.8,
            "userRatingCount": 212,
            "businessStatus": "OPERATIONAL",
            "reviews": [
                {
                    "rating": 5,
                    "publishTime": "2026-08-02T10:00:00Z",
                    "text": {"text": "They  kept me\ninformed every step.", "languageCode": "en"},
                    "authorAttribution": {"displayName": "J. Smith"},
                    "googleMapsUri": "https://maps.google.com/review/1",
                },
                {
                    "rating": 2,
                    "publishTime": "2026-07-10T10:00:00Z",
                    "text": {"text": "Nobody called me back for three weeks."},
                    "authorAttribution": {"displayName": "R. Diaz"},
                },
                {"rating": 4, "publishTime": "2026-06-01T10:00:00Z"},  # no text: dropped
            ],
        },
        {
            "id": "ChIJ999",
            "displayName": {"text": "Hartley Dental"},
            "primaryTypeDisplayName": {"text": "Dentist"},
        },
    ]
}


@respx.mock
def test_google_places_maps_the_listing_and_its_reviews_from_one_call():
    route = respx.post(GOOGLE_URL).mock(return_value=httpx.Response(200, json=_GOOGLE_ANSWER))
    p = GooglePlacesProvider("k")
    found = p.find("Hartley Injury Law Atlanta GA")
    req = route.calls.last.request
    assert req.headers["X-Goog-Api-Key"] == "k"
    assert "places.reviews" in req.headers["X-Goog-FieldMask"]
    assert b'"textQuery":"Hartley Injury Law Atlanta GA"' in req.read()
    assert [f["name"] for f in found] == ["Hartley Injury Law, P.C.", "Hartley Dental"]
    listing = found[0]
    assert listing["category"] == "Personal Injury Attorney"
    assert listing["phone"] == "(404) 555-0100"
    assert listing["website"] == "https://hartleylaw.com/"
    assert listing["rating"] == 4.8 and listing["review_count"] == 212
    assert listing["url"] == "https://maps.google.com/?cid=42"
    assert listing["place_id"] == "ChIJ123" and listing["status"] == "operational"
    # The reviews came with the listing: no second call, whitespace folded.
    reviews = p.reviews(listing, 10)
    assert route.call_count == 1
    assert reviews == [
        {"author": "J. Smith", "rating": 5, "date": "2026-08-02",
         "text": "They kept me informed every step.", "url": "https://maps.google.com/review/1"},
        {"author": "R. Diaz", "rating": 2, "date": "2026-07-10",
         "text": "Nobody called me back for three weeks.", "url": None},
    ]
    assert p.reviews(listing, 1) == reviews[:1]


@respx.mock
def test_google_places_quota_is_a_block_and_a_bad_key_is_an_error():
    respx.post(GOOGLE_URL).mock(return_value=httpx.Response(429, text="quota"))
    with pytest.raises(SearchBlocked):
        GooglePlacesProvider("k").find("x")
    respx.post(GOOGLE_URL).mock(return_value=httpx.Response(403, text="nope"))
    with pytest.raises(RuntimeError, match="refused the key"):
        GooglePlacesProvider("k").find("x")
    with pytest.raises(ValueError):
        GooglePlacesProvider("")


@respx.mock
def test_serper_reads_places_then_reviews_by_cid():
    respx.post(PLACES_URL).mock(return_value=httpx.Response(200, json={
        "places": [{"title": "Doe Law", "address": "1 Main St, Atlanta, GA 30303",
                    "rating": 4.7, "ratingCount": 88, "phoneNumber": "+1 404-555-0100",
                    "website": "https://doelaw.com", "cid": "42", "category": "Law firm"}],
    }))
    reviews_route = respx.post(REVIEWS_URL).mock(return_value=httpx.Response(200, json={
        "reviews": [
            {"rating": 1, "isoDate": "2026-05-05T00:00:00Z", "date": "4 months ago",
             "snippet": "Calls  went unanswered.", "user": {"name": "A. Lee"}},
            {"rating": 5, "date": "a year ago", "snippet": "Great team.", "user": {"name": "B"}},
        ],
        "nextPageToken": "more",
    }))
    p = SerperListingProvider("k", low_stars_first=False)
    found = p.find("Doe Law Atlanta GA")
    assert found[0]["name"] == "Doe Law" and found[0]["category"] == "Law firm"
    assert found[0]["url"] == "https://www.google.com/maps?cid=42"
    reviews = p.reviews(found[0], 10)
    assert b'"cid":"42"' in reviews_route.calls.last.request.read()
    assert reviews_route.call_count == 1  # one page by default, token or not
    assert reviews[0] == {"author": "A. Lee", "rating": 1, "date": "2026-05-05",
                          "text": "Calls went unanswered.", "url": None}
    assert reviews[1]["date"] == "a year ago"
    # A listing with no handle has no reviews to ask for.
    assert p.reviews({"name": "x"}, 10) == []


@respx.mock
def test_serper_pages_reviews_when_asked_and_stops_at_the_cap():
    calls = []

    def answer(request):
        calls.append(request.read())
        return httpx.Response(200, json={
            "reviews": [{"rating": 3, "snippet": f"review {len(calls)}"}],
            "nextPageToken": "t",
        })

    respx.post(REVIEWS_URL).mock(side_effect=answer)
    p = SerperListingProvider("k", max_pages=3, low_stars_first=False)
    got = p.reviews({"name": "x", "_cid": "1"}, 10)
    assert len(got) == 3 and b'"nextPageToken":"t"' in calls[1]
    p2 = SerperListingProvider("k", max_pages=3, low_stars_first=False)
    assert len(p2.reviews({"name": "x", "_cid": "1"}, 2)) == 2


@respx.mock
def test_serper_star_only_reviews_do_not_count_towards_the_cap():
    respx.post(REVIEWS_URL).mock(return_value=httpx.Response(200, json={
        "reviews": [
            {"rating": 5}, {"rating": 4}, {"rating": 1, "snippet": "Never called back."},
            {"rating": 5, "snippet": "Superb."},
        ],
    }))
    got = SerperListingProvider("k", low_stars_first=False).reviews({"name": "x", "_cid": "1"}, 2)
    assert [r["text"] for r in got] == ["Never called back.", "Superb."]


@respx.mock
def test_serper_keeps_the_poor_reviews_first_then_fills_from_the_relevant_page():
    """D-069: the lowest-rated page first, every review at or below three
    stars kept, then the most relevant page for the rest of the cap, never
    a repeat, two credits at most."""
    bodies = []

    def answer(request):
        body = request.read()
        bodies.append(body)
        if b'"sortBy":"lowestRating"' in body:
            return httpx.Response(200, json={"reviews": [
                {"rating": 1, "snippet": "Never called back.", "user": {"name": "A"}, "link": "u1"},
                {"rating": 2, "snippet": "Slow, expensive.", "user": {"name": "B"}, "link": "u2"},
                {"rating": 3, "snippet": "Fine, not great.", "user": {"name": "C"}, "link": "u3"},
                {"rating": 4, "snippet": "Good.", "user": {"name": "D"}, "link": "u4"},
                {"rating": 5, "snippet": "Superb.", "user": {"name": "E"}, "link": "u5"},
            ], "nextPageToken": "t"})
        return httpx.Response(200, json={"reviews": [
            {"rating": 5, "snippet": "Superb.", "user": {"name": "E"}, "link": "u5"},
            {"rating": 5, "snippet": "Wonderful.", "user": {"name": "F"}, "link": "u6"},
            {"rating": 1, "snippet": "Never called back.", "user": {"name": "A"}, "link": "u1"},
            {"rating": 4, "snippet": "Solid.", "user": {"name": "G"}, "link": "u7"},
        ]})

    respx.post(REVIEWS_URL).mock(side_effect=answer)
    got = SerperListingProvider("k").reviews({"name": "x", "_cid": "1"}, 5)
    assert [r["rating"] for r in got] == [1, 2, 3, 5, 5]
    assert [r["text"] for r in got][3:] == ["Superb.", "Wonderful."]  # no repeat of u1/u5
    assert len(bodies) == 2 and b'"sortBy"' not in bodies[1]
    # Enough poor reviews to fill the cap: one page, one credit.
    bodies.clear()
    got = SerperListingProvider("k").reviews({"name": "x", "_cid": "1"}, 3)
    assert [r["rating"] for r in got] == [1, 2, 3] and len(bodies) == 1


def _settings(**seams) -> Settings:
    return Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                    openrouter_api_key="", live=False, **seams)


def test_the_settings_choose_google_first_then_serper_then_nothing():
    assert seam.provider_name(_settings(google_places_api_key="g", serper_api_key="s")) == (
        "google_places"
    )
    assert seam.source(_settings(google_places_api_key="g")) == "listing:google_places"
    assert seam.provider_name(_settings(serper_api_key="s")) == "serper"
    assert seam.provider_name(_settings()) == "none"
    assert seam.provider_name(_settings(listings="none", google_places_api_key="g")) == "none"
    # What the screens' "places" light reports: a provider with its key.
    assert seam.has_provider(_settings(google_places_api_key="g")) is True
    assert seam.has_provider(_settings(serper_api_key="s")) is True
    assert seam.has_provider(_settings()) is False
    assert seam.has_provider(_settings(listings="google_places")) is False  # forced, no key
    assert seam.get_provider(_settings()) is None


class FakeProvider:
    name = "google_places"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def find(self, query):
        self.queries.append(query)
        if query == "blocked":
            raise SearchBlocked("429")
        return [{"name": query}]

    def reviews(self, listing, max_reviews):
        return [{"author": None, "rating": 5, "date": None, "text": listing["name"], "url": None}]


def test_the_seam_paces_the_provider_and_answers_none_on_a_block(monkeypatch):
    seam.reset()
    fake = FakeProvider()
    monkeypatch.setitem(seam._providers, "google_places", fake)
    monkeypatch.setitem(seam._pacers, "google_places", Pacer(Pace(block_backoff_s=0.0)))
    monkeypatch.setattr(seam, "get_settings", lambda: _settings(google_places_api_key="g"))
    assert seam.find("hello") == [{"name": "hello"}]
    assert seam.reviews({"name": "hello"})[0]["text"] == "hello"
    assert seam.find("blocked") is None  # blocked twice: a cooldown, no crash
    assert seam.find("hello") is None  # cooling off
    seam.reset()
    monkeypatch.setattr(seam, "get_settings", lambda: _settings())
    assert seam.find("hello") is None  # no provider at all
    seam.reset()


def test_the_matcher_adopts_the_firm_and_not_its_namesake():
    listings = [
        {"name": "Hartley Dental", "category": "Dentist"},
        {"name": "Hartley Injury Law, P.C.", "category": "Personal injury attorney"},
        {"name": "Injury Law Center", "category": "Law firm"},
    ]
    assert pick_listing("Hartley Injury Law", listings)["name"] == "Hartley Injury Law, P.C."
    assert pick_listing("Hartley Injury Law", [listings[0]]) is None  # a dentist is never it
    assert pick_listing("Smith & Jones", listings) is None
    assert pick_listing("Hartley Injury Law", None) is None
    assert listing_query("Hartley Injury Law", "Atlanta", "GA") == "Hartley Injury Law Atlanta GA"
    assert listing_query("Hartley Injury Law", None, None) == "Hartley Injury Law"
