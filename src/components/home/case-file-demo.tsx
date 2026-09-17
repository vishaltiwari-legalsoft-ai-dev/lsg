"use client";

import { CheckIcon, MinusIcon, RotateCcwIcon } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

import { Highlight } from "@/components/record/proof-quote";
import { Button } from "@/components/ui/button";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

/**
 * One lead, built in front of you. The same case file the work queue shows,
 * filled in stage by stage: a sheet row, the site verified, what the site
 * said, the tier and the urgency, every check green, the first subject line.
 * `stage` 0–5 is how far it has got; `play` runs the stages once from the
 * top (the page's one unprompted motion), or shows the end at once for
 * people who prefer reduced motion.
 *
 * The firm is invented. Nothing here is read from the engine.
 */

export const LAST_STAGE = 5;
const STEP_MS = 720;

export const STAGE_NAMES = [
  "A row on a sheet",
  "Website verified",
  "The site read",
  "Tiered, and why now",
  "Every step done",
  "Drafted and exported",
] as const;

const CHECKS = [
  "Website read",
  "Fits the profile",
  "Decision-maker named",
  "Address on file",
  "Address verified",
  "LinkedIn profile",
  "Journey drafted",
] as const;

/** Which checks are green at each stage. */
const GREEN_AT: number[] = [0, 1, 4, 5, 7, 7];

