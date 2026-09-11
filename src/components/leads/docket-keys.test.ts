import { describe, expect, it } from "vitest";

import { resolveDocketKey, type DocketKeyInput } from "./docket-keys";

const ids = ["a", "b", "c"];
const press = (over: Partial<DocketKeyInput>) =>
  resolveDocketKey({ key: "j", ids, selectedId: null, zone: "docket", ...over });

describe("docket keyboard", () => {
  it("j selects the first lead when nothing is selected, then moves down", () => {
    expect(press({ key: "j" })).toEqual({ type: "select", id: "a" });
    expect(press({ key: "j", selectedId: "a" })).toEqual({ type: "select", id: "b" });
  });

  it("k moves up", () => {
    expect(press({ key: "k", selectedId: "c" })).toEqual({ type: "select", id: "b" });
  });

  it("stops at the ends instead of wrapping", () => {
    expect(press({ key: "j", selectedId: "c" })).toEqual({ type: "none" });
    expect(press({ key: "k", selectedId: "a" })).toEqual({ type: "none" });
  });

  it("does nothing on an empty docket", () => {
    expect(press({ key: "j", ids: [] })).toEqual({ type: "none" });
  });

  it("recovers when the selected lead is not in the list (a deep link)", () => {
    expect(press({ key: "j", selectedId: "zzz" })).toEqual({ type: "select", id: "a" });
  });

  it("arrow keys move only while the docket has focus", () => {
    expect(press({ key: "ArrowDown", selectedId: "a" })).toEqual({ type: "select", id: "b" });
    expect(press({ key: "ArrowDown", selectedId: "a", zone: "casefile" })).toEqual({ type: "none" });
    expect(press({ key: "ArrowUp", selectedId: "b", zone: "other" })).toEqual({ type: "none" });
  });

  it("j and k still move while reading the case file", () => {
    expect(press({ key: "j", selectedId: "a", zone: "casefile" })).toEqual({ type: "select", id: "b" });
  });

  it("Enter opens the full page, from the docket only", () => {
    expect(press({ key: "Enter", selectedId: "b" })).toEqual({ type: "open", id: "b" });
    expect(press({ key: "Enter", selectedId: "b", zone: "casefile" })).toEqual({ type: "none" });
    expect(press({ key: "Enter", selectedId: null })).toEqual({ type: "none" });
  });

  it("Esc closes the case file when one is open", () => {
    expect(press({ key: "Escape", selectedId: "b", zone: "casefile" })).toEqual({ type: "close" });
    expect(press({ key: "Escape", selectedId: null })).toEqual({ type: "none" });
  });

  it("1–7 record outcomes only while the case file has focus", () => {
    const cases: [string, string][] = [
      ["1", "sent"],
      ["2", "replied"],
      ["3", "meeting"],
      ["4", "won"],
      ["5", "lost"],
      ["6", "not_now"],
      ["7", "opt_out"],
    ];
    for (const [key, action] of cases) {
      expect(press({ key, selectedId: "a", zone: "casefile" })).toEqual({ type: "outcome", action });
      expect(press({ key, selectedId: "a", zone: "docket" })).toEqual({ type: "none" });
    }
    expect(press({ key: "8", selectedId: "a", zone: "casefile" })).toEqual({ type: "none" });
    expect(press({ key: "1", selectedId: null, zone: "casefile" })).toEqual({ type: "none" });
  });

  it("stands down when a modifier is held, so browser shortcuts still work", () => {
    expect(press({ key: "k", selectedId: "b", modified: true })).toEqual({ type: "none" });
    expect(press({ key: "1", selectedId: "a", zone: "casefile", modified: true })).toEqual({ type: "none" });
  });
});
