"""config/crawl.yml loader -- rate-discipline defaults shared by every
crawl-touching component (P1, P2, JA1). P1 also reads this file's
page_kinds/probe_paths/caps/sitemap sections directly (that part of the
schema is P1-specific, so it stays local to lge/planes/p/p1_site_map.py).
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "crawl.yml"


@functools.lru_cache(maxsize=1)
def load_crawl_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def rate_defaults() -> dict:
    return load_crawl_config()["rate"]
