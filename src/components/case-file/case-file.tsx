"use client";

import { XIcon } from "lucide-react";
import Link from "next/link";
import { useRef } from "react";

import { resolveDocketKey, zoneOf } from "@/components/leads/docket-keys";
import { Field, SectionHeading } from "@/components/layout/panel";
import { ProofQuote } from "@/components/record/proof-quote";
import { TierMark } from "@/components/record/tier-mark";
import { Unknown, ValueOrUnknown } from "@/components/record/unknown";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isShortcutBlocked, useKeydown } from "@/hooks/use-keydown";
import { useDrafts, useLead } from "@/lib/api/hooks";
import type { LeadDetail } from "@/lib/api/types";
import { formatPlace } from "@/lib/format";
import { BAND_LABEL } from "@/lib/labels";
import { DraftSequence } from "./draft-sequence";
import { OutcomeBar, type OutcomeBarHandle } from "./outcome-bar";
import { PeopleSection } from "./people";
import { RecordSection } from "./record-timeline";
import { ScoreBreakdown } from "./score-breakdown";

type Mode = "panel" | "page";

function ExclusionNote({ reasons }: { reasons: string[] }) {
  return (
    <div role="note" className="grid gap-1.5 border-l-2 border-redline py-0.5 pl-4">
      <p className="text-body font-medium text-ink">Off the email list</p>
      <ul className="grid gap-1 text-body text-slate">
        {reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </div>
  );
}

function RecordFields({ lead }: { lead: LeadDetail }) {
  const place = formatPlace(lead.firm.city, lead.firm.state);
  return (
    <dl className="flex flex-wrap gap-x-9 gap-y-3">
      <Field label="Band">{lead.band ? BAND_LABEL[lead.band] : <Unknown>Not scored</Unknown>}</Field>
      <Field label="Practice">
        <ValueOrUnknown value={lead.firm.practice_display} />
      </Field>
      <Field label="Fee model">
        <ValueOrUnknown value={lead.firm.fee_display} />
      </Field>
      <Field label="Place">
        <ValueOrUnknown value={place} />
      </Field>
      <Field label="Website">
        {lead.firm.domain ? (
          <Link href={`/firms/${lead.firm.id}`} className="block truncate text-cobalt hover:underline">
            {lead.firm.domain}
          </Link>
        ) : (
          <Unknown />
        )}
      </Field>
    </dl>
  );
}

function CaseFileSkeleton({ mode }: { mode: Mode }) {
  return (
    <div className="grid gap-8 px-8 py-6" aria-busy="true" aria-label="Loading the case file">
      <div className="grid gap-3">
        {mode === "panel" ? <Skeleton className="h-6 w-2/3" /> : null}
        <Skeleton className="h-4 w-1/3" />
        <div className="mt-2 grid grid-cols-4 gap-6">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-8" />
          ))}
        </div>
      </div>
      <div className="grid gap-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-7 w-5/6" />
        <Skeleton className="h-4 w-1/2" />
      </div>
      <div className="grid gap-3">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-16 w-full" />
      </div>
    </div>
  );
}

/**
 * The case file: the proof, then people, drafts, the record and the score.
 * The outcome bar stays pinned to the bottom; 1–7 record while the case file
 * has focus (on the full page, anywhere on the page).
 */
export function CaseFile({ id, mode, onClose }: { id: string; mode: Mode; onClose?: () => void }) {
  const lead = useLead(id);
  const drafts = useDrafts(id);
  const bar = useRef<OutcomeBarHandle>(null);

  useKeydown((event) => {
    if (isShortcutBlocked(event)) return;
    let zone = zoneOf(event.target);
    if (mode === "page" && zone === "other") zone = "casefile";
    const command = resolveDocketKey({
      key: event.key,
      ids: [id],
      selectedId: id,
      zone,
      modified: event.ctrlKey || event.metaKey || event.altKey,
    });
    if (command.type === "outcome") {
      event.preventDefault();
      bar.current?.trigger(command.action);
    }
  }, lead.isSuccess);

  if (lead.isPending) return <CaseFileSkeleton mode={mode} />;
  if (lead.isError) {
    return (
      <div className="px-8 py-8">
        <ErrorState error={lead.error} onRetry={() => void lead.refetch()} />
      </div>
    );
  }

  const data = lead.data;
  const titleId = `casefile-title-${id}`;

  return (
    <article
      data-casefile=""
      aria-labelledby={mode === "panel" ? titleId : undefined}
      aria-label={mode === "page" ? "Case file" : undefined}
      className="group/casefile flex min-h-full flex-col"
    >
      <header className="grid grid-cols-[minmax(0,1fr)] gap-4 border-b border-rule px-7 pt-6 pb-5">
        <div className="flex items-start justify-between gap-4">
          {mode === "panel" ? (
            <div className="grid min-w-0 gap-1">
              <div className="flex min-w-0 items-center gap-2.5">
                <h2 id={titleId} className="min-w-0 truncate text-title font-medium text-ink">
                  {data.firm.name}
                </h2>
                <TierMark firm={data.firm} />
              </div>
              <p className="text-body text-slate">{data.state_display}</p>
            </div>
          ) : (
            // On the full page the firm's name is the page title.
            <div className="flex min-w-0 items-center gap-2.5">
              <TierMark firm={data.firm} />
              <p className="text-body text-slate">{data.state_display}</p>
            </div>
          )}
          {mode === "panel" ? (
            <div className="-mr-2 flex shrink-0 items-center gap-1">
              <Button asChild variant="ghost" size="sm">
                <Link href={`/leads/${id}`}>Open full page</Link>
              </Button>
              <Button variant="ghost" size="icon-sm" aria-label="Close case file" onClick={onClose}>
                <XIcon className="size-4" aria-hidden="true" />
              </Button>
            </div>
          ) : null}
        </div>
        <RecordFields lead={data} />
      </header>

      <div className="grid flex-1 content-start gap-10 px-7 py-7">
        {data.exclusion_reasons.length > 0 ? <ExclusionNote reasons={data.exclusion_reasons} /> : null}

        <section aria-labelledby="proof-heading" className="grid gap-4">
          <SectionHeading id="proof-heading">The proof</SectionHeading>
          {data.proof ? (
            <ProofQuote proof={data.proof} size="title" animate />
          ) : (
            <p className="text-body text-slate">
              No open signal yet. Proof appears here when the engine reads one on the firm&apos;s own site.
            </p>
          )}
        </section>

        <PeopleSection lead={data} />

        <DraftSequence
          drafts={drafts.data}
          isPending={drafts.isPending}
          isError={drafts.isError}
          expand={mode === "page" ? "all" : "first"}
        />

        <RecordSection lead={data} />

        <ScoreBreakdown lead={data} />
      </div>

      <footer className="sticky bottom-0 z-10 border-t border-rule bg-sheet px-7 py-3">
        <OutcomeBar ref={bar} lead={data} />
      </footer>
    </article>
  );
}
