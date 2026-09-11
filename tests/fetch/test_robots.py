"""robots.txt state mapping: 200/404/410/401/403/5xx/timeout -> the correct
source_state, never a boolean. Crawl-delay -> rate_limited + the limiter
picks it up. A fully-disallowed root -> policy_closed. persist() upserts
source_registry without clobbering platform/notes."""

from __future__ import annotations

import httpx
import pytest
import respx

from lge.fetch.client import Fetcher
from lge.fetch.robots import RobotsCache, RobotsPolicy, check_host, persist

UA = "TestBot/1.0 (+https://example.com/bot)"


@respx.mock
async def test_200_with_no_crawl_delay_is_open():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")
    )
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "example.com", UA)
    assert policy.source_state == "open"
    assert policy.crawl_delay_s is None
    assert policy.crawlable() is True


@respx.mock
async def test_200_with_crawl_delay_is_rate_limited():
    respx.get("https://slow.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n")
    )
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "slow.example.com", UA)
    assert policy.source_state == "rate_limited"
    assert policy.crawl_delay_s == 5.0
    assert policy.crawlable() is True


@respx.mock
async def test_404_robots_is_open_no_rules():
    respx.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "example.com", UA)
    assert policy.source_state == "open"
    assert policy.parser is None
    # No robots.txt -> every path allowed.
    assert policy.decision("https://example.com/anything", UA) == "allowed"


@respx.mock
async def test_410_robots_is_open_no_rules():
    respx.get("https://example.com/robots.txt").mock(return_value=httpx.Response(410))
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "example.com", UA)
    assert policy.source_state == "open"


@respx.mock
async def test_403_on_robots_itself_is_edge_blocked_not_closed():
    respx.get("https://waf.example.com/robots.txt").mock(return_value=httpx.Response(403))
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "waf.example.com", UA)
    assert policy.source_state == "edge_blocked"
    assert policy.crawlable() is False


@respx.mock
async def test_401_on_robots_itself_is_edge_blocked():
    respx.get("https://auth.example.com/robots.txt").mock(return_value=httpx.Response(401))
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "auth.example.com", UA)
    assert policy.source_state == "edge_blocked"


@respx.mock
async def test_5xx_is_unreachable_not_a_policy_conclusion():
    respx.get("https://down.example.com/robots.txt").mock(return_value=httpx.Response(503))
    async with Fetcher(user_agent=UA, sleep=_no_sleep) as f:
        policy = await check_host(f, "down.example.com", UA)
    assert policy.source_state == "unreachable"
    assert policy.crawlable() is False


@respx.mock
async def test_connect_timeout_is_unreachable():
    respx.get("https://timeout.example.com/robots.txt").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    async with Fetcher(user_agent=UA, sleep=_no_sleep) as f:
        policy = await check_host(f, "timeout.example.com", UA)
    assert policy.source_state == "unreachable"


@respx.mock
async def test_root_disallowed_for_our_ua_is_policy_closed():
    respx.get("https://closed.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text=f"User-agent: {UA}\nDisallow: /\n")
    )
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "closed.example.com", UA)
    assert policy.source_state == "policy_closed"
    assert policy.crawlable() is False


@respx.mock
async def test_specific_path_disallowed_still_open_and_per_url_decision():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")
    )
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "example.com", UA)
    assert policy.source_state == "open"
    assert policy.decision("https://example.com/about", UA) == "allowed"
    assert policy.decision("https://example.com/admin/secret", UA) == "disallowed"


@respx.mock
async def test_sitemap_lines_are_parsed():
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text="User-agent: *\nSitemap: https://example.com/sitemap1.xml\n"
            "Sitemap: https://example.com/sitemap2.xml\n",
        )
    )
    async with Fetcher(user_agent=UA) as f:
        policy = await check_host(f, "example.com", UA)
    assert policy.sitemap_urls == (
        "https://example.com/sitemap1.xml",
        "https://example.com/sitemap2.xml",
    )


@respx.mock
async def test_robots_cache_fetches_a_host_at_most_once_per_run():
    route = respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    async with Fetcher(user_agent=UA) as f:
        cache = RobotsCache(f, UA)
        p1 = await cache.get("example.com")
        p2 = await cache.get("example.com")
    assert p1 is p2
    assert route.call_count == 1


@respx.mock
async def test_robots_cache_pushes_crawl_delay_into_the_limiter():
    respx.get("https://slow.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 7\n")
    )
    async with Fetcher(user_agent=UA) as f:
        cache = RobotsCache(f, UA)
        await cache.get("slow.example.com")
        assert f.limiter.interval_for("slow.example.com") == 7.0


async def _no_sleep(_seconds: float) -> None:
    return None


# --- persistence -------------------------------------------------------


@pytest.mark.db
def test_persist_upserts_source_registry_without_clobbering_platform(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO source_registry (host, source_state, platform, notes) "
            "VALUES (%s, %s, %s, %s)",
            ("example.com", "open", "wordpress", "hand-curated note"),
        )

    persist(
        db,
        RobotsPolicy(host="example.com", source_state="rate_limited", crawl_delay_s=5.0,
                      robots_txt="User-agent: *\nCrawl-delay: 5\n"),
    )

    with db.cursor() as cur:
        cur.execute(
            "SELECT source_state, crawl_delay_s, platform, notes, robots_txt "
            "FROM source_registry WHERE host = %s",
            ("example.com",),
        )
        row = cur.fetchone()
    assert row["source_state"] == "rate_limited"
    assert float(row["crawl_delay_s"]) == 5.0
    assert row["platform"] == "wordpress"  # untouched
    assert row["notes"] == "hand-curated note"  # untouched
    assert "Crawl-delay: 5" in row["robots_txt"]


@pytest.mark.db
def test_persist_inserts_a_new_host(db):
    persist(db, RobotsPolicy(host="new.example.com", source_state="open", crawl_delay_s=None))

    with db.cursor() as cur:
        cur.execute(
            "SELECT source_state FROM source_registry WHERE host = %s", ("new.example.com",)
        )
        row = cur.fetchone()
    assert row["source_state"] == "open"


# Found live: a robots.txt declaring "Sitemap: /sitemap.xml" (relative — the spec
# requires absolute) aborted the 242-firm probe.
@pytest.mark.asyncio
@respx.mock
async def test_relative_sitemap_url_is_resolved_against_the_host():
    from lge.fetch.client import Fetcher
    from lge.fetch.ratelimit import HostRateLimiter
    from lge.fetch.robots import RobotsCache

    respx.get("https://rel.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nSitemap: /sitemap.xml\n")
    )
    async with Fetcher(
        user_agent="TestUA/1.0 (+https://example.test)",
        limiter=HostRateLimiter(default_interval_s=0.0),
    ) as fetcher:
        policy = await RobotsCache(fetcher, "TestUA/1.0").get("rel.example.com")
    assert policy.sitemap_urls == ("https://rel.example.com/sitemap.xml",)
