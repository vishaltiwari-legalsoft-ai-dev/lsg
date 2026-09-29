"""Which listing is this firm. A provider answers with the firm and its
namesakes ("Hartley Injury Law, P.C." next to "Hartley Dental"); the one
adopted is the best name overlap once the law words are set aside, and
never a listing whose category is not a law practice. Shared by the
listings step and the search step's fallback (D-045, D-062).
"""

from __future__ import annotations

import re
from typing import Any

from lge.search.base import clean_term

_LAW_WORDS_RE = re.compile(
    r"\b(?:law|legal|attorneys?|lawyers?|firm|group|office|offices|associates|"
    r"llc|llp|pllc|pc|pa|p\.c\.|p\.a\.|inc|ltd|the|of|and|&)\b",
    re.I,
)
_LAW_CATEGORY_RE = re.compile(r"law|legal|attorney|lawyer|justice|barrister|solicitor", re.I)
_MIN_OVERLAP = 0.34


def listing_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", _LAW_WORDS_RE.sub(" ", text.casefold())) if len(t) > 1
    }


def listing_query(firm_name: str, city: str | None, state: str | None) -> str:
    # Cleaned: a sheet's firm name is a phrase, never an operator.
    return " ".join(p for p in (clean_term(firm_name), clean_term(city), clean_term(state)) if p)


def pick_listing(firm_name: str, listings: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The business listing that is this firm, or None when nothing overlaps
    enough to be it."""
    if not listings:
        return None
    firm = listing_tokens(firm_name)
    if not firm:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for p in listings:
        category = str(p.get("category") or "")
        if category and not _LAW_CATEGORY_RE.search(category):
            continue
        name = listing_tokens(str(p.get("name") or ""))
        if not name:
            continue
        score = len(firm & name) / len(firm | name)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= _MIN_OVERLAP else None
