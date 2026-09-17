"""Pydantic response/request models -- THE contract (plan/api-contract.md).
`scripts/export_openapi.py` / `lge openapi` serialise these straight to
`openapi.json`; the frontend generates its TypeScript types from that file.
Field names and shapes here must match the contract exactly -- this module
*is* the contract, not a convenience layer over it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

Band = Literal["STRIKE", "SEQUENCE", "NURTURE", "HOLD"]
Contest = Literal["NONE", "LOW", "MED", "HIGH"]
EmailStatus = Literal["valid", "catch_all", "risky", "invalid", "unverified"]
Role = Literal["owner", "admin", "attorney", "unknown"]
LeadView = Literal["STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED", "UNSCORED"]
OutcomeAction = Literal["sent", "replied", "meeting", "won", "lost", "not_now", "opt_out"]
Stage = Literal[
    "researching", "no_website", "needs_review", "needs_contact", "ready", "parked",
    "in_outreach", "replied", "handed_off", "won", "lost", "disqualified", "do_not_contact",
    "needs_refresh",
]
DecisionAction = Literal["qualify", "disqualify", "hold", "reopen", "handoff"]
BatchAction = Literal["research", "find_contacts", "disqualify", "hold", "assign"]
JobKind = Literal["research", "find_contacts"]
JobStatus = Literal["queued", "running", "done", "failed"]
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
    linkedin_url: str | None = None
    # What the search engine showed about the profile ("Partner at Freehill Hogan & Mahar").
    linkedin_headline: str | None = None


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
    # What still keeps this lead off the email list, in plain words ("Email not
    # verified", "Fee model unknown — not tiered yet"). Empty when it is on the list.
    blockers: list[str]
    # Where the lead is as a person works it, and what to do next (lge/api/stage.py).
    stage: Stage
    stage_display: str
    next_action: str
    owner: str | None


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
    # Open leads per stage (lge/api/stage.py), for the work queue's tabs.
    stage_counts: dict[str, int]


# =============================================================================
# GET /api/qualified -- the leads with every step done, ready to reach (D-047)
# =============================================================================

QualifiedCheckKey = Literal[
    "site_read", "fit", "person", "email", "email_verified", "linkedin", "journey"
]


class QualifiedCheck(BaseModel):
    key: QualifiedCheckKey
    label: str
    ok: bool
    detail: str | None  # what was found, or why not, in plain words


class QualifiedRow(LeadRow):
    checks: list[QualifiedCheck]
    ready: bool  # every check passed
    missing: list[str]  # the failed checks' labels, in plain words
    why_now: bool  # an open pain signal on the firm -- shown, not required


class QualifiedCounts(BaseModel):
    ready: int
    almost: int  # every step but one or two
    checked: int  # open leads at firms that are not disqualified
    # Among the almost-ready, how many fail each check -- what is holding them back.
    missing_by_check: dict[str, int]


class QualifiedResponse(BaseModel):
    items: list[QualifiedRow]
    next_offset: int | None
    counts: QualifiedCounts


# =============================================================================
# GET /api/overview -- the landing page: the pipeline with live numbers
# =============================================================================


class PipelineStep(BaseModel):
    key: Literal["lists", "research", "qualify", "people", "outreach"]
    number: int
    label: str
    what: str
    count: int
    count_label: str
    detail: str
    href: str


class StageCount(BaseModel):
    stage: Stage
    label: str
    help: str
    count: int


class RunningJob(BaseModel):
    id: str
    kind: JobKind
    status: JobStatus
    firm_id: str
    firm_name: str
    done_steps: int
    total_steps: int
    started_at: datetime | None


class LastRun(BaseModel):
    component: str
    label: str
    finished_at: datetime
    processed: int
    failed: int


class ListsSummary(BaseModel):
    count: int
    rows: int
    latest_file: str | None
    latest_status: str | None
    latest_at: datetime | None


class OverviewResponse(BaseModel):
    steps: list[PipelineStep]
    stages: list[StageCount]
    running: list[RunningJob]
    last_runs: list[LastRun]
    lists: ListsSummary
    attention: Attention


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


class LeadNote(BaseModel):
    id: int
    text: str
    actor: str
    at: datetime


class JobStep(BaseModel):
    name: str
    status: Literal["pending", "running", "done", "failed"]
    note: str | None = None


class ActionJob(BaseModel):
    id: str
    kind: JobKind
    firm_id: str
    lead_id: str | None
    status: JobStatus
    steps: list[JobStep]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class LeadDetail(LeadRow):
    contacts: list[ContactSummary]
    missing_roles: list[Literal["owner", "admin"]]
    score: ScoreBreakdown
    exclusion_reasons: list[str]
    outcomes: list[LeadOutcome]
    timeline: list[TimelineEvent]
    notes: list[LeadNote]
    job: ActionJob | None


# =============================================================================
# Actions -- POST /api/firms/{id}/research, /api/leads/{id}/decision, ...
# =============================================================================


class ResearchRequest(BaseModel):
    scope: Literal["full", "contacts"] = "full"


class JobResponse(BaseModel):
    job: ActionJob


class JobsResponse(BaseModel):
    items: list[ActionJob]


class ContactCreate(BaseModel):
    full_name: str
    title: str | None = None
    role: Role | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None


class ContactPatch(BaseModel):
    full_name: str | None = None
    title: str | None = None
    role: Role | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None


class ContactRemove(BaseModel):
    reason: str | None = None


class ContactResponse(BaseModel):
    contact: ContactSummary


class PrimaryContactRequest(BaseModel):
    contact_id: str


class DecisionRequest(BaseModel):
    action: DecisionAction
    reason: str | None = None
    until: date | None = None


class DecisionResponse(BaseModel):
    lead: LeadDetail
    message: str


class NoteRequest(BaseModel):
    text: str


class OwnerRequest(BaseModel):
    owner: str | None


class BatchRequest(BaseModel):
    lead_ids: list[str]
    action: BatchAction
    reason: str | None = None
    until: date | None = None
    owner: str | None = None


class BatchResult(BaseModel):
    lead_id: str
    ok: bool
    message: str
    job_id: str | None = None


class BatchResponse(BaseModel):
    results: list[BatchResult]


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


# =============================================================================
# Imports -- any sheet, mapped, batched, loaded (D-029)
# =============================================================================


class ImportColumn(BaseModel):
    column: str
    field: str | None  # vocabulary name, or null when the column stays extra data
    field_label: str | None
    confidence: float
    reason: str
    samples: list[str]


class FieldOption(BaseModel):
    name: str
    label: str
    mandatory_group: str | None
    filled_by: str  # where research gets it when the sheet lacks it; "" when only a sheet can


class ImportBatch(BaseModel):
    batch_no: int
    row_start: int
    row_end: int
    status: str
    rows_loaded: int
    rows_skipped: int
    health: dict[str, Any] | None
    error: str | None


class ImportSummary(BaseModel):
    id: str
    file_name: str
    format: str
    row_count: int
    status: str  # mapped | loading | loaded | failed
    status_display: str
    missing: list[str]  # mandatory data the sheet lacks, in plain words
    research_fills: list[str]  # what the sheet lacks that research supplies, in plain words
    reader: str  # which reader mapped the columns: "rules" | "llm"
    batch_size: int
    batches_total: int
    batches_loaded: int
    health_score: int | None
    created_at: datetime
    loaded_at: datetime | None


class ImportDetail(ImportSummary):
    columns: list[ImportColumn]
    fields: list[FieldOption]
    batches: list[ImportBatch]
    health: dict[str, Any] | None
    notes: list[str]


class ImportsResponse(BaseModel):
    items: list[ImportSummary]


class MappingRequest(BaseModel):
    overrides: dict[str, str | None]  # column -> field name, or null to unmap


class ImportLoadResponse(BaseModel):
    id: str
    status: str
    message: str
