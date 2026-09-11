/**
 * Opt-in contract check against the running engine:
 *
 *   LGE_LIVE_API=http://127.0.0.1:8000 npm run test
 *
 * Every read endpoint the UI uses is fetched and parsed with the same strict,
 * type-pinned schemas the fixtures are held to. Skipped when the variable is
 * unset, so the normal suite never needs the engine. Read-only: it never
 * records an outcome or a hand-check verdict.
 */
import { describe, expect, it } from "vitest";

import {
  DraftsResponse,
  FirmDetail,
  FirmsResponse,
  HandcheckResponse,
  HealthResponse,
  LeadDetail,
  LeadsResponse,
  TodayResponse,
} from "@/test/contract-schemas";
import { createApi } from "./client";
import { httpTransport } from "./transport";
import type { LeadView } from "./types";

const base = process.env.LGE_LIVE_API;
const VIEWS: LeadView[] = ["STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED", "UNSCORED"];

describe.skipIf(!base)("live engine matches the contract", () => {
  const api = createApi(httpTransport(base ?? ""));

  it("GET /api/health", async () => {
    expect(HealthResponse.parse(await api.health()).db).toBe("ok");
  });

  it("GET /api/today", async () => {
    TodayResponse.parse(await api.today());
  });

  it("GET /api/leads for every view, and one case file with its drafts", async () => {
    let sampled: string | undefined;
    for (const view of VIEWS) {
      const res = LeadsResponse.parse(await api.leads({ view, limit: 5 }));
      sampled ??= res.items[0]?.id;
    }
    if (sampled) {
      LeadDetail.parse(await api.lead(sampled));
      DraftsResponse.parse(await api.drafts(sampled));
    }
  });

  it("GET /api/firms and one firm record", async () => {
    const firms = FirmsResponse.parse(await api.firms({ limit: 5 }));
    if (firms.items[0]) FirmDetail.parse(await api.firm(firms.items[0].id));
  });

  it("GET /api/handcheck", async () => {
    HandcheckResponse.parse(await api.handcheck());
  });

  it("answers an unknown lead with the error envelope", async () => {
    // A well-formed id. (A malformed one currently answers 500 internal_error
    // instead of 404 — reported to the backend.)
    await expect(api.lead("00000000-0000-0000-0000-000000000000")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "not_found",
    });
  });
});
