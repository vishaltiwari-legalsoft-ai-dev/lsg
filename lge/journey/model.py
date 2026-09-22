"""Trusted types the renderer works with. `lge/export/list.py` is the
boundary: it reads raw DB rows, validates/shapes them into these dataclasses,
and only then hands them to `lge.journey.build`. Nothing in this module
touches the database.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Signal:
    id: int
    kind: str
    first_seen: datetime
    last_seen: datetime
    closed_at: datetime | None
    repost_count: int
    evidence: dict


@dataclass(frozen=True, slots=True)
class Firm:
    id: str
    canonical_name: str
    city: str | None
    state: str | None
    tier: str
    fee_model: str | None
    primary_practice: str | None
    cms_detected: str | None


@dataclass(frozen=True, slots=True)
class Contact:
    id: str
    full_name: str
    title: str | None
    role: str | None  # owner | admin | attorney | unknown (contact.role)


@dataclass(frozen=True, slots=True)
class JourneyLead:
    """Everything `build_journey` needs for one lead. `band` must already be
    STRIKE-and-HOLD-filtered by the caller -- this type only ever carries
    SEQUENCE or NURTURE through the renderer."""

    lead_id: str
    band: str  # 'SEQUENCE' | 'NURTURE'
    firm: Firm
    contact: Contact
    signal: Signal | None
    repost_first_seen: date | None  # first sighting where the board's date
    # moved past signal.first_seen -- see sql/... repost_month query. None
    # when signal.repost_count == 0 or no signal_sighting row proves it.
    at: datetime  # reference "now" for days_open / determinism in tests


@dataclass(frozen=True, slots=True)
class RenderedTouch:
    step: int
    day: int
    subject: str
    body: str
    # The copy files this email was built from (journey/copy/-relative), the
    # email's own first -- so a screen can say which wording to change.
    templates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JourneyEdits:
    """What the Email journey screen changed (D-057): new wording for a copy
    file, a new day for an email. `lge.export.list.fetch_journey_edits` reads
    them from the store; the renderer takes them as given. Empty means the
    originals -- journey/copy/ and journey/sequences.yml."""

    # copy file path -> (subject, body); step -> days after email 1
    copy: Mapping[str, tuple[str | None, str]] = field(default_factory=dict)
    days: Mapping[int, int] = field(default_factory=dict)


NO_EDITS = JourneyEdits()


@dataclass(frozen=True, slots=True)
class JourneyResult:
    """Success: `touches` is non-empty and `excluded_reason` is None.
    Exclusion: `touches` is empty and `excluded_reason` explains why --
    always `"unresolved_token:<name>"` for a missing token, or one of the
    named structural reasons (`sequence_missing_signal_evidence`,
    `fee_model_unresolved:<value>`, `no_touch1_variant:<kind>`)."""

    touches: list[RenderedTouch]
    excluded_reason: str | None
