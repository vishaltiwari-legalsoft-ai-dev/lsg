"""Google results through serper.dev: the production engine (D-045). One
POST per query; `organic` becomes the common result rows; `/places` is the
Google Business Profile lookup -- rating, review count, phone, website and
the listing itself -- read from the API, not scraped off a page."""

from __future__ import annotations

from typing import Any

import httpx

from lge.search.base import Place, Result, SearchBlocked

SEARCH_URL = "https://google.serper.dev/search"
PLACES_URL = "https://google.serper.dev/places"


class SerperEngine:
    name = "serper"

    def __init__(self, api_key: str, *, timeout_s: float = 15.0) -> None:
        if not api_key:
            raise ValueError("SERPER_API_KEY is empty")
        self._client = httpx.Client(
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout_s,
        )

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post(url, json=body)
        if resp.status_code == 429:
            raise SearchBlocked("serper answered 429 (rate limit)")
        if resp.status_code in (401, 403):
            raise RuntimeError(f"serper refused the key ({resp.status_code})")
        if resp.status_code >= 500:
            raise RuntimeError(f"serper answered {resp.status_code} (server error, 503-class)")
        if resp.status_code != 200:
            raise RuntimeError(f"serper answered {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def search(self, query: str, max_results: int, page: int = 1) -> list[Result]:
        data = self._post(
            SEARCH_URL,
            {"q": query, "num": max(1, min(100, max_results)), "page": page,
             "gl": "us", "hl": "en"},
        )
        rows = data.get("organic") or []
        return [
            {"title": str(r.get("title") or ""), "href": str(r.get("link") or ""),
             "body": str(r.get("snippet") or "")}
            for r in rows[:max_results]
        ]

    def places(self, query: str) -> list[Place] | None:
        data = self._post(PLACES_URL, {"q": query, "gl": "us", "hl": "en"})
        out: list[Place] = []
        for p in data.get("places") or []:
            cid = p.get("cid")
            out.append({
                "name": str(p.get("title") or ""),
                "address": p.get("address"),
                "rating": float(p["rating"]) if p.get("rating") is not None else None,
                "review_count": int(p["ratingCount"]) if p.get("ratingCount") is not None else None,
                "phone": p.get("phoneNumber"),
                "website": p.get("website"),
                "url": f"https://www.google.com/maps?cid={cid}" if cid else None,
                "category": p.get("category"),
            })
        return out
