"""Variant selection: which touch-1 copy fires for a given signal, which
touch-3 copy fires for a given fee model, and the banned-phrase scan. Reads
journey/sequences.yml once (cached) -- pure functions, no DB access.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

from lge.journey.model import Signal

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEQUENCES_YML = _PROJECT_ROOT / "journey" / "sequences.yml"


@functools.lru_cache(maxsize=1)
def load_config() -> dict:
    with SEQUENCES_YML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def select_touch1_variant(signal: Signal | None) -> str | None:
    """'1A'..'1F', or None when there is no signal or its kind has no
    touch-1 copy (an unmapped/unsupported signal kind)."""
    if signal is None:
        return None
    cfg = load_config()["pain_map"]
    if signal.kind == "job_posting_open":
        entry = cfg["job_posting_open"]
        return entry["repost"] if (signal.repost_count or 0) >= 1 else entry["no_repost"]
    value = cfg.get(signal.kind)
    return value if isinstance(value, str) else None


def select_touch3_variant(fee_model: str | None, tier: str) -> str | None:
    """Copy-file key under journey/copy/touch3/, or None when fee_model is
    mixed/unknown/NULL -- the lead is excluded in that case, see
    journey/sequences.yml's touch3_variants comment."""
    cfg = load_config()["touch3_variants"]
    entry = cfg.get(fee_model or "")
    if entry is None:
        return None
    overrides = entry.get("tier_overrides") or {}
    return overrides.get(tier, entry["file"])


@functools.lru_cache(maxsize=1)
def _banned_patterns() -> tuple[re.Pattern[str], ...]:
    phrases = load_config()["banned_phrases"]
    return tuple(re.compile(re.escape(p), re.IGNORECASE) for p in phrases)


def scan_banned(text: str) -> list[str]:
    """Every banned phrase (journey/sequences.yml's banned_phrases) found in
    `text`, in config order. Empty list = clean."""
    hits: list[str] = []
    for pattern in _banned_patterns():
        if pattern.search(text):
            hits.append(pattern.pattern)
    return hits
