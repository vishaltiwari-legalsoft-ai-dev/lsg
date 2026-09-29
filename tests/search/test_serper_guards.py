"""The rules every Serper call runs under (28 Sep 2026, before the first paid
bulk run): a bad key or an empty balance refuses the run at once, credits
are metered from the provider's own answer, a sheet's value cannot change a
query, and a paid step never walks the whole store by accident."""

from __future__ import annotations

import httpx
import pytest
import respx

from lge.listings.serper import PLACES_URL as LISTING_PLACES_URL
from lge.listings.serper import REVIEWS_URL, SerperListingProvider
from lge.search import meter, paid_run_refusal
from lge.search.base import SearchBlocked, SearchRefused, clean_term, is_failure
from lge.search.pace import Pace, Pacer
from lge.search.serper import SEARCH_URL, SerperEngine
from tests.search.test_pace import Clock


@respx.mock
def test_a_bad_key_and_an_empty_balance_refuse_for_good():
    e = SerperEngine("k")
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(SearchRefused, match="refused the key"):
        e.search("x", 8, 1)
    respx.post(SEARCH_URL).mock(
        return_value=httpx.Response(400, json={"message": "Not enough credits"})
    )
    with pytest.raises(SearchRefused, match="no credit left"):
        e.search("x", 8, 1)
    # A refusal is a kind of block: whoever catches blocks catches it too.
    assert issubclass(SearchRefused, SearchBlocked)
    # A 400 that is not about credit is one failed query, not a refusal.
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(400, json={"message": "bad q"}))
    with pytest.raises(RuntimeError, match="400"):
        e.search("x", 8, 1)
    # A 200 that is not JSON is a failed query, never a crash further up.
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(RuntimeError, match="not JSON"):
        e.search("x", 8, 1)


@respx.mock
def test_the_listing_provider_runs_under_the_same_rules_and_credits_are_metered():
    meter.reset()
    p = SerperListingProvider("k")
    respx.post(LISTING_PLACES_URL).mock(return_value=httpx.Response(200, json={
        "places": [{"title": "Doe Law", "cid": "42", "rating": 4.5, "ratingCount": 3}],
        "credits": 1,
    }))
    respx.post(REVIEWS_URL).mock(return_value=httpx.Response(200, json={
        "reviews": [{"rating": 5, "snippet": "Great", "user": {"name": "A"}}], "credits": 1,
    }))
    found = p.find("Doe Law Atlanta GA")
    assert found[0]["name"] == "Doe Law"
    assert len(p.reviews(found[0], 10)) == 1
    assert meter.snapshot() == {"serper": (2, 2)}
    respx.post(LISTING_PLACES_URL).mock(return_value=httpx.Response(403, text="no"))
    with pytest.raises(SearchRefused):
        p.find("Doe Law")
    assert meter.snapshot() == {"serper": (2, 2)}  # a refusal is not a charged call
    before = meter.snapshot()
    meter.record("serper", 1)
    assert meter.note(before) == "serper: 1 call(s), 1 credit(s)"
    assert meter.note(meter.snapshot()) is None
    meter.reset()


def test_a_refusal_cools_the_engine_off_at_once_without_a_retry():
    clock = Clock()
    p = Pacer(Pace(block_backoff_s=30.0, block_cooldown_s=300.0), monotonic=clock.monotonic,
              sleep=clock.sleep, jitter=lambda a, b: 0)
    calls = 0

    def refused():
        nonlocal calls
        calls += 1
        raise SearchRefused("serper refused the key (401)")

    rows = p.call(refused, engine="serper")
    assert is_failure(rows) and "refused" in rows[0]["body"]
    assert calls == 1 and clock.slept == []  # no patient second try for a dead key
    # Every later query in the cooldown fails without a call.
    assert is_failure(p.call(refused, engine="serper")) and calls == 1
    assert "refused" in (p.blocked_reason() or "")
    clock.now += 301
    assert p.blocked_reason() is None


def test_the_pacer_serialises_threads():
    import threading

    clock = Clock()
    p = Pacer(Pace(interval_s=0.0), monotonic=clock.monotonic, sleep=clock.sleep,
              jitter=lambda a, b: 0)
    inside = 0
    overlap = False

    def work():
        nonlocal inside, overlap
        inside += 1
        if inside > 1:
            overlap = True
        threading.Event().wait(0.01)
        inside -= 1
        return []

    threads = [threading.Thread(target=lambda: p.call(work, engine="x")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlap is False


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ('Smith "Injury" Law', "Smith Injury Law"),
        ("site:evil.com Smith Law", "Smith Law"),
        ("-Smith Law", "Smith Law"),
        ("Smith\x00Law\n& Co", "Smith Law & Co"),
        ("  Smith   Law  ", "Smith Law"),
        ("O'Neil & Ross, P.C.", "O'Neil & Ross, P.C."),
        ("x" * 300, "x" * 120),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_term(raw, cleaned):
    assert clean_term(raw) == cleaned


def test_the_meter_counts_per_thread():
    import threading

    meter.reset()
    meter.record("serper", 1)
    seen: dict[str, object] = {}

    def other():
        seen["before"] = meter.snapshot()
        meter.record("serper", 3)
        seen["after"] = meter.snapshot()

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert seen["before"] == {}  # the other thread starts from nothing
    assert seen["after"] == {"serper": (1, 3)}
    assert meter.snapshot() == {"serper": (1, 1)}  # and never leaks into this one
    meter.reset()


def test_the_maps_link_is_judged_by_its_host():
    from lge.planes.r.r_search_links import is_maps_url

    assert is_maps_url("https://www.google.com/maps/place/Doe+Law")
    assert is_maps_url("https://maps.google.com/?cid=1")
    assert is_maps_url("https://maps.app.goo.gl/abc")
    assert is_maps_url("https://g.page/doe-law")
    assert is_maps_url("https://www.google.com/search?q=doe&ludocid=1")
    assert not is_maps_url("https://x.example/?u=google.com/maps")
    assert not is_maps_url("https://notgoogle.com/maps")
    assert not is_maps_url("https://www.google.com/search?q=doe+law")
    assert not is_maps_url("")


def test_a_paid_step_refuses_the_whole_store_unless_told():
    assert paid_run_refusal({}, what="the listing lookup", firms=250) is None
    refusal = paid_run_refusal({}, what="the listing lookup", firms=100_000)
    assert refusal and "100000 firms" in refusal and "all=1" in refusal
    assert paid_run_refusal({"limit": "10"}, what="x", firms=100_000) is None
    assert paid_run_refusal({"firm_ids_file": "ids.txt"}, what="x", firms=100_000) is None
    assert paid_run_refusal({"all": "1"}, what="x", firms=100_000) is None
