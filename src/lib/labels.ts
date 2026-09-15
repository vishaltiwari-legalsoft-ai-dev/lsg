import type { Band, Contest, LeadView, OutcomeAction, Role, Stage } from "@/lib/api/types";

/*
 * The stages a person works a lead through (lge/api/stage.py). The engine's
 * sixteen states stay the truth; these are the words on the tabs.
 */
export const QUEUE_STAGES: Stage[] = [
  "needs_review", "needs_contact", "ready", "in_outreach", "replied", "parked", "researching",
];
export const OTHER_STAGES: Stage[] = [
  "no_website", "needs_refresh", "handed_off", "won", "lost", "disqualified", "do_not_contact",
];
export const STAGE_LABEL: Record<Stage, string> = {
  researching: "Researching",
  no_website: "No website",
  needs_review: "Needs a decision",
  needs_contact: "Needs a person",
  ready: "Ready to reach",
  parked: "Parked",
  in_outreach: "In outreach",
  replied: "Replied",
  handed_off: "Handed off",
  won: "Won",
  lost: "Lost",
  disqualified: "Disqualified",
  do_not_contact: "Do not contact",
  needs_refresh: "Needs a refresh",
};
export const STAGE_EMPTY: Record<Stage, string> = {
  researching: "Nothing is being researched. Upload a list, or open a firm and research it.",
  no_website: "Every firm has a website on record.",
  needs_review: "No lead is waiting for a decision. They arrive as research finishes.",
  needs_contact: "Every qualified lead has a decision-maker with an address.",
  ready: "Nothing is ready to reach yet. A lead lands here with a person, an address and a tier.",
  parked: "Nothing is parked.",
  in_outreach: "No sequence is running.",
  replied: "No replies waiting.",
  handed_off: "Nothing with sales.",
  won: "Nothing won yet.",
  lost: "Nothing lost.",
  disqualified: "Nothing disqualified.",
  do_not_contact: "Nobody has opted out.",
  needs_refresh: "Nothing needs a refresh.",
};

/** Priority is the engine's band, in plain words. */
export const PRIORITY_LABEL: Record<Band, string> = {
  STRIKE: "Strike",
  SEQUENCE: "Sequence",
  NURTURE: "Nurture",
  HOLD: "Hold",
};
export const PRIORITY_HINT: Record<Band, string> = {
  STRIKE: "An open role right now — write today, by hand.",
  SEQUENCE: "Fits, and a live signal — the nine-touch sequence.",
  NURTURE: "Fits, no signal yet — a light touch until one appears.",
  HOLD: "Not yet — fit or urgency too low.",
};

/** The three numbers on a lead, in words. */
export const SCORE_LABEL = { fit: "Fit", intent: "Urgency", contest: "Competition" } as const;

/*
 * Interface copy for the contract's closed enums. These carry no display
 * string in api-contract.md (band, contest, role, view, outcome action), so
 * the words live here, once. Anything the backend *does* label — tier,
 * state, source, headline, email status — is always rendered verbatim.
 *
 * Filter options (tiers, signal kinds) are listed here until the API offers
 * a facets endpoint; see the report for that proposal.
 */

export const VIEWS: LeadView[] = ["STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED", "UNSCORED"];

export const VIEW_LABEL: Record<LeadView, string> = {
  STRIKE: "Strike",
  SEQUENCE: "Sequence",
  NURTURE: "Nurture",
  PHONE: "Phone list",
  EXCLUDED: "Excluded",
  UNSCORED: "Unscored",
};

export const VIEW_EMPTY: Record<LeadView, { title: string; body: string }> = {
  STRIKE: {
    title: "No STRIKE leads yet.",
    body: "They appear once the probe's careers sweep finds an open role.",
  },
  SEQUENCE: {
    title: "No leads are ready for the sequence yet.",
    body: "They appear after the nightly score finds fit and an open signal.",
  },
  NURTURE: {
    title: "No nurture leads yet.",
    body: "Fit-only firms land here after the nightly score.",
  },
  PHONE: {
    title: "No phone-list leads.",
    body: "A lead lands here when it has a named owner but no verifiable email.",
  },
  EXCLUDED: {
    title: "Nothing is excluded.",
    body: "The hygiene filter hasn't removed any lead from the lists.",
  },
  UNSCORED: {
    title: "Every lead has been scored.",
    body: "New firms show up here until the next nightly score reaches them.",
  },
};

export const BAND_LABEL: Record<Band, string> = {
  STRIKE: "Strike",
  SEQUENCE: "Sequence",
  NURTURE: "Nurture",
  HOLD: "Hold",
};

export const CONTEST_LABEL: Record<Contest, string> = {
  NONE: "None",
  LOW: "Low",
  MED: "Medium",
  HIGH: "High",
};

export const ROLE_LABEL: Record<Role, string> = {
  owner: "Owner",
  admin: "Office manager",
  attorney: "Attorney",
  unknown: "Role unknown",
};

export interface OutcomeDef {
  action: OutcomeAction;
  /** Button text. The group is labelled "Record outcome". */
  label: string;
  /** Accessible name — contains the visible label (WCAG 2.5.3). */
  verb: string;
  /** Number key, active while the case file has focus. */
  key: string;
  /** Opens a follow-up step (date or confirmation) instead of recording. */
  needsInput?: "date" | "confirm";
}

export const OUTCOMES: OutcomeDef[] = [
  { action: "sent", label: "Sent", verb: "Mark as sent", key: "1" },
  { action: "replied", label: "Replied", verb: "Mark as replied", key: "2" },
  { action: "meeting", label: "Meeting", verb: "Mark as meeting booked", key: "3" },
  { action: "won", label: "Won", verb: "Mark as won", key: "4" },
  { action: "lost", label: "Lost", verb: "Mark as lost", key: "5" },
  { action: "not_now", label: "Not now", verb: "Mark as not now", key: "6", needsInput: "date" },
  { action: "opt_out", label: "Opt out", verb: "Opt out this firm", key: "7", needsInput: "confirm" },
];

export const OUTCOME_LABEL: Record<OutcomeAction, string> = {
  sent: "Sent",
  replied: "Replied",
  meeting: "Meeting booked",
  won: "Won",
  lost: "Lost",
  not_now: "Not now",
  opt_out: "Opted out",
};

export const TIER_OPTIONS = [
  { value: "1A", label: "Tier 1A" },
  { value: "1B", label: "Tier 1B" },
  { value: "2", label: "Tier 2" },
  { value: "3", label: "Tier 3" },
  { value: "4_NONBILLABLE", label: "Tier 4" },
];

export const SIGNAL_OPTIONS = [
  { value: "job_posting_open", label: "Open role" },
  { value: "multi_opening", label: "Several open roles" },
  { value: "mass_tort_campaign", label: "Mass-tort campaign" },
  { value: "review_unreturned_call", label: "Unreturned calls in reviews" },
  { value: "cms_implemented", label: "New case software" },
];

export const CONTEST_OPTIONS = (["NONE", "LOW", "MED", "HIGH"] as Contest[]).map((value) => ({
  value,
  label: CONTEST_LABEL[value],
}));
