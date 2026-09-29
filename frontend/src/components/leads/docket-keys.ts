import type { OutcomeAction } from "@/lib/api/types";
import { OUTCOMES } from "@/lib/labels";

/** Where keyboard focus is when a key is pressed. */
export type DocketZone = "docket" | "casefile" | "other";

export type DocketCommand =
  | { type: "select"; id: string }
  | { type: "open"; id: string }
  | { type: "close" }
  | { type: "outcome"; action: OutcomeAction }
  | { type: "none" };

export interface DocketKeyInput {
  key: string;
  /** Lead ids in docket order. */
  ids: readonly string[];
  selectedId: string | null;
  zone: DocketZone;
  /** Ctrl, Meta or Alt held — shortcuts stand down for browser/OS keys. */
  modified?: boolean;
}

const NONE: DocketCommand = { type: "none" };

/**
 * The docket's keyboard, as a pure function of (key, list, selection, focus):
 *   j / ↓  next lead        k / ↑  previous lead     (arrows only in the docket)
 *   Enter  open the full case file (docket only — elsewhere Enter stays native)
 *   Esc    close the case file
 *   1–7    record an outcome, only while the case file has focus
 */
export function resolveDocketKey({ key, ids, selectedId, zone, modified }: DocketKeyInput): DocketCommand {
  if (modified) return NONE;

  const index = selectedId ? ids.indexOf(selectedId) : -1;
  const isArrow = key === "ArrowDown" || key === "ArrowUp";
  if (isArrow && zone !== "docket") return NONE;

  switch (key) {
    case "j":
    case "ArrowDown": {
      if (ids.length === 0) return NONE;
      const next = index === -1 ? 0 : Math.min(index + 1, ids.length - 1);
      return ids[next] === selectedId ? NONE : { type: "select", id: ids[next] };
    }
    case "k":
    case "ArrowUp": {
      if (ids.length === 0) return NONE;
      const prev = index === -1 ? 0 : Math.max(index - 1, 0);
      return ids[prev] === selectedId ? NONE : { type: "select", id: ids[prev] };
    }
    case "Enter":
      return zone === "docket" && selectedId ? { type: "open", id: selectedId } : NONE;
    case "Escape":
      return selectedId ? { type: "close" } : NONE;
    default: {
      if (zone !== "casefile" || !selectedId) return NONE;
      const outcome = OUTCOMES.find((o) => o.key === key);
      return outcome ? { type: "outcome", action: outcome.action } : NONE;
    }
  }
}

/** Which zone an event target sits in, by the data attributes on the layout. */
export function zoneOf(target: EventTarget | null): DocketZone {
  if (!(target instanceof Element)) return "other";
  if (target.closest("[data-casefile]")) return "casefile";
  if (target.closest("[data-docket]")) return "docket";
  return "other";
}
