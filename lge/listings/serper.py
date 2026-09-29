"""The Google Business Profile through serper.dev: `/places` for the
listing and `/reviews` for its reviews, both read from the API, never off a
page (D-045, D-062). The same key the search seam uses; a machine with a
Serper key and no Google key gets the listing this way.

`/reviews` is the one Serper endpoint with cursor pagination; one page is
asked for by default (`max_pages`), most relevant first as Google ranks
them, and a listing with no `cid` has no reviews to fetch.
"""

from __future__ import annotations

from typing import Any

import httpx

from lge.listings.base import Listing, Review, listing, review
from lge.search.serper import serper_post

PLACES_URL = "https://google.serper.dev/places"
REVIEWS_URL = "https://google.serper.dev/reviews"
_REVIEWS_PER_PAGE = 10


class SerperListingProvider:
    name = "serper"

    def __init__(
        self, api_key: str, *, timeout_s: float = 15.0, max_pages: int = 1,
        low_stars_first: bool = True, low_star_max: int = 3,
    ) -> None:
        if not api_key:
            raise ValueError("SERPER_API_KEY is empty")
        self._client = httpx.Client(
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout_s,
        )
        self._max_pages = max(1, int(max_pages))
        # The reviews that name a pain are the poor ones. Ask Google for the
        # lowest-rated first (one page, one credit), keep every one at or
        # below `low_star_max` stars, then fill the rest of the cap from the
        # most relevant page (a second credit, only when there is room). On
        # a 54-review listing the relevant page showed one 1-star review;
        # the lowest page showed eight (D-069, 29 Sep 2026).
        self._low_stars_first = bool(low_stars_first)
        self._low_star_max = int(low_star_max)

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        # The one set of rules for every Serper call (lge.search.serper):
        # 429 blocks, a bad key or an empty balance refuses, credits are metered.
        return serper_post(self._client, url, body)

    def find(self, query: str) -> list[Listing]:
        data = self._post(PLACES_URL, {"q": query, "gl": "us", "hl": "en"})
        out: list[Listing] = []
        for p in data.get("places") or []:
            name = str(p.get("title") or "").strip()
            if not name:
                continue
            cid = p.get("cid")
            row = listing(
                name=name,
                category=p.get("category"),
                address=p.get("address"),
                phone=p.get("phoneNumber"),
                website=p.get("website"),
                rating=p.get("rating"),
                review_count=p.get("ratingCount"),
                url=f"https://www.google.com/maps?cid={cid}" if cid else None,
                place_id=p.get("placeId"),
            )
            row["_cid"] = str(cid) if cid else None
            row["_fid"] = p.get("fid")
            out.append(row)
        return out

    def reviews(self, listing: Listing, max_reviews: int) -> list[Review]:
        key: dict[str, Any]
        if listing.get("_cid"):
            key = {"cid": listing["_cid"]}
        elif listing.get("place_id"):
            key = {"placeId": listing["place_id"]}
        elif listing.get("_fid"):
            key = {"fid": listing["_fid"]}
        else:
            return []
        if not self._low_stars_first:
            return self._pages(key, max_reviews, sort_by=None)[:max_reviews]
        # The poor reviews first: keep every one at or below the star cap,
        # stopping when a page runs past it (they come in ascending order).
        low: list[Review] = []
        for row in self._pages(key, max_reviews, sort_by="lowestRating"):
            if row.get("rating") is not None and row["rating"] > self._low_star_max:
                break
            low.append(row)
        low = low[:max_reviews]
        if len(low) >= max_reviews:
            return low
        # Then the most relevant ones for the rest of the cap, never a repeat.
        seen = {_key(r) for r in low}
        rest = [r for r in self._pages(key, max_reviews - len(low), sort_by=None)
                if _key(r) not in seen]
        return (low + rest)[:max_reviews]

    def _pages(self, key: dict[str, Any], wanted: int, *, sort_by: str | None) -> list[Review]:
        """Up to `max_pages` pages of reviews with words, in the provider's
        order for `sort_by`, at most `wanted` rows."""
        out: list[Review] = []
        token: str | None = None
        for _ in range(self._max_pages):
            body: dict[str, Any] = {**key, "gl": "us", "hl": "en"}
            if sort_by:
                body["sortBy"] = sort_by
            if token:
                body["nextPageToken"] = token
            data = self._post(REVIEWS_URL, body)
            for r in data.get("reviews") or []:
                row = _review(r)
                # A star-only review has nothing to quote and does not count
                # towards the cap, or three of them would hide seven with words.
                if row.get("text"):
                    out.append(row)
                if len(out) >= wanted:
                    return out[:wanted]
            token = data.get("nextPageToken")
            if not token or len(out) >= wanted:
                break
        return out[:wanted]


def _key(r: Review) -> str:
    return r.get("url") or f"{r.get('author')}|{r.get('date')}|{(r.get('text') or '')[:60]}"


def _review(r: dict[str, Any]) -> Review:
    user = r.get("user") or {}
    when = r.get("isoDate") or r.get("date")
    return review(
        author=user.get("name") if isinstance(user, dict) else str(user or ""),
        rating=r.get("rating"),
        date=str(when)[:10] if when and str(when)[:4].isdigit() else when,
        text=r.get("snippet") or r.get("text"),
        url=r.get("link"),
    )
