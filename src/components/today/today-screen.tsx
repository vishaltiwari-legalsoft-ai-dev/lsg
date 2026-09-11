"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { CopyButton, emailText } from "@/components/copy-button";
import { DocketTable } from "@/components/leads/docket-table";
import { Panel, SectionHeading } from "@/components/layout/panel";
import { Quotation, SourceCite } from "@/components/record/proof-quote";
import { AlertStateBadge, EmailStatusBadge, StatusBadge } from "@/components/record/status-badge";
import { TierMark } from "@/components/record/tier-mark";
import { Unknown } from "@/components/record/unknown";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLead, useToday } from "@/lib/api/hooks";
import type { AlertState, LeadRow, ReviewQueueCounts, TodayResponse } from "@/lib/api/types";
import { formatCount, formatPlace } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function useTodayLabel() {
  return useSyncExternalStore(
    () => () => {},
    () => {
      const d = new Date();
      return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
    },
    () => "",
  );
}

/** Who to write to. When only an attorney was found, say so — honestly. */
function WriteTo({ lead }: { lead: LeadRow }) {
  const detail = useLead(lead.contact ? null : lead.id);
  const contact = lead.contact;

  if (contact) {
    return (
      <div className="grid gap-1.5">
        <p className="text-body font-medium text-ink">{contact.full_name}</p>
        <p className="text-table text-slate">{contact.title ?? ROLE_LABEL[contact.role]}</p>
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          {contact.email ? (
            <a href={`mailto:${contact.email}`} className="text-table text-cobalt hover:underline">
              {contact.email}
            </a>
          ) : (
            <Unknown className="text-table">No email found</Unknown>
          )}
          <EmailStatusBadge contact={contact} />
        </div>
      </div>
    );
  }

  const others = detail.data?.contacts ?? [];
  return (
    <div className="grid gap-1.5">
      <Unknown className="text-body">No owner or office manager found yet.</Unknown>
      {others.length > 0 ? (
        <p className="text-table text-slate">
          {others.length === 1 ? "The only person found is " : "People found so far: "}
          {others.map((c, i) => (
            <span key={c.id}>
              {i > 0 ? "; " : ""}
              <span className="text-ink">{c.full_name}</span>
              {c.title ? `, ${c.title}` : ""}
            </span>
          ))}
          .
        </p>
      ) : null}
    </div>
  );
}

function TopProof({ data }: { data: TodayResponse }) {
  const lead = data.top_proof!;
  const proof = lead.proof!;
  const draft = data.first_draft;
  const place = formatPlace(lead.firm.city, lead.firm.state);

  return (
    <Panel aria-labelledby="top-proof-firm" className="grid overflow-hidden xl:grid-cols-[minmax(0,1fr)_21rem]">
      <figure className="grid content-between gap-10 px-10 pt-9 pb-9">
        <div className="grid gap-7">
          <div className="grid gap-1.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 id="top-proof-firm" className="text-title font-medium text-ink">
                <Link href={`/leads/${lead.id}`} className="hover:underline">
                  {lead.firm.name}
                </Link>
              </h2>
              <TierMark firm={lead.firm} />
            </div>
            <p className="text-body text-slate">
              {[lead.firm.practice_display, place].filter(Boolean).join(", ")}
            </p>
          </div>
          <div className="grid gap-4">
            <p className="text-body text-ink">{proof.headline}</p>
            {proof.quote ? <Quotation key={proof.signal_id} text={proof.quote} size="proof" animate /> : null}
          </div>
        </div>
        {/* The pinpoint citation sits at the foot, like a footnote on a record page. */}
        <figcaption className="border-t border-rule pt-5">
          <SourceCite proof={proof} />
        </figcaption>
      </figure>

      <aside
        aria-label="Write to this firm"
        className="grid content-start gap-7 border-rule bg-sheet px-8 pt-9 pb-9 max-xl:border-t xl:border-l"
      >
        <div className="grid gap-2">
          <h3 className="text-meta text-slate">Write to</h3>
          <WriteTo lead={lead} />
        </div>

        {draft ? (
          <div className="grid gap-2">
            <h3 className="text-meta text-slate">First email</h3>
            <p className="quotation text-quote text-ink">
              <span className="sr-only">Subject: </span>
              {draft.subject}
            </p>
          </div>
        ) : (
          <p className="text-body text-slate">
            No first draft for this lead. Write it by hand from the proof, then record the outcome.
          </p>
        )}

        <div className="grid gap-2.5">
          {draft ? (
            <CopyButton
              variant="primary"
              size="lg"
              label="Copy first email"
              toastText="Copied first email"
              text={emailText(draft.subject, draft.body)}
              className="w-full"
            />
          ) : null}
          <Link
            href={`/leads?lead=${encodeURIComponent(lead.id)}`}
            className={cn(buttonVariants({ variant: "secondary", size: "lg" }), "w-full")}
          >
            Open case file
          </Link>
        </div>
      </aside>
    </Panel>
  );
}

