"""Per-host async token bucket -- the crawler's rate discipline.

DEFERRED: context/40-pipeline/02-component-register.md specifies a per-host
token bucket *in Redis*, shared across worker processes. This is an
in-process asyncio implementation only -- correct within one component
invocation (one `lge run <name>` process), not across concurrently running
worker processes hitting the same host. Acceptable for this stage since
components run one at a time; revisit if the crawler is ever split across
worker processes that could contend for the same host concurrently.

interval = max(default_interval_s, the host's declared Crawl-delay). One
host never sees more than one request per interval, regardless of how many
coroutines try to fetch it at once -- enforced with one asyncio.Lock plus a
next-allowed-at timestamp per host, so concurrent callers for the same host
queue up single file rather than colliding. Different hosts never share a
lock, so they proceed fully concurrently (bounded elsewhere by
`max_concurrent_hosts` -- see config/crawl.yml).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

DEFAULT_INTERVAL_S = 2.0

ClockFn = Callable[[], float]
SleepFn = Callable[[float], Awaitable[None]]


class HostRateLimiter:
    def __init__(
        self,
        *,
        default_interval_s: float = DEFAULT_INTERVAL_S,
        clock: ClockFn | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self.default_interval_s = default_interval_s
        # Real wall-clock defaults; both are swappable for deterministic tests.
        self._clock: ClockFn = clock or time.monotonic
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._intervals: dict[str, float] = {}
        self._next_allowed: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_interval(self, host: str, interval_s: float | None) -> None:
        """Record a host's declared Crawl-delay. The effective interval is
        always >= default_interval_s -- a host declaring a *shorter* delay
        than our floor does not speed us up (context/20-signals/05-crawl-
        policy-and-audit.md: "Crawl-delay is read, not assumed", "falling
        back to 2s only where none is declared" -- never below it)."""
        if interval_s is None:
            return
        self._intervals[host] = max(self.default_interval_s, float(interval_s))

    def interval_for(self, host: str) -> float:
        return self._intervals.get(host, self.default_interval_s)

    def push_next_allowed(self, host: str, at: float) -> None:
        """Force the next request to `host` no earlier than `at` (clock
        units). Used to honour a 429's Retry-After without blocking the
        calling coroutine for the whole duration."""
        current = self._next_allowed.get(host)
        if current is None or at > current:
            self._next_allowed[host] = at

    def _lock(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def acquire(self, host: str) -> None:
        """Block until it is this host's turn. Concurrent callers for the
        same host queue on the lock; each one re-reads the clock after
        waking so a chain of waiters pays the full interval from the
        previous grant, never less."""
        async with self._lock(host):
            interval = self.interval_for(host)
            now = self._clock()
            next_allowed = self._next_allowed.get(host, now)
            wait = next_allowed - now
            if wait > 0:
                await self._sleep(wait)
                now = self._clock()
            self._next_allowed[host] = now + interval
