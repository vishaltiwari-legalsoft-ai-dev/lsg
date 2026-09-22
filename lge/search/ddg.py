"""DuckDuckGo through the `ddgs` library's own engine: keyless, throttled,
and the only path on a machine without a search key. The library folds a
bot check into "No results found."; the status is read here, because an
empty answer under a bot check proves nothing and must not be logged as
"not found" for ninety days (D-039)."""

from __future__ import annotations

from typing import Any

from lge.search.base import Place, Result, SearchBlocked

_BLOCKED_STATUSES = frozenset({202, 403, 429})  # 202 is DuckDuckGo's anomaly page


def _engine() -> Any:
    from ddgs.engines.duckduckgo import Duckduckgo

    return Duckduckgo(timeout=10)


class DDGEngine:
    name = "ddg"
    has_listings = False

    def search(self, query: str, max_results: int, page: int = 1) -> list[Result]:
        engine = _engine()
        payload = engine.build_payload(
            query=query, region="us-en", safesearch="moderate", timelimit=None, page=page
        )
        resp = engine.http_client.request(engine.search_method, engine.search_url, data=payload)
        if resp.status_code in _BLOCKED_STATUSES:
            raise SearchBlocked(f"DuckDuckGo answered {resp.status_code} (bot check), not results")
        if resp.status_code != 200:
            raise RuntimeError(f"DuckDuckGo answered {resp.status_code}")
        rows = engine.post_extract_results(engine.extract_results(resp.text))
        return [{"title": r.title, "href": r.href, "body": r.body} for r in rows[:max_results]]

    def places(self, query: str) -> list[Place] | None:
        return None  # no listings endpoint: reviews are read off snippets
