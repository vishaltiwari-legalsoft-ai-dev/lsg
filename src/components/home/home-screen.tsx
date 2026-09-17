"use client";

import { ChevronDownIcon } from "lucide-react";
import Link from "next/link";

import { Panel, SectionHeading } from "@/components/layout/panel";
import { AlertStateBadge } from "@/components/record/status-badge";
import { TitleBar } from "@/components/shell/title-bar";
import { ErrorState } from "@/components/states/error-state";
import { buttonVariants } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
  const empty = by.lists.count === 0;
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
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/imports" className={buttonVariants({ variant: empty ? "primary" : "secondary", size: "lg" })}>
          Upload a list
        </Link>
        <Link href="/leads?stage=needs_review" className={buttonVariants({ variant: empty ? "secondary" : "primary", size: "lg" })}>
          Open the work queue
        </Link>
        <a href="#how-to" className={cn(buttonVariants({ variant: "link", size: "lg" }), "ml-2")}>
          How to use it
        </a>
        <a href="#faq" className={buttonVariants({ variant: "link", size: "lg" })}>
          Questions
        </a>
      </div>
      {empty ? (
        <p className="max-w-[62ch] text-body text-slate">
          Nothing is loaded yet. Start with a sheet of firms — any layout; a firm name and a website,
          email or location is all it needs — and the engine fills in the rest.
        </p>
      ) : null}
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

/* ── How to use it: from a sheet to a ready lead ────────────────────────── */

const HOW_TO: { title: string; you: string; engine: string; where: { href: string; label: string }; takes: string }[] = [
  {
    title: "Upload a sheet",
    you: "Drop in any sheet of firms — a vendor export, a conference list, last quarter's outreach. A firm name plus a website, an email or a location is all it needs. The AI reads the columns; you confirm the mapping, or correct a column with one click.",
    engine: "Reads the header and a dozen sample rows, says what each column is and what the sheet lacks, and lists what research will fill in for itself.",
    where: { href: "/imports", label: "Lists" },
    takes: "Under a minute, any size of sheet.",
  },
  {
    title: "Load it",
    you: "Press Load. The screen shows progress per batch of 500 rows.",
    engine: "Rows become firms, the same firm from two sources becomes one record, and every website is verified — alive, this firm, or searched for when it is wrong.",
    where: { href: "/imports", label: "Lists" },
    takes: "Minutes for a thousand rows; longer if many sites need searching for.",
  },
  {
    title: "Research the firms",
    you: "In the work queue, select leads — up to a hundred at a time — and choose Research. Or open any firm and research it alone. Keep working; it runs in the background.",
    engine: "Reads six pages of each site (home, about, contact, the team, testimonials, careers), pulls out the people and their titles, the addresses, the fee promise, the practice areas and what the site lacks; then searches for LinkedIn profiles, business listings and addresses, and finds or verifies the decision-maker's email.",
    where: { href: "/leads", label: "Work queue" },
    takes: "The long pole — see the question below.",
  },
  {
    title: "Decide",
    you: "The queue groups leads by what they need next. On Needs a decision, disqualify, park, qualify or assign. On Needs a person, add or correct the contact.",
    engine: "Tiers each firm by fit, reads urgency from its pain, and writes the next action on every lead in words.",
    where: { href: "/leads?stage=needs_review", label: "Work queue" },
    takes: "Your pace. Keyboard: J and K move, Enter opens, numbers record an outcome.",
  },
  {
    title: "Take the ready ones",
    you: "Qualified leads shows only the leads on which every step is done, and — on its second tab — what still holds the rest back.",
    engine: "Seven checks per lead: site read, fits the profile, decision-maker named, address on file, address verified, LinkedIn profile, journey drafted.",
    where: { href: "/qualified", label: "Qualified leads" },
    takes: "Instant.",
  },
  {
    title: "Export and record",
    you: "Export the ready leads as a sheet for your sending vendor. As replies come in, record the outcome on the lead — sent, replied, meeting, won, lost, opted out.",
    engine: "Drafts the nine-touch journey from the proof, keeps the lifecycle, and returns a lost lead to the pool after its cooldown with its contact intact.",
    where: { href: "/qualified", label: "Qualified leads" },
    takes: "Seconds.",
  },
];

