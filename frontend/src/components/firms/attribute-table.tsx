"use client";

import { ArrowUpRightIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";

import { Quotation } from "@/components/record/proof-quote";
import { StatusBadge } from "@/components/record/status-badge";
import { AttributeValue, isUnknownDisplay } from "@/components/record/unknown";
import type { AttributeClaim, AttributeRow } from "@/lib/api/types";
import { formatDate, formatDecimal } from "@/lib/format";
import { cn } from "@/lib/utils";

function StateBadge({ row }: { row: AttributeRow }) {
  if (row.state === "conflict") return <StatusBadge state="failure">Conflict</StatusBadge>;
  if (row.state === "stale") return <StatusBadge state="unverified">Stale</StatusBadge>;
  return null;
}

function claimVerdict(claim: AttributeClaim, winner: AttributeClaim | undefined) {
  if (claim.won) return <StatusBadge state="verified">Won</StatusBadge>;
  if (winner && claim.display === winner.display) {
    return <span className="text-meta text-slate">Agrees</span>;
  }
  return <span className="text-meta text-redline">Lost</span>;
}

function Claims({ row, id }: { row: AttributeRow; id: string }) {
  const winner = row.claims.find((c) => c.won);
  const ordered = [...row.claims].sort((a, b) => Number(b.won) - Number(a.won) || b.confidence - a.confidence);
  return (
    <ol id={id} className="grid gap-4 py-1" aria-label={`Claims for ${row.label}`}>
      {ordered.map((claim, i) => (
        <li key={`${claim.source_label}-${i}`} className="grid grid-cols-[4.5rem_minmax(0,1fr)_4rem] items-start gap-3">
          <span className="pt-0.5">{claimVerdict(claim, winner)}</span>
          <div className="grid min-w-0 gap-1.5">
            <p className="text-table">
              <span className="text-ink">{claim.display}</span>
              <span className="text-slate">
                , from {claim.source_label}, read {formatDate(claim.observed_at)}
              </span>
            </p>
            {claim.evidence ? <Quotation text={claim.evidence} size="table" marked={claim.won} /> : null}
          </div>
          <span className="text-right text-table text-ink tabular-nums">{formatDecimal(claim.confidence)}</span>
        </li>
      ))}
    </ol>
  );
}

function Row({ row }: { row: AttributeRow }) {
  const [open, setOpen] = useState(false);
  const claimsId = `claims-${row.attr}`;
  const unknown = row.state === "unknown" || isUnknownDisplay(row.display);
  const expandable = row.claims.length > 0;

  return (
    <tbody className="border-b border-rule last:border-b-0">
      <tr className={cn("align-top", open && "bg-paper/60")}>
        <th scope="row" className="w-[12rem] py-3.5 pr-4 pl-6 text-left font-normal">
          {expandable ? (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={claimsId}
              onClick={() => setOpen((o) => !o)}
              className="group flex items-start gap-1.5 rounded-[4px] text-left text-table text-slate hover:text-ink"
            >
              <ChevronRightIcon
                aria-hidden="true"
                className={cn("mt-0.5 size-3.5 shrink-0 transition-transform duration-150", open && "rotate-90")}
              />
              <span>
                {row.label}
                <span className="sr-only">, {row.claims.length} claims</span>
              </span>
            </button>
          ) : (
            <span className="block pl-5 text-table text-slate">{row.label}</span>
          )}
        </th>

        {unknown ? (
          <td colSpan={3} className="py-3.5 pr-6">
            <AttributeValue display={row.display} state={row.state} className="text-body" />
          </td>
        ) : (
          <>
            <td className="py-3.5 pr-4">
              <div className="grid gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <AttributeValue display={row.display} state={row.state} className="text-body font-medium" />
                  <StateBadge row={row} />
                </div>
                {row.evidence ? <Quotation text={row.evidence} size="table" className="max-w-[56ch]" /> : null}
              </div>
            </td>
            <td className="w-[15rem] py-3.5 pr-4 text-table">
              <span className="block text-ink">{row.source_label ?? "Source not recorded"}</span>
              {row.observed_at ? (
                <span className="block text-meta text-slate">Read {formatDate(row.observed_at)}</span>
              ) : null}
              {row.evidence_url ? (
                <a
                  href={row.evidence_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-0.5 inline-flex items-center gap-0.5 text-meta text-cobalt hover:underline"
                >
                  View the page
                  <ArrowUpRightIcon className="size-3" aria-hidden="true" />
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              ) : null}
            </td>
            <td className="w-[6rem] py-3.5 pr-6 text-right text-body text-ink tabular-nums">
              {row.confidence === null ? (
                <span className="text-meta text-slate italic">Not scored</span>
              ) : (
                formatDecimal(row.confidence)
              )}
            </td>
          </>
        )}
      </tr>
      {expandable && open ? (
        <tr className="bg-paper/60">
          <td />
          <td colSpan={3} className="pr-6 pb-5">
            <Claims row={row} id={claimsId} />
          </td>
        </tr>
      ) : null}
    </tbody>
  );
}

/**
 * The firm as a record: attribute, the value that won, where it was read and
 * how sure the engine is. Expanding a row shows the competing claims, like a
 * record keeping the losing arguments.
 */
export function AttributeTable({ attributes }: { attributes: AttributeRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-rule text-meta text-slate">
            <th scope="col" className="h-9 pl-6 font-normal">
              Attribute
            </th>
            <th scope="col" className="font-normal">
              Value and evidence
            </th>
            <th scope="col" className="font-normal">
              Source
            </th>
            <th scope="col" className="pr-6 text-right font-normal">
              Confidence
            </th>
          </tr>
        </thead>
        {attributes.map((row) => (
          <Row key={row.attr} row={row} />
        ))}
      </table>
    </div>
  );
}
