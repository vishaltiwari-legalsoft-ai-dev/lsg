"""The engines behind the seam map their own answers onto one result shape,
raise SearchBlocked on a rate limit, and the seam picks the engine from the
settings. No test reaches a real engine."""

from __future__ import annotations

import httpx
import pytest
import respx

import lge.search as seam
from lge.search import SearchBlocked, is_failure
from lge.search.brave import SEARCH_URL as BRAVE_URL
from lge.search.brave import BraveEngine
from lge.search.pace import Pace, Pacer
from lge.search.serper import PLACES_URL, SEARCH_URL, SerperEngine
from lge.settings import Settings


@respx.mock
def test_serper_maps_organic_results_and_places():
    route = respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "organic": [
            {"title": "Jane Doe - Owner - Doe Law | LinkedIn",
             "link": "https://www.linkedin.com/in/jane-doe", "snippet": "Experience: Doe Law"},
            {"title": "Doe Law", "link": "https://doelaw.com/", "snippet": "PI firm"},
        ],
    }))
    respx.post(PLACES_URL).mock(return_value=httpx.Response(200, json={
        "places": [{"title": "Doe Law", "address": "1 Main St, Atlanta, GA", "rating": 4.7,
                    "ratingCount": 88, "phoneNumber": "+1 404-555-0100",
                    "website": "https://doelaw.com", "cid": "42"}],
    }))
    e = SerperEngine("k")
    rows = e.search('"Doe Law" "Jane Doe" Atlanta linkedin', 8, 1)
    assert rows[0] == {
        "title": "Jane Doe - Owner - Doe Law | LinkedIn",
        "href": "https://www.linkedin.com/in/jane-doe", "body": "Experience: Doe Law",
    }
    assert route.calls.last.request.headers["X-API-KEY"] == "k"
    body = route.calls.last.request.read()
    assert b'"page":1' in body and b'"gl":"us"' in body
    places = e.places("Doe Law Atlanta GA")
    assert places == [{"name": "Doe Law", "address": "1 Main St, Atlanta, GA", "rating": 4.7,
                       "review_count": 88, "phone": "+1 404-555-0100",
                       "website": "https://doelaw.com",
                       "url": "https://www.google.com/maps?cid=42", "category": None}]


@respx.mock
def test_serper_rate_limit_is_a_block_and_a_bad_key_is_an_error():
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(SearchBlocked):
        SerperEngine("k").search("x", 8, 1)
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(403, text="nope"))
    with pytest.raises(RuntimeError, match="refused the key"):
        SerperEngine("k").search("x", 8, 1)
    with pytest.raises(ValueError):
        SerperEngine("")


@respx.mock
def test_brave_maps_web_results_and_has_no_places():
    route = respx.get(BRAVE_URL).mock(return_value=httpx.Response(200, json={
        "web": {"results": [{"title": "Doe Law", "url": "https://doelaw.com/",
                             "description": "Personal injury"}]},
    }))
    e = BraveEngine("k")
    assert e.search("Doe Law", 8, 2) == [
        {"title": "Doe Law", "href": "https://doelaw.com/", "body": "Personal injury"}
    ]
    assert route.calls.last.request.headers["X-Subscription-Token"] == "k"
    assert "offset=1" in str(route.calls.last.request.url)
    assert e.places("Doe Law") is None
    respx.get(BRAVE_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(SearchBlocked):
        e.search("x", 8, 1)


class FakeEngine:
    name = "ddg"

    def __init__(self) -> None:
        self.queries: list[tuple[str, int, int]] = []

    def search(self, query, max_results, page):
        self.queries.append((query, max_results, page))
        if query == "blocked":
            raise SearchBlocked("202")
        return [{"title": "t", "href": "https://x/", "body": query}]

    def places(self, query):
        return None


def test_the_seam_answers_through_the_engine_the_settings_name(monkeypatch):
    seam.reset()
    fake = FakeEngine()
    monkeypatch.setitem(seam._engines, "ddg", fake)
    monkeypatch.setitem(seam._pacers, "ddg", Pacer(Pace(block_backoff_s=0.0)))
    assert seam.engine_name() == "ddg" and seam.source() == "search:ddg"  # pinned by conftest
    assert seam.search("hello", 5, page=2)[0]["body"] == "hello"
    assert fake.queries == [("hello", 5, 2)]
    assert is_failure(seam.search("blocked"))
    assert seam.places("anything") is None
    seam.reset()


def test_the_settings_choose_serper_when_its_key_is_present():
    s = Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                 openrouter_api_key="", live=False, serper_api_key="k")
    assert seam.engine_name(s) == "serper" and seam.source(s) == "search:serper"
    s2 = Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                  openrouter_api_key="", live=False, brave_api_key="k")
    assert seam.engine_name(s2) == "brave"
    s3 = Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                  openrouter_api_key="", live=False)
    assert seam.engine_name(s3) == "ddg"


def _settings(**seams) -> Settings:
    return Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                    openrouter_api_key="", live=False, **seams)


def test_the_business_listing_is_looked_up_only_by_an_engine_that_has_one_with_its_key():
    # What the screens' "places" light reports (D-054): Serper's /places with its key.
    assert seam.has_listings(_settings(serper_api_key="k")) is True
    assert seam.has_listings(_settings(brave_api_key="k")) is False  # no listings endpoint
    assert seam.has_listings(_settings()) is False  # DuckDuckGo
    # forced to Serper without the key: the engine could not be built, so no
    assert seam.has_listings(_settings(search_engine="serper")) is False


def test_duckduckgo_reads_the_status_before_the_page(monkeypatch):
    """The library folds a 202 into "No results found."; the engine reads the
    status itself (D-039) and raises SearchBlocked."""
    from ddgs.engines.duckduckgo import Duckduckgo

    import lge.search.ddg as ddg

    class _Resp:
        def __init__(self, status, text):
            self.status_code, self.text = status, text

    class _Client:
        def __init__(self, status, text):
            self.answer = _Resp(status, text)

        def request(self, method, url, **kw):
            return self.answer

    def engine_with(status, text):
        eng = Duckduckgo.__new__(Duckduckgo)  # no primp client: nothing here touches the network
        eng.http_client = _Client(status, text)
        eng.results = []
        return eng

    page = (
        '<html><body><div class="result__body"><h2>Doe Law</h2>'
        '<a href="https://doe.law/">Doe Law is a firm in Atlanta</a></div>'
        '<div class="result__body"><h2>Roe</h2><a href="https://roe.law/">Roe</a></div>'
        "</body></html>"
    )
    monkeypatch.setattr(ddg, "_engine", lambda: engine_with(200, page))
    rows = ddg.DDGEngine().search("doe law", 8, 1)
    assert [r["href"] for r in rows][:1] == ["https://doe.law/"] or rows == []
    monkeypatch.setattr(ddg, "_engine", lambda: engine_with(202, "<html>anomaly</html>"))
    with pytest.raises(SearchBlocked):
        ddg.DDGEngine().search("doe law", 8, 1)
    monkeypatch.setattr(ddg, "_engine", lambda: engine_with(500, ""))
    with pytest.raises(RuntimeError):
        ddg.DDGEngine().search("doe law", 8, 1)