const ALERT_ORDER: Record<AlertState, number> = { firing: 0, no_data: 1, ok: 2 };

/** Alert details can run long (a list of hosts); show two lines, the rest on request. */
function AlertDetail({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 150;
  return (
    <span className="block text-table text-slate">
      <span className={cn("block", long && !open && "line-clamp-2")}>{text}</span>
      {long ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="mt-0.5 text-meta text-cobalt hover:underline"
        >
          {open ? "Show less" : "Show all"}
        </button>
      ) : null}
    </span>
  );
}

const QUEUES: { key: keyof ReviewQueueCounts; label: string; href?: string }[] = [
  { key: "handcheck", label: "Hand-check, gate G2", href: "/review/handcheck" },
  { key: "conflicts", label: "Conflicting claims to settle" },
  { key: "identity", label: "Possible duplicate firms" },
  { key: "agency", label: "Agency postings to confirm" },
  { key: "discovery", label: "New firms found in postings" },
];

function Attention({ data }: { data: TodayResponse }) {
  const { alerts, queues, bench, providers_inert } = data.attention;
  const sorted = [...alerts].sort((a, b) => ALERT_ORDER[a.state] - ALERT_ORDER[b.state]);
  const benchProblem = bench.skus_available === 0 || bench.stale;

  return (
    <section aria-labelledby="attention-heading" className="grid gap-4">
      <SectionHeading id="attention-heading">Needs attention</SectionHeading>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Panel aria-labelledby="alerts-heading" className="px-6 pt-5 pb-3">
          <h3 id="alerts-heading" className="pb-2 text-meta text-slate">
            Alerts
          </h3>
          {sorted.length === 0 ? (
            <p className="py-3 text-body text-slate">No alerts are registered with the engine.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {sorted.map((alert) => (
                <li key={alert.name} className="grid grid-cols-[4.75rem_minmax(0,1fr)] items-baseline gap-3 py-3">
                  <span>
                    <AlertStateBadge state={alert.state} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-body text-ink">{alert.label}</span>
                    <AlertDetail text={alert.detail} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid content-start gap-5">
          <Panel aria-labelledby="queues-heading" className="px-6 pt-5 pb-3">
            <h3 id="queues-heading" className="pb-2 text-meta text-slate">
              Waiting for a person
            </h3>
            <dl className="divide-y divide-rule">
              {QUEUES.map((q) => (
                <div key={q.key} className="flex items-baseline justify-between gap-4 py-2.5">
                  <dt className="text-body text-ink">
                    {q.href ? (
                      <Link href={q.href} className="text-cobalt hover:underline">
                        {q.label}
                      </Link>
                    ) : (
                      q.label
                    )}
                  </dt>
                  <dd className="text-body text-ink tabular-nums">{formatCount(queues[q.key])}</dd>
                </div>
              ))}
            </dl>
          </Panel>

          <Panel aria-labelledby="bench-heading" className="grid gap-3 px-6 py-5">
            <div className="flex items-baseline justify-between gap-4">
              <h3 id="bench-heading" className="text-meta text-slate">
                Bench
              </h3>
              <StatusBadge state={benchProblem ? "firing" : "ok"}>
                {bench.skus_available === 0 ? "Empty" : bench.stale ? "Stale" : "Current"}
              </StatusBadge>
            </div>
            <p className="text-body text-ink">{bench.message}</p>
            <p className="text-table text-slate tabular-nums">
              {formatCount(bench.skus_available)} {bench.skus_available === 1 ? "person" : "people"} available
              {bench.stale ? ", and the inventory is out of date" : ""}.
            </p>
            {providers_inert.length > 0 ? (
              <div className="grid gap-1 border-t border-rule pt-3">
                <h4 className="text-meta text-slate">Not configured</h4>
                <p className="text-body text-ink">{providers_inert.join(", ")}</p>
                <p className="text-table text-slate">
                  These steps are skipped until a key is set on the engine.
                </p>
              </div>
            ) : null}
          </Panel>
        </div>
      </div>
    </section>
  );
}

function OtherStrike({ rows }: { rows: LeadRow[] }) {
  const router = useRouter();
  return (
    <section aria-labelledby="strike-heading" className="grid gap-4">
      <SectionHeading
        id="strike-heading"
        aside={
          rows.length > 0 ? (
            <Link href="/leads" className="text-cobalt hover:underline">
              Open in Leads
            </Link>
          ) : undefined
        }
      >
        Other STRIKE leads
        {rows.length > 0 ? (
          <span className="ml-2 text-body font-normal text-slate tabular-nums">{rows.length}</span>
        ) : null}
      </SectionHeading>
      {rows.length === 0 ? (
        <p className="text-body text-slate">
          No other STRIKE leads right now. New ones appear after the next careers sweep.
        </p>
      ) : (
        <Panel className="overflow-hidden">
          <DocketTable
            rows={rows}
            selectedId={null}
            compact={false}
            onSelect={(id) => router.push(`/leads?lead=${encodeURIComponent(id)}`)}
            caption="Other STRIKE leads. Select one to open its case file."
          />
        </Panel>
      )}
    </section>
  );
}

function TodaySkeleton() {
  return (
    <div className="grid gap-12" aria-busy="true" aria-label="Loading today">
      <div className="grid overflow-hidden rounded-panel border border-rule bg-sheet xl:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="grid gap-5 px-10 pt-9 pb-10">
          <Skeleton className="h-6 w-80" />
          <Skeleton className="h-4 w-56" />
          <div className="mt-4 grid gap-3">
            <Skeleton className="h-9 w-full max-w-[40rem]" />
            <Skeleton className="h-9 w-2/3 max-w-[30rem]" />
          </div>
          <div className="mt-2 flex gap-8">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-8 w-40" />
          </div>
        </div>
        <div className="grid content-start gap-5 border-rule px-8 pt-9 pb-10 max-xl:border-t xl:border-l">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
      <div className="grid gap-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    </div>
  );
}

export function TodayScreen() {
  const today = useToday();
  const dateLabel = useTodayLabel();

  return (
    <>
      <TitleBar title="Today" meta={dateLabel || undefined} />
      <div className="grid max-w-[76rem] gap-12 px-8 pt-8 pb-16">
        {today.isPending ? (
          <TodaySkeleton />
        ) : today.isError ? (
          <ErrorState error={today.error} onRetry={() => void today.refetch()} />
        ) : (
          <>
            {today.data.top_proof?.proof ? (
              <TopProof data={today.data} />
            ) : (
              <Panel className="px-10">
                <EmptyState title="No STRIKE leads yet.">
                  They appear once the probe&apos;s careers sweep finds an open role.
                </EmptyState>
              </Panel>
            )}
            {today.data.top_proof ? <OtherStrike rows={today.data.strike} /> : null}
            <Attention data={today.data} />
          </>
        )}
      </div>
    </>
  );
}
