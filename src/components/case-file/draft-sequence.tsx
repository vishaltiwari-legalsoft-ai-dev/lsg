"use client";

import { ChevronRightIcon } from "lucide-react";
import { useState } from "react";

import { CopyButton, emailText } from "@/components/copy-button";
import { SectionHeading } from "@/components/layout/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { DraftTouch, DraftsResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

function Touch({ touch, defaultOpen }: { touch: DraftTouch; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `touch-${touch.step}-body`;

  return (
    <li className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-4 py-5 first:pt-1">
      <div className="grid content-start justify-items-start gap-0.5 pt-0.5">
        <span className="text-section leading-none font-medium text-ink tabular-nums">{touch.step}</span>
        <span className="text-meta whitespace-nowrap text-slate tabular-nums">Day {touch.day}</span>
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
              aria-label={`Copy touch ${touch.step}`}
              toastText={`Copied touch ${touch.step}`}
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

/**
 * The nine touches as the sequence they are: numbered, with day offsets.
 * Email copy is set in Caslon as quoted copy. Skipped touches say why.
 */
export function DraftSequence({
  drafts,
  isPending,
  isError,
  expand,
}: {
  drafts: DraftsResponse | undefined;
  isPending: boolean;
  isError: boolean;
  /** Panel shows touch 1 open; the full page shows every touch. */
  expand: "first" | "all";
}) {
  const rendered = drafts?.touches.filter((t) => !t.skipped_reason) ?? [];
  const lastDay = drafts?.touches.at(-1)?.day;

  return (
    <section aria-labelledby="drafts-heading" className="grid gap-3">
      <SectionHeading
        id="drafts-heading"
        aside={
          drafts && drafts.touches.length > 0
            ? `${rendered.length} of ${drafts.touches.length} touches, over ${lastDay} days`
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
          {drafts?.excluded_reason ?? "No drafts: the journey renderer returned no touches for this lead."}
        </p>
      ) : (
        <ol className="divide-y divide-rule" aria-label="Touches">
          {drafts.touches.map((touch, i) => (
            <Touch key={touch.step} touch={touch} defaultOpen={expand === "all" || i === 0} />
          ))}
        </ol>
      )}
    </section>
  );
}
