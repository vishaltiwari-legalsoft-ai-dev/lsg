/**
 * DEV ONLY. An in-memory stand-in for the engine, serving src/fixtures/*.json
 * when NEXT_PUBLIC_API_MODE=fixtures. It is loaded with a dynamic import, so
 * the api-mode bundle never downloads it.
 *
 * It filters, pages and records outcomes so the UI can be exercised end to
 * end before the API is live. The real API owns every one of those rules;
 * nothing here is a source of truth.
 */
import draftsJson from "@/fixtures/drafts.json";
import firmDetailsJson from "@/fixtures/firm-details.json";
import firmsJson from "@/fixtures/firms.json";
import handcheckJson from "@/fixtures/handcheck.json";
import healthJson from "@/fixtures/health.json";
import leadDetailsJson from "@/fixtures/lead-details.json";
import leadsJson from "@/fixtures/leads.json";
import todayJson from "@/fixtures/today.json";

import { ApiError } from "./errors";
import type { RequestSpec, Transport } from "./transport";
import type {
  ActionJob,
  BatchRequest,
  BatchResponse,
  ContactCreate,
  ContactPatch,
  ContactResponse,
  ContactSummary,
  DecisionRequest,
  DecisionResponse,
  DraftsResponse,
  FirmDetail,
  FirmsResponse,
  HandcheckDecision,
  HandcheckResponse,
  HealthResponse,
  JobResponse,
  LeadCounts,
  LeadDetail,
  LeadRow,
  LeadsResponse,
  LeadView,
  OutcomeRequest,
  OutcomeResponse,
  OverviewResponse,
  TodayResponse,
} from "./types";

interface FixtureDb {
  health: HealthResponse;
  today: TodayResponse;
  leads: Record<LeadView, LeadsResponse>;
  leadDetails: Record<string, LeadDetail>;
  drafts: Record<string, DraftsResponse>;
  firms: FirmsResponse;
  firmDetails: Record<string, FirmDetail>;
  handcheck: HandcheckResponse;
}

const VIEWS: LeadView[] = ["STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED", "UNSCORED"];

/** Small pages so "Load more" is exercised with a handful of fixtures. */
export const FIXTURE_PAGE_LIMIT = 4;

function loadDb(): FixtureDb {
  // JSON imports widen literal unions to `string`; src/fixtures/fixtures.test.ts
  // parses every file against the contract, which is what backs this cast.
  return structuredClone({
    health: healthJson,
    today: todayJson,
    leads: leadsJson,
    leadDetails: leadDetailsJson,
    drafts: draftsJson,
    firms: firmsJson,
    firmDetails: firmDetailsJson,
    handcheck: handcheckJson,
  }) as unknown as FixtureDb;
}

const notFound = (what: string) =>
  new ApiError(404, "not_found", `${what} not found.`, "Check the id.");

const delay = (ms: number) =>
  ms > 0 ? new Promise<void>((resolve) => setTimeout(resolve, ms)) : Promise.resolve();

function param(spec: RequestSpec, key: string): string | undefined {
  const value = spec.query?.[key];
  return value === undefined || value === null || value === "" ? undefined : String(value);
}

function page<T>(items: T[], spec: RequestSpec, cap: number) {
  const offset = Number(param(spec, "cursor") ?? 0) || 0;
  const limit = Math.min(Number(param(spec, "limit") ?? cap) || cap, cap);
  const slice = items.slice(offset, offset + limit);
  const next = offset + limit < items.length ? String(offset + limit) : null;
  return { slice, next };
}

function matchesLead(row: LeadRow, spec: RequestSpec): boolean {
  const q = param(spec, "q")?.toLowerCase();
  const tier = param(spec, "tier");
  const city = param(spec, "city")?.toLowerCase();
  const signal = param(spec, "signal");
  const contest = param(spec, "contest");
  const verified = param(spec, "verified");
  if (q && !`${row.firm.name} ${row.firm.domain ?? ""}`.toLowerCase().includes(q)) return false;
  if (tier && row.firm.tier !== tier) return false;
  if (city && !(row.firm.city ?? "").toLowerCase().includes(city)) return false;
  if (signal && row.proof?.kind !== signal) return false;
  if (contest && row.contest !== contest) return false;
  if (verified !== undefined) {
    const isVerified = row.contact?.email_status === "valid";
    if ((verified === "true") !== isVerified) return false;
  }
  return true;
}

