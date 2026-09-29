"""What every business-listing provider behind the seam looks like to the
rest of the engine: a query in, listings out, and for one listing its
reviews -- the same two shapes whichever provider answered, so no consumer
knows whether Google's own API or Serper was asked.

A listing is the Google Business Profile as the provider returns it --
never a page scraped off Google Maps (standing rule: no defeating bot
management, and Maps is not a site the crawler may read). `SearchBlocked`
is the provider asking us to stop (a rate limit); it is never worked around.
"""

from __future__ import annotations

from typing import Any, Protocol

from lge.search.base import SearchBlocked

Listing = dict[str, Any]
# name, category, address, phone, website, rating, review_count, url, place_id, status
Review = dict[str, Any]
# author, rating, date, text, url

__all__ = ["Listing", "ListingProvider", "Review", "SearchBlocked", "listing", "review"]


def listing(
    *,
    name: str,
    category: str | None = None,
    address: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    rating: float | None = None,
    review_count: int | None = None,
    url: str | None = None,
    place_id: str | None = None,
    status: str | None = None,
) -> Listing:
    """One listing in the seam's shape. Every provider builds its answers
    through this so a missing field is None everywhere, never absent."""
    return {
        "name": name,
        "category": category,
        "address": address,
        "phone": phone,
        "website": website,
        "rating": float(rating) if rating is not None else None,
        "review_count": int(review_count) if review_count is not None else None,
        "url": url,
        "place_id": place_id,
        "status": status,
    }


def review(
    *,
    author: str | None,
    rating: int | None,
    date: str | None,
    text: str | None,
    url: str | None = None,
) -> Review:
    """One review. `text` is the reviewer's own words with whitespace folded
    onto one line -- the pain analyser quotes a review as ONE line of the
    record, so a review must be one line."""
    return {
        "author": (author or "").strip() or None,
        "rating": int(rating) if rating is not None else None,
        "date": (date or "").strip() or None,
        "text": " ".join((text or "").split()) or None,
        "url": url,
    }


class ListingProvider(Protocol):
    name: str

    def find(self, query: str) -> list[Listing]:
        """The listings the provider returns for a firm's name and place.
        Raises SearchBlocked on a rate limit and any other exception on a
        transport or server failure; the seam turns those into "no answer".
        An empty list is a real "nothing found"."""
        ...

    def reviews(self, listing: Listing, max_reviews: int) -> list[Review]:
        """The most useful reviews of one listing, newest or most relevant
        first as the provider ranks them, at most `max_reviews`."""
        ...
