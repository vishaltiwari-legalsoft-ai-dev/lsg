"use client";

import Link from "next/link";

import { Panel, SectionHeading } from "@/components/layout/panel";
import { AlertStateBadge } from "@/components/record/status-badge";
import { TitleBar } from "@/components/shell/title-bar";
import { ErrorState } from "@/components/states/error-state";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOverview } from "@/lib/api/hooks";
import type { OverviewResponse, PipelineStep, Stage, StageCount } from "@/lib/api/types";
import { formatCount, formatDateTime } from "@/lib/format";
import { PRIORITY_HINT, PRIORITY_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

/* ── The story ──────────────────────────────────────────────────────────── */

function Hero({ data }: { data: OverviewResponse }) {
  const by = Object.fromEntries(data.steps.map((s) => [s.key, s])) as Record<PipelineStep["key"], PipelineStep>;
  const stage = Object.fromEntries(data.stages.map((s) => [s.stage, s.count])) as Record<Stage, number>;
  const running = data.running.length;
  return (
    <section aria-labelledby="hero-heading" className="grid max-w-[64rem] gap-6">
      <h1 id="hero-heading" className="max-w-[22ch] text-display font-medium text-ink">
        Law firms that need support staff — found, proven, and ready to write to.
      </h1>
      <p className="max-w-[62ch] text-section leading-relaxed text-slate">
        The engine reads each firm&apos;s own website, tiers it by fit, reads urgency from its pain,
        finds the owner or office manager with an address, and drafts the outreach. You decide; it
        does the reading.
      </p>
      <p className="flex flex-wrap gap-x-5 gap-y-1 text-body text-ink tabular-nums">
        <span>
          <strong className="font-medium">{formatCount(by.lists.count)}</strong> firms on file
        </span>
        <span>
          <strong className="font-medium">{formatCount(by.research.count)}</strong> researched
        </span>
        <span>
          <strong className="font-medium">{formatCount(stage.ready)}</strong> ready to reach
        </span>
        <span>
          <strong className="font-medium">{formatCount(stage.needs_review + stage.needs_contact + stage.replied)}</strong>{" "}
          waiting for you
        </span>
        <span className={cn(running > 0 ? "text-cobalt" : "text-slate")}>
          {running > 0 ? `${running} job${running === 1 ? "" : "s"} running now` : "Nothing running now"}
        </span>
      </p>
      <div className="flex flex-wrap gap-2">
        <Link href="/leads?stage=needs_review" className={buttonVariants({ variant: "primary", size: "lg" })}>
          Open the work queue
        </Link>
        <Link href="/imports" className={buttonVariants({ variant: "secondary", size: "lg" })}>
          Upload a list
        </Link>
      </div>
    </section>
  );
}

/* ── The pipeline: five stations on one track ───────────────────────────── */

function Station({ step }: { step: PipelineStep }) {
  const live = step.count > 0;
  return (
    <li className="relative grid content-start gap-3 md:pr-6">
      <span
        aria-hidden="true"
        className={cn(
          "relative z-10 flex size-8 items-center justify-center rounded-full border-2 bg-sheet text-table font-medium tabular-nums",
          live ? "border-cobalt text-cobalt" : "border-rule-strong text-slate",
        )}
      >
        {step.number}
      </span>
      <div className="grid gap-0.5">
        <h3 className="text-section font-medium text-ink">
          <span className="sr-only">Step {step.number}: </span>
          {step.label}
        </h3>
        <p className="text-figure font-medium text-ink tabular-nums">{formatCount(step.count)}</p>
        <p className="text-meta text-slate">{step.count_label}</p>
      </div>
      <p className="text-table text-slate">{step.detail}</p>
      <p className="text-body text-ink">{step.what}</p>
      <Link href={step.href} className="text-table text-cobalt hover:underline">
        Open {step.label.toLowerCase()}
      </Link>
    </li>
  );
}

function Pipeline({ steps }: { steps: PipelineStep[] }) {
  return (
    <section aria-labelledby="pipeline-heading" className="grid gap-6">
      <SectionHeading id="pipeline-heading">How it works — five steps, left to right</SectionHeading>
      <ol className="relative grid gap-8 md:grid-cols-5 md:gap-4">
        <span aria-hidden="true" className="absolute top-4 right-8 left-0 hidden h-px bg-rule-strong md:block" />
        {steps.map((step) => (
          <Station key={step.key} step={step} />
        ))}
      </ol>
    </section>
  );
}

/* ── What needs a person ────────────────────────────────────────────────── */

const HUMAN_STAGES: Stage[] = ["needs_review", "needs_contact", "ready", "replied"];

function NeedsYou({ data }: { data: OverviewResponse }) {
  const stages = Object.fromEntries(data.stages.map((s) => [s.stage, s])) as Record<Stage, StageCount>;
  const { queues, alerts } = data.attention;
  const firing = alerts.filter((a) => a.state === "firing");
  return (
    <section aria-labelledby="needs-heading" className="grid gap-5">
      <SectionHeading id="needs-heading">What needs a person</SectionHeading>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel className="divide-y divide-rule">
          {HUMAN_STAGES.map((key) => {
            const s = stages[key];
            return (
              <Link
                key={key}
                href={`/leads?stage=${key}`}
                className="grid grid-cols-[5rem_minmax(0,1fr)] items-baseline gap-4 px-6 py-4 transition-colors hover:bg-paper"
              >
                <span className="text-figure font-medium text-ink tabular-nums">{formatCount(s.count)}</span>
                <span className="grid gap-0.5">
                  <span className="text-body font-medium text-ink">{s.label}</span>
                  <span className="text-table text-slate">{s.help}</span>
                </span>
              </Link>
            );
          })}
        </Panel>
        <div className="grid content-start gap-5">
          <Panel className="grid gap-3 px-6 py-5">
            <h3 className="text-meta text-slate">Checks waiting</h3>
            <dl className="grid gap-2">
              <Row label="Accuracy check — 50 firms read by the engine, checked by hand" href="/review/handcheck" n={queues.handcheck} />
              <Row label="Conflicting claims to settle" n={queues.conflicts} />
              <Row label="Possible duplicate firms" n={queues.identity} />
              <Row label="Agency postings to confirm" n={queues.agency} />
            </dl>
          </Panel>
          {firing.length > 0 ? (
            <Panel className="grid gap-3 px-6 py-5">
              <h3 className="text-meta text-slate">Alerts</h3>
              <ul className="grid gap-2">
                {firing.map((a) => (
                  <li key={a.name} className="grid grid-cols-[4.75rem_minmax(0,1fr)] items-baseline gap-3">
                    <AlertStateBadge state={a.state} />
                    <span className="grid min-w-0 gap-0.5 text-body text-ink">
                      <span>{a.label}</span>
                      <span className="line-clamp-2 text-table text-slate" title={a.detail}>
                        {a.detail}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function Row({ label, n, href }: { label: string; n: number; href?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-body text-ink">
        {href ? (
          <Link href={href} className="text-cobalt hover:underline">
            {label}
          </Link>
        ) : (
          label
        )}
      </dt>
      <dd className="text-body text-ink tabular-nums">{formatCount(n)}</dd>
    </div>
  );
}

/* ── What the engine is doing ───────────────────────────────────────────── */

function Engine({ data }: { data: OverviewResponse }) {
  const { running, last_runs, lists } = data;
  return (
    <section aria-labelledby="engine-heading" className="grid gap-5">
      <SectionHeading id="engine-heading">The engine</SectionHeading>
      <div className="grid gap-5 lg:grid-cols-3">
        <Panel className="grid content-start gap-3 px-6 py-5">
          <h3 className="text-meta text-slate">Running now</h3>
          {running.length === 0 ? (
            <p className="text-body text-slate">
              Nothing. Research a firm from its page, or several from the work queue.
            </p>
          ) : (
            <ul className="grid gap-2">
              {running.map((job) => (
                <li key={job.id} className="grid gap-0.5">
                  <Link href={`/firms/${job.firm_id}`} className="text-body text-cobalt hover:underline">
                    {job.firm_name}
                  </Link>
                  <span className="text-table text-slate tabular-nums">
                    {job.kind === "research" ? "Researching the site" : "Finding people and addresses"} —{" "}
                    {job.done_steps} of {job.total_steps} steps
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel className="grid content-start gap-3 px-6 py-5">
          <h3 className="text-meta text-slate">Recent runs</h3>
          {last_runs.length === 0 ? (
            <p className="text-body text-slate">No runs in the last week.</p>
          ) : (
            <ul className="grid gap-1.5">
              {last_runs.slice(0, 8).map((run) => (
                <li key={run.component} className="flex items-baseline justify-between gap-3 text-table">
                  <span className="text-ink">{run.label}</span>
                  <span className="shrink-0 text-slate tabular-nums">
                    {formatCount(run.processed)} · {formatDateTime(run.finished_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel className="grid content-start gap-3 px-6 py-5">
          <h3 className="text-meta text-slate">Lists</h3>
          {lists.count === 0 ? (
            <p className="text-body text-slate">No sheet uploaded yet.</p>
          ) : (
            <p className="text-body text-ink tabular-nums">
              {formatCount(lists.count)} {lists.count === 1 ? "sheet" : "sheets"}, {formatCount(lists.rows)} rows.
              {lists.latest_file ? (
                <span className="block text-table text-slate">
                  Latest: {lists.latest_file} ({lists.latest_status}
                  {lists.latest_at ? `, ${formatDateTime(lists.latest_at)}` : ""})
                </span>
              ) : null}
            </p>
          )}
          <Link href="/imports" className="text-table text-cobalt hover:underline">
            Open lists
          </Link>
        </Panel>
      </div>
    </section>
  );
}

/* ── Reading the screens ────────────────────────────────────────────────── */

const GLOSSARY: { term: string; means: string }[] = [
  { term: "Stage", means: "Where a lead is as a person works it: researching, needs a decision, needs a person, ready to reach, in outreach, replied, parked, closed." },
  { term: "Next action", means: "The one thing to do for that lead now, in words." },
  { term: "Priority", means: `${PRIORITY_LABEL.STRIKE}: ${PRIORITY_HINT.STRIKE} ${PRIORITY_LABEL.SEQUENCE}: ${PRIORITY_HINT.SEQUENCE} ${PRIORITY_LABEL.NURTURE}: ${PRIORITY_HINT.NURTURE} ${PRIORITY_LABEL.HOLD}: ${PRIORITY_HINT.HOLD}` },
  { term: "Why now", means: "The evidence the engine read on the firm's own site — an open role, no support staff listed, no way to take a lead after hours, reviews about unreturned calls. Marked in yellow, always with its source." },
  { term: "Tier", means: "Fit by the record: 1A is a contingency personal-injury firm of two to twelve attorneys, the sweet spot. Lower tiers fit less; DQ means disqualified by rule." },
  { term: "Fit, Urgency, Competition", means: "Fit is how well the firm matches (0–50). Urgency is how strong and fresh its signals are (0–50). Competition is how many others are likely chasing the same signal." },
  { term: "Unverified", means: "An address read off a page, found by search, or minted from the firm's pattern. Real enough to write to by hand; not yet checked by a verifier." },
];

function Glossary() {
  return (
    <section aria-labelledby="glossary-heading" className="grid gap-5">
      <SectionHeading id="glossary-heading">Reading the screens</SectionHeading>
      <dl className="grid gap-x-10 gap-y-4 md:grid-cols-2">
        {GLOSSARY.map((g) => (
          <div key={g.term} className="grid gap-1 border-l-2 border-rule pl-4">
            <dt className="text-body font-medium text-ink">{g.term}</dt>
            <dd className="text-body text-slate">{g.means}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function HomeSkeleton() {
  return (
    <div className="grid gap-12" aria-busy="true" aria-label="Loading">
      <div className="grid gap-4">
        <Skeleton className="h-10 w-3/4 max-w-[40rem]" />
        <Skeleton className="h-10 w-1/2 max-w-[28rem]" />
        <Skeleton className="h-5 w-2/3 max-w-[36rem]" />
      </div>
      <div className="grid gap-4 md:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-44" />
        ))}
      </div>
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

/** The home page: what the engine does, as five steps with live numbers. */
export function HomeScreen() {
  const overview = useOverview();
  return (
    <>
      <TitleBar title="Home" meta="What the engine does, and where things stand" />
      <div className="grid max-w-[76rem] gap-14 px-8 pt-10 pb-20">
        {overview.isPending ? (
          <HomeSkeleton />
        ) : overview.isError ? (
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        ) : (
          <>
            <Hero data={overview.data} />
            <Pipeline steps={overview.data.steps} />
            <NeedsYou data={overview.data} />
            <Engine data={overview.data} />
            <Glossary />
          </>
        )}
      </div>
    </>
  );
}
