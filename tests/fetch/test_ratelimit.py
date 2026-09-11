"""HostRateLimiter: one host serialised to <=1 request/interval regardless
of concurrency; different hosts run fully concurrently; a declared
Crawl-delay overrides the default only upward, never down."""

from __future__ import annotations

import asyncio

import pytest

from lge.fetch.ratelimit import DEFAULT_INTERVAL_S, HostRateLimiter


class FakeClock:
    """A virtual clock: sleep() advances time instantly instead of really
    waiting, so the arithmetic is tested without a slow test suite."""

    def __init__(self) -> None:
        self.t = 0.0

    def time(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        # A real checkpoint (unlike a synchronous no-op) so other ready
        # coroutines get a turn while this one is "waiting" -- otherwise
        # nothing in this test would ever interleave and every acquire()
        # would run to completion back-to-back regardless of host.
        await asyncio.sleep(0)
        self.t += seconds


def make_limiter(default_interval_s: float = 2.0) -> tuple[HostRateLimiter, FakeClock]:
    clock = FakeClock()
    limiter = HostRateLimiter(
        default_interval_s=default_interval_s, clock=clock.time, sleep=clock.sleep
    )
    return limiter, clock


async def test_default_interval_is_two_seconds():
    assert DEFAULT_INTERVAL_S == 2.0


async def test_first_request_never_waits():
    limiter, clock = make_limiter()
    await limiter.acquire("example.com")
    assert clock.t == 0.0


async def test_same_host_serialised_to_interval():
    limiter, clock = make_limiter(default_interval_s=2.0)
    grant_times: list[float] = []

    async def worker():
        await limiter.acquire("example.com")
        grant_times.append(clock.t)

    # Three concurrent callers for the SAME host.
    await asyncio.gather(worker(), worker(), worker())

    grant_times.sort()
    assert grant_times == [0.0, 2.0, 4.0]


async def test_different_hosts_run_concurrently():
    limiter, clock = make_limiter(default_interval_s=2.0)
    grant_times: dict[str, float] = {}

    async def worker(host: str):
        await limiter.acquire(host)
        grant_times[host] = clock.t

    await asyncio.gather(worker("a.example.com"), worker("b.example.com"))

    # Neither host waited on the other -- both granted at the same (zero) time.
    assert grant_times["a.example.com"] == 0.0
    assert grant_times["b.example.com"] == 0.0


async def test_one_host_serialised_while_another_runs_concurrently():
    limiter, clock = make_limiter(default_interval_s=2.0)
    grants: list[tuple[str, float]] = []

    async def worker(host: str):
        await limiter.acquire(host)
        grants.append((host, clock.t))

    await asyncio.gather(
        worker("busy.example.com"),
        worker("busy.example.com"),
        worker("other.example.com"),
    )

    busy_times = sorted(t for h, t in grants if h == "busy.example.com")
    other_times = [t for h, t in grants if h == "other.example.com"]
    assert busy_times == [0.0, 2.0]
    assert other_times == [0.0]  # unaffected by busy.example.com's queue


async def test_crawl_delay_overrides_default_upward():
    limiter, clock = make_limiter(default_interval_s=2.0)
    limiter.set_interval("slow.example.com", 5.0)
    assert limiter.interval_for("slow.example.com") == 5.0

    await limiter.acquire("slow.example.com")
    await limiter.acquire("slow.example.com")
    assert clock.t == 5.0


async def test_crawl_delay_never_goes_below_default():
    limiter, clock = make_limiter(default_interval_s=2.0)
    limiter.set_interval("fast.example.com", 0.5)  # declares LESS than our floor
    assert limiter.interval_for("fast.example.com") == 2.0

    await limiter.acquire("fast.example.com")
    await limiter.acquire("fast.example.com")
    assert clock.t == 2.0


async def test_set_interval_none_is_a_no_op():
    limiter, _clock = make_limiter(default_interval_s=2.0)
    limiter.set_interval("example.com", None)
    assert limiter.interval_for("example.com") == 2.0


async def test_push_next_allowed_delays_the_next_acquire():
    limiter, clock = make_limiter(default_interval_s=2.0)
    await limiter.acquire("example.com")  # grant at t=0, next_allowed=2
    limiter.push_next_allowed("example.com", 10.0)  # e.g. a 429 Retry-After
    await limiter.acquire("example.com")
    assert clock.t == 10.0


async def test_push_next_allowed_never_moves_time_backward():
    limiter, clock = make_limiter(default_interval_s=2.0)
    await limiter.acquire("example.com")  # next_allowed = 2.0
    limiter.push_next_allowed("example.com", 1.0)  # earlier than current -- ignored
    await limiter.acquire("example.com")
    assert clock.t == 2.0


@pytest.mark.asyncio
async def test_real_clock_default_works_without_injection():
    limiter = HostRateLimiter(default_interval_s=0.05)
    start = asyncio.get_event_loop().time()
    await limiter.acquire("example.com")
    await limiter.acquire("example.com")
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.04  # allow small scheduling jitter under 0.05s
