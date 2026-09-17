"""config/crawl.yml loader -- and the one answer to "which page kinds does
the engine read?" (D-044).

The `caps` block is the truth: a kind with a cap above zero is *wanted* --
mapped by P1, crawled into by P2, read by every claim reader; a kind at
zero is classified (so a link to it is recognised) but never fetched or
read. Readers keep their own preference order and pass it through
`only_wanted`, so adding a kind back is one line in the config and no
code moves anywhere.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "crawl.yml"


@functools.lru_cache(maxsize=1)
def load_crawl_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def rate_defaults() -> dict:
    return load_crawl_config()["rate"]


def caps() -> dict[str, int]:
    return load_crawl_config()["caps"]


def kind_cap(kind: str) -> int:
    """Pages of this kind per firm. A kind without its own line gets `other`."""
    c = caps()
    return int(c.get(kind, c.get("other", 0)))


def wanted_kinds() -> tuple[str, ...]:
    """The kinds the engine reads, in the config's order (home first). The
    order is also the fetch priority when a slow host cannot have them all."""
    return tuple(k for k, n in caps().items() if k != "total" and int(n) > 0)


def crawl_into_kinds() -> tuple[str, ...]:
    """Kinds worth following a link to. 'home' is never crawled into."""
    return tuple(k for k in wanted_kinds() if k != "home")


def only_wanted(preference: Sequence[str]) -> tuple[str, ...]:
    """A reader's own page order, minus the kinds the config does not read."""
    wanted = set(wanted_kinds())
    return tuple(k for k in preference if k in wanted)


def kinds_version() -> str:
    """Folded into every claim reader's idempotency version, so a change to
    which kinds are read re-derives every firm even where its pages did not
    change -- the same rule as a config edit (D-031)."""
    return "kinds:" + ",".join(wanted_kinds())
