import { API_BASE, API_MODE } from "./config";
import { httpTransport, type Transport } from "./transport";
import type {
  BatchRequest,
  BatchResponse,
  ContactCreate,
  ContactPatch,
  ContactResponse,
  DecisionRequest,
  DecisionResponse,
  DraftsResponse,
  FirmDetail,
  JobResponse,
  JobsResponse,
  FirmsQuery,
  FirmsResponse,
  HandcheckDecision,
  HandcheckResponse,
  HealthResponse,
  ImportDetail,
  ImportLoadResponse,
  ImportsResponse,
  LeadDetail,
  LeadsQuery,
  LeadsResponse,
  LeadView,
  MappingRequest,
  OutcomeRequest,
  OutcomeResponse,
  OverviewResponse,
  QualifiedQuery,
  QualifiedResponse,
  TodayResponse,
} from "./types";

const enc = encodeURIComponent;

/** One typed function per endpoint in api-contract.md. */
export function createApi(transport: Transport) {
  return {
    health: (signal?: AbortSignal) =>
      transport.json<HealthResponse>({ method: "GET", path: "/api/health", signal }),

    today: (signal?: AbortSignal) =>
      transport.json<TodayResponse>({ method: "GET", path: "/api/today", signal }),

    overview: (signal?: AbortSignal) =>
      transport.json<OverviewResponse>({ method: "GET", path: "/api/overview", signal }),

    qualified: (query: QualifiedQuery, signal?: AbortSignal) =>
      transport.json<QualifiedResponse>({
        method: "GET",
        path: "/api/qualified",
        query: { ...query },
        signal,
      }),

    exportQualifiedCsv: () =>
      transport.text({ method: "GET", path: "/api/qualified/export.csv" }),

    leads: (query: LeadsQuery, signal?: AbortSignal) =>
      transport.json<LeadsResponse>({
        method: "GET",
        path: "/api/leads",
        query: { ...query },
        signal,
      }),

    lead: (id: string, signal?: AbortSignal) =>
      transport.json<LeadDetail>({ method: "GET", path: `/api/leads/${enc(id)}`, signal }),

    drafts: (id: string, signal?: AbortSignal) =>
      transport.json<DraftsResponse>({
        method: "GET",
        path: `/api/leads/${enc(id)}/drafts`,
        signal,
      }),

    recordOutcome: (id: string, body: OutcomeRequest) =>
      transport.json<OutcomeResponse>({
        method: "POST",
        path: `/api/leads/${enc(id)}/outcome`,
        body,
      }),

    /** Runs build_list on the engine, so list hygiene applies at export time. */
    exportLeadsCsv: (view: LeadView, filters: Omit<LeadsQuery, "view" | "cursor" | "limit"> = {}) =>
      transport.text({
        method: "GET",
        path: "/api/leads/export.csv",
        query: { view, ...filters },
      }),

    firms: (query: FirmsQuery, signal?: AbortSignal) =>
      transport.json<FirmsResponse>({
        method: "GET",
        path: "/api/firms",
        query: { ...query },
        signal,
      }),

    firm: (id: string, signal?: AbortSignal) =>
      transport.json<FirmDetail>({ method: "GET", path: `/api/firms/${enc(id)}`, signal }),

    handcheck: (signal?: AbortSignal) =>
      transport.json<HandcheckResponse>({ method: "GET", path: "/api/handcheck", signal }),

    decideHandcheck: (firmId: string, attr: string, decision: HandcheckDecision) =>
      transport.json<void>({
        method: "POST",
        path: `/api/handcheck/${enc(firmId)}/${enc(attr)}`,
        body: decision,
      }),

    // ── Imports: any sheet, read, corrected, loaded in batches ────────────
    imports: (signal?: AbortSignal) =>
      transport.json<ImportsResponse>({ method: "GET", path: "/api/imports", signal }),

    importDetail: (id: string, signal?: AbortSignal) =>
      transport.json<ImportDetail>({ method: "GET", path: `/api/imports/${enc(id)}`, signal }),

    uploadImport: (file: File, batchSize: number) => {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("batch_size", String(batchSize));
      return transport.json<ImportDetail>({ method: "POST", path: "/api/imports", form });
    },

    updateImportMapping: (id: string, body: MappingRequest) =>
      transport.json<ImportDetail>({
        method: "PUT",
        path: `/api/imports/${enc(id)}/mapping`,
        body,
      }),

    startImportLoad: (id: string) =>
      transport.json<ImportLoadResponse>({
        method: "POST",
        path: `/api/imports/${enc(id)}/load`,
      }),

    // ── Actions: the user can act ────────────────────────────────────────
    research: (firmId: string, scope: "full" | "contacts") =>
      transport.json<JobResponse>({
        method: "POST",
        path: `/api/firms/${enc(firmId)}/research`,
        body: { scope },
      }),

    job: (id: string, signal?: AbortSignal) =>
      transport.json<JobResponse>({ method: "GET", path: `/api/jobs/${enc(id)}`, signal }),

    firmJobs: (firmId: string, signal?: AbortSignal) =>
      transport.json<JobsResponse>({
        method: "GET",
        path: `/api/firms/${enc(firmId)}/jobs`,
        query: { limit: 3 },
        signal,
      }),

    addContact: (firmId: string, body: ContactCreate) =>
      transport.json<ContactResponse>({
        method: "POST",
        path: `/api/firms/${enc(firmId)}/contacts`,
        body,
      }),

    patchContact: (contactId: string, body: ContactPatch) =>
      transport.json<ContactResponse>({
        method: "PATCH",
        path: `/api/contacts/${enc(contactId)}`,
        body,
      }),

    removeContact: (contactId: string, reason?: string) =>
      transport.json<ContactResponse>({
        method: "POST",
        path: `/api/contacts/${enc(contactId)}/remove`,
        body: { reason: reason ?? null },
      }),

    setPrimaryContact: (leadId: string, contactId: string) =>
      transport.json<LeadDetail>({
        method: "PUT",
        path: `/api/leads/${enc(leadId)}/contact`,
        body: { contact_id: contactId },
      }),

    decide: (leadId: string, body: DecisionRequest) =>
      transport.json<DecisionResponse>({
        method: "POST",
        path: `/api/leads/${enc(leadId)}/decision`,
        body,
      }),

    addNote: (leadId: string, text: string) =>
      transport.json<LeadDetail>({
        method: "POST",
        path: `/api/leads/${enc(leadId)}/notes`,
        body: { text },
      }),

    setOwner: (leadId: string, owner: string | null) =>
      transport.json<LeadDetail>({
        method: "PUT",
        path: `/api/leads/${enc(leadId)}/owner`,
        body: { owner },
      }),

    batch: (body: BatchRequest) =>
      transport.json<BatchResponse>({ method: "POST", path: "/api/leads/batch", body }),
  };
}

export type Api = ReturnType<typeof createApi>;

/*
 * Fixture mode: the fixture server is fetched lazily, only when used. The
 * import sits behind the build-time constant itself, so an api-mode build
 * drops it and ships no fixture data at all.
 */
const loadFixtureServer =
  process.env.NEXT_PUBLIC_API_MODE === "fixtures"
    ? () => import("./fixture-server").then((m) => m.getFixtureServer())
    : null;

function fixtureTransport(load: NonNullable<typeof loadFixtureServer>): Transport {
  return {
    json: async (spec) => (await load()).json(spec),
    text: async (spec) => (await load()).text(spec),
  };
}

export const api: Api = createApi(
  API_MODE === "fixtures" && loadFixtureServer
    ? fixtureTransport(loadFixtureServer)
    : httpTransport(API_BASE),
);
