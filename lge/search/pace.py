"""Pacing and retries, the same for every engine (D-039, D-041): a steady
gap with jitter, a rest once the window's worth has gone out, a retry after
a dropped connection, and -- on a bot check or a rate limit -- one patient
second try, then a cooldown during which every query fails at once so the
planes' breaker stops the run. Clock and sleep are injectable for tests.
"""

from __future__ import annotations

import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from lge.search.base import FAILURE_PREFIX, Result, SearchBlocked, failure


@dataclass(frozen=True)
class Pace:
    interval_s: float = 0.0
    jitter_s: float = 0.0
    window_queries: int = 0
    window_s: float = 0.0
    backoff_s: tuple[float, ...] = (15.0, 45.0)
    block_backoff_s: float = 90.0
    block_cooldown_s: float = 1200.0

    @classmethod
    def from_config(cls, raw: dict | None) -> Pace:
        raw = raw or {}
        return cls(
            interval_s=float(raw.get("interval_s", 0.0)),
            jitter_s=float(raw.get("jitter_s", 0.0)),
            window_queries=int(raw.get("window_queries", 0)),
            window_s=float(raw.get("window_s", 0.0)),
            backoff_s=tuple(float(x) for x in raw.get("backoff_s", (15.0, 45.0))),
            block_backoff_s=float(raw.get("block_backoff_s", 90.0)),
            block_cooldown_s=float(raw.get("block_cooldown_s", 1200.0)),
        )


def transient(exc: Exception) -> bool:
    """A dropped connection, a timeout, a rate limit: worth a second try."""
    text = f"{type(exc).__name__}: {exc}".lower()
    words = ("connect", "timeout", "timed out", "ratelimit", "rate limit", "503", "502")
    return any(w in text for w in words)


class Pacer:
    def __init__(
        self,
        pace: Pace,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.pace = pace
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter
        self._last_at = 0.0
        self._recent: deque[float] = deque()
        self._blocked_until = 0.0

    def blocked_reason(self) -> str | None:
        if self._monotonic() < self._blocked_until:
            return "blocked -- the engine asked for a bot check earlier; leaving it alone for now"
        return None

    def mark(self) -> None:
        """A request is going out now."""
        self._last_at = self._monotonic()
        self._recent.append(self._last_at)

    def wait(self) -> None:
        """Until the next query is due: the steady interval with a little
        jitter, and a rest when the window's worth has already gone out."""
        p = self.pace
        now = self._monotonic()
        jitter = self._jitter(0, p.jitter_s) if p.jitter_s else 0.0
        wait = p.interval_s + jitter - (now - self._last_at)
        while self._recent and now - self._recent[0] >= p.window_s:
            self._recent.popleft()
        if p.window_queries and len(self._recent) >= p.window_queries:
            wait = max(wait, self._recent[0] + p.window_s - now)
        if wait > 0:
            self._sleep(wait)

    def call(self, fn: Callable[[], list[Result]], *, engine: str) -> list[Result]:
        """Run one engine request under the pace. Returns results, an empty
        list for a real "nothing", or one failure row."""
        reason = self.blocked_reason()
        if reason:
            return failure(f"{FAILURE_PREFIX}: {reason}")
        self.wait()
        pauses = list(self.pace.backoff_s)
        blocked_once = False
        while True:
            self.mark()
            try:
                return fn()
            except SearchBlocked as exc:
                if blocked_once or not self.pace.block_backoff_s:
                    self._blocked_until = self._monotonic() + self.pace.block_cooldown_s
                    return failure(f"{FAILURE_PREFIX}: blocked -- {engine}: {exc}")
                blocked_once = True
                self._sleep(self.pace.block_backoff_s)  # the check usually clears if we stop asking
            except Exception as exc:  # noqa: BLE001 -- a failed search is an unresolved answer
                if not pauses or not transient(exc):
                    return failure(f"{FAILURE_PREFIX}: {type(exc).__name__}: {exc}")
                self._sleep(pauses.pop(0))  # wait, then try again
