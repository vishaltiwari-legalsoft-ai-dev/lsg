"use client";

import { CheckIcon, MinusIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Panel } from "@/components/layout/panel";
import { Unknown } from "@/components/record/unknown";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useUrlState } from "@/hooks/use-url-state";
import { api } from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";
import { useQualified } from "@/lib/api/hooks";
import type { QualifiedCheck, QualifiedCheckKey, QualifiedOnly, QualifiedRow } from "@/lib/api/types";
import { formatCount, formatPlace, toDateInputValue } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The seven steps, in the order the engine does them. Labels come from the API. */
const CHECK_ORDER: QualifiedCheckKey[] = [
  "site_read", "fit", "person", "email", "email_verified", "linkedin", "journey",
];

const TABS: { only: QualifiedOnly; label: string }[] = [
  { only: "ready", label: "Ready to reach" },
  { only: "almost", label: "One step away" },
];

function parseOnly(value: string | null): QualifiedOnly {
  return value === "almost" || value === "all" ? value : "ready";
}

function check(row: QualifiedRow, key: QualifiedCheckKey): QualifiedCheck | undefined {
  return row.checks.find((c) => c.key === key);
}

function StepMarks({ row }: { row: QualifiedRow }) {
  return (
    <ol className="flex items-center gap-1" aria-label="Steps">
      {CHECK_ORDER.map((key) => {
        const c = check(row, key);
        if (!c) return null;
        return (
          <li
            key={key}
            title={`${c.label}: ${c.detail ?? (c.ok ? "done" : "missing")}`}
            className={cn(
              "inline-flex size-5 items-center justify-center rounded-[4px] border",
              c.ok ? "border-ledger/40 bg-ledger-wash text-ledger" : "border-redline/40 bg-redline-wash text-redline",
            )}
          >
            {c.ok ? <CheckIcon className="size-3" aria-hidden="true" /> : <MinusIcon className="size-3" aria-hidden="true" />}
            <span className="sr-only">{c.label}: {c.ok ? "done" : "missing"}</span>
          </li>
        );
      })}
    </ol>
  );
}

function QualifiedSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading qualified leads">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-rule px-6 py-3 last:border-b-0">
          <div className="grid w-[26%] gap-1.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-5 w-40" />
        </div>
      ))}
    </div>
  );
}

