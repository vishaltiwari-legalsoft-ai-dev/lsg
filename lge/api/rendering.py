"""Raw SQL row -> pydantic response model. Shared by every route that
returns a `LeadRow`/`FirmRef`/`Proof`/`ContactSummary` (leads, today, firms)
so the same lead built two different ways never disagrees. Reuses
`lge.export.list.best_email` for "which of a contact's emails is the one to
show" -- the exact rule `build_list`'s CSV export already uses -- and
`lge.journey.tokens` for evidence reading, both rather than re-deriving
either here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from lge.api.labels import (
    cms_display,
    email_status_display,
    fee_display,
    practice_display,
    proof_headline,
    source_label,
    state_display,
    tier_display,
)
from lge.api.models import ContactSummary, FirmRef, LeadRow, Proof
from lge.export.list import best_email
from lge.journey.model import Signal
from lge.journey.tokens import days_open as _days_open


def build_firm_ref(row: dict[str, Any]) -> FirmRef:
    return FirmRef(
        id=str(row["firm_id"]),
        name=row["canonical_name"],
        domain=row.get("domain"),
        city=row.get("city"),
        state=row.get("state"),
        tier=row.get("tier"),
        tier_display=tier_display(row.get("tier")),
        practice_display=practice_display(row.get("primary_practice")),
        fee_display=fee_display(row.get("fee_model")),
        cms_display=cms_display(row.get("cms_detected")),
    )


def build_proof(
    signal: Signal | None,
    board_posted_date: Any,
    signal_scores: dict[int, dict[str, Any]],
    at: datetime,
) -> Proof | None:
    """`signal_scores` is `{signal_id: {"weight": int, "decay": float,
    "contest": str}}`, computed by one batched call to
    sql/002_functions.sql's `signal_weight`/`decay`/`contest_level` -- the
    score breakdown is never recomputed in Python."""
    if signal is None:
        return None
    scores = signal_scores.get(signal.id, {})
    evidence = signal.evidence or {}
    sources = evidence.get("sources")
    if not isinstance(sources, list):
        single = evidence.get("source")
        sources = [single] if single else []
    days_raw = _days_open(signal.first_seen, at)
    return Proof(
        signal_id=signal.id,
        kind=signal.kind,
        headline=proof_headline(signal.kind, evidence, signal.first_seen, at, signal.repost_count),
        quote=evidence.get("quote"),
        source_label=source_label(sources[0] if sources else None),
        source_url=evidence.get("url"),
        first_seen=signal.first_seen,
        board_posted_date=board_posted_date,
        days_open=int(days_raw) if days_raw is not None else None,
        repost_count=signal.repost_count,
        sources=[str(s) for s in sources],
        closed_at=signal.closed_at,
        weight=int(scores.get("weight", 0) or 0),
        decay=float(scores.get("decay", 0) or 0),
        contest=scores.get("contest") or "HIGH",
    )


def build_contact_summary(
    contact_row: dict[str, Any] | None, emails_by_contact: dict[str, list[dict[str, Any]]]
) -> ContactSummary | None:
    if contact_row is None:
        return None
    email_row = best_email(emails_by_contact.get(contact_row["id"], []))
    return ContactSummary(
        id=str(contact_row["id"]),
        full_name=contact_row["full_name"],
        title=contact_row.get("title"),
        role=contact_row.get("role") or "unknown",
        source_label=source_label(contact_row.get("source")),
        email=email_row["email"] if email_row else None,
        email_status=email_row["status"] if email_row else None,
        email_status_display=(
            email_status_display(email_row["status"], email_row.get("vendor_status"))
            if email_row
            else None
        ),
        phone=contact_row.get("phone_direct"),
    )


def fetch_signal_scores(
    conn: Any, signal_ids: list[int], at: datetime
) -> dict[int, dict[str, Any]]:
    """One batched call to sql/002_functions.sql's
    `signal_weight`/`decay`/`contest_level` for a whole page of signals --
    never one query per row. Shared by every route that renders a `Proof`
    (leads list/detail, today, firm detail)."""
    ids = sorted({i for i in signal_ids if i is not None})
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id,
                   signal_weight(s.kind, s.first_seen, s.closed_at, s.repost_count, %(at)s)
                     AS weight,
                   decay(EXTRACT(EPOCH FROM (%(at)s - s.last_seen)) / 86400.0) AS decay,
                   contest_level(s.kind) AS contest
            FROM signal s WHERE s.id = ANY(%(ids)s)
            """,
            {"at": at, "ids": ids},
        )
        return {row["id"]: row for row in cur.fetchall()}


def build_lead_row(
    row: dict[str, Any], proof: Proof | None, contact: ContactSummary | None
) -> LeadRow:
    return LeadRow(
        id=str(row["lead_id"]),
        firm=build_firm_ref(row),
        state=row.get("lead_state") or "",
        state_display=state_display(row.get("lead_state")),
        band=row.get("band"),
        fit=row.get("fit_score"),
        intent=row.get("intent_score"),
        contest=row.get("contest"),
        grade=row.get("grade"),
        proof=proof,
        contact=contact,
        scored_at=row.get("scored_at"),
    )
