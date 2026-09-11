/**
 * Fixtures must match the contract exactly: every file is parsed with the
 * strict, type-pinned schemas in src/test/contract-schemas.ts.
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
  pins,
  TodayResponse,
} from "@/test/contract-schemas";
import drafts from "./drafts.json";
import firmDetails from "./firm-details.json";
import firms from "./firms.json";
import handcheck from "./handcheck.json";
import health from "./health.json";
import leadDetails from "./lead-details.json";
import leads from "./leads.json";
import today from "./today.json";

describe("fixtures match the contract exactly", () => {
  it("pins every schema to its contract type", () => {
    expect(pins.every(Boolean)).toBe(true);
  });

  it.each([
    ["health.json", HealthResponse, health],
    ["today.json", TodayResponse, today],
    ["firms.json", FirmsResponse, firms],
    ["handcheck.json", HandcheckResponse, handcheck],
  ] as const)("%s", (_name, schema, data) => {
    expect(() => schema.parse(data)).not.toThrow();
  });

  it("leads.json: every view is a LeadsResponse", () => {
    for (const [view, response] of Object.entries(leads)) {
      expect(() => LeadsResponse.parse(response), view).not.toThrow();
    }
  });

  it("lead-details.json: every lead is a LeadDetail, keyed by its id", () => {
    for (const [id, detail] of Object.entries(leadDetails)) {
      expect(LeadDetail.parse(detail).id).toBe(id);
    }
  });

  it("drafts.json: every entry is a DraftsResponse", () => {
    for (const [id, response] of Object.entries(drafts)) {
      expect(() => DraftsResponse.parse(response), id).not.toThrow();
    }
  });

  it("firm-details.json: every firm is a FirmDetail, keyed by its id", () => {
    for (const [id, detail] of Object.entries(firmDetails)) {
      expect(FirmDetail.parse(detail).firm.id).toBe(id);
    }
  });

  it("dev-only firms are obviously dev-only: .example domains, fictional phones", () => {
    for (const detail of Object.values(firmDetails)) {
      if (detail.firm.id === "firm-atlinjurylawgroup") continue;
      expect(detail.firm.domain).toMatch(/\.example$/);
      for (const c of detail.contacts) {
        if (c.email) expect(c.email).toMatch(/@[a-z]+\.example$/);
        if (c.phone) expect(c.phone).toMatch(/555-01\d\d$/);
      }
    }
  });
});
