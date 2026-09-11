"""The Fetcher -- the only place components make outbound HTTP calls.

Honest identity: refuses to construct at all with an empty user agent, so
nothing downstream can fetch anonymously or under a borrowed identity ("never
rotated to evade, never impersonating a browser or a named search bot" --
context/70-decisions/02-deliberate-exclusions.md). The live-network gate
itself (settings.live / --opt live=1) is each component's job, not this
module's -- a component checks that BEFORE ever constructing a Fetcher.

Every fetch goes through the per-host token bucket
(lge.fetch.ratelimit.HostRateLimiter) and is recorded as a FetchResult
regardless of outcome -- url, final url, status, headers, body, duration,
whether it succeeded, and why not when it didn't.

Timeouts: connect 10s, read 20s. <=5 redirects (httpx follows them and
reports the final url). Body capped at 5MB -- anything larger is truncated,
never buffered without bound. One retry on connect error or 5xx, with a
short fixed backoff.

429 honours Retry-After by pushing the host's next-allowed time out on the
shared limiter, rather than blocking this coroutine for the full duration.
Three 403/429 responses from one host in a run -- "stop, do not retry
harder" (context/20-signals/05-crawl-policy-and-audit.md) -- trip the
HostBlockTracker; every subsequent fetch to that host in this run
short-circuits to a synthetic failure without ever touching the network.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from lge.fetch.ratelimit import HostRateLimiter

logger = logging.getLogger("lge.fetch.client")

CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 20.0
MAX_REDIRECTS = 5
BODY_CAP_BYTES = 5 * 1024 * 1024  # 5 MB
ACCEPTED_CONTENT_TYPES = ("text/html", "application/json")
RETRY_BACKOFF_S = 1.0
MAX_ATTEMPTS = 2  # one retry on connect error / 5xx
BLOCK_THRESHOLD = 3  # three 403/429 in a run -> stop requesting the host

_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class EmptyUserAgentError(RuntimeError):
    """Refused: settings.user_agent is empty. Never fetch anonymously."""


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max(0.0, (dt - datetime.now(UTC)).total_seconds())


@dataclass
class FetchResult:
    url: str
    final_url: str | None = None
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    fetch_ok: bool = False
    error: str | None = None
    # 'allowed' | 'disallowed' | None (host not crawlable / not checked)
    robots_decision: str | None = None
    elapsed_ms: int = 0
    content_type_ok: bool = True

    @property
    def content_hash(self) -> str | None:
        if self.body is None:
            return None
        return hashlib.sha256(self.body).hexdigest()


@dataclass
class HostBlockTracker:
    """Counts 403/429 responses per host during one run. At BLOCK_THRESHOLD
    the host is marked blocked and every later `Fetcher.fetch` to it
    short-circuits without a network call."""

    _counts: dict[str, dict[int, int]] = field(default_factory=dict)
    _blocked: dict[str, str] = field(default_factory=dict)

    def record(self, host: str, status: int) -> str | None:
        """Returns the source_state newly tripped this call, or None."""
        if status not in (403, 429):
            return None
        counts = self._counts.setdefault(host, {403: 0, 429: 0})
        counts[status] += 1
        if host in self._blocked:
            return None
        total = counts[403] + counts[429]
        if total >= BLOCK_THRESHOLD:
            state = "edge_blocked" if counts[403] >= counts[429] else "rate_limited"
            self._blocked[host] = state
            logger.warning(
                "host %s: %d blocking response(s) this run (403=%d 429=%d) -- "
                "stopping, marking %s",
                host,
                total,
                counts[403],
                counts[429],
                state,
            )
            return state
        return None

    def is_blocked(self, host: str) -> bool:
        return host in self._blocked

    def blocked_state(self, host: str) -> str | None:
        return self._blocked.get(host)

    def blocked_hosts(self) -> dict[str, str]:
        return dict(self._blocked)


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        limiter: HostRateLimiter | None = None,
        block_tracker: HostBlockTracker | None = None,
        client: httpx.AsyncClient | None = None,
        clock: object | None = None,
        sleep: object | None = None,
    ) -> None:
        if not user_agent or not user_agent.strip():
            raise EmptyUserAgentError(
                "refusing to fetch: no honest user agent configured "
                "(settings.user_agent is empty) -- set LGE_USER_AGENT"
            )
        self.user_agent = user_agent
        self.limiter = limiter or HostRateLimiter()
        self.block_tracker = block_tracker or HostBlockTracker()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_S,
                read=READ_TIMEOUT_S,
                write=READ_TIMEOUT_S,
                pool=READ_TIMEOUT_S,
            ),
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
        )
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def fetch(self, url: str, *, robots_decision: str | None = None) -> FetchResult:
        host = host_of(url)

        if robots_decision == "disallowed":
            return FetchResult(
                url=url,
                fetch_ok=False,
                error="robots.txt disallows this path for our user agent",
                robots_decision=robots_decision,
            )

        if self.block_tracker.is_blocked(host):
            blocked_state = self.block_tracker.blocked_state(host)
            return FetchResult(
                url=url,
                fetch_ok=False,
                error=f"host blocked this run (source_state={blocked_state})",
                robots_decision=robots_decision,
            )

        await self.limiter.acquire(host)
        start = self._clock()
        attempt = 0
        resp: httpx.Response | None = None
        last_error: str | None = None

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            try:
                resp = await self._client.get(url, headers={"User-Agent": self.user_agent})
            except _RETRYABLE_TRANSPORT_ERRORS as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                resp = None
                if attempt < MAX_ATTEMPTS:
                    await self._sleep(RETRY_BACKOFF_S)
                    continue
                break
            if resp.status_code >= 500 and attempt < MAX_ATTEMPTS:
                last_error = f"http {resp.status_code}"
                await self._sleep(RETRY_BACKOFF_S)
                continue
            break

        elapsed_ms = int((self._clock() - start) * 1000)

        if resp is None:
            return FetchResult(
                url=url,
                fetch_ok=False,
                error=last_error,
                robots_decision=robots_decision,
                elapsed_ms=elapsed_ms,
            )

        if resp.status_code in (403, 429):
            self.block_tracker.record(host, resp.status_code)
            if resp.status_code == 429:
                retry_after = _parse_retry_after(resp.headers.get("retry-after"))
                if retry_after is not None:
                    self.limiter.push_next_allowed(host, self._clock() + retry_after)

        content_type = resp.headers.get("content-type", "")
        content_type_ok = (
            any(ct in content_type for ct in ACCEPTED_CONTENT_TYPES) if content_type else True
        )

        body = resp.content
        if len(body) > BODY_CAP_BYTES:
            body = body[:BODY_CAP_BYTES]

        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            headers=dict(resp.headers),
            body=body,
            fetch_ok=True,
            error=None,
            robots_decision=robots_decision,
            elapsed_ms=elapsed_ms,
            content_type_ok=content_type_ok,
        )
