"""What every search engine behind the seam looks like to the rest of the
engine: one query in, rows of {title, href, body} out, the same shape the
DuckDuckGo path always returned, so no consumer knows which engine answered.

A *failure* travels as one row whose body starts with "search failed" -- the
convention the planes' five-failure breaker reads -- and an empty list is a
real "nothing found". `SearchBlocked` is the engine asking us to stop: a bot
check, a rate limit. It is never worked around (D-039).
"""

from __future__ import annotations

import re
from typing import Any, Protocol

Result = dict[str, str]  # title, href, body
Place = dict[str, Any]  # name, address, rating, review_count, phone, website, url

FAILURE_PREFIX = "search failed"

# A term from a sheet or a scraped page goes into a query inside quotes: a
# quote or a control character in it would break the phrase, and a search
# operator (site:, inurl:, a leading minus) would change what is asked. The
# engine's own query builders add the operators; the term itself carries none.
_TERM_JUNK_RE = re.compile(r'["\x00-\x1f\x7f]+')
# A leading sign on a word (-word, +word, ~word) and a whole operator token
# (site:x.com, inurl:foo) -- the token goes, since its argument was never
# part of the name.
_TERM_OPERATOR_RE = re.compile(r"(?<!\S)[-+~](?=\S)|(?<!\S)\w+:\S+")
MAX_TERM_CHARS = 120


def clean_term(text: str | None, limit: int = MAX_TERM_CHARS) -> str:
    """A firm, person or place name as it may appear inside a query: no
    quotes, no control characters, no leading operators, whitespace folded,
    at most `limit` characters. Empty in, empty out."""
    if not text:
        return ""
    cleaned = _TERM_JUNK_RE.sub(" ", str(text))
    cleaned = _TERM_OPERATOR_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit].strip()


class SearchBlocked(Exception):
    """The engine answered with a bot check or a rate limit instead of results."""


class SearchRefused(SearchBlocked):
    """The engine refused us for good, not for a moment: a bad key, no credit
    left, a plan that lacks the endpoint. Retrying spends time and, once the
    key is fixed, nothing else -- but a run must stop on the first one, never
    walk five firms into the same wall (28 Sep 2026)."""


class SearchEngine(Protocol):
    name: str
    # Whether `places` answers at all -- read off the class, so the screens can
    # say whether the Google Business Profile is looked up without a client
    # being built (lge.search.has_listings).
    has_listings: bool

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
