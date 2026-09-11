"""Pydantic response/request models -- THE contract (plan/api-contract.md).
`scripts/export_openapi.py` / `lge openapi` serialise these straight to
`openapi.json`; the frontend generates its TypeScript types from that file.
Field names and shapes here must match the contract exactly -- this module
*is* the contract, not a convenience layer over it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Band = Literal["STRIKE", "SEQUENCE", "NURTURE", "HOLD"]
Contest = Literal["NONE", "LOW", "MED", "HIGH"]
EmailStatus = Literal["valid", "catch_all", "risky", "invalid", "unverified"]
Role = Literal["owner", "admin", "attorney", "unknown"]
LeadView = Literal["STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED", "UNSCORED"]
OutcomeAction = Literal["sent", "replied", "meeting", "won", "lost", "not_now", "opt_out"]
AttributeState = Literal["resolved", "unknown", "conflict", "stale"]
AlertState = Literal["ok", "firing", "no_data"]


class ErrorBody(BaseModel):
    code: str
    message: str
    fix: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# =============================================================================
# Shared types
# =============================================================================


class FirmRef(BaseModel):
    id: str
    name: str
    domain: str | None
    city: str | None
    state: str | None
    tier: str | None
    tier_display: str
    practice_display: str | None
    fee_display: str | None
    cms_display: str | None


class Proof(BaseModel):
    signal_id: int
    kind: str
    headline: str
    quote: str | None
    source_label: str
    source_url: str | None
    first_seen: datetime
    board_posted_date: date | None
    days_open: int | None
    repost_count: int
    sources: list[str]
    closed_at: datetime | None
    weight: int
    decay: float
    contest: Contest


class ContactSummary(BaseModel):
    id: str
    full_name: str
    title: str | None
    role: Role
    source_label: str
    email: str | None
    email_status: EmailStatus | None
    email_status_display: str | None
    phone: str | None


class LeadRow(BaseModel):
    id: str
    firm: FirmRef
    state: str
    state_display: str
    band: Band | None
    fit: int | None
    intent: int | None
    contest: Contest | None
    grade: Literal["A", "B"] | None
    proof: Proof | None
    contact: ContactSummary | None
    scored_at: datetime | None


# =============================================================================
# GET /api/health
# =============================================================================


class HealthResponse(BaseModel):
    db: Literal["ok", "down"]
    version: str


# =============================================================================
# GET /api/today
# =============================================================================


class FirstDraft(BaseModel):
    subject: str
    body: str


class AlertSummary(BaseModel):
    name: str
    label: str
    state: AlertState
    detail: str


class QueueCounts(BaseModel):
    handcheck: int
    conflicts: int
    identity: int
    agency: int
    discovery: int


class BenchStatus(BaseModel):
    skus_available: int
    stale: bool
    message: str


class Attention(BaseModel):
    alerts: list[AlertSummary]
    queues: QueueCounts
    bench: BenchStatus
    providers_inert: list[str]


class TodayResponse(BaseModel):
    top_proof: LeadRow | None
    first_draft: FirstDraft | None
    strike: list[LeadRow]
    attention: Attention


# =============================================================================
# GET /api/leads
# =============================================================================


class LeadViewCounts(BaseModel):
    STRIKE: int
    SEQUENCE: int
    NURTURE: int
    PHONE: int
    EXCLUDED: int
    UNSCORED: int


class LeadsResponse(BaseModel):
    items: list[LeadRow]
    next_cursor: str | None
    counts: LeadViewCounts


# =============================================================================
# GET /api/leads/{id}
# =============================================================================


class ScoreFitTerm(BaseModel):
    label: str
    points: int


class ScoreIntentTerm(BaseModel):
    label: str
    weight: int
    decay: float
    points: float


class ScoreBreakdown(BaseModel):
    fit_terms: list[ScoreFitTerm]
    intent_terms: list[ScoreIntentTerm]
    note: str


class LeadOutcome(BaseModel):
    id: int
    action: OutcomeAction
    until: date | None
    note: str | None
    actor: str
    transition_applied: bool
    at: datetime


class TimelineEvent(BaseModel):
    from_state: str | None
    to_state: str
    label: str
    trigger: str
    actor: str
    at: datetime


class LeadDetail(LeadRow):
    contacts: list[ContactSummary]
    missing_roles: list[Literal["owner", "admin"]]
    score: ScoreBreakdown
    exclusion_reasons: list[str]
    outcomes: list[LeadOutcome]
    timeline: list[TimelineEvent]


# =============================================================================
# GET /api/leads/{id}/drafts
# =============================================================================


class Touch(BaseModel):
    step: int
    day: int
    subject: str
    body: str
    skipped_reason: str | None


class DraftsResponse(BaseModel):
    band: Band | None
    excluded_reason: str | None
    touches: list[Touch]


# =============================================================================
# POST /api/leads/{id}/outcome
# =============================================================================


class OutcomeRequest(BaseModel):
    action: OutcomeAction
    until: date | None = None
    note: str | None = None


class OutcomeResponse(BaseModel):
    lead: LeadDetail
    transition_applied: bool
    message: str


# =============================================================================
# GET /api/firms
# =============================================================================


class FirmListItem(BaseModel):
    id: str
    name: str
    domain: str | None
    city: str | None
    state: str | None
    tier_display: str
    state_display: str | None
    fit: int | None


class FirmsResponse(BaseModel):
    items: list[FirmListItem]
    next_cursor: str | None
    total: int


# =============================================================================
# GET /api/firms/{id}
# =============================================================================


class AttributeClaim(BaseModel):
    source_label: str
    display: str
    confidence: float
    evidence: str | None
    observed_at: datetime
    won: bool


class AttributeRow(BaseModel):
    attr: str
    label: str
    display: str
    state: AttributeState
    source_label: str | None
    confidence: float | None
    evidence: str | None
    evidence_url: str | None
    observed_at: datetime | None
    claims: list[AttributeClaim]


class DocumentRow(BaseModel):
    url: str
    page_kind: str | None
    status_code: int | None
    words: int | None
    robots_decision: str | None
    fetched_at: datetime


class AliasRow(BaseModel):
    name: str | None
    domain: str | None
    phone: str | None
    merge_rule: str | None
    source_label: str


class FirmLeadRef(BaseModel):
    id: str
    state_display: str
    band: Band | None


class FirmDetail(BaseModel):
    firm: FirmRef
    tier_reason: str
    attributes: list[AttributeRow]
    documents: list[DocumentRow]
    signals: list[Proof]
    contacts: list[ContactSummary]
    aliases: list[AliasRow]
    lead: FirmLeadRef | None


# =============================================================================
# Hand-check -- gate G2
# =============================================================================


class HandcheckGate(BaseModel):
    needed: int
    reviewed_firms: int
    passed: bool
    rule: str


class HandcheckAccuracyRow(BaseModel):
    attr: str
    label: str
    checked: int
    correct: int


class HandcheckReview(BaseModel):
    correct: bool
    corrected_value: str | None


class HandcheckSampleFirm(BaseModel):
    firm_id: str
    name: str
    domain: str | None
    attributes: list[AttributeRow]
    reviews: dict[str, HandcheckReview]


class HandcheckResponse(BaseModel):
    gate: HandcheckGate
    accuracy: list[HandcheckAccuracyRow]
    sample: list[HandcheckSampleFirm]


class HandcheckDecisionRequest(BaseModel):
    correct: bool
    corrected_value: str | None = None


# =============================================================================
# Meta / pipeline
# =============================================================================


class ProvidersResponse(BaseModel):
    ai_extraction: bool
    email_verification: bool
    places: bool
    crawler_identity: str


class AlertItem(BaseModel):
    name: str
    label: str
    state: AlertState
    value: float | None
    detail: str


class AlertsResponse(BaseModel):
    items: list[AlertItem]


class GateItem(BaseModel):
    name: str
    label: str
    passed: bool
    report: str


class GatesResponse(BaseModel):
    items: list[GateItem]
