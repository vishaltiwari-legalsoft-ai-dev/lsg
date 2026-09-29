"""The Google Business Profile through Google's own Places API (New) --
the official, licensed way to read a listing and its reviews (D-062).

One POST per firm to `places:searchText` with a field mask that asks for
the listing and its reviews in the same answer, so a firm costs one call.
Google returns at most five reviews per place and ranks them itself
("most relevant"); that is what the field gives and nothing here pages for
more. The mask names the Enterprise + Atmosphere SKU, which Google's
pricing page puts at 1,000 free calls a month -- a batch of 250 firms fits
four times over.

Never scraped: nothing here reads maps.google.com, and a 429 is a
`SearchBlocked` the pacer backs off from, never worked around.
"""

from __future__ import annotations

from typing import Any

import httpx

from lge.listings.base import Listing, Review, SearchBlocked, listing, review

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Everything the brief asks of the listing, plus the reviews, in one call.
FIELD_MASK = ",".join((
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.googleMapsUri",
    "places.rating",
    "places.userRatingCount",
    "places.businessStatus",
    "places.reviews",
))
_PAGE_SIZE = 5  # candidates: the firm and its namesakes; pick_listing chooses


class GooglePlacesProvider:
    name = "google_places"

    def __init__(self, api_key: str, *, timeout_s: float = 15.0) -> None:
        if not api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY is empty")
        self._client = httpx.Client(
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": FIELD_MASK,
                "Content-Type": "application/json",
            },
            timeout=timeout_s,
        )

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post(SEARCH_URL, json=body)
        if resp.status_code == 429:
            raise SearchBlocked("google places answered 429 (quota or rate limit)")
        if resp.status_code in (401, 403):
            raise RuntimeError(f"google places refused the key ({resp.status_code})")
        if resp.status_code >= 500:
            raise RuntimeError(f"google places answered {resp.status_code} (server error)")
        if resp.status_code != 200:
            raise RuntimeError(f"google places answered {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def find(self, query: str) -> list[Listing]:
        data = self._post({
            "textQuery": query,
            "pageSize": _PAGE_SIZE,
            "languageCode": "en",
            "regionCode": "US",
        })
        out: list[Listing] = []
        for p in data.get("places") or []:
            name = ((p.get("displayName") or {}).get("text") or "").strip()
            if not name:
                continue
            category = (p.get("primaryTypeDisplayName") or {}).get("text") or p.get("primaryType")
            row = listing(
                name=name,
                category=str(category).replace("_", " ") if category else None,
                address=p.get("formattedAddress"),
                phone=p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber"),
                website=p.get("websiteUri"),
                rating=p.get("rating"),
                review_count=p.get("userRatingCount"),
                url=p.get("googleMapsUri"),
                place_id=p.get("id"),
                status=(p.get("businessStatus") or "").lower().replace("_", " ") or None,
            )
            # The reviews ride along in the same answer; kept on the listing
            # so `reviews()` never makes a second, paid call.
            row["_reviews"] = [_review(r) for r in (p.get("reviews") or [])]
            out.append(row)
        return out

    def reviews(self, listing: Listing, max_reviews: int) -> list[Review]:
        rows = [r for r in listing.get("_reviews") or [] if r.get("text")]
        return rows[:max_reviews]


def _review(r: dict[str, Any]) -> Review:
    text = (r.get("text") or {}).get("text") or (r.get("originalText") or {}).get("text")
    author = (r.get("authorAttribution") or {}).get("displayName")
    when = r.get("publishTime")
    return review(
        author=author,
        rating=r.get("rating"),
        date=str(when)[:10] if when else r.get("relativePublishTimeDescription"),
        text=text,
        url=r.get("googleMapsUri"),
    )
