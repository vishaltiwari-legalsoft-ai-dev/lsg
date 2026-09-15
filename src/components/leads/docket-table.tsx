"use client";

import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import Link from "next/link";
import { memo, useEffect, useRef } from "react";

import { Highlight } from "@/components/record/proof-quote";
import { EmailStatusBadge } from "@/components/record/status-badge";
import { TierMark } from "@/components/record/tier-mark";
import { Unknown } from "@/components/record/unknown";
import type { LeadRow } from "@/lib/api/types";
import { ROLE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

type ColumnMeta = { th?: string; td?: string };

const features = tableFeatures({ columnMeta: {} as ColumnMeta });
const helper = createColumnHelper<typeof features, LeadRow>();

/**
 * What still keeps the lead off the email list, in the engine's words ("Email not
 * verified"). A lead with an open role and an unverified owner email used to be
 * hidden under Excluded; now it sits in its band with this line on it.
 */
function Blockers({ lead, className }: { lead: LeadRow; className?: string }) {
  if (lead.blockers.length === 0) return null;
  return (
    <span className={cn("block truncate text-meta text-redline", className)} title={lead.blockers.join("; ")}>
      {lead.blockers.join("; ")}
    </span>
  );
}

function ContactLine({ row }: { row: LeadRow }) {
  const c = row.contact;
  // No contact: the blockers line already says so.
  if (!c) return row.blockers.length ? null : <Unknown>No owner or office manager found</Unknown>;
  return (
    <span className="truncate">
      <span className="text-ink">{c.full_name}</span>
      <span className="text-slate">, {c.title ?? ROLE_LABEL[c.role]}</span>
    </span>
  );
}

/** Where the lead is as a person works it, and what to do next. */
function StageLine({ lead, className }: { lead: LeadRow; className?: string }) {
  return (
    <span className={cn("block truncate text-meta", className)} title={lead.next_action}>
      <span className="text-ink">{lead.stage_display}</span>
      <span className="text-slate"> · {lead.next_action}</span>
      {lead.owner ? <span className="text-slate"> · {lead.owner}</span> : null}
    </span>
  );
}

function FirmCell({ lead }: { lead: LeadRow }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <Link
        href={`/leads/${lead.id}`}
        tabIndex={-1}
        // A plain click selects into the case file; a modified click opens a tab.
        onClick={(event) => {
          if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
            event.preventDefault();
          }
        }}
        className="line-clamp-2 text-body font-medium text-ink hover:underline"
      >
        {lead.firm.name}
      </Link>
      <span className="truncate text-meta text-slate">{lead.firm.domain ?? lead.firm.city ?? ""}</span>
    </div>
  );
}

const firmColumn = helper.display({
  id: "firm",
  header: "Firm",
  meta: { th: "w-[24%] min-w-48", td: "min-w-0" },
  cell: ({ row }) => <FirmCell lead={row.original} />,
});

/**
 * With the case file open, each lead becomes a stacked docket entry — firm
 * and tier, the highlighted pain, then the contact — so a narrow docket
 * still reads in full lines instead of squeezed columns.
 */
const entryColumn = helper.display({
  id: "entry",
  header: "Lead",
  meta: { td: "min-w-0" },
  cell: ({ row }) => {
    const lead = row.original;
    const proof = lead.proof;
    return (
      <div className="grid min-w-0 gap-1">
        <div className="flex min-w-0 items-center gap-2.5">
          <Link
            href={`/leads/${lead.id}`}
            tabIndex={-1}
            onClick={(event) => {
              if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
                event.preventDefault();
              }
            }}
            className="min-w-0 truncate text-body font-medium text-ink hover:underline"
          >
            {lead.firm.name}
          </Link>
          <TierMark firm={lead.firm} variant="stamp" className="shrink-0" />
        </div>
        {proof?.quote ? (
          <span className="quotation block truncate text-quote-table leading-snug text-ink" title={proof.headline}>
            <Highlight>{proof.quote}</Highlight>
          </span>
        ) : proof ? (
          <span className="truncate text-table text-ink">{proof.headline}</span>
        ) : (
          <Unknown className="text-table">No open signal yet</Unknown>
        )}
        <span className="truncate text-meta">
          <ContactLine row={lead} />
        </span>
        <Blockers lead={lead} />
        <StageLine lead={lead} />
      </div>
    );
  },
});

const tierColumn = helper.display({
  id: "tier",
  header: () => <span className="sr-only">Tier</span>,
  meta: { th: "w-16", td: "min-w-0" },
  cell: ({ row }) => <TierMark firm={row.original.firm} variant="stamp" />,
});

const painColumn = helper.display({
  id: "pain",
  header: "Pain",
  meta: { td: "min-w-0" },
  cell: ({ row }) => {
    const proof = row.original.proof;
    if (!proof) return <Unknown>No open signal yet</Unknown>;
    return (
      <div className="grid min-w-0 gap-1">
        <span className="truncate text-table text-ink">{proof.headline}</span>
        {proof.quote ? (
          <span className="quotation block truncate text-quote-table leading-snug text-ink">
            <Highlight>{proof.quote}</Highlight>
          </span>
        ) : null}
      </div>
    );
  },
});

