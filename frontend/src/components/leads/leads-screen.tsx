"use client";

import { DownloadIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { CaseFile } from "@/components/case-file/case-file";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { isShortcutBlocked, useKeydown } from "@/hooks/use-keydown";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";
import { useLeads } from "@/lib/api/hooks";
import type { Band, Contest, LeadRow, LeadView, Stage } from "@/lib/api/types";
import { formatCount, toDateInputValue } from "@/lib/format";
import { OTHER_STAGES, QUEUE_STAGES, STAGE_EMPTY, STAGE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { BatchBar } from "./batch-bar";
import { resolveDocketKey, zoneOf } from "./docket-keys";
import { DocketTable } from "./docket-table";
import { FilterBar, type LeadFilters } from "./filter-bar";
import { StageTabs } from "./stage-tabs";

const EMPTY_ROWS: LeadRow[] = [];
const CONTESTS: Contest[] = ["NONE", "LOW", "MED", "HIGH"];
const PRIORITIES: Band[] = ["STRIKE", "SEQUENCE", "NURTURE", "HOLD"];
const EXPORTS: { view: LeadView; label: string; what: string }[] = [
  { view: "STRIKE", label: "Strike list", what: "An open role right now; write by hand, today" },
  { view: "SEQUENCE", label: "Sequence list", what: "Fits, with a live signal; the nine touches" },
  { view: "NURTURE", label: "Nurture list", what: "Fits, no signal yet; a light touch" },
  { view: "PHONE", label: "Phone list", what: "A named owner with no verifiable email" },
];

function parseStage(value: string | null): Stage {
  const all: Stage[] = [...QUEUE_STAGES, ...OTHER_STAGES];
  return all.includes(value as Stage) ? (value as Stage) : "needs_review";
}

function DocketSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading leads">
      <div className="h-10 border-b border-rule" />
      {Array.from({ length: 7 }, (_, i) => (
        <div key={i} className="flex gap-6 border-b border-rule py-4 pr-8 pl-8">
          <div className="grid w-[24%] gap-2">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-2/5" />
          </div>
          <Skeleton className="h-5 w-7" />
          <div className="grid flex-1 gap-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-11/12" />
          </div>
          <div className="grid w-[18%] gap-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/3" />
          </div>
          <Skeleton className="h-4 w-8" />
        </div>
      ))}
    </div>
  );
}

function KeyHints() {
  return (
    <p className="flex flex-wrap items-center gap-x-5 gap-y-1 px-8 py-5 text-meta text-slate">
      <span className="inline-flex items-center gap-1.5">
        <Kbd>J</Kbd>
        <Kbd>K</Kbd> move
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Kbd>Enter</Kbd> opens the lead&apos;s page
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Kbd>Esc</Kbd> closes
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Kbd>1</Kbd>–<Kbd>7</Kbd> record an outcome while the lead has focus
      </span>
    </p>
  );
}

