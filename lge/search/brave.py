"""Brave Search API: an official index behind a key, the fallback engine
(D-045). No listings endpoint -- reviews are read off snippets as before."""

from __future__ import annotations

import httpx

from lge.search.base import Place, Result, SearchBlocked

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveEngine:
    name = "brave"

    def __init__(self, api_key: str, *, timeout_s: float = 15.0) -> None:
        if not api_key:
            raise ValueError("BRAVE_API_KEY is empty")
        self._client = httpx.Client(
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
            timeout=timeout_s,
        )

    def search(self, query: str, max_results: int, page: int = 1) -> list[Result]:
        count = max(1, min(20, max_results))
        resp = self._client.get(
            SEARCH_URL,
            params={"q": query, "count": count, "offset": max(0, min(9, page - 1)),
                    "country": "us", "search_lang": "en"},
        )
        if resp.status_code == 429:
            raise SearchBlocked("brave answered 429 (rate limit)")
        if resp.status_code in (401, 403):
            raise RuntimeError(f"brave refused the key ({resp.status_code})")
        if resp.status_code >= 500:
            raise RuntimeError(f"brave answered {resp.status_code} (server error, 503-class)")
        if resp.status_code != 200:
            raise RuntimeError(f"brave answered {resp.status_code}: {resp.text[:200]}")
        rows = ((resp.json().get("web") or {}).get("results")) or []
        return [
            {"title": str(r.get("title") or ""), "href": str(r.get("url") or ""),
             "body": str(r.get("description") or "")}
            for r in rows[:max_results]
        ]

    def places(self, query: str) -> list[Place] | None:
        return None