/** The primary contact and role, with the email status beneath — always in words. */
const contactColumn = helper.display({
  id: "contact",
  header: "Contact",
  meta: { th: "w-[23%] min-w-60", td: "min-w-0" },
  cell: ({ row }) => {
    const lead = row.original;
    const c = lead.contact;
    if (!c) {
      return lead.blockers.length ? (
        <Blockers lead={lead} className="text-table" />
      ) : (
        <Unknown className="text-table">No owner or office manager found</Unknown>
      );
    }
    return (
      <div className="grid min-w-0 justify-items-start gap-1">
        <span className="max-w-full truncate text-table">
          <span className="text-ink">{c.full_name}</span>
          <span className="text-slate">, {c.title ?? ROLE_LABEL[c.role]}</span>
        </span>
        <EmailStatusBadge contact={c} />
        <Blockers lead={lead} className="max-w-full" />
        <StageLine lead={lead} className="max-w-full" />
      </div>
    );
  },
});

const intentColumn = helper.display({
  id: "intent",
  header: () => <span className="block text-right">Intent</span>,
  meta: { th: "w-28", td: "text-right" },
  cell: ({ row }) =>
    row.original.intent === null ? (
      <Unknown className="text-meta whitespace-nowrap">Not scored</Unknown>
    ) : (
      <span className="text-body text-ink tabular-nums">{row.original.intent}</span>
    ),
});

const FULL_COLUMNS = [firmColumn, tierColumn, painColumn, contactColumn, intentColumn];
const COMPACT_COLUMNS = [entryColumn, intentColumn];
const NO_TICKS: ReadonlySet<string> = new Set();

/**
 * The docket: one entry per lead — firm, tier, the pain headline with its
 * highlighted fragment, the contact with the email status, and intent. With
 * the case file open it narrows to what triage needs; the rest is in the
 * case file.
 */
export const DocketTable = memo(function DocketTable({
  rows,
  selectedId,
  compact,
  onSelect,
  caption,
  checked,
  onToggle,
}: {
  rows: LeadRow[];
  selectedId: string | null;
  compact: boolean;
  onSelect: (id: string) => void;
  caption: string;
  /** Leads ticked for a batch action; the tick is separate from the case-file selection. */
  checked?: ReadonlySet<string>;
  /** Without it there is no tick column (the Today screen's short list). */
  onToggle?: (id: string, on: boolean) => void;
}) {
  const ticks = checked ?? NO_TICKS;
  const columns = compact ? COMPACT_COLUMNS : FULL_COLUMNS;
  const table = useTable({ features, columns, data: rows, getRowId: (row) => row.id });
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  // Keep the selected entry in view as j/k move through the docket.
  useEffect(() => {
    if (!selectedId) return;
    const el = bodyRef.current?.querySelector<HTMLElement>(`[data-row-id="${CSS.escape(selectedId)}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  const hasSelection = rows.some((r) => r.id === selectedId);

  return (
    <table className="w-full table-fixed border-collapse text-left">
      <caption className="sr-only">{caption}</caption>
      <thead className="sticky top-0 z-10 bg-sheet">
        {table.getHeaderGroups().map((group) => (
          <tr key={group.id} className="border-b border-rule">
            {onToggle ? (
              <th scope="col" className="h-9 w-10 pl-5">
                <input
                  type="checkbox"
                  aria-label="Select every lead shown"
                  className="size-3.5 accent-cobalt"
                  checked={rows.length > 0 && rows.every((r) => ticks.has(r.id))}
                  onChange={(event) => {
                    for (const r of rows) onToggle(r.id, event.target.checked);
                  }}
                />
              </th>
            ) : null}
            {group.headers.map((header) => (
              <th
                key={header.id}
                scope="col"
                className={cn(
                  "h-9 px-3 text-meta font-normal text-slate last:pr-8",
                  !onToggle && "first:pl-8",
                  header.column.columnDef.meta?.th,
                )}
              >
                {header.isPlaceholder ? null : <table.FlexRender header={header} />}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody ref={bodyRef}>
        {table.getRowModel().rows.map((row, i) => {
          const selected = row.id === selectedId;
          // Roving tab stop: the docket is one stop in the tab order.
          const tabbable = selected || (!hasSelection && i === 0);
          return (
            <tr
              key={row.id}
              data-row-id={row.id}
              tabIndex={tabbable ? 0 : -1}
              aria-current={selected ? "true" : undefined}
              onClick={() => onSelect(row.id)}
              onFocus={(event) => {
                if (event.target === event.currentTarget && !selected) onSelect(row.id);
              }}
              className={cn(
                "cursor-pointer border-b border-rule align-top transition-colors duration-75 outline-offset-[-2px] hover:bg-paper",
                selected &&
                  "bg-cobalt-wash hover:bg-cobalt-wash [&>td:first-child]:shadow-[inset_3px_0_0_var(--color-cobalt)]",
                ticks.has(row.id) && !selected && "bg-paper",
              )}
            >
              {onToggle ? (
                <td className="w-10 py-3 pl-5 align-top">
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.original.firm.name}`}
                    className="mt-0.5 size-3.5 accent-cobalt"
                    checked={ticks.has(row.id)}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => onToggle(row.id, event.target.checked)}
                  />
                </td>
              ) : null}
              {row.getAllCells().map((cell) => (
                <td
                  key={cell.id}
                  className={cn(
                    "px-3 py-3 last:pr-8",
                    !onToggle && "first:pl-8",
                    cell.column.columnDef.meta?.td,
                  )}
                >
                  <table.FlexRender cell={cell} />
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
});
