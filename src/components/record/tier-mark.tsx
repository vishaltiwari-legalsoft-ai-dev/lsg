import type { FirmRef } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const STAMP =
  "inline-flex h-5 min-w-7 items-center justify-center rounded-control border px-1 text-meta leading-none font-medium tabular-nums";

/**
 * The tier as a docket code: a small inked stamp ("1A").
 *
 * - `full` (records, headers): anything that isn't a tier code is written
 *   out in the backend's words ("Unclassified", "Disqualified — legal aid").
 * - `stamp` (dense columns): an unclassified firm is absence of data, so it
 *   gets the dashed "no data" stamp, empty; other labels truncate. The full
 *   words stay available to assistive tech and on hover.
 */
export function TierMark({
  firm,
  variant = "full",
  className,
}: {
  firm: Pick<FirmRef, "tier" | "tier_display">;
  variant?: "full" | "stamp";
  className?: string;
}) {
  const code = firm.tier && /^[0-9][A-Z]?$/.test(firm.tier) ? firm.tier : null;

  if (code) {
    return (
      <span title={firm.tier_display} className={cn(STAMP, "border-ink/75 text-ink", className)}>
        <span className="sr-only">Tier </span>
        {code}
      </span>
    );
  }

  const unclassified = !firm.tier || firm.tier.toUpperCase() === "UNCLASSIFIED";
  if (variant === "stamp" && unclassified) {
    return (
      <span title={firm.tier_display} className={cn(STAMP, "border-dashed border-slate/55", className)}>
        <span className="sr-only">{firm.tier_display}</span>
      </span>
    );
  }

  return (
    <span
      title={firm.tier_display}
      className={cn("text-meta text-slate", variant === "stamp" && "block truncate", className)}
    >
      {firm.tier_display}
    </span>
  );
}
