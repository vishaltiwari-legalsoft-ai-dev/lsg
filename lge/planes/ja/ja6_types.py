"""The row shape JA6's stages pass between each other. One SELECT (in
ja6_normalise.py) populates these from `raw_posting`; every other JA6 module
takes `Posting` objects, never a bare db row -- keeps the field list in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class Posting:
    id: int
    source: str
    source_key: str
    source_url: str | None
    firm_id: str | None
    company_name: str | None
    title: str
    location_raw: str | None
    city: str | None
    state: str | None
    metro_code: str | None
    body: str | None
    apply_email: str | None
    outbound_links: list[str] | None
    phone_raw: str | None
    ats_slug: str | None
    board_posted_date: date | None
    first_published: datetime | None
    updated_at_src: datetime | None
    fetch_ok: bool
    fetched_at: datetime

    # filled in by later JA6 stages, not by the initial SELECT
    canonical_role: str | None = None
    is_support: bool = False
    resolution_rung: int | None = None


_POSTING_COLUMNS = (
    "id", "source", "source_key", "source_url", "firm_id", "company_name", "title",
    "location_raw", "city", "state", "metro_code", "body", "apply_email",
    "outbound_links", "phone_raw", "ats_slug", "board_posted_date", "first_published",
    "updated_at_src", "fetch_ok", "fetched_at",
)


def posting_from_row(row: dict) -> Posting:
    values = {col: row[col] for col in _POSTING_COLUMNS}
    # psycopg adapts a `uuid` column to uuid.UUID, not str -- normalize to str
    # once here so every consumer (fingerprint hashing, dict keys, %s params)
    # deals with one type instead of guessing at each call site.
    if values["firm_id"] is not None:
        values["firm_id"] = str(values["firm_id"])
    return Posting(**values)
