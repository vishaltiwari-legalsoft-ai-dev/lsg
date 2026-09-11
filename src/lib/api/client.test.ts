import { beforeEach, describe, expect, it, vi } from "vitest";

import { createApi } from "./client";
import { ApiError, EngineUnreachableError } from "./errors";
import { createFixtureServer, FIXTURE_PAGE_LIMIT, type FixtureServer } from "./fixture-server";
import { httpTransport } from "./transport";

let server: FixtureServer;
let api: ReturnType<typeof createApi>;

beforeEach(() => {
  server = createFixtureServer({ latencyMs: 0 });
  api = createApi(server);
});

describe("api client in fixture mode", () => {
  it("opens Today on the real hero record", async () => {
    const today = await api.today();
    const hero = today.top_proof!;
    expect(hero.firm.name).toBe("Atlanta Personal Injury Law Group");
    expect(hero.firm.domain).toBe("atlinjurylawgroup.com");
    expect(hero.firm.tier).toBe("1A");
    expect(hero.proof!.quote).toBe(
      "The attorneys at Atlanta Personal Injury Law Group work on a contingency fee basis.",
    );
    expect(hero.proof!.source_label).toBe("Firm website (fee language)");
    expect(hero.contact).toBeNull();
    expect(today.first_draft?.subject).toBeTruthy();
    expect(today.strike.some((r) => r.id === hero.id)).toBe(false);
  });

  it("states the hero's missing roles and its one attorney", async () => {
    const lead = await api.lead("lead-atlinjurylawgroup");
    expect(lead.missing_roles).toEqual(["owner", "admin"]);
    expect(lead.contacts.map((c) => [c.full_name, c.title, c.role])).toEqual([
      ["Mats Rosen", "Associate Attorney", "attorney"],
    ]);
    const firm = await api.firm(lead.firm.id);
    const fee = firm.attributes.find((a) => a.attr === "fee_model")!;
    expect(fee.confidence).toBe(0.95);
    expect(firm.attributes.find((a) => a.attr === "spanish_intake")?.display).toBe("Yes");
  });

  it("serves a view with counts and cursor paging", async () => {
    const first = await api.leads({ view: "SEQUENCE", limit: 50 });
    expect(first.items).toHaveLength(FIXTURE_PAGE_LIMIT);
    expect(first.next_cursor).not.toBeNull();
    expect(first.counts.SEQUENCE).toBe(5);
    const second = await api.leads({ view: "SEQUENCE", cursor: first.next_cursor! });
    expect(second.items).toHaveLength(1);
    expect(second.next_cursor).toBeNull();
    const all = [...first.items, ...second.items].map((r) => r.id);
    expect(new Set(all).size).toBe(5);
  });

  it("filters by tier, search and verified email", async () => {
    const tier1b = await api.leads({ view: "STRIKE", tier: "1B" });
    expect(tier1b.items.map((r) => r.firm.tier)).toEqual(["1B"]);
    const q = await api.leads({ view: "STRIKE", q: "atlinjury" });
    expect(q.items.map((r) => r.id)).toEqual(["lead-atlinjurylawgroup"]);
    const verified = await api.leads({ view: "STRIKE", verified: true });
    expect(verified.items.every((r) => r.contact?.email_status === "valid")).toBe(true);
  });

  it("records an outcome and returns the message the toast will show", async () => {
    const res = await api.recordOutcome("lead-fx-harbor", { action: "replied" });
    expect(res.transition_applied).toBe(false);
    expect(res.message).toMatch(/^Marked as replied\./);
    expect(res.lead.outcomes.at(-1)).toMatchObject({ action: "replied", transition_applied: false });
    // The record persists for the session.
    expect((await api.lead("lead-fx-harbor")).outcomes).toHaveLength(1);
  });

  it("opt-out suppresses the domain and moves the lead to Excluded", async () => {
    const res = await api.recordOutcome("lead-fx-harbor", { action: "opt_out" });
    expect(res.transition_applied).toBe(true);
    expect(res.message).toContain("harborstreetinjury.example");
    const excluded = await api.leads({ view: "EXCLUDED" });
    expect(excluded.counts.EXCLUDED).toBe(3);
    expect((await api.leads({ view: "STRIKE" })).counts.STRIKE).toBe(3);
  });

  it("refuses not-now without a date, with the contract's error envelope", async () => {
    await expect(api.recordOutcome("lead-fx-harbor", { action: "not_now" })).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
    });
  });

  it("searches firms by name or domain", async () => {
    const res = await api.firms({ q: "harbor" });
    expect(res.items.map((f) => f.name)).toEqual(["Harbor Street Injury Law"]);
    expect(res.total).toBe(1);
  });

  it("records a hand-check verdict and recomputes the gate", async () => {
    const before = await api.handcheck();
    const hero = before.sample.find((f) => f.firm_id === "firm-atlinjurylawgroup")!;
    for (const a of hero.attributes) {
      await api.decideHandcheck(hero.firm_id, a.attr, { correct: true });
    }
    const after = await api.handcheck();
    expect(after.gate.reviewed_firms).toBe(before.gate.reviewed_firms + 1);
    expect(after.gate.passed).toBe(false);
    const fee = after.accuracy.find((a) => a.attr === "fee_model")!;
    expect(fee.checked).toBe(before.accuracy.find((a) => a.attr === "fee_model")!.checked + 1);
  });

  it("exports CSV with grade B kept off the email list", async () => {
    const csv = await api.exportLeadsCsv("SEQUENCE");
    expect(csv.split("\n")[0]).toContain("email_status");
    expect(csv).not.toContain("Riverbend");
  });

  it("answers an unknown id with a 404 ApiError", async () => {
    await expect(api.lead("nope")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("api client over http", () => {
  it("turns a refused connection into EngineUnreachableError", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const http = createApi(httpTransport("http://127.0.0.1:8000", fetchImpl));
    await expect(http.today()).rejects.toBeInstanceOf(EngineUnreachableError);
  });

  it("reads the contract's error envelope", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "not_found", message: "Lead not found.", fix: "Check the id." } }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      ),
    );
    const http = createApi(httpTransport("http://127.0.0.1:8000", fetchImpl));
    await expect(http.lead("x")).rejects.toMatchObject({
      status: 404,
      code: "not_found",
      message: "Lead not found.",
      fix: "Check the id.",
    });
  });

  it("builds query strings without empty filters", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null, counts: {} }), { status: 200 }),
    );
    const http = createApi(httpTransport("http://127.0.0.1:8000", fetchImpl));
    await http.leads({ view: "STRIKE", tier: "1A", q: "", verified: false });
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8000/api/leads?view=STRIKE&tier=1A&verified=false",
    );
  });
});
