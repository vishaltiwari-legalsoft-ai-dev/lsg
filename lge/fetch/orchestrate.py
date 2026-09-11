"""Bound how many per-firm fetch tasks run concurrently at once.

This caps concurrent HOSTS (config/crawl.yml: max_concurrent_hosts) — it
does NOT relax any single host's own rate limit, which
lge.fetch.ratelimit.HostRateLimiter already enforces regardless of how many
coroutines are in flight. Shared by P1, P2 and JA1 so "different hosts run
concurrently, one host serialises" is one tested implementation instead of
three.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

_log = logging.getLogger(__name__)


async def gather_bounded[T](
    factories: Mapping[str, Callable[[], Awaitable[T]]], max_concurrent: int
) -> dict[str, T]:
    """Run every zero-arg async factory in `factories`, at most
    `max_concurrent` at a time, keyed by the same key on the way out."""
    if not factories:
        return {}
    semaphore = asyncio.Semaphore(max(1, max_concurrent))

    # One broken site must never stall the sweep. An unexpected exception in one
    # entity's work is logged with its key and that key is OMITTED from the result:
    # the caller writes nothing for it, so its idempotency marker is never set and
    # the next run retries it. (First found live: a robots.txt with a relative
    # "Sitemap: /sitemap.xml" aborted a 242-firm probe.)
    async def bound(key: str, factory: Callable[[], Awaitable[T]]) -> tuple[str, T] | None:
        async with semaphore:
            try:
                return key, await factory()
            except Exception:  # noqa: BLE001 — isolation is the point
                _log.exception("entity %s failed; skipped this run, retried next run", key)
                return None

    results = await asyncio.gather(*(bound(key, factory) for key, factory in factories.items()))
    return dict(r for r in results if r is not None)
