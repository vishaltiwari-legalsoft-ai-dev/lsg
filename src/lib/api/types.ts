/**
 * The API contract, as types.
 *
 * These alias the schemas generated from the backend's openapi.json
 * (`npm run api:types` → schema.d.ts), so the UI compiles against what the
 * engine actually serves; re-run the script whenever the backend changes.
 * `Lead Gen Engine/plan/api-contract.md` is the spec: where the generated
 * schema and the doc disagree, the backend is fixed — see the drift list in
 * the report — and the UI stays safe for both shapes meanwhile.
 *
 * Display strings (`*_display`, `label`, `headline`, `source_label`,
 * `message`, `note`) come from the backend. The frontend renders them
 * verbatim and never humanises a slug, recomputes a tier or filters a list.
 */
import type { components } from "./schema";

type S = components["schemas"];

// ── Shared types ────────────────────────────────────────────────────────────

export type Band = NonNullable<S["LeadRow"]["band"]>;
export type Contest = S["Proof"]["contest"];
export type EmailStatus = NonNullable<S["ContactSummary"]["email_status"]>;
export type Role = S["ContactSummary"]["role"];

export type FirmRef = S["FirmRef"];
/** The evidence the engine read on the firm's own site. `first_seen` is OURS. */
export type Proof = S["Proof"];
export type ContactSummary = S["ContactSummary"];
export type LeadRow = S["LeadRow"];

// ── Health and Today ────────────────────────────────────────────────────────

export type HealthResponse = S["HealthResponse"];
export type AlertState = S["AlertSummary"]["state"];
export type TodayAlert = S["AlertSummary"];
export type ReviewQueueCounts = S["QueueCounts"];
export type BenchStatus = S["BenchStatus"];
export type FirstDraft = S["FirstDraft"];
export type TodayResponse = S["TodayResponse"];

// ── Leads ───────────────────────────────────────────────────────────────────

export type LeadCounts = S["LeadViewCounts"];
export type LeadView = keyof LeadCounts;
export type LeadsResponse = S["LeadsResponse"];

/** Narrower than the generated query (which types view/contest as string). */
export interface LeadsQuery {
  view?: LeadView;
  /** The work queue: one stage, whatever the band. Takes precedence over `view`. */
  stage?: Stage;
  band?: Band;
  owner?: string;
  tier?: string;
  city?: string;
  signal?: string;
  contest?: Contest;
  verified?: boolean;
  q?: string;
  cursor?: string;
  limit?: number;
}

export type OutcomeAction = S["OutcomeRequest"]["action"];
export type LeadOutcome = S["LeadOutcome"];
export type ScoreBreakdown = S["ScoreBreakdown"];
export type TimelineEntry = S["TimelineEvent"];
export type LeadDetail = S["LeadDetail"];

export type DraftTouch = S["Touch"];
export type DraftsResponse = S["DraftsResponse"];

export type OutcomeRequest = S["OutcomeRequest"];
/** `message` is the toast copy, shown verbatim. */
export type OutcomeResponse = S["OutcomeResponse"];

// ── Actions: research, contacts, decisions, notes, owner, batch ─────────────

export type Stage = S["LeadRow"]["stage"];
export type LeadNote = S["LeadNote"];
export type JobStep = S["JobStep"];
export type ActionJob = S["ActionJob"];
export type JobResponse = S["JobResponse"];
export type JobsResponse = S["JobsResponse"];
export type ResearchRequest = S["ResearchRequest"];
export type ContactCreate = S["ContactCreate"];
export type ContactPatch = S["ContactPatch"];
export type ContactResponse = S["ContactResponse"];
export type DecisionAction = S["DecisionRequest"]["action"];
export type DecisionRequest = S["DecisionRequest"];
export type DecisionResponse = S["DecisionResponse"];
export type BatchAction = S["BatchRequest"]["action"];
export type BatchRequest = S["BatchRequest"];
export type BatchResponse = S["BatchResponse"];

// ── Overview: the home page ─────────────────────────────────────────────────

export type PipelineStep = S["PipelineStep"];
export type StageCount = S["StageCount"];
export type RunningJob = S["RunningJob"];
export type LastRun = S["LastRun"];
export type ListsSummary = S["ListsSummary"];
export type OverviewResponse = S["OverviewResponse"];

// ── Firms ───────────────────────────────────────────────────────────────────

export interface FirmsQuery {
  q?: string;
  tier?: string;
  city?: string;
  lead_state?: string;
  cursor?: string;
  limit?: number;
}

export type FirmListItem = S["FirmListItem"];
export type FirmsResponse = S["FirmsResponse"];

export type AttributeState = S["AttributeRow"]["state"];
export type AttributeClaim = S["AttributeClaim"];
export type AttributeRow = S["AttributeRow"];
export type FirmDocument = S["DocumentRow"];
export type FirmAlias = S["AliasRow"];
export type FirmDetail = S["FirmDetail"];

// ── Hand-check — gate G2 ────────────────────────────────────────────────────

export type HandcheckReview = S["HandcheckReview"];
export type HandcheckSampleFirm = S["HandcheckSampleFirm"];
export type HandcheckResponse = S["HandcheckResponse"];
export type HandcheckDecision = S["HandcheckDecisionRequest"];

// ── Imports ─────────────────────────────────────────────────────────────────

export type ImportColumn = S["ImportColumn"];
export type ImportFieldOption = S["FieldOption"];
export type ImportBatch = S["ImportBatch"];
export type ImportSummary = S["ImportSummary"];
export type ImportDetail = S["ImportDetail"];
export type ImportsResponse = S["ImportsResponse"];
export type MappingRequest = S["MappingRequest"];
export type ImportLoadResponse = S["ImportLoadResponse"];

// ── Errors ──────────────────────────────────────────────────────────────────
// The error envelope is written by the backend's exception handler, so it is
// not in openapi.json. `fix` is omitted when there is nothing to suggest.

export interface ApiErrorBody {
  error: { code: string; message: string; fix?: string };
}
