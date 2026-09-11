"""normalize_title / is_support_role — JA6's job-title normalizer.

Bump the caller's stored title norm/version whenever this output can change for any
input. This is the title half of the dedupe fingerprint in
context/20-signals/04-dedupe-dates-and-closure.md — one opening posted to six boards
must normalize to one signal, not six.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "title_synonyms.yml"

_SENIORITY_RE = re.compile(r"\b(?:sr|jr|senior|junior|lead|i|ii|iii)\b\.?", re.IGNORECASE)
_EMPLOYMENT_RE = re.compile(
    r"\b(?:full[- ]time|part[- ]time|contract|temp)\b", re.IGNORECASE
)
_PAREN_RE = re.compile(r"\([^)]*\)")
_DASH_SPLIT_RE = re.compile(r"\s-\s")
_TRAILING_CITY_STATE_RE = re.compile(r",\s*[a-z][a-z .]*,\s*[a-z]{2}\s*$")
_WHITESPACE_RE = re.compile(r"\s+")


@functools.lru_cache(maxsize=1)
def _load_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _role_order() -> tuple[str, ...]:
    cfg = _load_config()
    return tuple(cfg["roles"].keys())


@functools.lru_cache(maxsize=1)
def _support_flags() -> dict[str, bool]:
    cfg = _load_config()
    return {role: bool(body["support_role"]) for role, body in cfg["roles"].items()}


@functools.lru_cache(maxsize=1)
def _synonym_pattern() -> tuple[re.Pattern[str], dict[str, str]]:
    """One combined regex, alternatives ordered by (role order, synonym order).

    re.search finds the leftmost match in the title text; when multiple synonyms
    could start at that exact same position, Python's regex engine picks whichever
    alternative appears first in the pattern — which is exactly role/synonym order,
    giving the documented tie-break for free.
    """
    cfg = _load_config()
    alternatives: list[str] = []
    phrase_to_role: dict[str, str] = {}
    for role, body in cfg["roles"].items():
        for phrase in body["synonyms"]:
            key = phrase.lower()
            alternatives.append(re.escape(key))
            phrase_to_role[key] = role
    pattern = re.compile(r"\b(?:" + "|".join(alternatives) + r")\b")
    return pattern, phrase_to_role


def normalize_title(title: str, firm_name: str | None = None) -> str | None:
    """Canonical role slug for a raw job-posting title, or None if nothing maps."""
    if not title or not title.strip():
        return None

    text = title.lower()
    text = _PAREN_RE.sub(" ", text)
    text = _DASH_SPLIT_RE.split(text, maxsplit=1)[0]
    text = _TRAILING_CITY_STATE_RE.sub("", text)
    if firm_name and firm_name.strip():
        text = text.replace(firm_name.strip().lower(), " ")
    text = _SENIORITY_RE.sub(" ", text)
    text = _EMPLOYMENT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None

    pattern, phrase_to_role = _synonym_pattern()
    m = pattern.search(text)
    if not m:
        return None
    return phrase_to_role[m.group(0)]


def is_support_role(slug: str | None) -> bool:
    """True for a delegable support-staff role slug; False for attorney or an
    unrecognized/empty slug."""
    if not slug:
        return False
    return _support_flags().get(slug, False)
