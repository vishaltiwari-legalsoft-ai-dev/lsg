/**
 * The contract as strict runtime schemas (an unknown key fails), for tests:
 * fixtures.test.ts parses every fixture with them, and live-api.test.ts
 * parses the running engine's answers. Each schema is pinned at compile time
 * to the types in src/lib/api/types.ts, which alias the schema generated from
 * the backend's openapi.json — so none of the three can drift unnoticed.
 */
import { z } from "zod";

import type * as T from "@/lib/api/types";

const s = z.string();
const ns = z.string().nullable();
const n = z.number();
const nn = z.number().nullable();

const Band = z.enum(["STRIKE", "SEQUENCE", "NURTURE", "HOLD"]);
const Contest = z.enum(["NONE", "LOW", "MED", "HIGH"]);
const EmailStatus = z.enum(["valid", "catch_all", "risky", "invalid", "unverified"]);
const Role = z.enum(["owner", "admin", "attorney", "unknown"]);
const OutcomeAction = z.enum(["sent", "replied", "meeting", "won", "lost", "not_now", "opt_out"]);

export const FirmRef = z.strictObject({
  id: s, name: s, domain: ns, city: ns, state: ns, tier: ns,
  tier_display: s, practice_display: ns, fee_display: ns, cms_display: ns,
});
export const Proof = z.strictObject({
  signal_id: n, kind: s, headline: s, quote: ns, source_label: s, source_url: ns,
  first_seen: s, board_posted_date: ns, days_open: nn, repost_count: n, sources: z.array(s),
  closed_at: ns, weight: n, decay: n, contest: Contest,
});
export const ContactSummary = z.strictObject({
  id: s, full_name: s, title: ns, role: Role, source_label: s, email: ns,
  email_status: EmailStatus.nullable(), email_status_display: ns, phone: ns,
  linkedin_url: ns.optional(),
});
const Stage = z.enum([
  "researching", "no_website", "needs_review", "needs_contact", "ready", "parked",
  "in_outreach", "replied", "handed_off", "won", "lost", "disqualified", "do_not_contact",
  "needs_refresh",
]);
const leadRowShape = {
  id: s, firm: FirmRef, state: s, state_display: s, band: Band.nullable(), fit: nn, intent: nn,
  contest: Contest.nullable(), grade: z.enum(["A", "B"]).nullable(), proof: Proof.nullable(),
  contact: ContactSummary.nullable(), scored_at: ns, blockers: z.array(s),
  stage: Stage, stage_display: s, next_action: s, owner: ns,
};
export const LeadRow = z.strictObject(leadRowShape);
const LeadNote = z.strictObject({ id: n, text: s, actor: s, at: s });
const JobStep = z.strictObject({
  name: s, status: z.enum(["pending", "running", "done", "failed"]), note: ns.optional(),
});
export const ActionJob = z.strictObject({
  id: s, kind: z.enum(["research", "find_contacts"]), firm_id: s, lead_id: ns,
  status: z.enum(["queued", "running", "done", "failed"]), steps: z.array(JobStep), error: ns,
  created_at: s, started_at: ns, finished_at: ns,
});
const LeadCounts = z.strictObject({
  STRIKE: n, SEQUENCE: n, NURTURE: n, PHONE: n, EXCLUDED: n, UNSCORED: n,
});
export const LeadsResponse = z.strictObject({
  items: z.array(LeadRow), next_cursor: ns, counts: LeadCounts, stage_counts: z.record(s, n),
});
const LeadOutcome = z.strictObject({
  id: n, action: OutcomeAction, until: ns, note: ns, actor: s, at: s, transition_applied: z.boolean(),
});
export const LeadDetail = z.strictObject({
  ...leadRowShape,
  contacts: z.array(ContactSummary),
  missing_roles: z.array(z.enum(["owner", "admin"])),
  score: z.strictObject({
    fit_terms: z.array(z.strictObject({ label: s, points: n })),
    intent_terms: z.array(z.strictObject({ label: s, weight: n, decay: n, points: n })),
    note: s,
  }),
  exclusion_reasons: z.array(s),
  outcomes: z.array(LeadOutcome),
  timeline: z.array(
    z.strictObject({ from_state: ns, to_state: s, label: s, trigger: s, actor: s, at: s }),
  ),
  notes: z.array(LeadNote),
  job: ActionJob.nullable(),
});
export const DraftsResponse = z.strictObject({
  band: Band.nullable(),
  excluded_reason: ns,
  touches: z.array(
    z.strictObject({ step: n, day: n, subject: s, body: s, skipped_reason: ns }),
  ),
});
export const TodayResponse = z.strictObject({
  top_proof: LeadRow.nullable(),
  first_draft: z.strictObject({ subject: s, body: s }).nullable(),
  strike: z.array(LeadRow),
  attention: z.strictObject({
    alerts: z.array(
      z.strictObject({ name: s, label: s, state: z.enum(["ok", "firing", "no_data"]), detail: s }),
    ),
    queues: z.strictObject({ handcheck: n, conflicts: n, identity: n, agency: n, discovery: n }),
    bench: z.strictObject({ skus_available: n, stale: z.boolean(), message: s }),
    providers_inert: z.array(s),
  }),
});
export const FirmsResponse = z.strictObject({
  items: z.array(
    z.strictObject({
      id: s, name: s, domain: ns, city: ns, state: ns, tier_display: s, state_display: ns, fit: nn,
    }),
  ),
  next_cursor: ns,
  total: n,
});
const AttributeRow = z.strictObject({
  attr: s, label: s, display: s, state: z.enum(["resolved", "unknown", "conflict", "stale"]),
  source_label: ns, confidence: nn, evidence: ns, evidence_url: ns, observed_at: ns,
  claims: z.array(
    z.strictObject({ source_label: s, display: s, confidence: n, evidence: ns, observed_at: s, won: z.boolean() }),
  ),
});
export const FirmDetail = z.strictObject({
  firm: FirmRef,
  tier_reason: s,
  attributes: z.array(AttributeRow),
  documents: z.array(
    z.strictObject({ url: s, page_kind: ns, status_code: nn, words: nn, robots_decision: ns, fetched_at: s }),
  ),
  signals: z.array(Proof),
  contacts: z.array(ContactSummary),
  aliases: z.array(
    z.strictObject({ name: ns, domain: ns, phone: ns, merge_rule: ns, source_label: s }),
  ),
  lead: z.strictObject({ id: s, state_display: s, band: Band.nullable() }).nullable(),
});
export const HandcheckResponse = z.strictObject({
  gate: z.strictObject({ needed: n, reviewed_firms: n, passed: z.boolean(), rule: s }),
  accuracy: z.array(z.strictObject({ attr: s, label: s, checked: n, correct: n })),
  sample: z.array(
    z.strictObject({
      firm_id: s, name: s, domain: ns, attributes: z.array(AttributeRow),
      reviews: z.record(s, z.strictObject({ correct: z.boolean(), corrected_value: ns })),
    }),
  ),
});
export const HealthResponse = z.strictObject({ db: z.enum(["ok", "down"]), version: s });
const Attention = TodayResponse.shape.attention;
export const OverviewResponse = z.strictObject({
  steps: z.array(
    z.strictObject({
      key: z.enum(["lists", "research", "qualify", "people", "outreach"]), number: n, label: s,
      what: s, count: n, count_label: s, detail: s, href: s,
    }),
  ),
  stages: z.array(z.strictObject({ stage: Stage, label: s, help: s, count: n })),
  running: z.array(
    z.strictObject({
      id: s, kind: z.enum(["research", "find_contacts"]),
      status: z.enum(["queued", "running", "done", "failed"]), firm_id: s, firm_name: s,
      done_steps: n, total_steps: n, started_at: ns,
    }),
  ),
  last_runs: z.array(z.strictObject({ component: s, label: s, finished_at: s, processed: n, failed: n })),
  lists: z.strictObject({ count: n, rows: n, latest_file: ns, latest_status: ns, latest_at: ns }),
  attention: Attention,
});

