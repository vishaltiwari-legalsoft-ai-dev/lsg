"""The business-listing seam (D-062): the Google Business Profile and its
reviews, from a licensed API and never from a scraped page.

Every component that wants the listing calls `find(query)` and
`reviews(listing)`; which provider answers is `settings.listings_provider_name()`
-- Google's own Places API when its key exists (1,000 free lookups a
month), else Serper's `/places` + `/reviews` on the search key, else none
-- and is written into every claim's source tag (`source()`, e.g.
`listing:google_places`) and every search_log row, so a phone number or a
review can always be traced to the API that produced it. Pacing per
provider is config/listings.yml, on the same pacer the search seam uses.

Components take `find` / `reviews` as injectable parameters and default to
this module's, so tests never reach a provider.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from lge.listings.base import Listing, ListingProvider, Review, SearchBlocked
from lge.listings.match import listing_query, pick_listing
from lge.search.base import is_failure
from lge.search.pace import Pace, Pacer
from lge.settings import Settings, get_settings

__all__ = [
    "FindFn", "Listing", "ListingProvider", "Review", "ReviewsFn", "SearchBlocked", "find",
    "get_provider", "has_provider", "listing_query", "pick_listing", "provider_name",
    "reset", "reviews", "source",
]

FindFn = Callable[[str], list[Listing] | None]
ReviewsFn = Callable[[Listing, int], list[Review] | None]

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "listings.yml"
_providers: dict[str, ListingProvider] = {}
_pacers: dict[str, Pacer] = {}


@functools.lru_cache(maxsize=1)
def load_listings_config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def provider_name(settings: Settings | None = None) -> str:
    return (settings or get_settings()).listings_provider_name()


def source(settings: Settings | None = None) -> str:
    """The claim / log source tag for whatever provider is answering."""
    return f"listing:{provider_name(settings)}"


def has_provider(settings: Settings | None = None) -> bool:
    """Whether the Google Business Profile and its reviews are looked up
    right now: a provider is chosen and its key is set. What the screens'
    "places" light reports."""
    s = settings or get_settings()
    name = s.listings_provider_name()
    return bool(_key(name, s))


def _key(name: str, settings: Settings) -> str:
    return {
        "google_places": settings.google_places_api_key,
        "serper": settings.serper_api_key,
    }.get(name, "")


def _build(name: str, settings: Settings) -> ListingProvider:
    cfg = load_listings_config()
    timeout_s = float((cfg.get("request") or {}).get("timeout_s", 15.0))
    if name == "google_places":
        from lge.listings.google_places import GooglePlacesProvider

        return GooglePlacesProvider(_key(name, settings), timeout_s=timeout_s)
    if name == "serper":
        from lge.listings.serper import SerperListingProvider

        pages = int(((cfg.get("providers") or {}).get("serper") or {}).get("review_pages", 1))
        req = cfg.get("request") or {}
        return SerperListingProvider(
            _key(name, settings), timeout_s=timeout_s, max_pages=pages,
            low_stars_first=bool(req.get("low_stars_first", True)),
            low_star_max=int(req.get("low_star_max", 3)),
        )
    raise ValueError(f"no listings provider {name!r}")


def get_provider(settings: Settings | None = None) -> ListingProvider | None:
    s = settings or get_settings()
    name = s.listings_provider_name()
    if name == "none" or not _key(name, s):
        return None
    if name not in _providers:
        _providers[name] = _build(name, s)
    return _providers[name]


def _pacer(name: str) -> Pacer:
    if name not in _pacers:
        raw = (load_listings_config().get("providers") or {}).get(name)
        _pacers[name] = Pacer(Pace.from_config(raw))
    return _pacers[name]


def _paced(name: str, fn: Callable[[], list[Any]]) -> list[Any] | None:
    """One provider request under the pace; None when it failed or the
    provider is cooling off after a block (the caller then has no answer,
    never a crash)."""
    rows = _pacer(name).call(fn, engine=name)
    return None if is_failure(rows) else rows


def find(query: str) -> list[Listing] | None:
    """The listings for a firm's name and place; None when no provider is
    configured or the lookup failed."""
    provider = get_provider()
    if provider is None:
        return None
    return _paced(provider.name, lambda: provider.find(query))


def reviews(listing: Listing, max_reviews: int = 10) -> list[Review] | None:
    """The reviews of one listing; None when the lookup failed."""
    provider = get_provider()
    if provider is None:
        return None
    return _paced(provider.name, lambda: provider.reviews(listing, max_reviews))


def reset() -> None:
    """Forget built providers and pacers (tests, or after settings change)."""
    _providers.clear()
    _pacers.clear()
    load_listings_config.cache_clear()