function HowTo() {
  return (
    <section id="how-to" aria-labelledby="how-to-heading" className="grid gap-6 scroll-mt-6">
      <SectionHeading id="how-to-heading" aside="From a sheet to a lead you can write to">
        How to use it
      </SectionHeading>
      <ol className="grid gap-0 divide-y divide-rule border-y border-rule">
        {HOW_TO.map((step, i) => (
          <li key={step.title} className="grid gap-4 py-6 md:grid-cols-[3rem_minmax(0,1fr)] md:gap-6">
            <span
              aria-hidden="true"
              className="flex size-8 items-center justify-center rounded-full border-2 border-cobalt bg-sheet text-table font-medium text-cobalt tabular-nums"
            >
              {i + 1}
            </span>
            <div className="grid gap-3">
              <h3 className="text-section font-medium text-ink">
                <span className="sr-only">Step {i + 1}: </span>
                {step.title}
                <span className="ml-3 text-table font-normal text-slate">
                  in{" "}
                  <Link href={step.where.href} className="text-cobalt hover:underline">
                    {step.where.label}
                  </Link>
                </span>
              </h3>
              <dl className="grid gap-x-8 gap-y-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_14rem]">
                <div className="grid gap-1">
                  <dt className="text-meta text-slate">You</dt>
                  <dd className="text-body text-ink">{step.you}</dd>
                </div>
                <div className="grid gap-1">
                  <dt className="text-meta text-slate">The engine</dt>
                  <dd className="text-body text-ink">{step.engine}</dd>
                </div>
                <div className="grid gap-1">
                  <dt className="text-meta text-slate">Takes</dt>
                  <dd className="text-body text-ink">{step.takes}</dd>
                </div>
              </dl>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ── The tabs ───────────────────────────────────────────────────────────── */

const TABS: { href: string; label: string; what: string }[] = [
  { href: "/", label: "Home", what: "This page: what the engine does, live numbers, what needs a person, and the answers below." },
  { href: "/leads", label: "Work queue", what: "Every open lead, grouped by what it needs next — a decision, a person, or nothing (ready). Research, decide, assign and record outcomes here; the lead opens beside the list." },
  { href: "/qualified", label: "Qualified leads", what: "Only the leads with every step done, ready to reach, and the ones one step away with what is missing. The export for the sending vendor lives here." },
  { href: "/firms", label: "Firms", what: "Every firm in the universe, searchable. A firm's page is the record: each fact with its source, the pages read, the people, the research buttons." },
  { href: "/imports", label: "Lists", what: "Upload a sheet, see how its columns were read, correct one, load it and watch the batches land." },
  { href: "/review/handcheck", label: "Accuracy check", what: "Fifty firms the engine read, checked by hand against their sites — the gate that keeps the reading honest before the list widens." },
];

function Tabs() {
  return (
    <section aria-labelledby="tabs-heading" className="grid gap-5">
      <SectionHeading id="tabs-heading" aside="Ctrl K searches firms from any screen">
        The tabs
      </SectionHeading>
      <dl className="grid gap-x-10 gap-y-4 md:grid-cols-2">
        {TABS.map((tab) => (
          <div key={tab.href} className="grid gap-1 border-l-2 border-rule pl-4">
            <dt className="text-body font-medium text-ink">
              <Link href={tab.href} className="hover:underline">
                {tab.label}
              </Link>
            </dt>
            <dd className="text-body text-slate">{tab.what}</dd>
          </div>
        ))}
      </dl>
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

/* ── Questions ──────────────────────────────────────────────────────────── */

/** For a thousand leads, step by step. Paces are the engine's own settings. */
const TIMING: { step: string; time: string; why: string }[] = [
  { step: "Reading the sheet", time: "under a minute", why: "One model call for the columns; rows stream in batches of 500." },
  { step: "Website check", time: "about 10 minutes", why: "One request per site, twelve sites at once, a polite two seconds between requests to the same site. Sites that must be searched for add a quarter second each with the search key — or 8–12 seconds each on the free engine." },
  { step: "Reading the sites", time: "40–60 minutes", why: "Twelve pages per firm at that same pace; slow hosts and pages that need a browser add to it." },
  { step: "Facts, fee model, practice, pain", time: "10–20 minutes", why: "Local computing over the pages already stored — no network." },
  { step: "LinkedIn, listings, addresses by search", time: "15–20 minutes", why: "Around four thousand queries at a quarter second each on Serper. On the free engine, at 8–12 seconds a query, this alone is about eleven hours — which is why the key matters." },
  { step: "Finding and verifying addresses", time: "minutes, not hours", why: "One Hunter call per decision-maker without an address, one per address to verify." },
];

const FAQ: { q: string; a: React.ReactNode }[] = [
  {
    q: "How do I get in?",
    a: (
      <>
        Today it runs on this machine: open <span className="text-ink">http://localhost:3100</span> with the engine
        running (the README lists the three commands: start the database, start the engine, start the app). There is no
        login yet. When it moves to a shared server, logins come first, because contacts are personal data.
      </>
    ),
  },
  {
    q: "What does a sheet need to have?",
    a: (
      <>
        A firm name, and one way to reach the firm — a website, an email address, or a location. Nothing else is
        required. Size, practice, people and addresses are marked &ldquo;filled by research&rdquo; on the Lists screen
        rather than &ldquo;missing&rdquo;. Any layout works; the AI reads the columns and you confirm.
      </>
    ),
  },
  {
    q: "How long does a thousand leads take?",
    a: (
      <div className="grid gap-3">
        <p>
          Around two hours end to end with the search and address keys in place; most of it is reading the sites,
          which runs in the background while you work the queue. Without the keys the reading is the same but the
          searching runs on the free engine and takes the better part of a day.
        </p>
        <table className="w-full border-collapse text-left text-table">
          <thead>
            <tr className="border-b border-rule text-meta text-slate">
              <th scope="col" className="py-1.5 pr-4 font-normal">Step</th>
              <th scope="col" className="py-1.5 pr-4 font-normal">1,000 leads</th>
              <th scope="col" className="py-1.5 font-normal">What sets the pace</th>
            </tr>
          </thead>
          <tbody>
            {TIMING.map((row) => (
              <tr key={row.step} className="border-b border-rule last:border-b-0 align-top">
                <td className="py-2 pr-4 text-ink">{row.step}</td>
                <td className="py-2 pr-4 whitespace-nowrap text-ink tabular-nums">{row.time}</td>
                <td className="py-2 text-slate">{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
  },
  {
    q: "How do I research a whole list, not one firm?",
    a: (
      <>
        From the work queue: select leads — up to a hundred at a time — and choose Research; ten batches cover a
        thousand. Each batch runs in the background and the Home page shows what is running. A firm&apos;s own page has
        the same buttons for one firm. A whole list can also be run in one go from the command line
        (<span className="text-ink">lge flow profile_probe</span>), which is how the first thousand will be run and measured.
      </>
    ),
  },
  {
    q: "Which keys make it work fully?",
    a: (
      <>
        Three, each one line in the engine&apos;s settings file. <span className="text-ink">OpenRouter</span> lets the AI
        read sheets and sites. <span className="text-ink">Serper</span> is the web search — LinkedIn profiles, Google
        Business listings, addresses in search results. <span className="text-ink">Hunter</span> finds and verifies the
        decision-maker&apos;s address. Without Serper and Hunter the platform still reads sites and finds people, but
        no address gets verified and nothing reaches Ready on Qualified leads.
      </>
    ),
  },
  {
    q: "What does “ready” mean on Qualified leads?",
    a: (
      <>
        All seven checks pass: the site was read; the firm fits the profile; a decision-maker is named; an address is
        on file; the address passed verification — &ldquo;valid&rdquo;, nothing less; a LinkedIn profile is on the
        person; and the journey drafts. The second tab lists the leads one or two steps short with the missing steps
        named, and a line at the top totals what holds them back.
      </>
    ),
  },
  {
    q: "Does it send the emails?",
    a: (
      <>
        No. It drafts the nine-touch journey from the proof and exports the ready leads as a sheet for the sending
        vendor. Replies and outcomes are recorded here — sent, replied, meeting, won, lost, opted out — and a lost lead
        returns to the pool after its cooldown.
      </>
    ),
  },
  {
    q: "Does it scrape LinkedIn or job boards?",
    a: (
      <>
        No. LinkedIn profiles come from search results only — the profile page is never opened. Job boards are never
        scraped; openings come from firms&apos; own careers pages. The crawler names itself honestly, honours every
        site&apos;s robots.txt, and stops when a site asks it to.
      </>
    ),
  },
  {
    q: "Where does a number come from?",
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
    a: (
      <>
        The website check notices — the page does not name the firm, or nothing answers — searches for the real one,
        and adopts a result only after that site&apos;s own homepage names the firm. If the site found already belongs
        to another firm on file, it opens a duplicate review for a person instead of rewriting anything.
      </>
    ),
  },
];

function Question({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <Collapsible className="border-b border-rule last:border-b-0">
      <CollapsibleTrigger className="group flex w-full items-center justify-between gap-6 py-4 text-left text-body font-medium text-ink hover:text-cobalt">
        <span>{q}</span>
        <ChevronDownIcon
          className="size-4 shrink-0 text-slate transition-transform duration-150 group-data-[state=open]:rotate-180"
          aria-hidden="true"
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="max-w-[72ch] pb-5 text-body text-slate">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-heading" className="grid gap-5 scroll-mt-6">
      <SectionHeading id="faq-heading" aside="Plain answers; the details are on each screen">
        Questions
      </SectionHeading>
      <div className="border-t border-rule">
        {FAQ.map((item) => (
          <Question key={item.q} q={item.q}>
            {item.a}
          </Question>
        ))}
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
  { term: "Filled by research", means: "A field the sheet did not carry and the engine finds for itself: size from the team page, practice from the site, people, addresses, profiles." },
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

/**
 * The home page: what the engine does as five steps with live numbers, how to
 * use it from a sheet to a ready lead, what each tab is for, what needs a
 * person, what the engine is doing, and the questions people ask first.
 */
export function HomeScreen() {
  const overview = useOverview();
  return (
    <>
      <TitleBar title="Home" meta="What the engine does, how to use it, and where things stand" />
      <div className="grid max-w-[76rem] gap-14 px-8 pt-10 pb-20">
        {overview.isPending ? (
          <HomeSkeleton />
        ) : overview.isError ? (
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        ) : (
          <>
            <Hero data={overview.data} />
            <Pipeline steps={overview.data.steps} />
            <HowTo />
            <Tabs />
            <NeedsYou data={overview.data} />
            <Engine data={overview.data} />
            <Faq />
            <Glossary />
          </>
        )}
      </div>
    </>
  );
}
