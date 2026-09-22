"""Raw SQL row -> pydantic response model. Shared by every route that
returns a `LeadRow`/`FirmRef`/`Proof`/`ContactSummary` (leads, today, firms)
so the same lead built two different ways never disagrees. Reuses
`lge.export.list.best_email` for "which of a contact's emails is the one to
show" -- the exact rule `build_list`'s CSV export already uses -- and
`lge.journey.tokens` for evidence reading, both rather than re-deriving
either here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from lge.api.labels import (
    cms_display,
    email_status_display,
    fee_display,
    practice_display,
    proof_headline,
    reason_display,
    source_label,
    state_display,
    tier_display,
)
from lge.api.models import ContactSummary, FirmRef, LeadRow, PainAnalysis, PainPoint, Proof
from lge.api.stage import STAGE_DISPLAY, stage_of
from lge.export.list import best_email
from lge.journey.model import Signal
from lge.journey.tokens import days_open as _days_open
from lge.planes.ja.ja6_signals import first_sentence


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
    latest_body = scores.get("latest_body")
    quote = first_sentence(latest_body) if latest_body else None
    return Proof(
        signal_id=signal.id,
        kind=signal.kind,
        headline=proof_headline(signal.kind, evidence, signal.first_seen, at, signal.repost_count),
        quote=quote or evidence.get("quote"),
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
        linkedin_url=contact_row.get("linkedin_url"),
        linkedin_headline=contact_row.get("linkedin_headline"),
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
        # `latest_body`: the newest stored posting behind the signal. Signal
        # evidence is immutable (I6) and is the record of what was first seen;
        # the quote a person reads is re-derived from the raw posting, so a
        # parser fix reaches the screen without touching the record.
        cur.execute(
            """
            SELECT s.id,
                   signal_weight(s.kind, s.first_seen, s.closed_at, s.repost_count, %(at)s)
                     AS weight,
                   decay(EXTRACT(EPOCH FROM (%(at)s - s.last_seen)) / 86400.0) AS decay,
                   contest_level(s.kind) AS contest,
                   q.body AS latest_body
            FROM signal s
            LEFT JOIN LATERAL (
              SELECT rp.body
              FROM signal_sighting ss JOIN raw_posting rp ON rp.id = ss.raw_posting_id
              WHERE ss.signal_id = s.id AND rp.body IS NOT NULL
              ORDER BY rp.fetched_at DESC, rp.id DESC
              LIMIT 1
            ) q ON true
            WHERE s.id = ANY(%(ids)s)
            """,
            {"at": at, "ids": ids},
        )
        return {row["id"]: row for row in cur.fetchall()}


def build_lead_row(
    row: dict[str, Any],
    proof: Proof | None,
    contact: ContactSummary | None,
    blockers: Sequence[str] = (),
) -> LeadRow:
    stage, next_action = stage_of(
        row.get("lead_state"),
        cooldown_until=row.get("cooldown_until"),
        contact_name=contact.full_name if contact else None,
        has_email=bool(contact and contact.email),
    )
    return LeadRow(
        blockers=[reason_display(b) for b in blockers],
        stage=stage,
        stage_display=STAGE_DISPLAY[stage],
        next_action=next_action,
        owner=row.get("owner"),
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


def fetch_pain_analysis(conn: Any, firm_id: Any) -> PainAnalysis | None:
    """The AI's reading of what hurts at this firm (ja8_pain, D-058), latest
    first. Every pain here carried a quote from the record when it was
    written; an ungrounded one was thrown away before the claim was made."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value, observed_at FROM firm_attribute WHERE firm_id = %s "
            "AND attr = 'pain_analysis' ORDER BY observed_at DESC LIMIT 1",
            (firm_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    value = row["value"] or {}
    return PainAnalysis(
        summary=value.get("summary") or "",
        pains=[PainPoint(**{k: p.get(k, "") for k in
                            ("kind", "headline", "quote", "source", "why_it_matters")})
               for p in value.get("pains") or []],
        read=list(value.get("read") or []),
        at=row["observed_at"],
    )
