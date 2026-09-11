import { cn } from "@/lib/utils";

export const UNKNOWN_TEXT = "Unknown — not guessed";

/**
 * An unknown is a state, not a blank. Slate italic, always in words —
 * never an empty cell, a dash or a zero.
 */
export function Unknown({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <span data-unknown="" className={cn("text-slate italic", className)}>
      {children ?? UNKNOWN_TEXT}
    </span>
  );
}

/** The backend writes unknowns as "Unknown — not guessed"; recognise its words. */
export function isUnknownDisplay(value: string): boolean {
  return /^unknown\b/i.test(value.trim());
}

/**
 * A value that may be missing. Missing — or the backend's own "Unknown —"
 * display — renders as the stated unknown.
 */
export function ValueOrUnknown({
  value,
  unknown,
  className,
}: {
  value: string | number | null | undefined;
  unknown?: string;
  className?: string;
}) {
  if (value === null || value === undefined || (typeof value === "string" && value.trim() === "")) {
    return <Unknown className={className}>{unknown}</Unknown>;
  }
  if (typeof value === "string" && isUnknownDisplay(value)) {
    return <Unknown className={className}>{value}</Unknown>;
  }
  return <span className={className}>{value}</span>;
}

/**
 * An attribute's display value. The backend already writes unknowns as
 * "Unknown — not guessed"; the state decides the treatment, and an empty
 * display can never render as a blank.
 */
export function AttributeValue({
  display,
  state,
  className,
}: {
  display: string;
  state: "resolved" | "unknown" | "conflict" | "stale";
  className?: string;
}) {
  if (state === "unknown" || display.trim() === "" || isUnknownDisplay(display)) {
    return <Unknown className={className}>{display.trim() || UNKNOWN_TEXT}</Unknown>;
  }
  return <span className={cn("text-ink", className)}>{display}</span>;
}
