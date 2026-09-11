"""The crawl layer P1, P2, P3 and JA1 build on.

Honest identity, per-host rate discipline, robots.txt compliance, and the
"stop, do not retry harder" rule all live here so every plane component
gets them for free instead of re-implementing (and re-getting-wrong) crawl
policy each time. See context/20-signals/05-crawl-policy-and-audit.md.
"""

from __future__ import annotations

from lge.fetch.client import (
    EmptyUserAgentError,
    Fetcher,
    FetchResult,
    HostBlockTracker,
    host_of,
)
from lge.fetch.config import load_crawl_config, rate_defaults
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.ratelimit import DEFAULT_INTERVAL_S, HostRateLimiter
from lge.fetch.robots import RobotsCache, RobotsPolicy, check_host
from lge.fetch.robots import persist as persist_robots_policy
from lge.fetch.selection import already_done, select_firm_ids

__all__ = [
    "DEFAULT_INTERVAL_S",
    "EmptyUserAgentError",
    "FetchResult",
    "Fetcher",
    "HostBlockTracker",
    "HostRateLimiter",
    "RobotsCache",
    "RobotsPolicy",
    "already_done",
    "check_host",
    "gather_bounded",
    "host_of",
    "load_crawl_config",
    "persist_robots_policy",
    "rate_defaults",
    "select_firm_ids",
]
