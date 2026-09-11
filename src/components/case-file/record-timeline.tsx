"use client";

import { SectionHeading } from "@/components/layout/panel";
import { usePendingOutcomes } from "@/lib/api/hooks";
import type { LeadDetail } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { OUTCOME_LABEL } from "@/lib/labels";

function actorWords(actor: string): string {
  return actor === "engine" ? "the engine" : actor;
}

/**
 * The record, like a court docket: the date in the margin, the entry beside
 * it. Outcomes are listed with whether the lifecycle moved — the engine only
 * applies a transition the state machine allows.
 */
export function RecordSection({ lead }: { lead: LeadDetail }) {
  const pending = usePendingOutcomes(lead.id);
  const outcomes = [...lead.outcomes].reverse();

  return (
    <section aria-labelledby="record-heading" className="grid gap-5">
      <SectionHeading id="record-heading">The record</SectionHeading>

      <div className="grid gap-2">
        <h3 className="text-meta text-slate">Outcomes</h3>
        {pending.length === 0 && outcomes.length === 0 ? (
          <p className="text-body text-slate">
            No outcome recorded yet. Record one after you write to the firm, so attribution can learn from it.
          </p>
        ) : (
          <ol className="grid gap-2" aria-label="Outcomes, newest first">
            {pending.map((p, i) => (
              <li key={`pending-${i}`} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 text-body" aria-busy="true">
                <span className="text-table text-slate tabular-nums">Now</span>
                <span>
                  <span className="text-ink">{OUTCOME_LABEL[p.action]}</span>
                  <span className="text-slate italic">, recording…</span>
                </span>
              </li>
            ))}
            {outcomes.map((o, i) => (
              <li key={`${o.at}-${i}`} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 text-body">
                <time dateTime={o.at} className="text-table text-slate tabular-nums">
                  {formatDateTime(o.at)}
                </time>
                <span className="min-w-0">
                  <span className="text-ink">
                    {OUTCOME_LABEL[o.action]}
                    {o.until ? ` until ${formatDate(o.until)}` : ""}
                  </span>
                  <span className="text-slate">, by {actorWords(o.actor)}. </span>
                  <span className={o.transition_applied ? "text-ledger" : "text-slate"}>
                    {o.transition_applied ? "State changed." : "State unchanged."}
                  </span>
                  {o.note ? <span className="block text-table text-slate">{o.note}</span> : null}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="grid gap-2">
        <h3 className="text-meta text-slate">Lifecycle</h3>
        <ol className="grid" aria-label="Lifecycle, oldest first">
          {lead.timeline.map((entry, i) => (
            <li
              key={`${entry.at}-${i}`}
              className="relative grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 pb-4 last:pb-0"
            >
              <time dateTime={entry.at} className="text-table text-slate tabular-nums">
                {formatDateTime(entry.at)}
              </time>
              <div className="relative border-l border-rule pl-4 [li:last-child>&]:border-transparent">
                <span
                  aria-hidden="true"
                  className="absolute top-[7px] -left-[4px] size-[7px] rounded-[1px] border border-ink bg-sheet [li:last-child_&]:bg-ink"
                />
                <p className="text-body text-ink">{entry.label}</p>
                <p className="text-table text-slate">
                  {entry.trigger}, by {actorWords(entry.actor)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
