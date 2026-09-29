"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { noDraftWords } from "@/components/case-file/draft-sequence";
import { CopyButton, emailText } from "@/components/copy-button";
import { SectionHeading } from "@/components/layout/panel";
import { TitleBar } from "@/components/shell/title-bar";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useDrafts, useJourney, useJourneyExample, useLead } from "@/lib/api/hooks";
import type {
  DraftTouch,
  DraftsResponse,
  JourneyExampleQuery,
  JourneyPain,
  JourneyResponse,
  JourneyStep,
  JourneyTier,
  JourneyTrack,
  JourneyTrackBand,
} from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { dayLabel } from "@/lib/journey";
import { cn } from "@/lib/utils";
import { ScheduleSection } from "./schedule-section";
import { findTemplate, TemplateEditor } from "./template-editor";

const TIERS: JourneyTier[] = ["1A", "1B", "2", "3", "4_NONBILLABLE"];
const PAINS: JourneyPain[] = ["open_role", "reposted_role", "two_roles", "mass_tort", "reviews", "new_system"];

function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** The example firm and track live in the URL, so a view can be shared and survives a reload. */
function useJourneyParams() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const query: JourneyExampleQuery = {
    tier: oneOf(params.get("tier"), TIERS, "1A"),
    pain: oneOf(params.get("pain"), PAINS, "open_role"),
    system: params.get("system") !== "false",
    band: oneOf<JourneyTrackBand>(params.get("track"), ["SEQUENCE", "NURTURE"], "SEQUENCE"),
  };
  function set(patch: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    const search = next.toString();
    router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
  }
  return { query, leadId: params.get("lead"), set };
}

export function JourneyScreen() {
  const journey = useJourney();
  const { query, leadId, set } = useJourneyParams();
  const example = useJourneyExample(query, !leadId);
  const lead = useLead(leadId);
  const leadDrafts = useDrafts(leadId);
  const [editing, setEditing] = useState<string | null>(null);

  const sequence = journey.data?.tracks.find((t) => t.band === "SEQUENCE");
  const lastDay = journey.data?.steps.at(-1)?.day;
  const meta =
    sequence && lastDay !== undefined
      ? `${sequence.steps.length} emails over ${lastDay + 1} days. The engine drafts; you or the vendor send.`
      : undefined;

  if (journey.isPending) {
    return (
      <>
        <TitleBar title="Email journey" />
        <JourneyLoading />
      </>
    );
  }
  if (journey.isError) {
    return (
      <>
        <TitleBar title="Email journey" />
        <div className="px-8 py-8 max-md:px-4">
          <ErrorState error={journey.error} onRetry={() => void journey.refetch()} />
        </div>
      </>
    );
  }

  const data = journey.data;
  const drafts = leadId ? leadDrafts.data : example.data?.drafts;
  const band = leadId ? drafts?.band : query.band;
  // A lead that is unscored, on Strike or on Hold has no email track at all.
  const track = data.tracks.find((t) => t.band === band && t.steps.length > 0) ?? null;
  const pending = leadId ? leadDrafts.isPending : example.isPending;
  const failed = leadId ? leadDrafts.error : example.error;

  return (
    <>
      <TitleBar title="Email journey" meta={meta} />
      <div className="grid flex-1 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,25rem)]">
        <div className="grid min-w-0 content-start gap-9 px-8 pt-7 pb-16 max-md:px-4">
          <p className="max-w-[68ch] text-body text-slate">
            Every lead on the sequence gets these emails, one on each day below, written from its own proof and
            details. Nothing is sent from here. Change the words or the days, and every lead&apos;s drafts change
            with them.
          </p>

          {data.sender_missing.length > 0 ? <NotReadyToSend missing={data.sender_missing} /> : null}

          {leadId ? (
            <LeadHeading
              leadId={leadId}
              firm={lead.data?.firm.name}
              person={lead.data?.contact ? lead.data.contact.full_name : null}
              onClear={() => set({ lead: null })}
            />
          ) : (
            <ExampleControls
              journey={data}
              query={query}
              person={example.data ? `${example.data.person}, at ${lowerFirst(example.data.firm)}.` : null}
              onChange={(patch) => set(patch)}
            />
          )}

          {pending ? (
            <EmailsLoading />
          ) : failed ? (
            <ErrorState error={failed} />
          ) : (
            <Emails
              journey={data}
              track={track}
              drafts={drafts}
              excludedWords={drafts?.excluded_display ?? (leadId ? noDraftWords(drafts?.excluded_reason, drafts?.band) : null)}
              isLead={Boolean(leadId)}
              onEdit={setEditing}
            />
          )}
        </div>

        <aside aria-label="How the journey runs" className="border-rule bg-paper/70 max-xl:border-t xl:border-l">
          <div className="grid content-start gap-9 px-7 pt-7 pb-12 xl:sticky xl:top-0 xl:max-h-dvh xl:overflow-y-auto">
            <ScheduleSection journey={data} />
            <TracksSection tracks={data.tracks} />
            <AnswersSection />
            <RulesSection banned={data.banned_phrases} />
          </div>
        </aside>
      </div>
      <TemplateEditor journey={data} templateId={editing} onClose={() => setEditing(null)} />
    </>
  );
}

