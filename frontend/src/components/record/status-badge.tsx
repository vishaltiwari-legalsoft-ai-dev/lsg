import type { AlertState, ContactSummary, EmailStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export type BadgeState = "verified" | "unverified" | "failure" | "no_data" | "ok" | "firing" | "act";

/*
 * Five treatments, each carrying its word so colour is never the only cue:
 *   confirmed  — ledger text, ledger rule, solid marker
 *   unverified — ink text, neutral rule, slate marker (not confirmed, not failed)
 *   problem    — redline text on a faint redline wash
 *   no data    — slate text, dashed outline, no marker: absence is information
 *   act        — cobalt on its wash: waiting for the person looking at it
 */
const STYLES: Record<BadgeState, { box: string; marker: string | null }> = {
  verified: { box: "border-ledger/45 text-ledger", marker: "bg-ledger" },
  ok: { box: "border-ledger/45 text-ledger", marker: "bg-ledger" },
  act: { box: "border-cobalt/45 bg-cobalt-wash text-cobalt", marker: "bg-cobalt" },
  unverified: { box: "border-rule-strong text-ink", marker: "bg-slate" },
  failure: { box: "border-redline/40 bg-redline-wash text-redline", marker: "bg-redline" },
  firing: { box: "border-redline/40 bg-redline-wash text-redline", marker: "bg-redline" },
  no_data: { box: "border-dashed border-slate/55 text-slate", marker: null },
};

export function StatusBadge({
  state,
  children,
  className,
}: {
  state: BadgeState;
  children: React.ReactNode;
  className?: string;
}) {
  const style = STYLES[state];
  return (
    <span
      data-state={state}
      className={cn(
        "inline-flex h-5 max-w-full items-center gap-1.5 rounded-control border bg-sheet px-1.5 text-meta leading-none font-medium whitespace-nowrap",
        style.box,
        className,
      )}
    >
      {style.marker ? (
        <span aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-[1px]", style.marker)} />
      ) : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

export function emailBadgeState(status: EmailStatus | null): BadgeState {
  switch (status) {
    case "valid":
      return "verified";
    case "unverified":
      return "unverified";
    case "catch_all":
    case "risky":
    case "invalid":
      return "failure";
    default:
      return "no_data";
  }
}

/** The email status, in the backend's words. Nothing is silently verified. */
export function EmailStatusBadge({
  contact,
  className,
}: {
  contact: Pick<ContactSummary, "email_status" | "email_status_display"> | null;
  className?: string;
}) {
  const status = contact?.email_status ?? null;
  const label = contact?.email_status_display ?? (status ? status : "No data");
  return (
    <StatusBadge state={emailBadgeState(status)} className={className}>
      {status ? label : "No data"}
    </StatusBadge>
  );
}

const ALERT_WORD: Record<AlertState, string> = { ok: "OK", firing: "Firing", no_data: "No data" };

export function AlertStateBadge({ state, className }: { state: AlertState; className?: string }) {
  return (
    <StatusBadge state={state === "no_data" ? "no_data" : state} className={className}>
      {ALERT_WORD[state]}
    </StatusBadge>
  );
}
