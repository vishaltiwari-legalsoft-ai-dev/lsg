/**
 * The email journey's checks as the screens run them (D-057). They must say
 * exactly what the engine says (lge/journey/catalogue.py), so a person reads
 * the same reason while typing and after saving. The fixture server's
 * journey routes are exercised here too, since they stand in for the engine.
 */
import { beforeEach, describe, expect, it } from "vitest";

import journeyJson from "@/fixtures/journey.json";
import { createApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { createFixtureServer } from "@/lib/api/fixture-server";
import type { JourneyResponse, JourneyTemplate } from "@/lib/api/types";
import { copyProblems, dayLabel, dayProblems, subjectHasCapitals, tokensIn, wordCount } from "./journey";

const journey = journeyJson as unknown as JourneyResponse;
const BANNED = journey.banned_phrases;
const template = (id: string): JourneyTemplate =>
  journey.steps.flatMap((s) => s.templates).find((t) => t.id === id)!;

describe("the journey's checks", () => {
  it("counts days from Day 1", () => {
    expect(dayLabel(0)).toBe("Day 1");
    expect(dayLabel(28)).toBe("Day 29");
  });

  it("passes every original wording", () => {
    for (const t of journey.steps.flatMap((s) => s.templates)) {
      expect(copyProblems(t, t.original_subject, t.original_body, BANNED), t.id).toEqual([]);
    }
  });

  it("refuses the banned words, in the engine's words", () => {
    expect(copyProblems(template("7"), "right person?", "We can replace your paralegal.", BANNED)).toEqual([
      "It uses words these emails never use: “replace”. They read as replacing someone's staff, " +
        "and the email dies in that person's inbox.",
    ]);
  });

  it("refuses a fill-in the email cannot fill, a stray brace and a missing subject", () => {
    expect(copyProblems(template("7"), "", "Hi {city}, {first name}.", BANNED)).toEqual([
      "Add a subject line.",
      "{city} can't be filled in here. This email can use {first_name}, {firm_name}.",
      "A { or } that is not part of a fill-in would be sent as it is.",
    ]);
  });

  it("keeps the tier's paragraph in the email it goes into", () => {
    const [problem] = copyProblems(template("1-open-role"), "your {role} opening", "No slot.", BANNED);
    expect(problem).toBe("Keep {middle_paragraph} in the body exactly once: the tier's paragraph goes there.");
    expect(copyProblems(template("1-paragraph-pi"), null, "Inside {cms}, one person.", BANNED)).toEqual([]);
  });

  it("wants the days in order, after Day 1", () => {
    const days = { 1: 0, 2: 3, 3: 7 };
    expect(dayProblems(days, 90)).toEqual([]);
    expect(dayProblems({ ...days, 3: 3 }, 90)).toEqual([
      "Email 3 must come after email 2, which goes on Day 4.",
    ]);
    expect(dayProblems({ ...days, 2: 91 }, 90)).toEqual(["Email 2 must go between Day 2 and Day 91."]);
    expect(dayProblems({ ...days, 1: 1 }, 90)).toEqual(["Email 1 always goes on Day 1."]);
  });

  it("reads fill-ins, words and capitals", () => {
    expect(tokensIn("{first_name} and {role}, {first_name}")).toEqual(["first_name", "role"]);
    expect(wordCount("{first_name} — the role is open.")).toBe(6);
    expect(subjectHasCapitals("you moved to {cms}")).toBe(false);
    expect(subjectHasCapitals("You moved")).toBe(true);
  });
});

describe("the fixture server's journey", () => {
  let api: ReturnType<typeof createApi>;
  beforeEach(() => {
    api = createApi(createFixtureServer({ latencyMs: 0 }));
  });

  it("saves wording for every lead, refuses a banned word, and restores the original", async () => {
    const saved = await api.saveJourneyTemplate("9", { subject: "closing the loop, {first_name}", body: "Done." });
    expect(saved.edited_at).not.toBeNull();
    expect((await api.journey()).steps[8].templates[0].subject).toBe("closing the loop, {first_name}");

    await expect(
      api.saveJourneyTemplate("9", { subject: "x", body: "We replace your staff." }),
    ).rejects.toMatchObject({ status: 422, code: "invalid_copy" });

    const restored = await api.restoreJourneyTemplate("9");
    expect(restored.subject).toBe(restored.original_subject);
    expect(restored.edited_at).toBeNull();
  });

  it("moves the days, refuses a schedule out of order, and restores them", async () => {
    const moved = await api.saveJourneyDays([{ step: 2, day: 1 }, { step: 3, day: 2 }]);
    expect(moved.steps.slice(0, 4).map((s) => s.day)).toEqual([0, 1, 2, 10]);
    await expect(api.saveJourneyDays([{ step: 3, day: 1 }])).rejects.toBeInstanceOf(ApiError);
    const restored = await api.restoreJourneyDays();
    expect(restored.steps.map((s) => s.day)).toEqual(restored.steps.map((s) => s.original_day));
  });

  it("derives nurture from the engine's sequence render: emails 1, 3 and 9 at half the pace", async () => {
    const example = await api.journeyExample({ tier: "1A", pain: "open_role", system: true, band: "NURTURE" });
    expect(example.drafts.touches.map((t) => [t.step, t.day])).toEqual([[1, 0], [3, 14], [9, 56]]);
    await expect(
      api.journeyExample({ tier: "2", pain: "mass_tort", system: false, band: "SEQUENCE" }),
    ).rejects.toMatchObject({ status: 404 });
  });
});
