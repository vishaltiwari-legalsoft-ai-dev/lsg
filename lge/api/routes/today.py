"""GET /api/today -- the SDR's first screen. `top_proof` and `strike` reuse
`lge.export.list.classify_open_scored_leads` (the same selector `build_list`
and `GET /api/leads` use); `first_draft` renders touch 1 through the exact
template/token machinery `lge.journey.build.build_journey` uses for the
same lead (STRIKE leads are never run through the full 9-touch renderer --
"STRIKE (human, same day, never rendered) ... is the caller's
responsibility to filter out" -- so touch 1 alone is rendered directly,
the one piece of that machinery that does not depend on band).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from lge.api.deps import ConnDep, providers_inert
from lge.api.handcheck_logic import pending_count
from lge.api.models import (
    AlertSummary,
    Attention,
    BenchStatus,
    FirstDraft,
    QueueCounts,
    TodayResponse,
)
from lge.api.queues import (
    agency_count,
    bench_status,
    conflicts_count,
    discovery_count,
    identity_count,
)
from lge.api.rendering import (
    build_contact_summary,
    build_lead_row,
    build_proof,
    fetch_signal_scores,
)
from lge.export.list import ClassifiedLead, classify_open_scored_leads, fetch_journey_edits
from lge.journey.build import _build_tokens, _render_touch1  # touch-1-only render, see docstring
from lge.journey.model import Contact as JourneyContact
from lge.journey.model import Firm as JourneyFirm
from lge.journey.model import JourneyEdits, JourneyLead
from lge.ops.alerts import evaluate_all
from lge.registry import RunContext
from lge.settings import get_settings

router = APIRouter(prefix="/api", tags=["today"])

_CONTEST_RANK = {"NONE": 0, "LOW": 1, "MED": 2, "HIGH": 3, None: 4}

_ALERT_LABELS: dict[str, str] = {
    "watcher_silence": "Job-posting watcher",
    "platform_parser_silence": "Bar-board parser",
    "dedupe_drift": "Identity dedupe",
    "extraction_confidence_drop": "Extraction confidence",
    "tier_distribution_shift": "Tier distribution",
    "bounce_rate": "Bounce rate",
    "signal_to_contact_latency": "Signal-to-contact latency",
    "bench_starvation": "Bench starvation",
    "bench_staleness": "Bench freshness",
    "stale_share": "Stale coverage",
    "source_yield_zero": "Source yield",
    "robots_diff": "robots.txt changes",
    "agency_rule3_spike": "Agency spike",
}


def _rank(cl: ClassifiedLead) -> tuple[int, int, int, str]:
    intent = cl.row.get("intent_score")
    fit = cl.row.get("fit_score")
    contest = cl.row.get("contest")
    return (
        -(intent if intent is not None else -1),
        _CONTEST_RANK.get(contest, 4),
        -(fit if fit is not None else -1),
        cl.lead_id,
    )


def _render_first_draft(cl: ClassifiedLead, at: datetime, edits: JourneyEdits) -> FirstDraft | None:
    if cl.primary_contact is None:
        return None
    row = cl.row
    firm = JourneyFirm(
        id=str(row["firm_id"]), canonical_name=row["canonical_name"], city=row["city"],
        state=row["state"], tier=row["tier"], fee_model=row["fee_model"],
        primary_practice=row["primary_practice"], cms_detected=row["cms_detected"],
    )
    contact = JourneyContact(
        id=str(cl.primary_contact["id"]), full_name=cl.primary_contact["full_name"],
        title=cl.primary_contact.get("title"), role=cl.primary_contact.get("role"),
    )
    journey_lead = JourneyLead(
        lead_id=cl.lead_id, band=cl.category, firm=firm, contact=contact, signal=cl.signal,
        repost_first_seen=cl.repost_first_seen, at=at,
    )
    tokens = _build_tokens(journey_lead)
    touch, _reason = _render_touch1(journey_lead, tokens, edits)
    if touch is None:
        return None
    return FirstDraft(subject=touch.subject, body=touch.body)


@router.get("/today", response_model=TodayResponse)
def get_today(conn: ConnDep) -> TodayResponse:
    at = datetime.now(UTC)
    classification = classify_open_scored_leads(conn, at)

    strike_cls = sorted(
        (cl for cl in classification.leads if cl.category == "STRIKE"), key=_rank
    )
    sequence_cls = sorted(
        (cl for cl in classification.leads if cl.category == "SEQUENCE"), key=_rank
    )

    top_cl = strike_cls[0] if strike_cls else (sequence_cls[0] if sequence_cls else None)
    rest_strike_cls = strike_cls[1:] if strike_cls else []

    signal_ids = [
        cl.signal.id
        for cl in ([top_cl] if top_cl else []) + rest_strike_cls
        if cl and cl.signal is not None
    ]
    signal_scores = fetch_signal_scores(conn, signal_ids, at)

    def _row(cl: ClassifiedLead):
        proof = build_proof(cl.signal, cl.repost_first_seen, signal_scores, at)
        contact = build_contact_summary(cl.primary_contact, classification.emails_by_contact)
        return build_lead_row(cl.row, proof, contact)

    top_proof = _row(top_cl) if top_cl else None
    first_draft = _render_first_draft(top_cl, at, fetch_journey_edits(conn)) if top_cl else None
    strike = [_row(cl) for cl in rest_strike_cls]

    return TodayResponse(
        top_proof=top_proof, first_draft=first_draft, strike=strike,
        attention=build_attention(conn, at),
    )


def build_attention(conn, at: datetime) -> Attention:
    """Alerts, the review queues, the bench and the providers that are not
    configured -- shared by Today and the overview."""
    ctx = RunContext(conn, get_settings())
    alert_outcomes = evaluate_all(ctx)
    alerts = [
        AlertSummary(
            name=o.name, label=_ALERT_LABELS.get(o.name, o.name.replace("_", " ").capitalize()),
            state=o.state, detail=o.detail,
        )
        for o in alert_outcomes
    ]
    queues = QueueCounts(
        handcheck=pending_count(conn), conflicts=conflicts_count(conn),
        identity=identity_count(conn), agency=agency_count(conn),
        discovery=discovery_count(conn),
    )
    bench = BenchStatus(**bench_status(conn, at))
    return Attention(alerts=alerts, queues=queues, bench=bench, providers_inert=providers_inert())
