"""norm_practice / map_practice_label — closed-vocabulary practice-area classification.

Bump NORM_VERSION["norm_practice"] whenever output can change for any input.

`primary` is the area with the most page real estate, not the first one listed — a
firm whose footer name-drops twelve practice areas but whose actual pages are 80%
personal injury is personal_injury. Getting this wrong makes tier assignment
non-deterministic across re-runs, since footer content order is not stable.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "practice_areas.yml"


@dataclass(frozen=True, slots=True)
class PracticeResult:
    areas: tuple[tuple[str, float], ...]  # (slug, share) desc by share, sums to 1.0
    primary: str | None
    confidence: float  # primary's share of total weight; 0.0 when nothing matched


@functools.lru_cache(maxsize=1)
def _load_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _compiled_patterns() -> dict[str, tuple[re.Pattern[str], ...]]:
    cfg = _load_config()
    out: dict[str, tuple[re.Pattern[str], ...]] = {}
    for slug, patterns in cfg["practices"].items():
        out[slug] = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
    return out


def _section_weight(text: str | None, weight: float) -> float:
    if weight and weight > 0:
        return float(weight)
    return float(len((text or "").split()))


def norm_practice(sections: Sequence[tuple[str, float]]) -> PracticeResult:
    """Score each of the 15 slugs by (pattern hits in a section) x (that section's
    share of total page weight), summed across sections. `primary` is the highest-
    scoring slug; ties broken alphabetically for determinism across re-runs."""
    patterns = _compiled_patterns()

    weights = [_section_weight(text, weight) for text, weight in sections]
    total_weight = sum(weights)
    if total_weight <= 0:
        return PracticeResult((), None, 0.0)

    scores: dict[str, float] = {}
    for (text, _weight), w in zip(sections, weights, strict=True):
        if not text:
            continue
        share = w / total_weight
        for slug, regs in patterns.items():
            hits = sum(len(r.findall(text)) for r in regs)
            if hits:
                scores[slug] = scores.get(slug, 0.0) + hits * share

    if not scores:
        return PracticeResult((), None, 0.0)

    total_score = sum(scores.values())
    normalized = {slug: score / total_score for slug, score in scores.items()}
    ordered = tuple(sorted(normalized.items(), key=lambda kv: (-kv[1], kv[0])))

    primary, confidence = ordered[0]
    return PracticeResult(ordered, primary, confidence)


def map_practice_label(label: str | None) -> str | None:
    """Map a single free-text category label onto the closed vocabulary, or None."""
    if not label or not label.strip():
        return None
    cfg = _load_config()
    labels: dict[str, str | None] = cfg.get("labels") or {}
    key = label.strip()
    if key in labels:
        return labels[key]
    lowered = {k.lower(): v for k, v in labels.items()}
    if key.lower() in lowered:
        return lowered[key.lower()]
    # Fall back to the same pattern set used for full-text classification.
    result = norm_practice([(label, 1.0)])
    return result.primary