// ── Compile-time pins: each schema's type IS the contract type. ─────────────
type Equals<A, B> = (<X>() => X extends A ? 1 : 2) extends <X>() => X extends B ? 1 : 2 ? true : false;
export const pins: [
  Equals<z.infer<typeof FirmRef>, T.FirmRef>,
  Equals<z.infer<typeof Proof>, T.Proof>,
  Equals<z.infer<typeof ContactSummary>, T.ContactSummary>,
  Equals<z.infer<typeof LeadRow>, T.LeadRow>,
  Equals<z.infer<typeof LeadsResponse>, T.LeadsResponse>,
  Equals<z.infer<typeof LeadDetail>, T.LeadDetail>,
  Equals<z.infer<typeof DraftsResponse>, T.DraftsResponse>,
  Equals<z.infer<typeof TodayResponse>, T.TodayResponse>,
  Equals<z.infer<typeof FirmsResponse>, T.FirmsResponse>,
  Equals<z.infer<typeof FirmDetail>, T.FirmDetail>,
  Equals<z.infer<typeof HandcheckResponse>, T.HandcheckResponse>,
  Equals<z.infer<typeof HealthResponse>, T.HealthResponse>,
  Equals<z.infer<typeof OverviewResponse>, T.OverviewResponse>,
] = [true, true, true, true, true, true, true, true, true, true, true, true, true];
