"use client";

import Link from "next/link";
import { useState } from "react";

import { CopyButton, emailText } from "@/components/copy-button";
import { SectionHeading } from "@/components/layout/panel";
import { Quotation, SourceCite } from "@/components/record/proof-quote";
import { AlertStateBadge, EmailStatusBadge } from "@/components/record/status-badge";
import { TierMark } from "@/components/record/tier-mark";
import { Unknown } from "@/components/record/unknown";
import { NAV_STEPS } from "@/components/shell/nav";
import { TitleBar } from "@/components/shell/title-bar";
import { ErrorState } from "@/components/states/error-state";
import { SetupNotice } from "@/components/states/setup-notice";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLead, useOverview, useToday } from "@/lib/api/hooks";
import type {
  FirstDraft,
  LeadRow,
  OverviewResponse,
  PipelineStep,
  Stage,
  StageCount,
  TodayResponse,
} from "@/lib/api/types";
import { formatCount, formatDateTime, formatPlace } from "@/lib/format";
import { PRIORITY_HINT, PRIORITY_LABEL, ROLE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { BuiltSoFar } from "./built-so-far";
import { CaseFileDemo } from "./case-file-demo";

function stepsByKey(data: OverviewResponse) {
  return Object.fromEntries(data.steps.map((s) => [s.key, s])) as Record<PipelineStep["key"], PipelineStep>;
}

function stageCounts(data: OverviewResponse) {
  return Object.fromEntries(data.stages.map((s) => [s.stage, s.count])) as Record<Stage, number>;
}

/* ── The hero: the strongest proof in the system, or -- before there is any --
      what the engine makes of one row on a sheet ─────────────────────────── */

/** Who to write to. When only an attorney was found, say so -- honestly. */
function WriteTo({ lead }: { lead: LeadRow }) {
  const detail = useLead(lead.contact ? null : lead.id);
  const contact = lead.contact;

  if (contact) {
    return (
      <div className="grid gap-1.5">
        <p className="text-section font-semibold text-ink">{contact.full_name}</p>
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

function ProofHero({ lead, draft }: { lead: LeadRow; draft: FirstDraft | null }) {
  const proof = lead.proof!;
  const place = formatPlace(lead.firm.city, lead.firm.state);
  return (
    <section
      aria-labelledby="proof-hero-heading"
      className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_19rem] xl:gap-14"
    >
      <figure className="grid content-start gap-7">
        <h2 id="proof-hero-heading" className="text-section font-semibold text-ink">
          The strongest proof right now
        </h2>
        {proof.quote ? (
          <Quotation key={proof.signal_id} text={proof.quote} size="proof" animate />
        ) : (
          <p className="max-w-[40ch] text-headline text-ink">{proof.headline}</p>
        )}
        <figcaption className="grid gap-5 border-t border-rule pt-5">
          <div className="grid gap-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <Link href={`/leads/${lead.id}`} className="caption text-caption-sm text-ink hover:underline">
                {lead.firm.name}
              </Link>
              <TierMark firm={lead.firm} />
            </div>
            <p className="text-body text-slate">
              {proof.headline}
              {place ? `, in ${place}` : ""}
            </p>
          </div>
          <SourceCite proof={proof} />
        </figcaption>
      </figure>

      <aside
        aria-label="Write to this firm"
        className="grid content-start gap-7 border-rule max-xl:border-t max-xl:pt-7 xl:border-l xl:pl-10"
      >
        <div className="grid gap-2">
          <h3 className="text-meta font-medium text-slate">Write to</h3>
          <WriteTo lead={lead} />
        </div>
        {draft ? (
          <div className="grid gap-2">
            <h3 className="text-meta font-medium text-slate">First email</h3>
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
        <div className="grid gap-2">
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
          <Link href={`/leads/${lead.id}`} className={cn(buttonVariants({ variant: "secondary", size: "lg" }), "w-full")}>
            Open the lead
          </Link>
        </div>
      </aside>
    </section>
  );
}

function PitchHero({ data }: { data: OverviewResponse }) {
  const empty = stepsByKey(data).lists.count === 0;
  return (
    <section
      aria-labelledby="hero-heading"
      // Top-aligned: the demo grows as it plays, and a centred headline would drift with it.
      className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start lg:gap-14"
    >
      <div className="grid content-start gap-6">
        <h2
          id="hero-heading"
          className="type-narrow max-w-[15ch] text-display font-semibold tracking-[-0.015em] text-ink"
        >
          Law firms that need support staff, found and proven.
        </h2>
        <p className="max-w-[50ch] text-section leading-relaxed text-slate">
          Give it a sheet of firms. It reads each firm&apos;s own website, finds the sentence that shows the
          need, names the owner or office manager with a checked address, and drafts the first email. You
          decide; it does the reading.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/imports" className={buttonVariants({ variant: "primary", size: "lg" })}>
            Upload a sheet
          </Link>
          {!empty ? (
            <Link href="/leads" className={buttonVariants({ variant: "secondary", size: "lg" })}>
              Open the work queue
            </Link>
          ) : null}
          <a href="#how-to" className={cn(buttonVariants({ variant: "link", size: "lg" }), "ml-1")}>
            How to use it
          </a>
        </div>
        <p className="max-w-[56ch] text-table text-slate">
          {empty
            ? "Nothing is loaded yet. Any layout of sheet works: a firm name, and a website, email or location, is all it needs."
            : "No firm shows a live signal yet. Research some from the work queue and the strongest proof takes this place."}
        </p>
      </div>
      <div className="grid gap-2">
        <CaseFileDemo play />
        <p className="text-meta text-slate">What the engine makes of one row on a sheet. An invented firm.</p>
      </div>
    </section>
  );
}

/* ── The three steps of the brief, with live numbers ─────────────────────── */

interface StepFigure {
  n: number;
  label: string;
}

function StepColumn({
  step,
  what,
  figures,
  detail,
  action,
  primary,
}: {
  step: (typeof NAV_STEPS)[number];
  what: string;
  figures: StepFigure[];
  detail: string | null;
  action: { href: string; label: string };
  primary: boolean;
}) {
  return (
    <li className="grid content-start gap-5 border-rule px-7 py-7 first:pl-0 max-md:border-t max-md:px-0 max-md:first:border-t-0 md:row-span-6 md:grid-rows-subgrid md:border-l md:first:border-l-0">
      <div className="flex items-baseline gap-3">
        <span aria-hidden="true" className="type-narrow text-display leading-none font-semibold text-cobalt tabular-nums">
          {step.step}
        </span>
        <h3 className="text-section font-semibold text-ink">
          <span className="sr-only">Step {step.step}: </span>
          {step.label}
        </h3>
      </div>
      <p className="max-w-[40ch] text-body text-slate">{what}</p>
      <dl className="flex flex-wrap gap-x-7 gap-y-3">
        {figures.map((f) => (
          <div key={f.label} className="grid gap-1">
            <dt className="order-2 text-meta text-slate">{f.label}</dt>
            <dd className="type-narrow order-1 text-figure font-semibold text-ink tabular-nums">{formatCount(f.n)}</dd>
          </div>
        ))}
      </dl>
      {detail ? <p className="text-table text-slate">{detail}</p> : null}
      <ul className="grid gap-2 border-t border-rule pt-4" aria-label={`Where ${step.label.toLowerCase()} is worked`}>
        {step.items.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="group grid gap-0.5">
              <span className="text-body font-medium text-cobalt group-hover:underline">{item.label}</span>
              <span className="text-table text-slate">{item.hint}</span>
            </Link>
          </li>
        ))}
      </ul>
      <div>
        <Link href={action.href} className={buttonVariants({ variant: primary ? "primary" : "secondary", size: "md" })}>
          {action.label}
        </Link>
      </div>
    </li>
  );
}

function StepsBand({ data }: { data: OverviewResponse }) {
  const by = stepsByKey(data);
  const stage = stageCounts(data);
  const empty = by.lists.count === 0;
  const readyNow = stage.ready > 0;
  return (
    <section aria-labelledby="steps-heading" className="grid gap-4">
      <SectionHeading id="steps-heading" aside="Live from the engine">
        Where the three steps stand
      </SectionHeading>
      <ol className="grid border-y border-rule md:grid-cols-3 md:grid-rows-[repeat(4,auto)_1fr_auto]">
        <StepColumn
          step={NAV_STEPS[0]}
          what="A sheet in any layout comes in. The engine reads its columns, checks every website, and searches for the ones that are wrong."
          figures={[
            { n: data.lists.count, label: data.lists.count === 1 ? "sheet" : "sheets" },
            { n: data.lists.rows, label: "rows" },
            { n: by.lists.count, label: "firms on file" },
          ]}
          detail={empty ? null : by.lists.detail}
          action={{ href: "/imports", label: "Upload a sheet" }}
          primary={empty}
        />
        <StepColumn
          step={NAV_STEPS[1]}
          what="Each firm's site is read: the people and their titles, the fee promise, the practice, what the site lacks. Then the web is searched for profiles, listings and addresses, and the addresses are checked."
          figures={[
            { n: by.research.count, label: "firms researched" },
            { n: by.qualify.count, label: "firms tiered" },
            { n: by.people.count, label: "people named" },
          ]}
          detail={empty ? null : by.people.detail}
          action={{ href: "/leads", label: "Open the work queue" }}
          primary={!empty && !readyNow}
        />
        <StepColumn
          step={NAV_STEPS[2]}
          what="A lead is ready when every step is done: a named decision-maker, a checked address, the proof and nine emails drafted. The ready ones go to a vendor as a sheet."
          figures={[
            { n: stage.ready, label: "ready to reach" },
            { n: stage.in_outreach, label: "in outreach" },
            { n: stage.replied, label: "replied" },
          ]}
          detail={null}
          action={{ href: "/qualified", label: "Open actual leads" }}
          primary={readyNow}
        />
      </ol>
    </section>
  );
}

/* ── What is waiting for a person, and what the engine is doing ─────────── */

const HUMAN_STAGES: Stage[] = ["needs_review", "needs_contact", "ready", "replied"];

function Waiting({ data }: { data: OverviewResponse }) {
  const stages = Object.fromEntries(data.stages.map((s) => [s.stage, s])) as Record<Stage, StageCount>;
  return (
    <section aria-labelledby="waiting-heading" className="grid content-start gap-4">
      <SectionHeading id="waiting-heading">Waiting for you</SectionHeading>
      <ul className="grid border-t border-rule">
        {HUMAN_STAGES.map((key) => {
          const s = stages[key];
          return (
            <li key={key} className="border-b border-rule">
              <Link
                href={`/leads?stage=${key}`}
                className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-baseline gap-4 py-3.5 pr-3 transition-colors hover:bg-paper"
              >
                <span
                  className={cn(
                    "type-narrow text-right text-figure font-semibold tabular-nums",
                    s.count > 0 ? "text-ink" : "text-slate/60",
                  )}
                >
                  {formatCount(s.count)}
                </span>
                <span className="grid gap-0.5">
                  <span className="text-body font-medium text-ink">{s.label}</span>
                  <span className="text-table text-slate">{s.help}</span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function EngineNow({ data }: { data: OverviewResponse }) {
  const { running, last_runs, attention } = data;
  const firing = attention.alerts.filter((a) => a.state === "firing");
  return (
    <section aria-labelledby="engine-heading" className="grid content-start gap-4">
      <SectionHeading id="engine-heading">The engine</SectionHeading>
      <div className="grid gap-6 border-t border-rule pt-4">
        <div className="grid gap-2">
          <h3 className="text-meta font-medium text-slate">Running now</h3>
          {running.length === 0 ? (
            <p className="text-body text-slate">
              Nothing. Research a firm from its page, or up to a hundred from the work queue.
            </p>
          ) : (
            <ul className="grid gap-2">
              {running.map((job) => (
                <li key={job.id} className="grid gap-0.5">
                  <Link href={`/firms/${job.firm_id}`} className="text-body text-cobalt hover:underline">
                    {job.firm_name}
                  </Link>
                  <span className="text-table text-slate tabular-nums">
                    {job.kind === "research" ? "Researching the site" : "Finding people and addresses"}:{" "}
                    {job.done_steps} of {job.total_steps} steps
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {firing.length > 0 ? (
          <div className="grid gap-2">
            <h3 className="text-meta font-medium text-slate">Alerts</h3>
            <ul className="grid gap-2.5">
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
          </div>
        ) : null}

        {last_runs.length > 0 ? (
          <div className="grid gap-1.5">
            <h3 className="text-meta font-medium text-slate">Last runs</h3>
            <ul className="grid gap-1">
              {last_runs.slice(0, 5).map((run) => (
                <li key={run.component} className="flex items-baseline justify-between gap-3 text-table">
                  <span className="text-ink">{run.label}</span>
                  <span className="shrink-0 text-slate tabular-nums">{formatDateTime(run.finished_at)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/* ── How to use it: six steps that drive the case file ──────────────────── */

const HOW_TO: {
  title: string;
  summary: string;
  you: string;
  engine: string;
  where: { href: string; label: string };
  takes: string;
}[] = [
  {
    title: "Upload a sheet",
    summary: "Any layout. A firm name and a way to reach the firm is all it needs.",
    you: "Drop in any sheet of firms: a vendor export, a conference list, last quarter's outreach. The AI reads the columns; you confirm the mapping, or correct a column with one click.",
    engine: "Reads the header and a dozen sample rows, says what each column is and what the sheet lacks, and lists what research will fill in for itself.",
    where: { href: "/imports", label: "Sheets" },
    takes: "Under a minute, any size of sheet.",
  },
  {
    title: "Load it",
    summary: "Rows become firms; every website is checked.",
    you: "Press Load. The screen shows progress batch by batch.",
    engine: "Collapses the same firm from two sources into one record, then checks every website: alive, this firm, or searched for when it is wrong.",
    where: { href: "/imports", label: "Sheets" },
    takes: "Minutes for a thousand rows; longer if many sites need searching for.",
  },
  {
    title: "Research the firms",
    summary: "The site read; people, addresses, profiles and the pain found.",
    you: "In the work queue, select leads (up to a hundred at a time) and choose Research sites. Or open any firm and research it alone. Keep working; it runs in the background.",
    engine: "Reads the home, about, contact, team, testimonials and careers pages; pulls out the people and their titles, the addresses, the fee promise, the practice and what the site lacks; then searches for LinkedIn profiles, business listings and addresses, and checks the decision-maker's email.",
    where: { href: "/leads", label: "Work queue" },
    takes: "The long pole: about an hour per thousand with the search key. See the questions below.",
  },
  {
    title: "Decide",
    summary: "The queue groups leads by what they need next.",
    you: "On Needs a decision: disqualify, park, qualify or assign. On Needs a person: add or correct the contact. J and K move, Enter opens, numbers record an outcome.",
    engine: "Tiers each firm by fit, reads urgency from its pain, and writes the next step on every lead in words.",
    where: { href: "/leads?stage=needs_review", label: "Work queue" },
    takes: "Your pace.",
  },
  {
    title: "Take the ready ones",
    summary: "Seven checks. Only all seven is ready.",
    you: "Actual leads shows the leads on which every step is done, and on its second tab what still holds the rest back.",
    engine: "Site read, fits the profile, decision-maker named, address on file, address verified, LinkedIn profile, journey drafted.",
    where: { href: "/qualified", label: "Actual leads" },
    takes: "Instant.",
  },
  {
    title: "Export and record",
    summary: "A sheet for the sending vendor; outcomes come back here.",
    you: "Export the ready leads. As replies come in, record the outcome on the lead: sent, replied, meeting, won, lost, opted out.",
    engine: "Drafts the nine-touch journey from the proof, keeps the lifecycle, and returns a lost lead to the pool after its cooldown with its contact intact.",
    where: { href: "/qualified", label: "Actual leads" },
    takes: "Seconds.",
  },
];

function HowTo() {
  const [step, setStep] = useState(0);
  const current = HOW_TO[step];
  return (
    <section id="how-to" aria-labelledby="how-to-heading" className="grid scroll-mt-6 gap-6">
      <SectionHeading id="how-to-heading" aside="Pick a step to see what it leaves behind">
        How to use it
      </SectionHeading>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-12">
        <div className="grid content-start gap-6">
          <ol className="grid border-y border-rule" aria-label="The six steps">
            {HOW_TO.map((s, i) => {
              const active = i === step;
              return (
                <li key={s.title} className="border-b border-rule last:border-b-0">
                  <button
                    type="button"
                    aria-current={active ? "step" : undefined}
                    onClick={() => setStep(i)}
                    className={cn(
                      "grid w-full grid-cols-[2.75rem_minmax(0,1fr)] items-baseline gap-2 py-3 pr-3 text-left transition-colors duration-100",
                      active ? "bg-cobalt-wash" : "hover:bg-paper",
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "type-narrow pl-3 text-subtitle leading-none font-semibold tabular-nums",
                        active ? "text-cobalt" : "text-slate/70",
                      )}
                    >
                      {i + 1}
                    </span>
                    <span className="grid gap-0.5">
                      <span className={cn("text-body font-semibold", active ? "text-cobalt-deep" : "text-ink")}>
                        {s.title}
                      </span>
                      <span className="text-table text-slate">{s.summary}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="grid gap-4" aria-live="polite">
            <p className="text-section font-semibold text-ink">
              {step + 1}. {current.title}
              <span className="ml-3 text-table font-normal text-slate">
                in{" "}
                <Link href={current.where.href} className="text-cobalt hover:underline">
                  {current.where.label}
                </Link>
              </span>
            </p>
            <dl className="grid gap-3">
              <div className="grid gap-1 border-l-2 border-cobalt pl-4">
                <dt className="text-meta font-medium text-slate">You</dt>
                <dd className="max-w-[62ch] text-body text-ink">{current.you}</dd>
              </div>
              <div className="grid gap-1 border-l-2 border-rule pl-4">
                <dt className="text-meta font-medium text-slate">The engine</dt>
                <dd className="max-w-[62ch] text-body text-ink">{current.engine}</dd>
              </div>
              <div className="grid gap-1 border-l-2 border-rule pl-4">
                <dt className="text-meta font-medium text-slate">Takes</dt>
                <dd className="max-w-[62ch] text-body text-ink">{current.takes}</dd>
              </div>
            </dl>
            <div className="flex gap-2">
              <button
                type="button"
                className={buttonVariants({ variant: "secondary", size: "sm" })}
                disabled={step === 0}
                onClick={() => setStep((s) => Math.max(0, s - 1))}
              >
                Previous step
              </button>
              <button
                type="button"
                className={buttonVariants({ variant: step === HOW_TO.length - 1 ? "secondary" : "primary", size: "sm" })}
                disabled={step === HOW_TO.length - 1}
                onClick={() => setStep((s) => Math.min(HOW_TO.length - 1, s + 1))}
              >
                Next step
              </button>
            </div>
          </div>
        </div>
        <div className="lg:sticky lg:top-6 lg:self-start">
          <CaseFileDemo stage={step} />
        </div>
      </div>
    </section>
  );
}

/* ── Questions: an index, and the answer beside it ──────────────────────── */

/** For a thousand leads, step by step. Paces are the engine's own settings. */
const TIMING: { step: string; time: string; why: string }[] = [
  { step: "Reading the sheet", time: "under a minute", why: "One model call for the columns; rows stream in batches." },
  { step: "Website check", time: "about 10 minutes", why: "One request per site, twelve sites at once, a polite two seconds between requests to the same site. Sites that must be searched for add a quarter second each with the search key, or 8–12 seconds each on the free engine." },
  { step: "Reading the sites", time: "40–60 minutes", why: "Up to twelve pages per firm at that same pace; slow hosts and pages that need a browser add to it." },
  { step: "Facts, fee model, practice, pain", time: "10–20 minutes", why: "Local computing over the pages already stored; no network." },
  { step: "LinkedIn, listings, addresses by search", time: "15–20 minutes", why: "Around four thousand queries at a quarter second each on Serper. On the free engine, at 8–12 seconds a query, this alone is about eleven hours, which is why the key matters." },
  { step: "Confirming addresses", time: "minutes, not hours", why: "One verifier call per candidate: the engine builds the candidates from the person's name and the firm's domain and stops at the first real one, two or three on average, about a cent each." },
];

function Timing() {
  return (
    <table className="w-full border-collapse text-left text-table">
      <thead>
        <tr className="border-b border-rule text-meta text-slate">
          <th scope="col" className="py-1.5 pr-4 font-medium">Step</th>
          <th scope="col" className="py-1.5 pr-4 font-medium">1,000 leads</th>
          <th scope="col" className="py-1.5 font-medium">What sets the pace</th>
        </tr>
      </thead>
      <tbody>
        {TIMING.map((row) => (
          <tr key={row.step} className="border-b border-rule align-top last:border-b-0">
            <td className="py-2 pr-4 text-ink">{row.step}</td>
            <td className="py-2 pr-4 whitespace-nowrap text-ink tabular-nums">{row.time}</td>
            <td className="py-2 text-slate">{row.why}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const FAQ: { q: string; short: string; a: React.ReactNode }[] = [
  {
    q: "How long does a thousand leads take?",
    short: "About two hours with the keys; a day without.",
    a: (
      <div className="grid gap-4">
        <p>
          Around two hours end to end with the search and address keys in place; most of it is reading the sites,
          which runs in the background while you work the queue. Without the keys the reading is the same but the
          searching runs on the free engine and takes the better part of a day.
        </p>
        <Timing />
        <p className="text-table">These are estimates from the engine&apos;s pacing. The first real run on your sheet replaces them with measured numbers.</p>
      </div>
    ),
  },
  {
    q: "How do I get in?",
    short: "On this machine, at localhost, no login yet.",
    a: (
      <>
        Today it runs on this machine: open <span className="text-ink">http://localhost:5000</span> with the engine
        running. The README lists the three commands: start the database, start the engine, start the app. There is
        no login yet. When it moves to a shared server, logins come first, because contacts are personal data.
      </>
    ),
  },
  {
    q: "What does a sheet need to have?",
    short: "A firm name and a way to reach the firm.",
    a: (
      <>
        A firm name, and one way to reach the firm: a website, an email address, or a location. Nothing else is
        required. Size, practice, people and addresses are marked &ldquo;filled by research&rdquo; on the Sheets screen
        rather than &ldquo;missing&rdquo;. Any layout works; the AI reads the columns and you confirm.
      </>
    ),
  },
  {
    q: "How do I research a whole list, not one firm?",
    short: "Batches of up to a hundred from the work queue.",
    a: (
      <>
        From the work queue: select leads, up to a hundred at a time, and choose Research sites; ten batches cover a
        thousand. Each batch runs in the background and the home page shows what is running. A firm&apos;s own page has
        the same buttons for one firm. A whole list can also be run in one go from the command line
        (<span className="text-ink">lge flow research</span>), which is how the first thousand will be run and measured.
      </>
    ),
  },
  {
    q: "Which keys make it work fully?",
    short: "OpenRouter, Serper, a verifier: one line each.",
    a: (
      <>
        Three, each one line in the engine&apos;s settings file. <span className="text-ink">OpenRouter</span> lets the AI
        read sheets and sites. <span className="text-ink">Serper</span> is the web search: LinkedIn profiles, Google
        Business listings, addresses in search results. A verification service,{" "}
        <span className="text-ink">NeverBounce</span> or ZeroBounce, confirms that an address exists; the engine finds
        the addresses itself, from the site, search results, the firm&apos;s pattern and the person&apos;s own name.
        Without Serper and a verifier the platform still reads sites and finds people, but no address gets confirmed
        and nothing reaches Ready on Actual leads.
      </>
    ),
  },
  {
    q: "What does “ready” mean on Actual leads?",
    short: "All seven checks pass, nothing less.",
    a: (
      <>
        The site was read; the firm fits the profile; a decision-maker is named; an address is on file; the address
        passed verification (&ldquo;valid&rdquo;, nothing less); a LinkedIn profile is on the person; and the journey
        drafts. The second tab lists the leads one or two steps short with the missing steps named. A lead the list
        rules hold back (parked, on the do-not-contact list, a customer) is never ready, and the screen says how many.
      </>
    ),
  },
  {
    q: "Does it send the emails?",
    short: "No. It drafts and exports; you record what came back.",
    a: (
      <>
        No. It drafts the nine-touch journey from the proof and exports the ready leads as a sheet for the sending
        vendor. Replies and outcomes are recorded here (sent, replied, meeting, won, lost, opted out), and a lost lead
        returns to the pool after its cooldown.
      </>
    ),
  },
  {
    q: "Does it scrape LinkedIn or job boards?",
    short: "No. Profiles come from search results; boards are never read.",
    a: (
      <>
        LinkedIn profiles come from search results only; the profile page is never opened. Job boards are never
        scraped; openings come from firms&apos; own careers pages. The crawler names itself honestly, honours every
        site&apos;s robots.txt, and stops when a site asks it to.
      </>
    ),
  },
  {
    q: "Where does a number come from?",
    short: "Every fact carries its source and evidence.",
    a: (
      <>
        Every fact carries its source and the evidence it was read from; a firm&apos;s page shows competing claims and
        which one won. Yellow marks only what was read on the firm&apos;s own site. A sheet&apos;s value is one source
        among several, never the last word.
      </>
    ),
  },
  {
    q: "What if a website on the sheet is wrong?",
    short: "It is searched for, and adopted only when its homepage names the firm.",
    a: (
      <>
        The website check notices (the page does not name the firm, or nothing answers), searches for the real one,
        and adopts a result only after that site&apos;s own homepage names the firm. If the site found already belongs
        to another firm on file, it opens a duplicate review for a person instead of rewriting anything.
      </>
    ),
  },
];

function Faq() {
  const [selected, setSelected] = useState(0);
  const item = FAQ[selected];
  return (
    <section id="faq" aria-labelledby="faq-heading" className="grid scroll-mt-6 gap-5">
      <SectionHeading id="faq-heading" aside="Plain answers; the details are on each screen">
        Questions
      </SectionHeading>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] lg:gap-10">
        <ol className="grid border-y border-rule" aria-label="Questions">
          {FAQ.map((f, i) => {
            const active = i === selected;
            return (
              <li key={f.q} className="border-b border-rule last:border-b-0">
                <button
                  type="button"
                  aria-expanded={active}
                  aria-controls="faq-answer"
                  onClick={() => setSelected(i)}
                  className={cn(
                    "grid w-full gap-0.5 px-3 py-2.5 text-left transition-colors duration-100",
                    active ? "bg-cobalt-wash" : "hover:bg-paper",
                  )}
                >
                  <span className={cn("text-body font-semibold", active ? "text-cobalt-deep" : "text-ink")}>{f.q}</span>
                  <span className="text-table text-slate">{f.short}</span>
                </button>
              </li>
            );
          })}
        </ol>
        <div id="faq-answer" aria-live="polite" className="grid content-start gap-3 lg:sticky lg:top-6 lg:self-start">
          <h3 className="text-subtitle font-semibold text-ink">{item.q}</h3>
          <div className="max-w-[68ch] text-body text-slate">{item.a}</div>
        </div>
      </div>
    </section>
  );
}

/* ── The words on the screens ───────────────────────────────────────────── */

const GLOSSARY: { term: string; means: string }[] = [
  { term: "Stage", means: "Where a lead is as a person works it: researching, needs a decision, needs a person, ready to reach, in outreach, replied, parked, closed." },
  { term: "Next step", means: "The one thing to do for that lead now, in words." },
  { term: "Priority", means: `${PRIORITY_LABEL.STRIKE}: ${PRIORITY_HINT.STRIKE} ${PRIORITY_LABEL.SEQUENCE}: ${PRIORITY_HINT.SEQUENCE} ${PRIORITY_LABEL.NURTURE}: ${PRIORITY_HINT.NURTURE} ${PRIORITY_LABEL.HOLD}: ${PRIORITY_HINT.HOLD}` },
  { term: "Why now", means: "The evidence the engine read on the firm's own site: an open role, no support staff listed, no way to take a lead after hours, reviews about unreturned calls. Marked in yellow, always with its source." },
  { term: "Tier", means: "Fit by the record: 1A is a contingency personal-injury firm of two to twelve attorneys, the sweet spot. Lower tiers fit less; DQ means disqualified by rule." },
  { term: "Fit, Urgency, Competition", means: "Fit is how well the firm matches (0–50). Urgency is how strong and fresh its signals are (0–50). Competition is how many others are likely chasing the same signal." },
  { term: "Unverified", means: "An address read off a page, found by search, or built from the firm's pattern. Real enough to write to by hand; not yet checked by a verifier." },
  { term: "Filled by research", means: "A field the sheet did not carry and the engine finds for itself: size from the team page, practice from the site, people, addresses, profiles." },
];

function Glossary() {
  return (
    <section aria-labelledby="glossary-heading" className="grid gap-5">
      <SectionHeading id="glossary-heading">The words on the screens</SectionHeading>
      <dl className="grid gap-x-10 gap-y-5 md:grid-cols-2">
        {GLOSSARY.map((g) => (
          <div key={g.term} className="grid gap-1 border-t border-rule pt-3">
            <dt className="text-body font-semibold text-ink">{g.term}</dt>
            <dd className="text-body text-slate">{g.means}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function HomeSkeleton() {
  return (
    <div className="grid gap-14" aria-busy="true" aria-label="Loading">
      <div className="grid gap-10 lg:grid-cols-2">
        <div className="grid gap-4">
          <Skeleton className="h-12 w-3/4" />
          <Skeleton className="h-12 w-1/2" />
          <Skeleton className="h-5 w-2/3" />
        </div>
        <Skeleton className="h-80 w-full" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-72" />
        ))}
      </div>
    </div>
  );
}

/**
 * Home: first where things stand -- the strongest proof in the system (or,
 * before there is any, what the engine makes of a row), the three steps of
 * the brief with live numbers, what is waiting for a person and what the
 * engine is doing -- then the manual: how to use it, the questions, the words.
 */
export function HomeScreen() {
  const overview = useOverview();
  const today = useToday();
  const topLead = today.data?.top_proof;
  return (
    <>
      <TitleBar title="Home" meta="Where things stand, and how to use it" />
      <div className="grid max-w-[80rem] gap-16 px-8 pt-10 pb-24 max-md:px-4">
        {overview.isPending ? (
          <HomeSkeleton />
        ) : overview.isError ? (
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        ) : (
          <>
            {topLead?.proof ? (
              <ProofHero lead={topLead} draft={(today.data as TodayResponse).first_draft} />
            ) : (
              <PitchHero data={overview.data} />
            )}
            <SetupNotice />
            <StepsBand data={overview.data} />
            <div className="grid gap-12 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:gap-16">
              <Waiting data={overview.data} />
              <EngineNow data={overview.data} />
            </div>
            <BuiltSoFar />
            <div className="grid gap-16 border-t-2 border-ink pt-12">
              <HowTo />
              <Faq />
              <Glossary />
            </div>
          </>
        )}
      </div>
    </>
  );
}
