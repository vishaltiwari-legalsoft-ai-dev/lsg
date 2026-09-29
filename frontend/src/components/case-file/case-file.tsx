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
import { BusinessListing } from "@/components/record/business-listing";
import { PainAnalysis } from "@/components/record/pain-analysis";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isShortcutBlocked, useKeydown } from "@/hooks/use-keydown";
import { useDrafts, useLead } from "@/lib/api/hooks";
import type { LeadDetail } from "@/lib/api/types";
import { formatPlace } from "@/lib/format";
import { PRIORITY_HINT, PRIORITY_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { ActionBar } from "./action-bar";
import { DraftSequence } from "./draft-sequence";
import { JobProgress } from "./job-progress";
import { NotesSection } from "./notes";
import { OutcomeBar, type OutcomeBarHandle } from "./outcome-bar";
import { PeopleSection } from "./people";
import { RecordSection } from "./record-timeline";
import { ScoreBreakdown } from "./score-breakdown";

type Mode = "panel" | "page";

function ExclusionNote({ reasons }: { reasons: string[] }) {
  return (
    <div role="note" className="grid gap-1.5 rounded-control bg-redline-wash px-4 py-3">
      <p className="text-body font-semibold text-redline">Off the email list</p>
      <ul className="grid gap-1 text-body text-ink">
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
      <Field label="Priority">
        {lead.band ? (
          <span title={PRIORITY_HINT[lead.band]}>{PRIORITY_LABEL[lead.band]}</span>
        ) : (
          <Unknown>Not scored</Unknown>
        )}
      </Field>
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
    <div className="grid gap-8 px-8 py-7" aria-busy="true" aria-label="Loading the lead">
      <div className="grid gap-3">
        {mode === "panel" ? <Skeleton className="h-7 w-2/3" /> : null}
        <Skeleton className="h-4 w-1/3" />
        <div className="mt-2 grid grid-cols-4 gap-6">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-9" />
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

function WhyNow({ lead, size }: { lead: LeadDetail; size: "title" | "proof" }) {
  return (
    <section aria-labelledby="proof-heading" className="grid gap-4">
      <SectionHeading id="proof-heading">Why now</SectionHeading>
      {lead.proof ? (
        <ProofQuote proof={lead.proof} size={size} animate />
      ) : (
        <p className="text-body text-slate">
          No live signal yet. One appears here when the engine reads an open role, a gap or a
          complaint on the firm&apos;s own site or in its reviews.
        </p>
      )}
    </section>
  );
}

/**
 * The case file: the proof, then people, drafts, the record and the score.
 * In the work queue it is one column beside the list, with the outcome bar
 * pinned to its foot. On its own page it opens into two: the reading --
 * proof, people, drafts -- on the left, and the working side -- the next
 * step, the decisions, the outcome, notes, history and numbers -- pinned on
 * the right. 1–7 record while the case file has focus (on the full page,
 * anywhere on the page).
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
  const draftSection = (
    <DraftSequence
      drafts={drafts.data}
      isPending={drafts.isPending}
      isError={drafts.isError}
      expand="first"
      band={data.band}
      leadId={data.id}
    />
  );

  if (mode === "page") {
    return (
      <article
        data-casefile=""
        aria-label="Lead"
        className="group/casefile grid flex-1 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,26rem)]"
      >
        <div className="grid min-w-0 content-start gap-11 px-8 pt-7 pb-16 max-md:px-4">
          <RecordFields lead={data} />
          {data.job ? <JobProgress job={data.job} leadId={data.id} /> : null}
          {data.exclusion_reasons.length > 0 ? <ExclusionNote reasons={data.exclusion_reasons} /> : null}
          <WhyNow lead={data} size="title" />
          {data.pain ? <PainAnalysis pain={data.pain} /> : null}
          <BusinessListing listing={data.listing} listingNote={data.listing_note} reviews={data.reviews} />
          <PeopleSection lead={data} />
          {draftSection}
        </div>

        {/* The tinted side runs the full height; its contents stay in view as the drafts scroll. */}
        <aside aria-label="Work this lead" className="border-rule bg-paper/70 max-xl:border-t xl:border-l">
          <div className="grid content-start gap-9 px-7 pt-7 pb-12 xl:sticky xl:top-0 xl:max-h-dvh xl:overflow-y-auto">
            <section aria-label="Next step and decisions" className="grid gap-5">
              <ActionBar lead={data} layout="stack" />
              <div className="border-t border-rule pt-4">
                <OutcomeBar ref={bar} lead={data} layout="stack" />
              </div>
            </section>
            <NotesSection lead={data} />
            <RecordSection lead={data} />
            <ScoreBreakdown lead={data} />
          </div>
        </aside>
      </article>
    );
  }

  return (
    <article
      data-casefile=""
      aria-labelledby={titleId}
      className="group/casefile flex min-h-full flex-col"
    >
      <header className="grid grid-cols-[minmax(0,1fr)] gap-4 border-b border-rule px-7 pt-6 pb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="grid min-w-0 gap-1.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <h2 id={titleId} className="caption min-w-0 truncate text-caption-sm text-ink">
                {data.firm.name}
              </h2>
              <TierMark firm={data.firm} />
            </div>
            <p className="text-body text-slate">{data.state_display}</p>
          </div>
          <div className="-mr-2 flex shrink-0 items-center gap-1">
            <Button asChild variant="ghost" size="sm">
              <Link href={`/leads/${id}`}>Open full page</Link>
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Close the lead" onClick={onClose}>
              <XIcon className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
        <RecordFields lead={data} />
        <ActionBar lead={data} layout="row" />
      </header>

      <div className="grid flex-1 content-start gap-10 px-7 py-7">
        {data.job ? <JobProgress job={data.job} leadId={data.id} /> : null}
        {data.exclusion_reasons.length > 0 ? <ExclusionNote reasons={data.exclusion_reasons} /> : null}
        <WhyNow lead={data} size="title" />
        <PeopleSection lead={data} />
        {draftSection}
        <NotesSection lead={data} />
        <RecordSection lead={data} />
        <ScoreBreakdown lead={data} />
      </div>

      <footer className={cn("sticky bottom-0 z-10 border-t border-rule bg-sheet px-7 py-3")}>
        <OutcomeBar ref={bar} lead={data} layout="row" />
      </footer>
    </article>
  );
}
