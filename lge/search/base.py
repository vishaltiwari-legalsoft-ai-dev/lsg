"""What every search engine behind the seam looks like to the rest of the
engine: one query in, rows of {title, href, body} out, the same shape the
DuckDuckGo path always returned, so no consumer knows which engine answered.

A *failure* travels as one row whose body starts with "search failed" -- the
convention the planes' five-failure breaker reads -- and an empty list is a
real "nothing found". `SearchBlocked` is the engine asking us to stop: a bot
check, a rate limit. It is never worked around (D-039).
"""

from __future__ import annotations

from typing import Any, Protocol

Result = dict[str, str]  # title, href, body
Place = dict[str, Any]  # name, address, rating, review_count, phone, website, url

FAILURE_PREFIX = "search failed"


class SearchBlocked(Exception):
    """The engine answered with a bot check or a rate limit instead of results."""


class SearchEngine(Protocol):
    name: str

    def search(self, query: str, max_results: int, page: int) -> list[Result]:
        """One request. Raises SearchBlocked on a bot check / rate limit and
        any other exception on a transport or server failure; the pacer
        turns those into retries, cooldowns and failure rows."""
        ...

    def places(self, query: str) -> list[Place] | None:
        """The engine's business-listing lookup (Google Business Profile),
        or None when this engine has no such thing -- the caller then reads
        what it can off ordinary result snippets."""
        ...


def failure(text: str) -> list[Result]:
    return [{"title": "", "href": "", "body": text}]


def is_failure(results: list[Result]) -> bool:
    return bool(results) and str(results[0].get("body", "")).startswith(FAILURE_PREFIX)
