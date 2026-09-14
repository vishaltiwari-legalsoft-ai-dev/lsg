"""Is this string a person we can address? Shared by every loader and resolver
that turns a name field into a `contact` row (the purchased list, P5's
structured-data people, the AI's decision makers).

Found in the probe: all three hand over things that are not people --
"Chicago Injury Attorneys Near Northwestern Memorial Hospital", "Lawyers With
An Edge", "Rosenberg, Minc, Falkoff & Wolff, LLP." -- and R3 then minted
emails for them. Real people arrive dressed up too: "Paul A. Greenberg -
Personal Injury Lawyer", "Jeremy D. Raincrow, J.D., Ph.D.", "Attorney Tiffany
Lunn". The name is what is left after the title suffix, the credentials after
the first comma and a leading honorific are dropped; it is a person when it
has two to four tokens, no digits, no "&", and no practice or firm words.
"""

from __future__ import annotations

import re

_NOT_A_PERSON_RE = re.compile(
    r"\b(?:attorneys?|lawyers?|injury|accident|law\s+(?:firm|group|office|offices)|"
    r"near|hospital|center|centre|llc|pllc|p\.?c\.?|llp|ltd|inc|clinic|practice|services?"
    r"|reporters?|support|team|group|associates)\b",
    re.IGNORECASE,
)
_NAME_SUFFIX_RE = re.compile(r"\s+[-|–—]\s+.*$|,.*$")
_HONORIFIC_RE = re.compile(r"^(?:attorney|atty\.?|dr\.?|mr\.?|mrs\.?|ms\.?|hon\.?)\s+", re.I)
# "Michael Lijoi Jr.", "Elena Butko Esq.", "Robert C Hahn III" -- credentials and
# generational suffixes with no comma before them.
_TRAILING_CREDENTIAL_RE = re.compile(
    r"(?:\s+(?:esq|jr|sr|ii|iii|iv|j\.?d|ph\.?d|cfa|cpa|md|mba|llm|pc)\.?)+$", re.IGNORECASE
)
_NOT_IN_A_NAME_RE = re.compile(r"[\d&/]|\band\b", re.IGNORECASE)


def person_name(raw: str | None) -> str | None:
    """The person's name, cleaned, or None when the string is not a person."""
    if not raw:
        return None
    name = _NAME_SUFFIX_RE.sub("", " ".join(raw.split()))
    name = _HONORIFIC_RE.sub("", name).strip(" ,.")
    name = _TRAILING_CREDENTIAL_RE.sub("", name).strip(" ,.")
    if not name or _NOT_A_PERSON_RE.search(name) or _NOT_IN_A_NAME_RE.search(name):
        return None
    if not 2 <= len(name.split()) <= 4:
        return None
    return name