async function downloadReadyCsv() {
  const csv = await api.exportQualifiedCsv();
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `qualified-leads-${toDateInputValue(new Date())}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Qualified leads: the leads on which every step has been done -- site read,
 * fit, a named decision-maker, an address, the address verified, a LinkedIn
 * profile, the journey drafted -- and the ones one step away, with exactly
 * what is missing. Tab and search live in the URL.
 */
export function QualifiedScreen() {
  const router = useRouter();
  const { params, update } = useUrlState();
  const only = parseOnly(params.get("only"));
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const next = draft.trim();
    if (next === q) return;
    const timer = setTimeout(() => update({ q: next || null }), 220);
    return () => clearTimeout(timer);
  }, [draft, q, update]);

  const qualified = useQualified({ only, q: q || undefined });
  const items = useMemo(() => qualified.data?.pages.flatMap((p) => p.items) ?? [], [qualified.data]);
  const counts = qualified.data?.pages[0]?.counts;
  const holdingBack = useMemo(() => {
    if (!counts) return [];
    const labels = new Map<QualifiedCheckKey, string>();
    for (const row of items) for (const c of row.checks) labels.set(c.key, c.label);
    return CHECK_ORDER
      .map((key) => ({ key, label: labels.get(key) ?? key, count: counts.missing_by_check[key] ?? 0 }))
      .filter((entry) => entry.count > 0);
  }, [counts, items]);

  return (
    <>
      <TitleBar
        title="Qualified leads"
        meta={
          counts
            ? `${formatCount(counts.ready)} ready · ${formatCount(counts.almost)} one step away · ${formatCount(counts.checked)} checked`
            : undefined
        }
        actions={
          <Button
            variant="secondary"
            size="sm"
            disabled={exporting || !counts || counts.ready === 0}
            onClick={async () => {
              setExporting(true);
              try {
                await downloadReadyCsv();
                toast.success("Exported the ready leads as CSV");
              } catch (error) {
                toast.error(describeError(error));
              } finally {
                setExporting(false);
              }
            }}
          >
            {exporting ? "Exporting…" : "Export the ready leads (CSV)"}
          </Button>
        }
      />
      <div className="grid max-w-[84rem] gap-5 px-8 pt-6 pb-16">
        <p className="max-w-[72ch] text-body text-slate">
          A lead is qualified when every step is done: the site was read, the firm fits the profile, a
          decision-maker is named, their address is on file and verified, their LinkedIn profile is found,
          and the journey drafts. Nothing less goes to outreach.
        </p>

        <div className="flex flex-wrap items-center gap-4">
          <div role="tablist" aria-label="Which leads" className="flex gap-1 rounded-control border border-rule bg-sheet p-0.5">
            {TABS.map((tab) => {
              const count = counts ? (tab.only === "ready" ? counts.ready : counts.almost) : null;
              const active = only === tab.only;
              return (
                <button
                  key={tab.only}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => update({ only: tab.only === "ready" ? null : tab.only })}
                  className={cn(
                    "h-8 rounded-[6px] px-3 text-table transition-colors duration-75",
                    active ? "bg-cobalt-wash text-cobalt-deep font-medium" : "text-slate hover:bg-paper",
                  )}
                >
                  {tab.label}
                  {count !== null ? <span className="ml-1.5 tabular-nums">{formatCount(count)}</span> : null}
                </button>
              );
            })}
          </div>
          <div className="relative w-72">
            <SearchIcon
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-slate"
              aria-hidden="true"
            />
            <Input
              type="search"
              aria-label="Search qualified leads by firm name or domain"
              placeholder="Search by firm or domain"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="pl-8"
            />
          </div>
        </div>

        {only === "almost" && holdingBack.length > 0 ? (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-table text-slate">
            <span>What is holding them back:</span>
            {holdingBack.map((entry) => (
              <span key={entry.key} className="inline-flex items-center gap-1 rounded-[4px] border border-rule bg-sheet px-2 py-0.5">
                <span className="text-ink">{entry.label}</span>
                <span className="text-redline tabular-nums">{formatCount(entry.count)}</span>
              </span>
            ))}
          </p>
        ) : null}

        <Panel className={cn("overflow-hidden transition-opacity duration-150", qualified.isPlaceholderData && "opacity-60")}>
          {qualified.isPending ? (
            <QualifiedSkeleton />
          ) : qualified.isError ? (
            <div className="px-6 py-6">
              <ErrorState error={qualified.error} onRetry={() => void qualified.refetch()} />
            </div>
          ) : items.length === 0 ? (
            <div className="px-6">
              {q ? (
                <EmptyState title={`No qualified lead matches “${q}”.`}>
                  Try part of the firm&apos;s name, or the domain without www.
                </EmptyState>
              ) : only === "ready" ? (
                <EmptyState
                  title="No lead has every step done yet."
                  action={
                    counts && counts.almost > 0 ? (
                      <Button variant="secondary" size="sm" onClick={() => update({ only: "almost" })}>
                        See the {formatCount(counts.almost)} one step away
                      </Button>
                    ) : null
                  }
                >
                  A lead appears here only when all seven steps are done. The nearest ones are one or two
                  steps short — usually a verified address or a LinkedIn profile.
                </EmptyState>
              ) : (
                <EmptyState title="Nothing is close yet.">
                  Leads land here once the site is read and a decision-maker with an address is found.
                  Research runs from the work queue.
                </EmptyState>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[64rem] border-collapse text-left">
                <caption className="sr-only">Qualified leads. Select a lead to open it.</caption>
                <thead>
                  <tr className="border-b border-rule text-meta text-slate">
                    <th scope="col" className="h-9 w-[20%] pl-6 font-normal">Firm</th>
                    <th scope="col" className="w-[16%] font-normal">Decision-maker</th>
                    <th scope="col" className="w-[22%] font-normal">Address</th>
                    <th scope="col" className="w-[7%] font-normal">LinkedIn</th>
                    <th scope="col" className="w-[13%] font-normal">Why now</th>
                    <th scope="col" className="pr-6 font-normal">{only === "ready" ? "Steps" : "Missing"}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => {
                    const person = check(row, "person");
                    const email = check(row, "email");
                    const verified = check(row, "email_verified");
                    const linkedin = check(row, "linkedin");
                    return (
                      <tr
                        key={row.id}
                        onClick={() => router.push(`/leads/${row.id}`)}
                        className="cursor-pointer border-b border-rule text-table transition-colors duration-75 last:border-b-0 hover:bg-paper"
                      >
                        <td className="max-w-0 truncate py-2.5 pr-4 pl-6">
                          <Link href={`/leads/${row.id}`} className="text-body font-medium text-ink hover:underline">
                            {row.firm.name}
                          </Link>
                          <div className="text-meta text-slate">
                            {[formatPlace(row.firm.city, row.firm.state), row.firm.tier_display].filter(Boolean).join(" · ")}
                          </div>
                        </td>
                        <td className="max-w-0 truncate pr-4 text-ink">
                          {person?.ok ? person.detail : <Unknown>{person?.detail ?? "No one named"}</Unknown>}
                        </td>
                        <td className="max-w-0 pr-4">
                          {email?.ok ? (
                            <div className="grid gap-0.5">
                              <span className="truncate text-ink" title={email.detail ?? undefined}>{email.detail}</span>
                              <span className={cn("truncate text-meta", verified?.ok ? "text-ledger" : "text-redline")}>
                                {verified?.detail}
                              </span>
                            </div>
                          ) : (
                            <Unknown>{email?.detail ?? "No address"}</Unknown>
                          )}
                        </td>
                        <td className="pr-4">
                          {linkedin?.ok && linkedin.detail ? (
                            <a
                              href={linkedin.detail}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-cobalt hover:underline"
                            >
                              Profile
                            </a>
                          ) : (
                            <Unknown>None found</Unknown>
                          )}
                        </td>
                        <td className="max-w-0 truncate pr-4 text-ink">
                          {row.proof ? row.proof.headline : <Unknown>{row.why_now ? "A signal is open" : "No open signal"}</Unknown>}
                        </td>
                        <td className="pr-6">
                          {only === "ready" ? (
                            <StepMarks row={row} />
                          ) : (
                            <div className="grid gap-1">
                              <span className="text-redline">{row.missing.join(" · ")}</span>
                              <StepMarks row={row} />
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {qualified.hasNextPage ? (
          <div className="flex items-center gap-4">
            <Button
              variant="secondary"
              size="sm"
              disabled={qualified.isFetchingNextPage}
              onClick={() => void qualified.fetchNextPage()}
            >
              {qualified.isFetchingNextPage ? "Loading more…" : "Load more"}
            </Button>
            <span className="text-table text-slate tabular-nums">Showing {formatCount(items.length)}</span>
          </div>
        ) : null}
      </div>
    </>
  );
}