/**
 * Every email is signed, and a commercial email owes the reader a postal
 * address and a way to stop (D-060). Until config/sender.yml carries them,
 * these are drafts to read, not emails to send -- and the screen says so
 * rather than letting a person find out from a complaint.
 */
function NotReadyToSend({ missing }: { missing: string[] }) {
  return (
    <div role="note" className="grid gap-1 rounded-control bg-redline-wash px-4 py-3">
      <p className="text-body font-semibold text-redline">Not ready to send</p>
      <p className="text-body text-ink">
        These emails still need {and(missing)}. An email nobody signs reads as a circular, and US
        law asks any commercial email for a postal address and a way to stop.
      </p>
      <p className="text-meta text-slate">Fill them in at config/sender.yml in the engine folder.</p>
    </div>
  );
}

function and(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

/** The engine's reasons come without a full stop; a sentence on screen ends with one. */
function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

// ── Whose emails: an example firm, or a real lead ───────────────────────────

function ExampleControls({
  journey,
  query,
  person,
  onChange,
}: {
  journey: JourneyResponse;
  query: JourneyExampleQuery;
  person: string | null;
  onChange: (patch: Record<string, string | null>) => void;
}) {
  return (
    <section aria-labelledby="example-heading" className="grid gap-3">
      <h2 id="example-heading" className="text-section font-semibold text-ink">
        What an example firm is sent
      </h2>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={query.tier} onValueChange={(tier) => onChange({ tier })}>
          <SelectTrigger className="w-[20rem] max-w-full" aria-label="The firm's kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {journey.tiers.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={query.pain} onValueChange={(pain) => onChange({ pain })}>
          <SelectTrigger className="w-[17rem] max-w-full" aria-label="The pain the engine found">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {journey.pains.map((p) => (
              <SelectItem key={p.value} value={p.value}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={query.system ? "known" : "unknown"}
          onValueChange={(v) => onChange({ system: v === "known" ? null : "false" })}
        >
          <SelectTrigger className="w-[13rem] max-w-full" aria-label="Whether the case system is known">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="known">Case system known</SelectItem>
            <SelectItem value="unknown">Case system not known</SelectItem>
          </SelectContent>
        </Select>
        <div role="group" aria-label="Track" className="flex rounded-control border border-rule-strong/70 p-0.5">
          {journey.tracks
            .filter((t) => t.steps.length > 0)
            .map((t) => (
              <button
                key={t.band}
                type="button"
                aria-pressed={query.band === t.band}
                onClick={() => onChange({ track: t.band === "SEQUENCE" ? null : t.band })}
                className="h-8 rounded-[5px] px-3 text-table text-slate transition-colors hover:text-ink aria-pressed:bg-cobalt-wash aria-pressed:font-medium aria-pressed:text-ink"
              >
                {t.label}
              </button>
            ))}
        </div>
      </div>
      <p className="min-h-5 text-table text-slate">{person}</p>
    </section>
  );
}

function LeadHeading({
  leadId,
  firm,
  person,
  onClear,
}: {
  leadId: string;
  firm: string | undefined;
  person: string | null;
  onClear: () => void;
}) {
  return (
    <section aria-labelledby="lead-heading" className="grid gap-1.5">
      <h2 id="lead-heading" className="text-section font-semibold text-ink">
        {firm ? `What ${firm} is sent` : "What this lead is sent"}
      </h2>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-table text-slate">
        {person ? <span>Written to {person}.</span> : null}
        <Link href={`/leads/${leadId}`} className="text-cobalt hover:underline">
          Open the lead
        </Link>
        <Button type="button" variant="link" className="text-table" onClick={onClear}>
          Show an example firm instead
        </Button>
      </p>
    </section>
  );
}

// ── The emails, day by day ──────────────────────────────────────────────────

interface Row {
  step: JourneyStep;
  day: number;
  touch: DraftTouch | null;
}

function rowsFor(journey: JourneyResponse, track: JourneyTrack, drafts: DraftsResponse | undefined): Row[] {
  const touches = new Map((drafts?.touches ?? []).map((t) => [t.step, t]));
  return track.steps.map((n) => {
    const step = journey.steps.find((s) => s.step === n)!;
    const touch = touches.get(n) ?? null;
    // A skipped email has no day of its own; it would have gone on the schedule's.
    const day = touch && !touch.skipped_reason ? touch.day : step.day * track.pace;
    return { step, day, touch };
  });
}

function Emails({
  journey,
  track,
  drafts,
  excludedWords,
  isLead,
  onEdit,
}: {
  journey: JourneyResponse;
  track: JourneyTrack | null;
  drafts: DraftsResponse | undefined;
  excludedWords: string | null;
  isLead: boolean;
  onEdit: (templateId: string) => void;
}) {
  if (track === null) {
    return (
      <p className="text-body text-slate">
        {drafts?.band === "STRIKE"
          ? "A Strike lead is written by hand, the same day. The engine drafts no journey for it."
          : "This lead is not on an email track yet, so no journey is drafted for it."}
      </p>
    );
  }

  const rows = rowsFor(journey, track, drafts);
  const none = !drafts || drafts.touches.length === 0;
  const who = isLead ? "This lead" : "This firm";

  return (
    <div className="grid gap-6">
      <Timeline rows={rows} />
      {none ? (
        <div role="note" className="grid gap-1 rounded-control bg-redline-wash px-4 py-3">
          <p className="text-body font-semibold text-redline">{who} would get no emails</p>
          <p className="text-body text-ink">
            {sentence(excludedWords ?? "No email could be written.")} Every version of each email is still listed
            below, to read and change.
          </p>
        </div>
      ) : null}
      <ol aria-label="The emails" className="grid">
        {rows.map((row) => (
          <EmailDay key={row.step.step} row={row} journey={journey} onEdit={onEdit} />
        ))}
      </ol>
    </div>
  );
}

/**
 * The journey as a line of days: each square is an email, placed on its day.
 * Spaced to scale where the days allow it, evenly on a phone or when days
 * crowd together; the numbers above always say the day.
 */
function Timeline({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return null;
  const last = Math.max(...rows.map((r) => r.day), 1);
  const gaps = rows.slice(1).map((r, i) => r.day - rows[i].day);
  const crowded = gaps.some((g) => g / last < 1 / 22);
  const even = (i: number) => (rows.length === 1 ? 0 : (i / (rows.length - 1)) * 100);

  // The day (12px, 17px tall) sits 6px above each 28px square: the line runs through the squares' centre.
  return (
    <nav aria-label="The emails by day" className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-2">
      <div aria-hidden="true" className="relative h-14 text-meta text-slate">
        <span className="absolute top-0 left-0">Day</span>
        <span className="absolute top-7 left-0">Email</span>
      </div>
      <ol className="relative mx-3.5 h-14">
        <span aria-hidden="true" className="absolute inset-x-0 top-9 h-px bg-rule-strong" />
        {rows.map((row, i) => {
          const sent = row.touch !== null && !row.touch.skipped_reason;
          const at = crowded ? even(i) : (row.day / last) * 100;
          return (
            <li
              key={row.step.step}
              className="absolute top-0 -translate-x-1/2 [left:var(--at-even)] md:[left:var(--at-scale)]"
              style={{ "--at-even": `${even(i)}%`, "--at-scale": `${at}%` } as React.CSSProperties}
            >
              <a
                href={`#email-${row.step.step}`}
                aria-label={`Email ${row.step.step}, ${row.step.title}, ${dayLabel(row.day)}${sent ? "" : ", not sent to this firm"}`}
                className="group grid justify-items-center gap-1.5"
              >
                <span className="text-meta text-slate tabular-nums group-hover:text-ink">{row.day + 1}</span>
                <span
                  className={cn(
                    "type-narrow flex size-7 items-center justify-center rounded-control text-body font-semibold tabular-nums transition-colors",
                    sent
                      ? "bg-cobalt text-white group-hover:bg-cobalt-deep"
                      : "border border-dashed border-rule-strong bg-sheet text-slate group-hover:text-ink",
                  )}
                >
                  {row.step.step}
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function EmailDay({
  row,
  journey,
  onEdit,
}: {
  row: Row;
  journey: JourneyResponse;
  onEdit: (templateId: string) => void;
}) {
  const { step, day, touch } = row;
  const sent = touch !== null && !touch.skipped_reason;
  const used = sent ? touch.templates : [];
  const usedTemplates = used.map((id) => findTemplate(journey, id)?.template).filter((t) => t !== undefined);
  const email = usedTemplates.find((t) => t.kind === "email");
  const paragraph = usedTemplates.find((t) => t.kind === "paragraph");
  const others = step.templates.filter((t) => !used.includes(t.id));

  return (
    <li
      id={`email-${step.step}`}
      className="grid scroll-mt-4 grid-cols-[6.5rem_minmax(0,1fr)] gap-x-6 border-t border-rule py-8 max-md:grid-cols-1 max-md:gap-y-3"
    >
      <div className="grid content-start gap-1">
        <p className="type-narrow text-headline leading-none font-semibold text-ink tabular-nums">{dayLabel(day)}</p>
        <p className="text-meta text-slate">Email {step.step}</p>
      </div>

      <div className="grid min-w-0 gap-4">
        <div className="grid gap-0.5">
          <h3 className="text-section font-semibold text-ink">{step.title}</h3>
          <p className="text-body text-slate">{step.purpose}</p>
        </div>

        {sent ? (
          <div className="grid gap-3">
            <div className="flex items-start justify-between gap-4">
              <p className="quotation text-quote-title text-ink">
                <span className="sr-only">Subject: </span>
                {touch.subject}
              </p>
              <CopyButton
                text={emailText(touch.subject, touch.body)}
                label="Copy"
                aria-label={`Copy email ${step.step}`}
                toastText={`Copied email ${step.step}`}
                variant="ghost"
                size="sm"
                className="-mt-0.5 shrink-0"
              />
            </div>
            <div className="quotation border-l-2 border-rule pl-4 text-quote whitespace-pre-line text-ink">
              {touch.body}
            </div>
          </div>
        ) : touch?.skipped_reason ? (
          <p className="text-body text-slate italic">Not sent to this firm: {touch.skipped_reason}.</p>
        ) : null}

        {email ? (
          <div className="grid gap-1 text-table">
            <p className="text-slate">
              Version: {email.used_when}.
              {paragraph ? ` Middle paragraph: ${paragraph.used_when.replace(/^Its middle paragraph for /, "")}.` : null}
            </p>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
              <Button type="button" variant="link" className="text-table" onClick={() => onEdit(email.id)}>
                Change the wording
              </Button>
              {paragraph ? (
                <Button type="button" variant="link" className="text-table" onClick={() => onEdit(paragraph.id)}>
                  Change the middle paragraph
                </Button>
              ) : null}
              <EditedNote dates={[email.edited_at, paragraph?.edited_at ?? null]} />
            </div>
          </div>
        ) : null}

        {others.length > 0 ? <OtherVersions others={others} open={!sent} onEdit={onEdit} /> : null}
      </div>
    </li>
  );
}

function EditedNote({ dates }: { dates: (string | null)[] }) {
  const latest = dates.filter((d): d is string => d !== null).sort().at(-1);
  if (!latest) return null;
  return <span className="text-slate">Wording changed {formatDate(latest)}</span>;
}

function OtherVersions({
  others,
  open: startOpen,
  onEdit,
}: {
  others: JourneyStep["templates"];
  open: boolean;
  onEdit: (templateId: string) => void;
}) {
  const [open, setOpen] = useState(startOpen);
  const noun = others.length === 1 ? "version" : `${others.length} versions`;
  // Beside a written email these are the others; with none written, they are all it has.
  const label = open
    ? startOpen
      ? `Hide its ${noun}`
      : "Hide the other versions"
    : startOpen
      ? `See its ${noun}`
      : `See the other ${noun}`;
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="grid gap-2">
      <CollapsibleTrigger asChild>
        <Button type="button" variant="link" className="justify-self-start text-table">
          {label}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="grid border-y border-rule">
          {others.map((t) => (
            <li
              key={t.id}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-rule py-2.5 last:border-b-0"
            >
              <div className="grid min-w-0 gap-0.5">
                <p className="text-table text-ink">{t.used_when}</p>
                {t.subject ? (
                  <p className="quotation truncate text-quote-table text-slate">{t.subject}</p>
                ) : (
                  <p className="text-meta text-slate">A paragraph set into the email</p>
                )}
              </div>
              <div className="flex items-center gap-3">
                {t.edited_at ? <span className="text-meta text-slate">Changed</span> : null}
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  aria-label={`Change the wording: ${t.used_when}`}
                  onClick={() => onEdit(t.id)}
                >
                  Change
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

// ── The working side: how the journey runs ──────────────────────────────────

function TracksSection({ tracks }: { tracks: JourneyTrack[] }) {
  return (
    <section aria-labelledby="tracks-heading" className="grid gap-3">
      <SectionHeading id="tracks-heading">Who gets which emails</SectionHeading>
      <dl className="grid gap-2.5">
        {tracks.map((t) => (
          <div key={t.band} className="grid gap-0.5">
            <dt className="text-body font-medium text-ink">{t.label}</dt>
            <dd className="text-table text-slate">{t.description}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function AnswersSection() {
  return (
    <section aria-labelledby="answers-heading" className="grid gap-3">
      <SectionHeading id="answers-heading">When the firm answers</SectionHeading>
      <ul className="grid gap-2 text-table text-slate">
        <li>
          <span className="font-medium text-ink">Any reply</span> stops the sequence, whatever it says. Mark it
          Replied on the lead.
        </li>
        <li>
          <span className="font-medium text-ink">A meeting</span> passes the lead to a person. Mark it Meeting.
        </li>
        <li>
          <span className="font-medium text-ink">&ldquo;Not now&rdquo;</span> puts the lead back in the pool until the
          date they name. Mark it Not now, with that date.
        </li>
        <li>
          <span className="font-medium text-ink">An opt-out</span> blocks the firm&apos;s domain for good. Only a
          person can lift it.
        </li>
        <li>
          <span className="font-medium text-ink">No reply</span> after the last email: mark it Not now with a date.
          The lead waits in the pool with its contact kept, ready for the next sign of need.
        </li>
      </ul>
    </section>
  );
}

function RulesSection({ banned }: { banned: string[] }) {
  return (
    <section aria-labelledby="rules-heading" className="grid gap-3">
      <SectionHeading id="rules-heading">Every email keeps to</SectionHeading>
      <ul className="grid gap-2 text-table text-slate">
        <li>The first email opens on the firm&apos;s own need, from its own record.</li>
        <li>
          A greeting, three or four short paragraphs, one ask, and a sign-off. The subject says
          something specific about this firm.
        </li>
        <li>
          Never these words, which read as replacing someone&apos;s staff:{" "}
          <span className="text-ink">{banned.map((b) => `“${b}”`).join(", ")}</span>. The engine refuses
          wording that uses them.
        </li>
        <li>An hourly firm is never pitched a paralegal. An email that names one is left out of its journey.</li>
        <li>A detail a firm lacks keeps it off the list. No email goes out with a gap where a name should be.</li>
      </ul>
    </section>
  );
}

// ── Loading ─────────────────────────────────────────────────────────────────

function EmailsLoading() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-label="Loading the emails">
      <Skeleton className="h-14 w-full" />
      {[0, 1].map((i) => (
        <div key={i} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-6 border-t border-rule pt-8">
          <Skeleton className="h-8 w-20" />
          <div className="grid gap-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-24 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

function JourneyLoading() {
  return (
    <div
      className="grid gap-8 px-8 pt-7 pb-16 xl:grid-cols-[minmax(0,1fr)_22rem] max-md:px-4"
      aria-busy="true"
      aria-label="Loading the email journey"
    >
      <div className="grid content-start gap-6">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-9 w-full" />
        <EmailsLoading />
      </div>
      <div className="grid content-start gap-3">
        <Skeleton className="h-5 w-32" />
        {Array.from({ length: 9 }, (_, i) => (
          <Skeleton key={i} className="h-5 w-full" />
        ))}
      </div>
    </div>
  );
}
