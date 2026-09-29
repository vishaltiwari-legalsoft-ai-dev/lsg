"""FastAPI dependencies: a pooled DB connection per request, and the
provider-configured booleans `GET /api/meta/providers` returns.

Each boolean asks the seam that does the work (brain/plan/plan-v2.md, "the
seams") -- the verifier the verification step would use, the listings
provider the listing step would ask, the search engine with a key -- so a
light can never say one thing while the engine does another. The "places"
light is the listings seam (lge.listings, D-062): Google's own Places API
on GOOGLE_PLACES_API_KEY, or Serper on the search key.
**Never expose a key's value -- booleans only**, per plan/api-contract.md's
meta/providers endpoint.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import Depends
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from lge.settings import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Lazily-built, process-wide connection pool. One request = one
    connection borrowed for the request's lifetime; `pool.connection()`
    commits on a clean exit and rolls back on an exception, the same
    contract `with psycopg.connect(...) as conn:` gives a single
    connection -- which is what lets `lge.db.writer`/`lge.db.lifecycle`'s
    transaction-local `set_config(..., true)` survive from the guard check
    through to the write it guards, within one request."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.dsn,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_conn() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as conn:
        yield conn


# `Annotated[..., Depends(...)]` puts the Depends() call in type metadata
# instead of a parameter default -- functionally identical to writing
# Depends(get_conn) as the parameter's default value on every route, but
# ruff's bugbear rule against calling a function in an argument default
# only fires on that latter spelling, and silencing it route by route is
# worse than spelling it the way that never trips the rule.
ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]


# =============================================================================
# Provider booleans -- each one asked of the seam that does the work.
# =============================================================================


def providers_status() -> dict[str, object]:
    from lge.listings import has_provider
    from lge.planes.r.r4_verify import configured_provider

    settings = get_settings()
    return {
        "ai_extraction": bool(settings.openrouter_api_key),
        "email_verification": configured_provider(settings) is not None,
        "places": has_provider(settings),
        # the search service on Home: an engine with a key (Serper or Brave),
        # not DuckDuckGo, which stops us after a few hundred queries
        "search": settings.search_engine_name() in ("serper", "brave"),
        # Google sign-in (D-067): the screens ask who you are once this is on
        "sign_in": settings.sign_in_configured(),
        "crawler_identity": settings.user_agent or "not configured",
    }


def providers_inert() -> list[str]:
    """Human labels for every provider currently unconfigured -- feeds
    GET /api/today's attention.providers_inert."""
    status = providers_status()
    inert = []
    if not status["ai_extraction"]:
        inert.append("AI extraction")
    if not status["email_verification"]:
        inert.append("Email verification")
    if not status["places"]:
        inert.append("Google Business Profile and reviews")
    return inert