function toRow(detail: LeadDetail): LeadRow {
  return {
    id: detail.id,
    firm: detail.firm,
    state: detail.state,
    state_display: detail.state_display,
    band: detail.band,
    fit: detail.fit,
    intent: detail.intent,
    contest: detail.contest,
    grade: detail.grade,
    proof: detail.proof,
    contact: detail.contact,
    scored_at: detail.scored_at,
    blockers: detail.blockers,
    stage: detail.stage,
    stage_display: detail.stage_display,
    next_action: detail.next_action,
    owner: detail.owner,
  };
}

const STAGE_DISPLAY: Record<LeadRow["stage"], string> = {
  researching: "Researching", no_website: "No website", needs_review: "Needs a decision",
  needs_contact: "Needs a person", ready: "Ready to reach", parked: "Parked",
  in_outreach: "In outreach", replied: "Replied", handed_off: "Handed off", won: "Won",
  lost: "Lost", disqualified: "Disqualified", do_not_contact: "Do not contact",
  needs_refresh: "Needs a refresh",
};

function setStage(lead: LeadDetail, stage: LeadRow["stage"], next: string, state?: string) {
  lead.stage = stage;
  lead.stage_display = STAGE_DISPLAY[stage];
  lead.next_action = next;
  if (state) {
    lead.state = state;
    lead.state_display = STAGE_DISPLAY[stage];
  }
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const formatDay = (isoDate: string) => {
  const d = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};

const OUTCOME_PAST: Record<OutcomeRequest["action"], string> = {
  sent: "sent",
  replied: "replied",
  meeting: "meeting booked",
  won: "won",
  lost: "lost",
  not_now: "not now",
  opt_out: "opted out",
};

function csvCell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export interface FixtureServer extends Transport {
  reset(): void;
}

export function createFixtureServer({ latencyMs = 0 }: { latencyMs?: number } = {}): FixtureServer {
  let db = loadDb();
  const jobs = new Map<string, ActionJob>();

  function counts(spec: RequestSpec): LeadCounts {
    return Object.fromEntries(
      VIEWS.map((view) => [view, db.leads[view].items.filter((row) => matchesLead(row, spec)).length]),
    ) as LeadCounts;
  }

  function stageCounts(): Record<string, number> {
    const out: Record<string, number> = Object.fromEntries(Object.keys(STAGE_DISPLAY).map((k) => [k, 0]));
    for (const d of Object.values(db.leadDetails)) out[d.stage] = (out[d.stage] ?? 0) + 1;
    return out;
  }

  function replaceRow(detail: LeadDetail, moveTo?: LeadView) {
    const row = toRow(detail);
    for (const view of VIEWS) {
      const items = db.leads[view].items;
      const index = items.findIndex((r) => r.id === row.id);
      if (index === -1) continue;
      if (moveTo && moveTo !== view) items.splice(index, 1);
      else items[index] = row;
    }
    if (moveTo && !db.leads[moveTo].items.some((r) => r.id === row.id)) {
      db.leads[moveTo].items.unshift(row);
    }
    if (db.today.top_proof?.id === row.id) db.today.top_proof = row;
    db.today.strike = db.today.strike.map((r) => (r.id === row.id ? row : r));
  }

  function recordOutcome(leadId: string, request: OutcomeRequest): OutcomeResponse {
    const lead = db.leadDetails[leadId];
    if (!lead) throw notFound("Lead");
    if (request.action === "not_now" && !request.until) {
      throw new ApiError(422, "until_required", "Not now needs a date.", "Pick the date to revisit this lead.");
    }

    const at = new Date().toISOString();
    let transition = false;
    let message: string;
    let moveTo: LeadView | undefined;

    if (request.action === "opt_out") {
      transition = true;
      lead.state = "SUPPRESSED";
      lead.state_display = "Suppressed — opted out";
      lead.exclusion_reasons = [
        ...lead.exclusion_reasons,
        `Opted out: ${lead.firm.domain ?? "the firm"} is suppressed.`,
      ];
      moveTo = "EXCLUDED";
      message = `Opted out. ${lead.firm.domain ?? "The firm"} is suppressed for good; only an admin can reverse it.`;
    } else if (request.action === "not_now") {
      transition = true;
      lead.state = "COOLDOWN";
      lead.state_display = `Not now — revisit on ${formatDay(request.until!)}`;
      message = `Marked as not now until ${formatDay(request.until!)}. The lead stays quiet until then.`;
    } else {
      message =
        `Marked as ${OUTCOME_PAST[request.action]}. Recorded for attribution; ` +
        "the lead's state didn't change because it can't be armed while the bench is empty.";
    }

    lead.outcomes = [
      ...lead.outcomes,
      {
        id: (lead.outcomes.at(-1)?.id ?? 0) + 1,
        action: request.action,
        until: request.until ?? null,
        note: request.note ?? null,
        actor: "You",
        at,
        transition_applied: transition,
      },
    ];
    if (transition) {
      lead.timeline = [
        ...lead.timeline,
        {
          from_state: lead.timeline.at(-1)?.to_state ?? null,
          to_state: lead.state,
          label: lead.state_display,
          trigger: `Outcome: ${OUTCOME_PAST[request.action]}`,
          actor: "You",
          at,
        },
      ];
    }
    replaceRow(lead, moveTo);
    return { lead: structuredClone(lead), transition_applied: transition, message };
  }

  function recomputeHandcheck() {
    const hc = db.handcheck;
    const order: { attr: string; label: string }[] = [];
    for (const firm of hc.sample) {
      for (const a of firm.attributes) {
        if (!order.some((o) => o.attr === a.attr)) order.push({ attr: a.attr, label: a.label });
      }
    }
    hc.accuracy = order.map(({ attr, label }) => {
      const reviews = hc.sample.map((f) => f.reviews[attr]).filter(Boolean);
      return { attr, label, checked: reviews.length, correct: reviews.filter((r) => r.correct).length };
    });
    hc.gate.reviewed_firms = hc.sample.filter((f) =>
      f.attributes.every((a) => f.reviews[a.attr] !== undefined),
    ).length;
    hc.gate.passed =
      hc.gate.reviewed_firms >= hc.gate.needed &&
      hc.accuracy.every((a) => a.checked > 0 && a.correct / a.checked >= 0.95);
  }

  function exportCsv(spec: RequestSpec): string {
    const view = (param(spec, "view") ?? "STRIKE") as LeadView;
    const rows = (db.leads[view]?.items ?? [])
      .filter((row) => matchesLead(row, spec))
      // Grade B never reaches an email export; the phone list is its own file.
      .filter((row) => (view === "PHONE" ? true : row.grade !== "B"));
    const header = ["firm", "domain", "city", "state", "tier", "contact", "title", "email", "email_status", "phone", "proof"];
    const lines = rows.map((row) =>
      [
        row.firm.name,
        row.firm.domain,
        row.firm.city,
        row.firm.state,
        row.firm.tier_display,
        row.contact?.full_name,
        row.contact?.title,
        view === "PHONE" ? null : row.contact?.email,
        view === "PHONE" ? null : row.contact?.email_status_display,
        row.contact?.phone,
        row.proof?.headline,
      ]
        .map(csvCell)
        .join(","),
    );
    return [header.join(","), ...lines].join("\n") + "\n";
  }

  function handle(spec: RequestSpec): unknown {
    const { method, path } = spec;
    let m: RegExpMatchArray | null;

    if (method === "GET" && path === "/api/health") return db.health;
    if (method === "GET" && path === "/api/today") return db.today;
    // Imports need a real engine (files land on its disk); the fixture has none.
    if (method === "GET" && path === "/api/imports") return { items: [] };

    if (method === "GET" && path === "/api/leads") {
      const stage = param(spec, "stage");
      if (stage) {
        const band = param(spec, "band");
        const all = Object.values(db.leadDetails).map(toRow);
        const rows = all.filter(
          (row) => row.stage === stage && (!band || row.band === band) && matchesLead(row, spec),
        );
        const { slice, next } = page(rows, spec, FIXTURE_PAGE_LIMIT);
        return { items: slice, next_cursor: next, counts: counts(spec), stage_counts: stageCounts() } satisfies LeadsResponse;
      }
      const view = (param(spec, "view") ?? "STRIKE") as LeadView;
      const source = db.leads[view];
      if (!source) throw new ApiError(422, "bad_view", `There is no ${view} view.`, "Use one of the band tabs.");
      const { slice, next } = page(source.items.filter((row) => matchesLead(row, spec)), spec, FIXTURE_PAGE_LIMIT);
      return { items: slice, next_cursor: next, counts: counts(spec), stage_counts: stageCounts() } satisfies LeadsResponse;
    }

    if (method === "GET" && path === "/api/overview") {
      const details = Object.values(db.leadDetails);
      const stages = stageCounts();
      const firms = db.firms.total;
      const withEmail = details.filter((d) => d.contact?.email).length;
      const step = (key: OverviewResponse["steps"][number]["key"], number: number, label: string, what: string, count: number, count_label: string, detail: string, href: string) =>
        ({ key, number, label, what, count, count_label, detail, href });
      return {
        steps: [
          step("lists", 1, "Lists", "A sheet in any layout comes in; every website on it is checked, and searched for when it is wrong.", firms, "firms on file", `${firms} websites verified, 0 behind a bot wall`, "/imports"),
          step("research", 2, "Research", "Each site is read end to end: who works there, offices, fee model, practice, testimonials, news, and what the site lacks.", details.length, "firms researched", `${details.length * 24} pages read`, "/firms"),
          step("qualify", 3, "Qualify", "Fit from the record (fee model, practice, size); urgency from pain -- open roles, no support staff, no intake, reviews about unreturned calls.", details.length, "firms tiered", `${details.filter((d) => d.firm.tier === "1A").length} tier 1A; ${stages.needs_review ?? 0} waiting for a decision`, "/leads?stage=needs_review"),
          step("people", 4, "People", "The owner or office manager, with an address from the site, a search, or the firm's own pattern, and a LinkedIn profile.", details.reduce((n, d) => n + d.contacts.length, 0), "people named", `${withEmail} firms with a decision-maker's address; 3 LinkedIn profiles`, "/leads?stage=needs_contact"),
          step("outreach", 5, "Outreach", "Nine touches drafted from the proof; outcomes recorded; a lead that does not convert returns to the pool with its contact intact.", (stages.ready ?? 0) + (stages.in_outreach ?? 0) + (stages.replied ?? 0), "leads in play", `${stages.ready ?? 0} ready to reach, ${stages.in_outreach ?? 0} in outreach, ${stages.replied ?? 0} replied`, "/leads?stage=ready"),
        ],
        stages: (Object.keys(STAGE_DISPLAY) as LeadRow["stage"][]).map((stage) => ({
          stage, label: STAGE_DISPLAY[stage], help: "", count: stages[stage] ?? 0,
        })),
        running: [],
        last_runs: [
          { component: "score", label: "Scored", finished_at: new Date().toISOString(), processed: details.length, failed: 0 },
        ],
        lists: { count: 1, rows: firms, latest_file: "firms-sample.csv", latest_status: "loaded", latest_at: new Date().toISOString() },
        attention: db.today.attention,
      } satisfies OverviewResponse;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)$/)) && method === "GET") {
      const lead = db.leadDetails[decodeURIComponent(m[1])];
      if (!lead) throw notFound("Lead");
      return lead;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)\/drafts$/)) && method === "GET") {
      const drafts = db.drafts[decodeURIComponent(m[1])];
      if (!drafts) throw notFound("Lead");
      return drafts;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)\/outcome$/)) && method === "POST") {
      return recordOutcome(decodeURIComponent(m[1]), spec.body as OutcomeRequest);
    }

    // ── Actions (a stand-in: the real rules live in the engine) ─────────────
    if ((m = path.match(/^\/api\/firms\/([^/]+)\/research$/)) && method === "POST") {
      const firmId = decodeURIComponent(m[1]);
      const scope = (spec.body as { scope?: string })?.scope ?? "full";
      const steps = (scope === "full"
        ? ["p1_site_map", "p2_fetch", "px_site_facts", "r_site_contacts", "r_search_emails", "score"]
        : ["px_site_facts", "r_site_contacts", "r_search_emails", "score"]
      ).map((name) => ({ name, status: "done" as const, note: "processed=1 skipped=0 failed=0" }));
      const now = new Date().toISOString();
      const job: ActionJob = {
        id: `job-${jobs.size + 1}`, kind: scope === "full" ? "research" : "find_contacts",
        firm_id: firmId, lead_id: null, status: "done", steps, error: null,
        created_at: now, started_at: now, finished_at: now,
      };
      jobs.set(job.id, job);
      for (const lead of Object.values(db.leadDetails)) if (lead.firm.id === firmId) lead.job = job;
      return { job } satisfies JobResponse;
    }

    if ((m = path.match(/^\/api\/jobs\/([^/]+)$/)) && method === "GET") {
      const job = jobs.get(decodeURIComponent(m[1]));
      if (!job) throw notFound("Job");
      return { job } satisfies JobResponse;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)\/decision$/)) && method === "POST") {
      const lead = db.leadDetails[decodeURIComponent(m[1])];
      if (!lead) throw notFound("Lead");
      const body = spec.body as DecisionRequest;
      const why = body.reason ? ` -- ${body.reason}` : "";
      let message: string;
      if (body.action === "disqualify") {
        setStage(lead, "disqualified", "Reopen if the reason was wrong", "DISQUALIFIED");
        message = "Disqualified.";
      } else if (body.action === "qualify") {
        setStage(lead, lead.contact?.email ? "ready" : "needs_contact",
          lead.contact?.email ? "Send touch 1 when a signal arms it, or hand off now" : "Find a decision-maker",
          "QUALIFIED_B");
        message = "Qualified (grade B -- no verified email yet; phone and LinkedIn only).";
      } else if (body.action === "hold") {
        if (!body.until) throw new ApiError(400, "bad_request", "`until` is required to hold a lead.", null);
        setStage(lead, "parked", `Parked until ${body.until}`);
        message = `Parked until ${body.until}.`;
      } else if (body.action === "handoff") {
        setStage(lead, "handed_off", "Sales owns it -- record won or lost", "HANDOFF");
        message = "Handed off to sales.";
      } else {
        setStage(lead, "needs_review", "Review the record; qualify or disqualify", "CLASSIFIED");
        message = "Reopened -- back to needing a decision.";
      }
      lead.notes = [{ id: (lead.notes[0]?.id ?? 0) + 1, text: `${message.replace(/\.$/, "")}${why}`, actor: "You", at: new Date().toISOString() }, ...lead.notes];
      replaceRow(lead);
      return { lead: structuredClone(lead), message } satisfies DecisionResponse;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)\/notes$/)) && method === "POST") {
      const lead = db.leadDetails[decodeURIComponent(m[1])];
      if (!lead) throw notFound("Lead");
      const text = (spec.body as { text: string }).text.trim();
      lead.notes = [{ id: (lead.notes[0]?.id ?? 0) + 1, text, actor: "You", at: new Date().toISOString() }, ...lead.notes];
      return lead;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)\/owner$/)) && method === "PUT") {
      const lead = db.leadDetails[decodeURIComponent(m[1])];
      if (!lead) throw notFound("Lead");
      lead.owner = (spec.body as { owner: string | null }).owner || null;
      replaceRow(lead);
      return lead;
    }

    if ((m = path.match(/^\/api\/leads\/([^/]+)\/contact$/)) && method === "PUT") {
      const lead = db.leadDetails[decodeURIComponent(m[1])];
      if (!lead) throw notFound("Lead");
      const contact = lead.contacts.find((c) => c.id === (spec.body as { contact_id: string }).contact_id);
      if (!contact) throw new ApiError(400, "bad_request", "That contact is not at this firm.", null);
      lead.contact = contact;
      replaceRow(lead);
      return lead;
    }

    if ((m = path.match(/^\/api\/firms\/([^/]+)\/contacts$/)) && method === "POST") {
      const firmId = decodeURIComponent(m[1]);
      const body = spec.body as ContactCreate;
      const contact: ContactSummary = {
        id: `contact-${Date.now()}`, full_name: body.full_name.trim(), title: body.title ?? null,
        role: body.role ?? "unknown", source_label: "Added by hand", email: body.email?.toLowerCase() ?? null,
        email_status: body.email ? "unverified" : null,
        email_status_display: body.email ? "Not verified yet" : null, phone: body.phone ?? null,
        linkedin_url: body.linkedin_url ?? null, linkedin_headline: null,
      };
      for (const lead of Object.values(db.leadDetails)) if (lead.firm.id === firmId) lead.contacts.push(contact);
      return { contact } satisfies ContactResponse;
    }

    if ((m = path.match(/^\/api\/contacts\/([^/]+)$/)) && method === "PATCH") {
      const id = decodeURIComponent(m[1]);
      const body = spec.body as ContactPatch;
      let found: ContactSummary | undefined;
      for (const lead of Object.values(db.leadDetails)) {
        const contact = lead.contacts.find((c) => c.id === id);
        if (!contact) continue;
        if (body.full_name != null) contact.full_name = body.full_name.trim();
        if (body.title != null) contact.title = body.title || null;
        if (body.role != null) contact.role = body.role;
        if (body.phone != null) contact.phone = body.phone || null;
        if (body.linkedin_url != null) contact.linkedin_url = body.linkedin_url || null;
        if (body.email) {
          contact.email = body.email.toLowerCase();
          contact.email_status = "unverified";
          contact.email_status_display = "Not verified yet";
        }
        found = contact;
        if (lead.contact?.id === id) lead.contact = contact;
      }
      if (!found) throw notFound("Contact");
      return { contact: found } satisfies ContactResponse;
    }

    if ((m = path.match(/^\/api\/contacts\/([^/]+)\/remove$/)) && method === "POST") {
      const id = decodeURIComponent(m[1]);
      let found: ContactSummary | undefined;
      for (const lead of Object.values(db.leadDetails)) {
        const contact = lead.contacts.find((c) => c.id === id);
        if (!contact) continue;
        found = contact;
        lead.contacts = lead.contacts.filter((c) => c.id !== id);
        if (lead.contact?.id === id) lead.contact = null;
        replaceRow(lead);
      }
      if (!found) throw notFound("Contact");
      return { contact: found } satisfies ContactResponse;
    }

    if (method === "POST" && path === "/api/leads/batch") {
      const body = spec.body as BatchRequest;
      const results = body.lead_ids.map((leadId) => {
        const lead = db.leadDetails[leadId];
        if (!lead) return { lead_id: leadId, ok: false, message: "Lead not found.", job_id: null };
        if (body.action === "assign") {
          lead.owner = body.owner || null;
          replaceRow(lead);
          return { lead_id: leadId, ok: true, message: "Assigned.", job_id: null };
        }
        if (body.action === "research" || body.action === "find_contacts") {
          return { lead_id: leadId, ok: true, message: "Job done.", job_id: `job-fixture-${leadId}` };
        }
        const response = handle({
          method: "POST", path: `/api/leads/${encodeURIComponent(leadId)}/decision`,
          body: { action: body.action, reason: body.reason ?? null, until: body.until ?? null },
        }) as DecisionResponse;
        return { lead_id: leadId, ok: true, message: response.message, job_id: null };
      });
      return { results } satisfies BatchResponse;
    }

    if (method === "GET" && path === "/api/firms") {
      const q = param(spec, "q")?.toLowerCase();
      const tier = param(spec, "tier");
      const items = db.firms.items.filter(
        (firm) =>
          (!q || `${firm.name} ${firm.domain ?? ""}`.toLowerCase().includes(q)) &&
          (!tier || firm.tier_display === `Tier ${tier}`),
      );
      const { slice, next } = page(items, spec, 50);
      return { items: slice, next_cursor: next, total: items.length } satisfies FirmsResponse;
    }

    if ((m = path.match(/^\/api\/firms\/([^/]+)$/)) && method === "GET") {
      const firm = db.firmDetails[decodeURIComponent(m[1])];
      if (!firm) throw notFound("Firm");
      return firm;
    }

    if (method === "GET" && path === "/api/handcheck") return db.handcheck;

    if ((m = path.match(/^\/api\/handcheck\/([^/]+)\/([^/]+)$/)) && method === "POST") {
      const firm = db.handcheck.sample.find((f) => f.firm_id === decodeURIComponent(m![1]));
      if (!firm) throw notFound("Hand-check firm");
      const attr = decodeURIComponent(m[2]);
      const decision = spec.body as HandcheckDecision;
      firm.reviews[attr] = {
        correct: decision.correct,
        corrected_value: decision.correct ? null : (decision.corrected_value ?? null),
      };
      recomputeHandcheck();
      return undefined;
    }

    throw new ApiError(404, "not_found", `No fixture for ${method} ${path}.`, "Add it to the fixture server.");
  }

  return {
    async json<T>(spec: RequestSpec): Promise<T> {
      await delay(latencyMs);
      // Hand back copies so callers can't mutate the fixture database.
      const result = handle(spec);
      return (result === undefined ? undefined : structuredClone(result)) as T;
    },
    async text(spec: RequestSpec): Promise<string> {
      await delay(latencyMs);
      if (spec.path === "/api/leads/export.csv") return exportCsv(spec);
      throw new ApiError(404, "not_found", `No fixture for ${spec.path}.`, "Add it to the fixture server.");
    },
    reset() {
      db = loadDb();
      jobs.clear();
    },
  };
}

let shared: FixtureServer | null = null;

/** The one fixture database the browser session talks to. */
export function getFixtureServer(): FixtureServer {
  shared ??= createFixtureServer({ latencyMs: 160 });
  return shared;
}
