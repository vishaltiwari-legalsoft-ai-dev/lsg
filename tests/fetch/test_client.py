"""Fetcher: honest-UA refusal, timeouts/redirects config, retry on connect
error/5xx, 429 Retry-After backoff, three-403-or-429 stops the host, robots
'disallowed' short-circuits without a network call, body cap."""

from __future__ import annotations

import httpx
import pytest
import respx

from lge.fetch.client import (
    BLOCK_THRESHOLD,
    BODY_CAP_BYTES,
    MAX_REDIRECTS,
    EmptyUserAgentError,
    Fetcher,
    HostBlockTracker,
    host_of,
)
from lge.fetch.ratelimit import HostRateLimiter


def _fast_limiter() -> HostRateLimiter:
    """Several tests below fire multiple requests at the SAME host to prove
    the 403/429 block-threshold -- rate-limiting behaviour itself is covered
    by test_ratelimit.py, so those use a zero-interval limiter to stay fast
    rather than paying the real 2s-per-request floor."""
    return HostRateLimiter(default_interval_s=0.0)

UA = "TestBot/1.0 (+https://example.com/bot)"


def test_empty_user_agent_refuses_to_construct():
    with pytest.raises(EmptyUserAgentError):
        Fetcher(user_agent="")


def test_whitespace_only_user_agent_refuses():
    with pytest.raises(EmptyUserAgentError):
        Fetcher(user_agent="   ")


def test_host_of_extracts_lowercase_hostname():
    assert host_of("https://Example.COM/path?q=1") == "example.com"


def test_client_config_constants():
    assert MAX_REDIRECTS == 5
    assert BODY_CAP_BYTES == 5 * 1024 * 1024


@respx.mock
async def test_successful_fetch_records_everything():
    respx.get("https://example.com/about").mock(
        return_value=httpx.Response(200, html="<html>hi</html>")
    )
    async with Fetcher(user_agent=UA) as f:
        r = await f.fetch("https://example.com/about")
    assert r.fetch_ok is True
    assert r.status == 200
    assert r.body == b"<html>hi</html>"
    assert r.content_hash is not None
    assert r.final_url == "https://example.com/about"
    assert r.content_type_ok is True
    assert r.elapsed_ms >= 0


@respx.mock
async def test_disallowed_robots_decision_never_makes_a_request():
    route = respx.get("https://example.com/admin")
    async with Fetcher(user_agent=UA) as f:
        r = await f.fetch("https://example.com/admin", robots_decision="disallowed")
    assert r.fetch_ok is False
    assert "disallow" in r.error.lower()
    assert route.call_count == 0


@respx.mock
async def test_connect_error_retries_once_then_fails():
    route = respx.get("https://down.example.com/x").mock(side_effect=httpx.ConnectError("boom"))
    async with Fetcher(user_agent=UA, sleep=_no_sleep) as f:
        r = await f.fetch("https://down.example.com/x")
    assert r.fetch_ok is False
    assert route.call_count == 2  # one original attempt + one retry


@respx.mock
async def test_connect_error_then_success_on_retry():
    route = respx.get("https://flaky.example.com/x")
    route.side_effect = [httpx.ConnectError("boom"), httpx.Response(200, text="ok")]
    async with Fetcher(user_agent=UA, sleep=_no_sleep) as f:
        r = await f.fetch("https://flaky.example.com/x")
    assert r.fetch_ok is True
    assert r.status == 200
    assert route.call_count == 2


@respx.mock
async def test_5xx_retries_once_then_records_the_failed_status():
    route = respx.get("https://error.example.com/x").mock(return_value=httpx.Response(503))
    async with Fetcher(user_agent=UA, sleep=_no_sleep) as f:
        r = await f.fetch("https://error.example.com/x")
    assert route.call_count == 2
    assert r.fetch_ok is True  # a response WAS received on the retry
    assert r.status == 503


@respx.mock
async def test_404_is_fetch_ok_true_not_a_failure():
    respx.get("https://example.com/nope").mock(return_value=httpx.Response(404))
    async with Fetcher(user_agent=UA) as f:
        r = await f.fetch("https://example.com/nope")
    assert r.fetch_ok is True
    assert r.status == 404


@respx.mock
async def test_429_honours_retry_after_by_pushing_next_allowed():
    respx.get("https://slow.example.com/x").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    tracker = HostBlockTracker()
    async with Fetcher(user_agent=UA, block_tracker=tracker, limiter=_fast_limiter()) as f:
        await f.fetch("https://slow.example.com/x")
        next_allowed = f.limiter._next_allowed.get("slow.example.com", 0.0)
        now = f.limiter._clock()
    # Retry-After pushed the host's next-allowed time out by ~30s beyond now.
    assert next_allowed - now >= 25.0


@respx.mock
async def test_three_403_responses_block_the_host_as_edge_blocked():
    respx.get("https://blocked.example.com/a").mock(return_value=httpx.Response(403))
    respx.get("https://blocked.example.com/b").mock(return_value=httpx.Response(403))
    respx.get("https://blocked.example.com/c").mock(return_value=httpx.Response(403))
    route_d = respx.get("https://blocked.example.com/d")

    async with Fetcher(user_agent=UA, sleep=_no_sleep, limiter=_fast_limiter()) as f:
        await f.fetch("https://blocked.example.com/a")
        await f.fetch("https://blocked.example.com/b")
        r3 = await f.fetch("https://blocked.example.com/c")
        assert f.block_tracker.is_blocked("blocked.example.com") is True
        assert f.block_tracker.blocked_state("blocked.example.com") == "edge_blocked"

        # A fourth fetch to the same host must short-circuit -- no request.
        r4 = await f.fetch("https://blocked.example.com/d")
    assert r3.status == 403
    assert r4.fetch_ok is False
    assert "blocked" in r4.error.lower()
    assert route_d.call_count == 0


@respx.mock
async def test_three_429_responses_block_the_host_as_rate_limited():
    for i in range(3):
        respx.get(f"https://ratelimited.example.com/{i}").mock(return_value=httpx.Response(429))

    async with Fetcher(user_agent=UA, sleep=_no_sleep, limiter=_fast_limiter()) as f:
        for i in range(3):
            await f.fetch(f"https://ratelimited.example.com/{i}")
        assert f.block_tracker.blocked_state("ratelimited.example.com") == "rate_limited"


@respx.mock
async def test_blocking_is_per_host_not_global():
    respx.get("https://a.example.com/x").mock(return_value=httpx.Response(403))
    respx.get("https://a.example.com/y").mock(return_value=httpx.Response(403))
    respx.get("https://a.example.com/z").mock(return_value=httpx.Response(403))
    respx.get("https://b.example.com/x").mock(return_value=httpx.Response(200, text="fine"))

    async with Fetcher(user_agent=UA, sleep=_no_sleep, limiter=_fast_limiter()) as f:
        await f.fetch("https://a.example.com/x")
        await f.fetch("https://a.example.com/y")
        await f.fetch("https://a.example.com/z")
        r = await f.fetch("https://b.example.com/x")
    assert f.block_tracker.is_blocked("a.example.com") is True
    assert f.block_tracker.is_blocked("b.example.com") is False
    assert r.fetch_ok is True
    assert r.status == 200


def test_block_threshold_is_three():
    assert BLOCK_THRESHOLD == 3


async def _no_sleep(_seconds: float) -> None:
    return None
