"use client";

import { useEffect, useRef, useState } from "react";

import { Panel } from "@/components/layout/panel";
import { Quotation } from "@/components/record/proof-quote";
import { StatusBadge } from "@/components/record/status-badge";
import { AttributeValue, isUnknownDisplay } from "@/components/record/unknown";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { isShortcutBlocked, useKeydown } from "@/hooks/use-keydown";
import { useUrlState } from "@/hooks/use-url-state";
import { useHandcheck, useHandcheckDecision } from "@/lib/api/hooks";
import type { AttributeRow, HandcheckResponse, HandcheckSampleFirm } from "@/lib/api/types";
import { formatCount, formatDecimal, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

function firstOpenIndex(firm: HandcheckSampleFirm): number {
  const i = firm.attributes.findIndex((a) => !firm.reviews[a.attr]);
  return i === -1 ? 0 : i;
}

function nextOpenIndex(firm: HandcheckSampleFirm, from: number, justDecided: string): number {
  for (let i = from + 1; i < firm.attributes.length; i++) {
    const a = firm.attributes[i];
    if (a.attr !== justDecided && !firm.reviews[a.attr]) return i;
  }
  return Math.min(from + 1, firm.attributes.length - 1);
}

function GatePanel({ gate }: { gate: HandcheckResponse["gate"] }) {
  const pct = Math.min(100, (gate.reviewed_firms / gate.needed) * 100);
  return (
    <Panel aria-labelledby="gate-heading" className="grid gap-4 px-6 py-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="gate-heading" className="text-meta text-slate">
          Gate G2
        </h2>
        <StatusBadge state={gate.passed ? "verified" : "unverified"}>
          {gate.passed ? "Passed" : "Not passed yet"}
        </StatusBadge>
      </div>
      <p className="text-title text-ink tabular-nums">
        {formatCount(gate.reviewed_firms)}
        <span className="text-body text-slate"> of {gate.needed} firms reviewed</span>
      </p>
      <div
        role="progressbar"
        aria-label="Firms reviewed"
        aria-valuemin={0}
        aria-valuemax={gate.needed}
        aria-valuenow={gate.reviewed_firms}
        className="h-1.5 w-full overflow-hidden rounded-[2px] bg-rule"
      >
        <div className={cn("h-full", gate.passed ? "bg-ledger" : "bg-ink")} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-table text-slate">{gate.rule}</p>
    </Panel>
  );
}

function AccuracyPanel({ accuracy }: { accuracy: HandcheckResponse["accuracy"] }) {
  return (
    <Panel aria-labelledby="accuracy-heading" className="px-6 pt-5 pb-3">
      <h2 id="accuracy-heading" className="pb-2 text-meta text-slate">
        Accuracy by attribute
      </h2>
      <table className="w-full text-table">
        <thead className="sr-only">
          <tr>
            <th scope="col">Attribute</th>
            <th scope="col">Correct of checked</th>
            <th scope="col">Accuracy</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {accuracy.map((a) => (
            <tr key={a.attr}>
              <th scope="row" className="py-2 pr-3 text-left font-normal text-ink">
                {a.label}
              </th>
              {a.checked === 0 ? (
                <td colSpan={2} className="py-2 text-right text-meta whitespace-nowrap text-slate italic">
                  Not checked
                </td>
              ) : (
                <>
                  <td className="py-2 pr-3 text-right text-slate tabular-nums">
                    {a.correct} of {a.checked}
                  </td>
                  <td
                    className={cn(
                      "w-12 py-2 text-right font-medium tabular-nums",
                      a.correct / a.checked >= 0.95 ? "text-ledger" : "text-redline",
                    )}
                  >
                    {formatPercent(a.correct, a.checked)}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function KeysPanel() {
  const keys: [string, string][] = [
    ["Y", "Correct"],
    ["N", "Wrong, then type the right value"],
    ["↑ ↓", "Move between attributes"],
    ["J", "Next firm"],
    ["K", "Previous firm"],
  ];
  return (
    <Panel aria-labelledby="keys-heading" className="px-6 py-5">
      <h2 id="keys-heading" className="pb-3 text-meta text-slate">
        Keys
      </h2>
      <dl className="grid gap-2">
        {keys.map(([key, what]) => (
          <div key={key} className="grid grid-cols-[3.25rem_minmax(0,1fr)] items-center gap-2">
            <dt>
              <Kbd>{key}</Kbd>
            </dt>
            <dd className="text-table text-ink">{what}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function AttributeCheck({
  attribute,
  review,
  current,
  correcting,
  onFocus,
  onCorrect,
  onWrong,
  onSave,
  onCancel,
}: {
  attribute: AttributeRow;
  review: { correct: boolean; corrected_value: string | null } | undefined;
  current: boolean;
  correcting: boolean;
  onFocus: () => void;
  onCorrect: () => void;
  onWrong: () => void;
  onSave: (value: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(review?.corrected_value ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  const rowRef = useRef<HTMLLIElement>(null);
  const unknown = attribute.state === "unknown" || isUnknownDisplay(attribute.display);

  useEffect(() => {
    if (correcting) inputRef.current?.focus();
  }, [correcting]);

  useEffect(() => {
    if (current) rowRef.current?.scrollIntoView({ block: "nearest" });
  }, [current]);

  return (
    <li
      ref={rowRef}
      aria-current={current ? "true" : undefined}
      onClick={onFocus}
      className={cn(
        "group grid gap-3 border-b border-rule px-6 py-4 last:border-b-0",
        current && "bg-cobalt-wash/55 shadow-[inset_3px_0_0_var(--color-cobalt)]",
      )}
    >
      <div className="grid grid-cols-[9.5rem_minmax(0,1fr)_auto] items-start gap-4">
        <span className="pt-px text-table text-slate">{attribute.label}</span>

        <div className="grid min-w-0 gap-2">
          <AttributeValue display={attribute.display} state={attribute.state} className="text-body font-medium" />
          {attribute.evidence ? <Quotation text={attribute.evidence} size="table" /> : null}
          {!unknown && attribute.source_label ? (
            <p className="text-meta text-slate">
              {attribute.source_label}
              {attribute.confidence !== null ? `, confidence ${formatDecimal(attribute.confidence)}` : ""}
            </p>
          ) : null}
          {review && !review.correct && review.corrected_value && !correcting ? (
            <p className="text-table text-ink">
              <span className="text-slate">Corrected to </span>
              {review.corrected_value}
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          {review && !correcting ? (
            <>
              <StatusBadge state={review.correct ? "verified" : "failure"}>
                {review.correct ? "Correct" : "Wrong"}
              </StatusBadge>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onFocus();
                  if (review.correct) onWrong();
                  else onCorrect();
                }}
                aria-label={`Change the verdict on ${attribute.label}`}
              >
                Change
              </Button>
            </>
          ) : correcting ? null : (
            // Verdicts show on the current row; elsewhere they appear on
            // hover or focus, so the list stays calm without shifting.
            <div
              className={cn(
                "flex items-center gap-1.5",
                !current && "invisible group-focus-within:visible group-hover:visible",
              )}
            >
              <Button
                variant="secondary"
                size="sm"
                aria-keyshortcuts={current ? "y" : undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  onFocus();
                  onCorrect();
                }}
                aria-label={`${attribute.label} is correct`}
              >
                <span aria-hidden="true" className="text-ledger">✓</span> Correct
                {current ? <Kbd className="ml-0.5 h-4 min-w-4 border-b">Y</Kbd> : null}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-keyshortcuts={current ? "n" : undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  onFocus();
                  onWrong();
                }}
                aria-label={`${attribute.label} is wrong`}
              >
                <span aria-hidden="true" className="text-redline">✗</span> Wrong
                {current ? <Kbd className="ml-0.5 h-4 min-w-4 border-b">N</Kbd> : null}
              </Button>
            </div>
          )}
        </div>
      </div>

      {correcting ? (
        <form
          className="ml-[calc(9.5rem+1rem)] flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const value = draft.trim();
            if (value) onSave(value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              onCancel();
            }
          }}
        >
          <label htmlFor={`correct-${attribute.attr}`} className="sr-only">
            The right value for {attribute.label}
          </label>
          <Input
            ref={inputRef}
            id={`correct-${attribute.attr}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={`The right ${attribute.label.toLowerCase()}`}
            className="w-72"
          />
          <Button type="submit" variant="primary" size="md" disabled={!draft.trim()}>
            Save as wrong
          </Button>
          <Button type="button" variant="ghost" size="md" onClick={onCancel}>
            Cancel
          </Button>
          <span className="text-meta text-slate">
            <Kbd>Enter</Kbd> saves, <Kbd>Esc</Kbd> cancels
          </span>
        </form>
      ) : null}
    </li>
  );
}

function HandcheckSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]" aria-busy="true" aria-label="Loading the hand-check">
      <div className="grid gap-3 rounded-panel border border-rule bg-sheet p-6">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-6 w-80" />
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
      <div className="grid content-start gap-5">
        <Skeleton className="h-40 w-full rounded-panel" />
        <Skeleton className="h-56 w-full rounded-panel" />
      </div>
    </div>
  );
}

function Checker({ data }: { data: HandcheckResponse }) {
  const { params, update } = useUrlState();
  const decide = useHandcheckDecision();
  const sample = data.sample;

  // Only the first load chooses the starting firm: the first with work left.
  const [defaultIndex] = useState(() => {
    const i = sample.findIndex((f) => f.attributes.some((a) => !f.reviews[a.attr]));
    return i === -1 ? 0 : i;
  });
  const requested = sample.findIndex((f) => f.firm_id === params.get("firm"));
  const firmIndex = requested === -1 ? defaultIndex : requested;
  const firm = sample[firmIndex];

  const [cursorState, setCursorState] = useState({ firmId: firm.firm_id, index: firstOpenIndex(firm) });
  const cursor = cursorState.firmId === firm.firm_id ? cursorState.index : firstOpenIndex(firm);
  const setCursor = (index: number) => setCursorState({ firmId: firm.firm_id, index });
  const [correcting, setCorrecting] = useState<string | null>(null);

  const reviewedHere = firm.attributes.filter((a) => firm.reviews[a.attr]).length;
  const allChecked = reviewedHere === firm.attributes.length;

  function goFirm(delta: number) {
    const next = sample[firmIndex + delta];
    if (!next) return;
    setCorrecting(null);
    update({ firm: next.firm_id });
  }

  function record(attr: AttributeRow, correct: boolean, correctedValue?: string) {
    decide.mutate({
      firmId: firm.firm_id,
      attr: attr.attr,
      decision: correct ? { correct: true } : { correct: false, corrected_value: correctedValue },
    });
    setCorrecting(null);
    const index = firm.attributes.indexOf(attr);
    setCursor(nextOpenIndex(firm, index, attr.attr));
  }

  useKeydown((event) => {
    if (isShortcutBlocked(event) || event.ctrlKey || event.metaKey || event.altKey) return;
    const current = firm.attributes[cursor];
    switch (event.key) {
      case "y":
        if (!current) return;
        event.preventDefault();
        record(current, true);
        break;
      case "n":
        if (!current) return;
        event.preventDefault();
        setCorrecting(current.attr);
        break;
      case "j":
        event.preventDefault();
        goFirm(1);
        break;
      case "k":
        event.preventDefault();
        goFirm(-1);
        break;
      case "ArrowDown":
        event.preventDefault();
        setCursor(Math.min(cursor + 1, firm.attributes.length - 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        setCursor(Math.max(cursor - 1, 0));
        break;
    }
  });

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <Panel aria-labelledby="checked-firm" className="overflow-hidden">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-rule px-6 py-5">
          <div className="grid gap-1">
            <p className="text-meta text-slate tabular-nums">
              Firm {firmIndex + 1} of {sample.length} in the sample
            </p>
            <h2 id="checked-firm" className="text-title font-medium text-ink">
              {firm.name}
            </h2>
            <p className="text-table text-slate">
              {firm.domain ?? "No website on record"}
              <span className="tabular-nums">
                {", "}
                {reviewedHere} of {firm.attributes.length} attributes checked
              </span>
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <Button variant="secondary" size="sm" disabled={firmIndex === 0} onClick={() => goFirm(-1)}>
              Previous firm <Kbd className="ml-0.5 h-4 min-w-4 border-b">K</Kbd>
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={firmIndex === sample.length - 1}
              onClick={() => goFirm(1)}
            >
              Next firm <Kbd className="ml-0.5 h-4 min-w-4 border-b">J</Kbd>
            </Button>
          </div>
        </header>

        <ol aria-label={`Attributes of ${firm.name}`}>
          {firm.attributes.map((attribute, i) => (
            <AttributeCheck
              key={`${firm.firm_id}-${attribute.attr}`}
              attribute={attribute}
              review={firm.reviews[attribute.attr]}
              current={i === cursor}
              correcting={correcting === attribute.attr}
              onFocus={() => setCursor(i)}
              onCorrect={() => record(attribute, true)}
              onWrong={() => setCorrecting(attribute.attr)}
              onSave={(value) => record(attribute, false, value)}
              onCancel={() => setCorrecting(null)}
            />
          ))}
        </ol>

        {allChecked ? (
          <p className="border-t border-rule px-6 py-4 text-body text-slate">
            Every attribute on this firm is checked.
            {firmIndex < sample.length - 1 ? (
              <>
                {" "}
                <Kbd>J</Kbd> moves to the next firm.
              </>
            ) : (
              " That was the last firm in the sample."
            )}
          </p>
        ) : null}
      </Panel>

      <div className="grid content-start gap-5 lg:sticky lg:top-6">
        <GatePanel gate={data.gate} />
        <AccuracyPanel accuracy={data.accuracy} />
        <KeysPanel />
      </div>
    </div>
  );
}

export function HandcheckScreen() {
  const handcheck = useHandcheck();
  return (
    <>
      <TitleBar title="Hand-check" meta="Gate G2" />
      <div className="max-w-[80rem] px-8 pt-6 pb-16">
        {handcheck.isPending ? (
          <HandcheckSkeleton />
        ) : handcheck.isError ? (
          <ErrorState error={handcheck.error} onRetry={() => void handcheck.refetch()} />
        ) : handcheck.data.sample.length === 0 ? (
          <EmptyState title="No probe firms to check yet.">
            The sample fills with 50 firms once the probe has crawled firms that have documents.
          </EmptyState>
        ) : (
          <Checker data={handcheck.data} />
        )}
      </div>
    </>
  );
}