async function downloadCsv(view: LeadView, filters: LeadFilters) {
  const csv = await api.exportLeadsCsv(view, filters);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `leads-${view.toLowerCase()}-${toDateInputValue(new Date())}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The lists the engine builds, each a CSV with the filters applied. */
function ExportMenu({ filters }: { filters: LeadFilters }) {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState<LeadView | null>(null);

  async function exportList(view: LeadView, label: string) {
    setExporting(view);
    try {
      await downloadCsv(view, filters);
      toast.success(`Exported the ${label} as CSV`);
      setOpen(false);
    } catch (error) {
      toast.error(describeError(error));
    } finally {
      setExporting(null);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="secondary" size="md" aria-expanded={open}>
          <DownloadIcon aria-hidden="true" />
          Export a list
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-1.5">
        <p className="px-2.5 pt-1.5 pb-2 text-meta text-slate">A CSV, with the filters on this screen applied.</p>
        <ul className="grid">
          {EXPORTS.map((e) => (
            <li key={e.view}>
              <button
                type="button"
                disabled={exporting !== null}
                onClick={() => void exportList(e.view, e.label)}
                className="grid w-full gap-0.5 rounded-control px-2.5 py-2 text-left transition-colors hover:bg-cobalt-wash disabled:opacity-50"
              >
                <span className="text-body font-medium text-ink">
                  {exporting === e.view ? "Exporting…" : e.label}
                </span>
                <span className="text-meta text-slate">{e.what}</span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

/**
 * The work queue: every lead, grouped by what it needs next, with the lead
 * itself beside the list. Stage, priority, filters and the open lead live
 * in the URL, so any state can be linked.
 */
export function LeadsScreen() {
  const router = useRouter();
  const { params, update } = useUrlState();

  const stage = parseStage(params.get("stage"));
  const selectedId = params.get("lead");
  const bandParam = params.get("band");
  const band = PRIORITIES.includes(bandParam as Band) ? (bandParam as Band) : undefined;
  const owner = params.get("owner") ?? undefined;
  const contestParam = params.get("contest");
  const verifiedParam = params.get("verified");
  const filters: LeadFilters = useMemo(
    () => ({
      tier: params.get("tier") ?? undefined,
      city: params.get("city") ?? undefined,
      signal: params.get("signal") ?? undefined,
      contest: CONTESTS.includes(contestParam as Contest) ? (contestParam as Contest) : undefined,
      verified: verifiedParam === "true" ? true : verifiedParam === "false" ? false : undefined,
      q: params.get("q") ?? undefined,
    }),
    [params, contestParam, verifiedParam],
  );

  const leads = useLeads({ stage, band, owner, ...filters });
  const rows = useMemo(() => leads.data?.pages.flatMap((p) => p.items) ?? EMPTY_ROWS, [leads.data]);
  const ids = useMemo(() => rows.map((r) => r.id), [rows]);
  const stageCounts = leads.data?.pages[0]?.stage_counts;
  const total = stageCounts?.[stage];
  const hasFilters = Object.values(filters).some((v) => v !== undefined) || band !== undefined || owner !== undefined;

  const select = useCallback((id: string) => update({ lead: id }), [update]);
  const close = useCallback(() => update({ lead: null }), [update]);

  // Leads ticked for a batch action -- cleared when the stage changes.
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = useCallback((id: string, on: boolean) => {
    setChecked((prev) => {
      if (prev.has(id) === on) return prev;
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);
  const clearChecked = useCallback(() => setChecked(new Set()), []);
  const checkedIds = useMemo(() => ids.filter((id) => checked.has(id)), [ids, checked]);

  const focusRow = (id: string) =>
    requestAnimationFrame(() =>
      document.querySelector<HTMLElement>(`[data-docket] [data-row-id="${CSS.escape(id)}"]`)?.focus(),
    );

  useKeydown((event) => {
    if (isShortcutBlocked(event)) return;
    const zone = zoneOf(event.target);
    const command = resolveDocketKey({
      key: event.key,
      ids,
      selectedId,
      zone,
      modified: event.ctrlKey || event.metaKey || event.altKey,
    });
    switch (command.type) {
      case "select":
        event.preventDefault();
        select(command.id);
        if (zone !== "casefile") focusRow(command.id);
        break;
      case "open":
        event.preventDefault();
        router.push(`/leads/${command.id}`);
        break;
      case "close": {
        event.preventDefault();
        const previous = selectedId;
        close();
        if (previous && zone === "casefile") focusRow(previous);
        break;
      }
      default:
        break;
    }
  });

  const panelOpen = Boolean(selectedId);

  return (
    // On a wide screen the queue fills the sheet and scrolls inside it, so the
    // lead beside it and the tabs above it stay put.
    <div className="flex flex-col lg:h-[calc(100dvh-2*var(--sheet-inset))]">
      <TitleBar
        title="Work queue"
        meta={
          total !== undefined
            ? `${formatCount(total)} ${total === 1 ? "lead" : "leads"} here${hasFilters ? " with these filters" : ""}`
            : undefined
        }
        actions={<ExportMenu filters={filters} />}
      />

      <div className="flex min-h-0 flex-1 max-lg:flex-col">
        <div className="flex min-w-0 flex-1 flex-col" data-docket="">
          <div className="border-b border-rule px-8 max-md:px-4">
            <StageTabs
              value={stage}
              counts={stageCounts}
              controls="docket-panel"
              onChange={(next) => {
                clearChecked();
                update({ stage: next === "needs_review" ? null : next, lead: null });
              }}
            />
          </div>
          <div className="border-b border-rule bg-paper/60 px-8 py-3 max-md:px-4">
            <FilterBar
              filters={filters}
              band={band}
              onChange={(patch) => update({ ...patch, lead: selectedId })}
              onBandChange={(next) => update({ band: next ?? null, lead: selectedId })}
            />
          </div>
          {checkedIds.length > 0 ? <BatchBar ids={checkedIds} onClear={clearChecked} /> : null}

          <div
            id="docket-panel"
            role="tabpanel"
            aria-labelledby={`stage-tab-${stage}`}
            className={cn(
              "min-h-0 flex-1 overflow-y-auto bg-sheet transition-opacity duration-150",
              leads.isPlaceholderData && "opacity-60",
            )}
            aria-busy={leads.isFetching || undefined}
          >
            {leads.isPending ? (
              <DocketSkeleton />
            ) : leads.isError ? (
              <div className="px-8 py-8">
                <ErrorState error={leads.error} onRetry={() => void leads.refetch()} />
              </div>
            ) : rows.length === 0 ? (
              <div className="px-8">
                {hasFilters ? (
                  <EmptyState
                    title={`Nothing ${STAGE_LABEL[stage].toLowerCase()} matches these filters.`}
                    action={
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() =>
                          update({ tier: null, city: null, signal: null, contest: null, verified: null, q: null, band: null, owner: null })
                        }
                      >
                        Clear filters
                      </Button>
                    }
                  >
                    Widen a filter, or clear them.
                  </EmptyState>
                ) : (
                  <EmptyState title={`No lead is at ${STAGE_LABEL[stage].toLowerCase()}.`}>{STAGE_EMPTY[stage]}</EmptyState>
                )}
              </div>
            ) : (
              <>
                <DocketTable
                  rows={rows}
                  selectedId={selectedId}
                  compact={panelOpen}
                  onSelect={select}
                  caption={`Leads that are ${STAGE_LABEL[stage].toLowerCase()}. J and K move, Enter opens the lead's page.`}
                  checked={checked}
                  onToggle={toggle}
                />
                {leads.hasNextPage ? (
                  <div className="flex items-center gap-4 px-8 pt-5">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={leads.isFetchingNextPage}
                      onClick={() => void leads.fetchNextPage()}
                    >
                      {leads.isFetchingNextPage ? "Loading more…" : "Load more"}
                    </Button>
                    {total !== undefined ? (
                      <span className="text-table text-slate tabular-nums">
                        Showing {formatCount(rows.length)} of {formatCount(total)}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                <KeyHints />
              </>
            )}
          </div>
        </div>

        {selectedId ? (
          <aside
            aria-label="Lead"
            className="shrink-0 border-rule bg-sheet max-lg:border-t lg:w-[clamp(26rem,46%,40rem)] lg:overflow-y-auto lg:rounded-br-(--radius-sheet) lg:border-l"
          >
            <CaseFile key={selectedId} id={selectedId} mode="panel" onClose={close} />
          </aside>
        ) : null}
      </div>
    </div>
  );
}
