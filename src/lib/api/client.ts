import { API_BASE, API_MODE } from "./config";
import { httpTransport, type Transport } from "./transport";
import type {
  DraftsResponse,
  FirmDetail,
  FirmsQuery,
  FirmsResponse,
  HandcheckDecision,
  HandcheckResponse,
  HealthResponse,
  LeadDetail,
  LeadsQuery,
  LeadsResponse,
  LeadView,
  OutcomeRequest,
  OutcomeResponse,
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
