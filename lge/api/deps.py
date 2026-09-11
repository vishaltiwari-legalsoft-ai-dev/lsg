"""FastAPI dependencies: a pooled DB connection per request, and the
provider-configured booleans `GET /api/meta/providers` returns.

Provider API keys are read directly from `os.environ` (with the same `.env`
fallback `lge.settings.Settings` gives itself), never by extending
`Settings` -- `lge/settings.py` is another agent's owned file, and
`lge/planes/r/r4_verify.py` already sets this precedent for
ZEROBOUNCE_API_KEY / NEVERBOUNCE_API_KEY. **Never expose a key's value --
booleans only**, per plan/api-contract.md's meta/providers endpoint.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

import psycopg
from fastapi import Depends
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from lge.settings import PROJECT_ROOT, get_settings

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
# Provider booleans -- config/*.env fallback, mirroring
# lge.settings._read_dotenv's contract exactly (duplicated in miniature
# rather than importing a private helper from another agent's owned file).
# =============================================================================


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str]:
    path = PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _env(name: str) -> str:
    if name in os.environ:
        return os.environ[name]
    return _dotenv().get(name, "")


def providers_status() -> dict[str, object]:
    settings = get_settings()
    return {
        "ai_extraction": bool(settings.openrouter_api_key),
        "email_verification": bool(_env("ZEROBOUNCE_API_KEY")) or bool(_env("NEVERBOUNCE_API_KEY")),
        "places": bool(_env("GOOGLE_PLACES_API_KEY")),
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
        inert.append("Places")
    return inert
