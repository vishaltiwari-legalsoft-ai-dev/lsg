"""Shared YAML config loading for JA6. Both files are re-read (cached, not baked
in) so a blocklist/threshold edit takes effect on the next `lge run ja6_normalise`
with no code change -- see context/40-pipeline/02-component-register.md, "Why JA6
is separate".
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


@functools.lru_cache(maxsize=1)
def agency_blocklist() -> dict:
    with (_CONFIG_DIR / "agency_blocklist.yml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def signal_rules() -> dict:
    with (_CONFIG_DIR / "signal_rules.yml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
