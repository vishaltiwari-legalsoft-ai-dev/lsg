"use client";

import { SearchIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Unknown, ValueOrUnknown } from "@/components/record/unknown";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Button, buttonVariants } from "@/components/ui/button";
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
        <div key={i} className="flex items-center gap-6 border-b border-rule py-3.5 last:border-b-0">
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

/** Every firm on file, searchable by name or domain. */
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
        meta={total !== undefined ? `${formatCount(total)} ${q ? "matching" : "on file"}` : undefined}
      />
      <div className="grid max-w-[80rem] gap-5 px-8 pt-6 pb-16 max-md:px-4">
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

        <section aria-label="Firms" className={cn("border-t border-rule transition-opacity duration-150", firms.isPlaceholderData && "opacity-60")}>
          {firms.isPending ? (
            <FirmsSkeleton />
          ) : firms.isError ? (
            <div className="py-6">
              <ErrorState error={firms.error} onRetry={() => void firms.refetch()} />
            </div>
          ) : items.length === 0 ? (
            <div>
              <EmptyState
                title={q ? `No firm matches “${q}”.` : "No firms on file yet."}
                action={
                  q ? null : (
                    <Link href="/imports" className={buttonVariants({ variant: "primary" })}>
                      Upload a sheet
                    </Link>
                  )
                }
              >
                {q ? "Try part of the name, or the domain without www." : "Firms appear here once a sheet of them is loaded."}
              </EmptyState>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[44rem] border-collapse text-left">
                <caption className="sr-only">Firms. Select a firm to open its record.</caption>
                <thead>
                  <tr className="border-b border-rule text-meta text-slate">
                    <th scope="col" className="h-10 w-[40%] font-medium">Firm</th>
                    <th scope="col" className="font-medium">Place</th>
                    <th scope="col" className="font-medium">Tier</th>
                    <th scope="col" className="font-medium">Lead</th>
                    <th scope="col" className="text-right font-medium">Fit</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((firm) => (
                    <tr
                      key={firm.id}
                      onClick={() => router.push(`/firms/${firm.id}`)}
                      className="cursor-pointer border-b border-rule text-table transition-colors duration-75 last:border-b-0 hover:bg-paper"
                    >
                      <td className="max-w-0 py-3 pr-4">
                        <Link href={`/firms/${firm.id}`} className="block truncate text-body font-semibold text-ink hover:underline">
                          {firm.name}
                        </Link>
                        <span className="block truncate text-meta text-slate">
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
                      <td className="text-right">
                        {firm.fit === null ? (
                          <Unknown className="text-meta">Not scored</Unknown>
                        ) : (
                          <span className="type-narrow text-subtitle leading-none font-semibold text-ink tabular-nums">{firm.fit}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

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
