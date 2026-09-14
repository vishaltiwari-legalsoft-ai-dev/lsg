"""One raw row + a column map -> the canonical row every downstream step reads.

Canonical keys (None when the sheet has nothing):
  firm_name, name_stem, website, domain, domain_from_email,
  city, state, zip, address, location, country,
  firm_size (as given), size_min, size_max, firm_type, job_post,
  person_name (cleaned), person_name_raw, is_person, person_title,
  email, email_valid, email_status, phone, phone_e164, linkedin,
  contacted_before (bool | None), contacted_at (ISO date | None),
  technology, notes, extra (unmapped columns with a value)
"""

from __future__ import annotations

import html
import re
from typing import Any

from dateutil import parser as dateutil_parser

from lge.classify.people import person_name as clean_person_name
from lge.ingest.sniff import ColumnMap
from lge.norm import norm_domain, norm_email_domain, norm_name, norm_phone

NORMALIZE_VERSION = "1"

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC", "puerto rico": "PR",
}
_STATE_CODES = set(_STATE_NAMES.values())
_LOCATION_RE = re.compile(
    r"^\s*(?P<city>[^,]+?)\s*,\s*(?P<state>[A-Za-z .]{2,20})(?:\s+(?P<zip>\d{5}))?\s*$"
)
_SIZE_RE = re.compile(r"(\d[\d,]*)\s*(?:to|-|–|—)\s*(\d[\d,]*)|(\d[\d,]*)\s*\+|^\s*(\d[\d,]*)\s*$")
_TRUE = {"yes", "y", "true", "1", "contacted", "done", "sent", "reached"}
_FALSE = {"no", "n", "false", "0", "not contacted", "never", "none", "pending", ""}


def norm_state(value: str | None) -> str | None:
    if not value:
        return None
    v = " ".join(value.strip().split()).rstrip(".")
    if v.upper() in _STATE_CODES:
        return v.upper()
    return _STATE_NAMES.get(v.lower())


def parse_size(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    m = _SIZE_RE.search(value.replace(",", ""))
    if not m:
        return None, None
    if m.group(1) and m.group(2):
        return int(m.group(1)), int(m.group(2))
    if m.group(3):
        return int(m.group(3)), None
    if m.group(4):
        n = int(m.group(4))
        return n, n
    return None, None


def parse_contacted(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return None if v == "" else False
    # any other non-empty text ("emailed 3x", "replied", "2025-01-02") means yes
    return True


def parse_date(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    try:
        return dateutil_parser.parse(value.strip(), fuzzy=False).date().isoformat()
    except (ValueError, OverflowError):
        return None


def norm_linkedin(value: str | None) -> str | None:
    if not value or "linkedin.com/" not in value.lower():
        return None
    url = value.strip().split("?", 1)[0].rstrip("/")
    if not url.lower().startswith("http"):
        url = "https://" + url.lstrip("/")
    return url


def email_domain_plausible(email_domain: str, name_stem: str | None) -> bool:
    """An email domain may stand in as the firm's identity key only when it
    visibly belongs to the firm: a name-stem token of >=4 chars appears in the
    domain's registered label, or the stem's initials (>=2 tokens) do. A
    contact's email can belong to a previous firm or an employer; used as a
    key it merges two firms, the unrecoverable direction (D-017)."""
    if not name_stem:
        return False
    label = re.sub(r"[^a-z0-9]", "", email_domain.split(".", 1)[0].lower())
    tokens = [t for t in re.split(r"\s+", name_stem.lower()) if t]
    if any(len(t) >= 4 and t in label for t in tokens):
        return True
    if len(tokens) >= 2:
        initials = "".join(t[0] for t in tokens)
        if len(initials) >= 2 and initials in label:
            return True
    return False


def resolve_domain(
    website: str | None, email: str | None, name_stem: str | None
) -> tuple[str | None, bool]:
    """(domain, from_email). The website wins; when it yields nothing (blank,
    shared host, garbage) the email's domain is used only when it plausibly
    belongs to the firm."""
    domain = norm_domain(website)
    if domain is not None:
        return domain, False
    domain = norm_email_domain(email)
    if domain is not None and email_domain_plausible(domain, name_stem):
        return domain, True
    return None, False


def _get(raw: dict[str, str], colmap: ColumnMap, name: str) -> str | None:
    for col in colmap.columns_for(name):
        v = (raw.get(col) or "").strip()
        if v:
            return html.unescape(v)
    return None


def _get_all(raw: dict[str, str], colmap: ColumnMap, name: str) -> str | None:
    """Every mapped column's value, distinct, joined -- for firm type, where an
    "Industry" column and a "Description" column both say something."""
    seen: list[str] = []
    for col in colmap.columns_for(name):
        v = html.unescape((raw.get(col) or "").strip())
        if v and v not in seen:
            seen.append(v)
    return " | ".join(seen) or None


def normalize_row(raw: dict[str, str], colmap: ColumnMap) -> dict[str, Any]:
    g = lambda name: _get(raw, colmap, name)  # noqa: E731

    firm_name = g("firm_name")
    name_stem = norm_name(firm_name) if firm_name else None
    website = g("website")
    email_raw = g("email")
    email = email_raw.lower() if email_raw else None
    email_valid = bool(email and _EMAIL_RE.match(email))
    domain, from_email = resolve_domain(website, email if email_valid else None, name_stem)

    city, state, zip5 = g("city"), g("state"), g("zip")
    address, location = g("address"), g("location")
    if location and (not city or not state):
        m = _LOCATION_RE.match(location)
        if m:
            city = city or m.group("city").strip()
            state = state or m.group("state").strip()
            zip5 = zip5 or m.group("zip")
    state = norm_state(state) if state else None
    if zip5:
        zip5 = zip5.strip()[:5] if zip5.strip()[:5].isdigit() else None

    person_raw = g("person_name")
    if not person_raw:
        first, last = g("first_name"), g("last_name")
        person_raw = " ".join(p for p in (first, last) if p) or None
    person = clean_person_name(person_raw) if person_raw else None

    size_raw = g("firm_size")
    size_min, size_max = parse_size(size_raw)
    phone = g("phone")

    mapped_cols = colmap.mapped_columns
    extra = {h: v for h, v in raw.items() if h not in mapped_cols and v and v.strip()}

    return {
        "firm_name": firm_name,
        "name_stem": name_stem,
        "website": website,
        "domain": domain,
        "domain_from_email": from_email,
        "city": city,
        "state": state,
        "zip": zip5,
        "address": address,
        "location": location,
        "country": g("country"),
        "firm_size": size_raw,
        "size_min": size_min,
        "size_max": size_max,
        "firm_type": _get_all(raw, colmap, "firm_type"),
        "job_post": g("job_post"),
        "person_name": person,
        "person_name_raw": person_raw,
        "is_person": person is not None,
        "person_title": g("person_title"),
        "email": email if email_valid else None,
        "email_valid": email_valid,
        "email_raw": email_raw,
        "email_status": g("email_status"),
        "phone": phone,
        "phone_e164": norm_phone(phone) if phone else None,
        "linkedin": norm_linkedin(g("linkedin")),
        "contacted_before": parse_contacted(g("contacted_before")),
        "contacted_at": parse_date(g("contacted_at")),
        "technology": g("technology"),
        "notes": g("notes"),
        "extra": extra,
    }
