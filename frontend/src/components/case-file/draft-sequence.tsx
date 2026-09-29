"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CopyButton, emailText } from "@/components/copy-button";
import { SectionHeading } from "@/components/layout/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { Band, DraftTouch, DraftsResponse } from "@/lib/api/types";
import { dayLabel } from "@/lib/journey";
import { cn } from "@/lib/utils";

function Touch({ touch, defaultOpen }: { touch: DraftTouch; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `touch-${touch.step}-body`;

  return (
    <li className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-4 py-3.5 first:pt-1">
      <div className="grid content-start justify-items-start gap-0.5 pt-0.5">
        <span className="type-narrow text-subtitle leading-none font-semibold text-ink tabular-nums">{touch.step}</span>
        {touch.skipped_reason ? null : (
          <span className="text-meta whitespace-nowrap text-slate tabular-nums">{dayLabel(touch.day)}</span>
        )}
      </div>

      {touch.skipped_reason ? (
        <p className="pt-0.5 text-body text-slate italic">{touch.skipped_reason}</p>
      ) : (
        <div className="grid min-w-0 gap-3">
          <div className="flex items-start justify-between gap-4">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={bodyId}
              onClick={() => setOpen((o) => !o)}
              className="group flex min-w-0 items-start gap-1.5 rounded-[4px] text-left"
            >
              <ChevronRightIcon
                aria-hidden="true"
                className={cn(
                  "mt-[5px] size-3.5 shrink-0 text-slate transition-transform duration-150",
                  open && "rotate-90",
                )}
              />
              <span className="quotation text-quote text-ink group-hover:underline">
                <span className="sr-only">Subject: </span>
                {touch.subject}
              </span>
            </button>
            <CopyButton
              text={emailText(touch.subject, touch.body)}
              label="Copy"
              aria-label={`Copy email ${touch.step}`}
              toastText={`Copied email ${touch.step}`}
              variant="ghost"
              size="sm"
              className="-mt-1 shrink-0"
            />
          </div>
          <div
            id={bodyId}
            hidden={!open}
            className="quotation ml-5 border-l-2 border-rule pl-4 text-quote whitespace-pre-line text-ink"
          >
            {touch.body}
          </div>
        </div>
      )}
    </li>
  );
}

/** Why there are no drafts, in words -- the engine sometimes sends its code. */
const NO_DRAFT_REASON: Record<string, string> = {
  no_usable_contact: "No owner or office manager to write to yet.",
  grade_not_set: "The address is not verified yet, so no sequence is drafted.",
  band_hold: "The score is too low for a sequence yet.",
  tier_unclassified: "The firm is not tiered yet, so no sequence is drafted.",
  tier_not_set: "The firm is not tiered yet, so no sequence is drafted.",
};

export function noDraftWords(reason: string | null | undefined, band: Band | null | undefined): string {
  if (band === "STRIKE") return "Strike leads are written by hand, today. The engine drafts no sequence for them.";
  if (!reason) return "No drafts for this lead yet.";
  if (NO_DRAFT_REASON[reason]) return NO_DRAFT_REASON[reason];
  if (reason.startsWith("missing_")) return `A draft can't be written: the ${reason.slice(8).replace(/_/g, " ")} is missing.`;
  if (/^[a-z0-9_]+$/.test(reason)) return reason.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) + ".";
  return reason;
}

/**
 * The emails as the sequence they are: numbered, with the day each goes.
 * Email copy is set in Caslon as quoted copy. Skipped emails say why; the
 * whole journey, and its wording, is on the Email journey screen.
 */
export function DraftSequence({
  drafts,
  isPending,
  isError,
  expand,
  band,
  leadId,
}: {
  drafts: DraftsResponse | undefined;
  /** The lead's priority: a Strike lead is written by hand, so it has no sequence. */
  band?: Band | null;
  isPending: boolean;
  isError: boolean;
  /** Email 1 opens; the rest show their subject lines and open on request. */
  expand: "first" | "all";
  /** Links to this lead's journey, day by day, where the wording is changed. */
  leadId?: string;
}) {
  const rendered = drafts?.touches.filter((t) => !t.skipped_reason) ?? [];
  const lastDay = Math.max(...rendered.map((t) => t.day));

  return (
    <section aria-labelledby="drafts-heading" className="grid gap-3">
      <SectionHeading
        id="drafts-heading"
        aside={
          drafts && rendered.length > 0
            ? `${rendered.length} of ${drafts.touches.length} emails, over ${lastDay + 1} days`
            : undefined
        }
      >
        Drafts
      </SectionHeading>

      {isPending ? (
        <div className="grid gap-3 pt-1">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : isError ? (
        <p className="text-body text-slate">
          The drafts didn&apos;t load. The rest of the case file is current; reload to try the drafts again.
        </p>
      ) : !drafts || drafts.touches.length === 0 ? (
        <p className="text-body text-slate">
          {band !== "STRIKE" && drafts?.excluded_display
            ? `${drafts.excluded_display.replace(/[.!?]$/, "")}.`
            : noDraftWords(drafts?.excluded_reason, band)}
        </p>
      ) : (
        <ol className="divide-y divide-rule" aria-label="Emails">
          {drafts.touches.map((touch, i) => (
            <Touch key={touch.step} touch={touch} defaultOpen={expand === "all" || i === 0} />
          ))}
        </ol>
      )}
      {leadId && rendered.length > 0 ? (
        <Link href={`/journey?lead=${encodeURIComponent(leadId)}`} className="text-table text-cobalt hover:underline">
          See this journey day by day, and change the wording
        </Link>
      ) : null}
    </section>
  );
}