function Reveal({
  at,
  stage,
  children,
  className,
  inline = false,
  collapse = false,
}: {
  at: number;
  stage: number;
  children: React.ReactNode;
  className?: string;
  /** A span, for use inside a paragraph (a div there is invalid HTML). */
  inline?: boolean;
  /** Take no space until shown (the walkthrough); the play keeps its height. */
  collapse?: boolean;
}) {
  const shown = stage >= at;
  const Tag = inline ? "span" : "div";
  if (!shown && collapse) return null;
  return (
    <Tag
      aria-hidden={!shown}
      className={cn(
        "transition-[opacity,transform] duration-300 ease-out motion-reduce:transition-none",
        shown ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-1 opacity-0",
        inline && "inline-block",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** False on the server and during hydration, true once the client owns the page. */
function useHydrated(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}

function Marks({ green }: { green: number }) {
  return (
    <ol className="flex items-center gap-1" aria-label={`${green} of 7 steps done`}>
      {CHECKS.map((label, i) => {
        const ok = i < green;
        return (
          <li
            key={label}
            title={`${label}: ${ok ? "done" : "not yet"}`}
            className={cn(
              "inline-flex size-6 items-center justify-center rounded-[4px] border transition-colors duration-300 motion-reduce:transition-none",
              ok ? "border-ledger/40 bg-ledger-wash text-ledger" : "border-rule bg-sheet text-slate/60",
            )}
          >
            {ok ? <CheckIcon className="size-3.5" aria-hidden="true" /> : <MinusIcon className="size-3.5" aria-hidden="true" />}
            <span className="sr-only">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function CaseFileDemo({
  stage: controlled,
  play = false,
  className,
}: {
  /** The stage to show. Ignored while `play` is running. */
  stage?: number;
  /** Run the stages once from the top on mount, with a replay control. */
  play?: boolean;
  className?: string;
}) {
  const reduced = useReducedMotion();
  // Starts at the top on every render path (the server reports reduced
  // motion, so the first client paint must not flash the finished file).
  const [played, setPlayed] = useState(0);
  const [run, setRun] = useState(0);

  // The effect only schedules; state changes happen inside the timeouts.
  // Replay resets from its own click, and reduced motion is derived below.
  useEffect(() => {
    if (!play || reduced) return;
    const timers = Array.from({ length: LAST_STAGE }, (_, i) =>
      setTimeout(() => setPlayed(i + 1), STEP_MS * (i + 1)),
    );
    return () => timers.forEach(clearTimeout);
  }, [play, reduced, run]);

  // Before the client owns the page the file shows its first stage, so the
  // finished file never flashes ahead of the play.
  const hydrated = useHydrated();
  const stage = play
    ? !hydrated
      ? 0
      : reduced
        ? LAST_STAGE
        : played
    : Math.max(0, Math.min(LAST_STAGE, controlled ?? LAST_STAGE));
  const green = GREEN_AT[stage] ?? 0;
  const verified = stage >= 4;
  const sweep = play && !reduced && stage === 2;

  return (
    <figure
      className={cn(
        "relative grid gap-0 overflow-hidden rounded-panel border border-rule bg-sheet",
        className,
      )}
      aria-label="A lead being built, stage by stage"
    >
      {/* Progress rule across the top: how far the file has got. */}
      <div aria-hidden="true" className="h-0.5 w-full bg-rule">
        <div
          className="h-full bg-cobalt transition-[width] duration-500 ease-out motion-reduce:transition-none"
          style={{ width: `${(stage / LAST_STAGE) * 100}%` }}
        />
      </div>

      <div className="grid gap-5 px-6 py-5">
        {/* The firm: from a sheet row to a record. */}
        <div className="flex items-start justify-between gap-4">
          <div className="grid gap-0.5">
            <p className="text-section font-medium text-ink">Harbor &amp; Vale Injury Law</p>
            <p className="text-table text-slate">
              harborvale.law
              <span className="mx-1.5">·</span>
              Atlanta, GA
              <Reveal at={3} stage={stage} inline>
                <span className="mx-1.5">·</span>
                <span className="text-ink">Tier 1A</span>
                <span className="text-slate"> — contingency, personal injury, 6 attorneys</span>
              </Reveal>
            </p>
          </div>
          <span
            className={cn(
              "shrink-0 rounded-[4px] border px-2 py-0.5 text-meta transition-colors duration-300 motion-reduce:transition-none",
              stage >= 4 ? "border-ledger/40 bg-ledger-wash text-ledger" : stage >= 1 ? "border-cobalt/30 bg-cobalt-wash text-cobalt-deep" : "border-rule text-slate",
            )}
          >
            {stage >= 5 ? "Exported" : stage >= 4 ? "Ready to reach" : stage >= 3 ? "Needs a decision" : stage >= 1 ? "Researching" : "On a sheet"}
          </span>
        </div>

        <figcaption className="text-meta text-slate">
          <span className="text-ink">{stage + 1}</span> of {LAST_STAGE + 1} — {STAGE_NAMES[stage]}
        </figcaption>

        {/* Stage 0: the row as the sheet gave it. */}
        <div className="grid gap-1.5 border-l-2 border-rule pl-4">
          <p className="text-meta text-slate">From the sheet — three columns read, the rest filled by research</p>
          <div className="grid grid-cols-3 gap-px overflow-hidden rounded-[4px] border border-rule bg-rule text-table">
            {[
              ["Law Firm", "Harbor & Vale Injury Law"],
              ["Web Address", "harborvale.law"],
              ["HQ", "Atlanta, GA"],
            ].map(([head, cell]) => (
              <div key={head} className="grid gap-0.5 bg-sheet px-2.5 py-1.5">
                <span className="text-meta text-slate">{head}</span>
                <span className="truncate text-ink">{cell}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Stage 1: the website check. */}
        <Reveal at={1} stage={stage} collapse={!play} className="grid gap-1 border-l-2 border-rule pl-4">
          <p className="text-meta text-slate">Website check</p>
          <p className="text-body text-ink">
            harborvale.law answers and names the firm — <span className="text-ledger">verified</span>.
          </p>
        </Reveal>

        {/* Stage 2: what the site said. */}
        <Reveal at={2} stage={stage} collapse={!play} className="grid gap-4">
          <div className="grid gap-1 border-l-2 border-rule pl-4">
            <p className="text-meta text-slate">Why now — read on the firm&apos;s careers page</p>
            <blockquote className="quotation text-quote text-ink">
              <p>
                <Highlight animate={sweep}>
                  We&rsquo;re hiring an experienced personal injury paralegal to join our Atlanta team.
                </Highlight>
              </p>
            </blockquote>
            <Reveal at={3} stage={stage}>
              <p className="text-table text-slate">Paralegal role open 26 days · urgency 38 of 50</p>
            </Reveal>
          </div>
          <div className="grid gap-1 border-l-2 border-rule pl-4">
            <p className="text-meta text-slate">People — 12 pages read</p>
            <p className="text-body text-ink">
              Dana Hart, Office Manager
              <span className="text-slate"> · M. Vale, Founding Partner · 4 attorneys, 2 support</span>
            </p>
            <p className="text-body">
              <span className="text-ink">dana@harborvale.law</span>
              <span
                className={cn(
                  "ml-2 text-meta transition-colors duration-300 motion-reduce:transition-none",
                  verified ? "text-ledger" : "text-redline",
                )}
              >
                {verified ? "Verified" : "Unverified"}
              </span>
              <span className="ml-3 text-cobalt">linkedin.com/in/danahart</span>
            </p>
          </div>
        </Reveal>

        {/* Stage 5: the first touch. */}
        <Reveal at={5} stage={stage} collapse={!play} className="grid gap-1 border-l-2 border-highlighter pl-4">
          <p className="text-meta text-slate">Touch 1 of 9 — drafted for Dana</p>
          <p className="quotation text-quote text-ink">Subject: your paralegal opening</p>
          <p className="text-table text-slate">Exported to the sending vendor. Outcomes are recorded here as replies come in.</p>
        </Reveal>

        {!play && stage < LAST_STAGE ? (
          <p className="text-table text-slate">Next: {STAGE_NAMES[stage + 1].toLowerCase()}.</p>
        ) : null}

        <div className="flex items-center justify-between gap-4 border-t border-rule pt-4">
          <Marks green={green} />
          {play ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setPlayed(0);
                setRun((n) => n + 1);
              }}
              aria-label="Replay the lead being built"
            >
              <RotateCcwIcon className="size-3.5" aria-hidden="true" />
              Replay
            </Button>
          ) : null}
        </div>
      </div>
    </figure>
  );
}
