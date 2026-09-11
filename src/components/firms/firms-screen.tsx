"use client";

import { SearchIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Panel } from "@/components/layout/panel";
import { Unknown, ValueOrUnknown } from "@/components/record/unknown";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useUrlState } from "@/hooks/use-url-state";
import { useFirms } from "@/lib/api/hooks";
import { formatCount, formatPlace } from "@/lib/format";
import { cn } from "@/lib/utils";

function FirmsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading firms">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-rule px-6 py-3 last:border-b-0">
          <div className="grid w-[34%] gap-1.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-8" />
        </div>
      ))}
    </div>
  );
}

/** Every firm in the universe, searchable by name or domain. */
export function FirmsScreen() {
  const router = useRouter();
  const { params, update } = useUrlState();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);

  useEffect(() => {
    const next = draft.trim();
    if (next === q) return;
    const timer = setTimeout(() => update({ q: next || null }), 220);
    return () => clearTimeout(timer);
  }, [draft, q, update]);

  const firms = useFirms({ q: q || undefined });
  const items = useMemo(() => firms.data?.pages.flatMap((p) => p.items) ?? [], [firms.data]);
  const total = firms.data?.pages[0]?.total;

  return (
    <>
      <TitleBar
        title="Firms"
        meta={total !== undefined ? `${formatCount(total)} ${q ? "matching" : "in the universe"}` : undefined}
      />
      <div className="grid max-w-[76rem] gap-5 px-8 pt-6 pb-16">
        <div className="relative w-80">
          <SearchIcon
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-slate"
            aria-hidden="true"
          />
          <Input
            type="search"
            aria-label="Search firms by name or domain"
            placeholder="Search by name or domain"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="pl-8"
          />
        </div>

        <Panel className={cn("overflow-hidden transition-opacity duration-150", firms.isPlaceholderData && "opacity-60")}>
          {firms.isPending ? (
            <FirmsSkeleton />
          ) : firms.isError ? (
            <div className="px-6 py-6">
              <ErrorState error={firms.error} onRetry={() => void firms.refetch()} />
            </div>
          ) : items.length === 0 ? (
            <div className="px-6">
              <EmptyState title={q ? `No firm matches “${q}”.` : "No firms loaded yet."}>
                {q
                  ? "Try part of the name, or the domain without www."
                  : "Firms appear once the purchased firm list has been loaded into the engine."}
              </EmptyState>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[44rem] border-collapse text-left">
                <caption className="sr-only">Firms. Select a firm to open its record.</caption>
                <thead>
                  <tr className="border-b border-rule text-meta text-slate">
                    <th scope="col" className="h-9 w-[44%] pl-6 font-normal">Firm</th>
                    <th scope="col" className="font-normal">Place</th>
                    <th scope="col" className="font-normal">Tier</th>
                    <th scope="col" className="font-normal">Lead</th>
                    <th scope="col" className="pr-6 text-right font-normal">Fit</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((firm) => (
                    <tr
                      key={firm.id}
                      onClick={() => router.push(`/firms/${firm.id}`)}
                      className="h-10 cursor-pointer border-b border-rule text-table transition-colors duration-75 last:border-b-0 hover:bg-paper"
                    >
                      <td className="max-w-0 truncate pr-4 pl-6">
                        <Link href={`/firms/${firm.id}`} className="text-body font-medium text-ink hover:underline">
                          {firm.name}
                        </Link>
                        <span className="ml-2 text-meta text-slate">
                          {firm.domain ?? <Unknown>No website on record</Unknown>}
                        </span>
                      </td>
                      <td className="pr-4 text-ink">
                        <ValueOrUnknown value={formatPlace(firm.city, firm.state)} />
                      </td>
                      <td className="pr-4 text-ink">{firm.tier_display}</td>
                      <td className="pr-4 text-slate">
                        <ValueOrUnknown value={firm.state_display} unknown="No lead yet" />
                      </td>
                      <td className="pr-6 text-right text-body text-ink tabular-nums">
                        {firm.fit === null ? <Unknown className="text-meta">Not scored</Unknown> : firm.fit}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {firms.hasNextPage ? (
          <div className="flex items-center gap-4">
            <Button
              variant="secondary"
              size="sm"
              disabled={firms.isFetchingNextPage}
              onClick={() => void firms.fetchNextPage()}
            >
              {firms.isFetchingNextPage ? "Loading more…" : "Load more"}
            </Button>
            {total !== undefined ? (
              <span className="text-table text-slate tabular-nums">
                Showing {formatCount(items.length)} of {formatCount(total)}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}
