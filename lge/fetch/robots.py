"""robots.txt: fetch once per host per run, parse, persist to
`source_registry`, and answer per-URL allow/disallow decisions for the rest
of the run.

Source state is not a boolean (context/20-signals/05-crawl-policy-and-
audit.md):

    200                            -> open (rate_limited if Crawl-delay set)
    404 / 410                      -> open (no rules published)
    401 / 403 on robots.txt itself -> edge_blocked -- NOT closed. No policy
                                       was read; never try to defeat it.
    5xx / connect error / timeout  -> unreachable -- skip this run, draw no
                                       conclusion about policy either way
    root '/' disallowed for our UA
    (or for '*')                   -> policy_closed -- a published rule,
                                       stable and deliberate

Each component (P1, P2, JA1) constructs its own `RobotsCache` per run and
fetches robots.txt itself rather than trusting a prior run's row in
`source_registry` -- "fetch /robots.txt once per host per run" is a
per-*run* guarantee, not a cross-run cache. `persist()` is called by the
component in its sequential DB-write phase, once per host visited.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

import psycopg
from protego import Protego

from lge.fetch.client import Fetcher

logger = logging.getLogger("lge.fetch.robots")

# A declared Crawl-delay above this is honoured but cannot be mapped or swept
# within one run: cavanaghlawgroup.com declares 600s, so robots + sitemap +
# homepage alone would take half an hour and one firm's pages two hours (D-026).
SLOW_HOST_DELAY_S = 60.0

VALID_SOURCE_STATES = (
    "open",
    "rate_limited",
    "policy_closed",
    "edge_blocked",
    "unreachable",
    "auth_required",
)


@dataclass
class RobotsPolicy:
    host: str
    source_state: str
    crawl_delay_s: float | None = None
    robots_txt: str | None = None
    sitemap_urls: tuple[str, ...] = ()
    parser: Protego | None = field(default=None, repr=False, compare=False)

    def crawlable(self) -> bool:
        return self.source_state in ("open", "rate_limited")

    @property
    def slow(self) -> bool:
        """Crawlable, but only a request or two per run fits (see SLOW_HOST_DELAY_S)."""
        return self.crawl_delay_s is not None and self.crawl_delay_s > SLOW_HOST_DELAY_S

    def decision(self, url: str, user_agent: str) -> str:
        """'allowed' | 'disallowed' for one specific URL under this policy.

        No robots.txt found (404/410) -> no rules -> always allowed.
        """
        if self.parser is None:
            return "allowed"
        return "allowed" if self.parser.can_fetch(url, user_agent) else "disallowed"


def _robots_url(host: str) -> str:
    return f"https://{host}/robots.txt"


def _state_from_status(status: int | None) -> str:
    if status == 200:
        return "open"
    if status in (404, 410):
        return "open"
    if status in (401, 403):
        return "edge_blocked"
    # 5xx, or no status at all (connect error / timeout / other transport
    # failure) -- a network condition, not a policy. Draw no conclusion.
    return "unreachable"


async def check_host(fetcher: Fetcher, host: str, user_agent: str) -> RobotsPolicy:
    """One robots.txt fetch for `host`. Never raises on a bad response --
    every failure mode maps to a source_state instead."""
    result = await fetcher.fetch(_robots_url(host))
    state = _state_from_status(result.status)

    parser: Protego | None = None
    crawl_delay: float | None = None
    sitemap_urls: tuple[str, ...] = ()
    robots_txt: str | None = None

    if state == "open" and result.status == 200 and result.body is not None:
        robots_txt = result.body.decode("utf-8", errors="replace")
        parser = Protego.parse(robots_txt)
        crawl_delay = parser.crawl_delay(user_agent)
        # The spec requires absolute Sitemap URLs; real sites write "Sitemap:
        # /sitemap.xml". Resolve against the host, as a browser would, and keep only
        # http(s) results.
        resolved = (urljoin(f"https://{host}/", s.strip()) for s in parser.sitemaps)
        sitemap_urls = tuple(u for u in resolved if u.startswith(("http://", "https://")))
        if crawl_delay is not None:
            state = "rate_limited"
        # A published rule closing the whole site to our UA (or to everyone)
        # is `policy_closed`, not merely `open` with an empty crawl set.
        if not parser.can_fetch(f"https://{host}/", user_agent):
            state = "policy_closed"

    return RobotsPolicy(
        host=host,
        source_state=state,
        crawl_delay_s=crawl_delay,
        robots_txt=robots_txt,
        sitemap_urls=sitemap_urls,
        parser=parser,
    )


def persist(conn: psycopg.Connection, policy: RobotsPolicy) -> None:
    """Upsert this run's robots reading into source_registry. Leaves
    `platform`, `source_kind` and `notes` alone -- those belong to other
    components (P7 tech fingerprint; manual registry curation)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO source_registry (host, source_state, crawl_delay_s,
                                          robots_checked, robots_txt)
            VALUES (%s, %s, %s, now(), %s)
            ON CONFLICT (host) DO UPDATE SET
              source_state   = EXCLUDED.source_state,
              crawl_delay_s  = EXCLUDED.crawl_delay_s,
              robots_checked = EXCLUDED.robots_checked,
              robots_txt     = EXCLUDED.robots_txt
            """,
            (policy.host, policy.source_state, policy.crawl_delay_s, policy.robots_txt),
        )


class RobotsCache:
    """Per-run memo: at most one robots.txt fetch per host within one
    component invocation. Also pushes the host's declared Crawl-delay (if
    any) into the fetcher's rate limiter so every subsequent request to that
    host in this run honours it."""

    def __init__(self, fetcher: Fetcher, user_agent: str) -> None:
        self._fetcher = fetcher
        self._ua = user_agent
        self._cache: dict[str, RobotsPolicy] = {}

    async def get(self, host: str) -> RobotsPolicy:
        cached = self._cache.get(host)
        if cached is not None:
            return cached
        policy = await check_host(self._fetcher, host, self._ua)
        self._cache[host] = policy
        self._fetcher.limiter.set_interval(host, policy.crawl_delay_s)
        return policy

    def snapshot(self) -> dict[str, RobotsPolicy]:
        return dict(self._cache)
