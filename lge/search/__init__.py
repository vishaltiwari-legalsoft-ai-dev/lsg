"""The web-search seam (brain/plan/plan-v2.md, D-045).

Every component that searches the web calls `search(query, n, page=)` and
gets rows of {title, href, body}; which engine answered is
`settings.search_engine_name()` -- serper when its key exists, else brave,
else DuckDuckGo -- and is written into every claim's source tag
(`source()`) and every search_log row (`engine_name()`), so a result can
always be traced to the engine that produced it. Pacing per engine is
config/search.yml. `places(query)` is the business-listing lookup for the
engines that have one, None for the rest.

Components take `search` as an injectable parameter and default to this
module's, so tests never reach an engine.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path

import yaml

from lge.search.base import (
    FAILURE_PREFIX,
    Place,
    Result,
    SearchBlocked,
    SearchEngine,
    failure,
    is_failure,
)
from lge.search.pace import Pace, Pacer
from lge.settings import Settings, get_settings

__all__ = [
    "FAILURE_PREFIX", "Place", "Result", "SearchBlocked", "SearchEngine", "SearchFn",
    "engine_name", "failure", "get_engine", "has_listings", "is_failure", "places", "reset",
    "search", "source",
]

SearchFn = Callable[..., list[Result]]  # (query, max_results, *, page=1)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "search.yml"
_engines: dict[str, SearchEngine] = {}
_pacers: dict[str, Pacer] = {}


@functools.lru_cache(maxsize=1)
def load_search_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def engine_name(settings: Settings | None = None) -> str:
    return (settings or get_settings()).search_engine_name()


def source(settings: Settings | None = None) -> str:
    """The claim / observation source tag for whatever engine is answering."""
    return f"search:{engine_name(settings)}"


def _engine_class(name: str) -> type:
    if name == "serper":
        from lge.search.serper import SerperEngine

        return SerperEngine
    if name == "brave":
        from lge.search.brave import BraveEngine

        return BraveEngine
    if name == "ddg":
        from lge.search.ddg import DDGEngine

        return DDGEngine
    raise ValueError(f"unknown search engine {name!r}")


def _key(name: str, settings: Settings) -> str | None:
    """The engine's key; None for an engine that needs none."""
    return {"serper": settings.serper_api_key, "brave": settings.brave_api_key}.get(name)


def _build(name: str, settings: Settings) -> SearchEngine:
    timeout_s = float((load_search_config().get("request") or {}).get("timeout_s", 15.0))
    cls = _engine_class(name)
    key = _key(name, settings)
    return cls() if key is None else cls(key, timeout_s=timeout_s)


def has_listings(settings: Settings | None = None) -> bool:
    """Whether the Google Business Profile is looked up directly right now:
    the engine answering has a listings endpoint (Serper's /places) and its
    key is set. Otherwise r_search_links reads what it can off snippets.
    Asked of the engine's class, so no client is built to answer."""
    s = settings or get_settings()
    name = s.search_engine_name()
    if not getattr(_engine_class(name), "has_listings", False):
        return False
    key = _key(name, s)
    return key is None or bool(key)


def get_engine(settings: Settings | None = None) -> SearchEngine:
    s = settings or get_settings()
    name = s.search_engine_name()
    if name not in _engines:
        _engines[name] = _build(name, s)
    return _engines[name]


def _pacer(name: str) -> Pacer:
    if name not in _pacers:
        raw = (load_search_config().get("engines") or {}).get(name)
        _pacers[name] = Pacer(Pace.from_config(raw))
    return _pacers[name]


def search(query: str, max_results: int = 8, *, page: int = 1) -> list[Result]:
    """Text results as {title, href, body}; `page` 2 is the next ten. Paced;
    a failure comes back as one row whose body starts with "search failed";
    an empty list is a real answer."""
    engine = get_engine()
    return _pacer(engine.name).call(
        lambda: engine.search(query, max_results, page), engine=engine.name
    )


def places(query: str) -> list[Place] | None:
    """The engine's business-listing lookup, paced like a query; None when
    the engine has none, or when the lookup failed (the caller then reads
    snippets)."""
    engine = get_engine()
    pacer = _pacer(engine.name)
    if pacer.blocked_reason():
        return None
    try:
        pacer.wait()
        pacer.mark()
        return engine.places(query)
    except Exception:  # noqa: BLE001 -- a listing lookup that fails is "no listing", never a crash
        return None


def reset() -> None:
    """Forget built engines and pacers (tests, or after settings change)."""
    _engines.clear()
    _pacers.clear()
    load_search_config.cache_clear()
