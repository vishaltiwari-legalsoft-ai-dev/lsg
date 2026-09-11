"""norm_addr — canonical USPS-style street address, with the secondary unit split out.

Bump NORM_VERSION["norm_addr"] whenever output can change for any input.

The secondary unit (suite/floor/apt/...) is deliberately excluded from addr_hash: two
floors of the same firm at the same street number must hash identically, or one firm's
two suites becomes two firms in the identity graph.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# USPS Publication 28 street-suffix abbreviations (subset relevant to small-firm
# addresses). Applied only to whole tokens.
_SUFFIX_MAP: dict[str, str] = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "ROAD": "RD",
    "DRIVE": "DR",
    "LANE": "LN",
    "COURT": "CT",
    "PLACE": "PL",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "CIRCLE": "CIR",
    "TERRACE": "TER",
    "SQUARE": "SQ",
    "PLAZA": "PLZ",
    "TRAIL": "TRL",
    "WAY": "WAY",
    "CENTER": "CTR",
    "EXPRESSWAY": "EXPY",
    "FREEWAY": "FWY",
}

_DIRECTIONAL_MAP: dict[str, str] = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}

# Secondary-unit designators -> their canonical abbreviation. A designator must be
# followed by an identifier (SUITE 400, STE #400, FLOOR 3) to count as a unit.
_UNIT_KEYWORDS: dict[str, str] = {
    "SUITE": "STE",
    "STE": "STE",
    "UNIT": "UNIT",
    "APT": "APT",
    "APARTMENT": "APT",
    "FLOOR": "FL",
    "FL": "FL",
    "RM": "RM",
    "ROOM": "RM",
    "BLDG": "BLDG",
    "BUILDING": "BLDG",
    "DEPT": "DEPT",
    "PH": "PH",
    "PENTHOUSE": "PH",
    "LOWR": "LOWR",
    "UPPR": "UPPR",
    "SPC": "SPC",
    "OFC": "OFC",
    "OFFICE": "OFC",
}

# Longest keyword first so e.g. "APARTMENT" is tried before a shorter alternative
# could partially shadow it inside the alternation.
#
# The 2-letter keywords (FL, RM, PH) are ordinary word prefixes too ("Philadelphia
# Ave", "Rmsdale Rd" is contrived but "Flanders St" is not) — for those only, require
# the identifier to contain a digit, so "Philadelphia" can never parse as unit "PH
# ILADELPHIA". The longer keywords are distinctive enough not to need this.
_SHORT_UNIT_KEYWORDS = {k for k in _UNIT_KEYWORDS if len(k) <= 2}
_LONG_UNIT_KEYWORDS = [k for k in _UNIT_KEYWORDS if len(k) > 2]

_LONG_KEYWORD_ALTS = sorted(_LONG_UNIT_KEYWORDS, key=len, reverse=True)
_SHORT_KEYWORD_ALTS = sorted(_SHORT_UNIT_KEYWORDS, key=len, reverse=True)

_UNIT_RE_LONG = re.compile(
    r"\b(" + "|".join(_LONG_KEYWORD_ALTS) + r")\.?\s*#?\s*([A-Z0-9][A-Z0-9\-]*)\b"
)
_UNIT_RE_SHORT = re.compile(
    r"\b(" + "|".join(_SHORT_KEYWORD_ALTS) + r")\.?\s*#?\s*([A-Z0-9\-]*\d[A-Z0-9\-]*)\b"
)
_ORDINAL_FLOOR_RE = re.compile(r"\b(\d+(?:ST|ND|RD|TH))\s+(?:FLOOR|FL)\b")
_ORDINAL_RE = re.compile(r"^(\d+)(?:ST|ND|RD|TH)$")
_HASH_UNIT_RE = re.compile(r"#\s*([A-Z0-9][A-Z0-9\-]*)")

_NON_STREET_CHARS_RE = re.compile(r"[^A-Z0-9#\s]")
_NON_WORD_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class AddrNorm:
    street_norm: str | None
    unit: str | None
    city: str | None
    state: str | None
    zip5: str | None
    zip4: str | None
    addr_hash: str | None


def _strip_ordinal(token: str) -> str:
    m = _ORDINAL_RE.match(token)
    return m.group(1) if m else token


def _extract_unit(text: str) -> tuple[str, str | None]:
    m = _ORDINAL_FLOOR_RE.search(text)
    if m:
        unit = f"FL {_strip_ordinal(m.group(1))}"
        return text[: m.start()] + " " + text[m.end() :], unit

    m = _UNIT_RE_LONG.search(text) or _UNIT_RE_SHORT.search(text)
    if m:
        canon = _UNIT_KEYWORDS[m.group(1)]
        unit = f"{canon} {m.group(2)}"
        return text[: m.start()] + " " + text[m.end() :], unit

    m = _HASH_UNIT_RE.search(text)
    if m:
        unit = f"# {m.group(1)}"
        return text[: m.start()] + " " + text[m.end() :], unit

    return text, None


def _process_street(street: str | None) -> tuple[str | None, str | None]:
    if not street or not street.strip():
        return None, None
    text = street.upper()
    text = _NON_STREET_CHARS_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None, None

    text, unit = _extract_unit(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    out_tokens = []
    for tok in text.split(" ") if text else []:
        if tok in _DIRECTIONAL_MAP:
            out_tokens.append(_DIRECTIONAL_MAP[tok])
        elif tok in _SUFFIX_MAP:
            out_tokens.append(_SUFFIX_MAP[tok])
        else:
            out_tokens.append(tok)
    street_norm = " ".join(out_tokens).strip()
    return (street_norm or None), unit


def _clean_simple(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    v = value.upper()
    v = _NON_WORD_RE.sub(" ", v)
    v = _WHITESPACE_RE.sub(" ", v).strip()
    return v or None


def _parse_zip(zip_code: str | None) -> tuple[str | None, str | None]:
    if not zip_code:
        return None, None
    digits = re.sub(r"\D", "", zip_code)
    if len(digits) < 5:
        return None, None
    zip5 = digits[:5]
    zip4 = digits[5:9] if len(digits) >= 9 else None
    return zip5, (zip4 or None)


def norm_addr(
    street: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> AddrNorm:
    """USPS-style canonical form. addr_hash covers street_norm + zip5 only — never
    the unit, and never city/state (ZIP already implies them)."""
    street_norm, unit = _process_street(street)
    zip5, zip4 = _parse_zip(zip_code)
    city_norm = _clean_simple(city)
    state_norm = _clean_simple(state)

    addr_hash: str | None = None
    if street_norm and zip5:
        addr_hash = hashlib.sha1((street_norm + zip5).encode()).hexdigest()

    return AddrNorm(
        street_norm=street_norm,
        unit=unit,
        city=city_norm,
        state=state_norm,
        zip5=zip5,
        zip4=zip4,
        addr_hash=addr_hash,
    )
