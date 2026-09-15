"use client";

import Link from "next/link";

import { useOverview } from "@/lib/api/hooks";
import { formatCount } from "@/lib/format";

/**
 * The five steps in the rail, each with its live count: the same story the
 * home page tells, always in view. Each step links to where it is worked.
 */
export function PipelineMini() {
  const overview = useOverview();
  const steps = overview.data?.steps;
  if (!steps) return null;
  return (
    <nav aria-label="Pipeline" className="grid gap-1 border-t border-rule pt-4">
      <p className="px-2.5 pb-1 text-meta text-slate">The pipeline</p>
      <ol className="grid gap-0.5">
        {steps.map((step) => (
          <li key={step.key}>
            <Link
              href={step.href}
              className="flex h-7 items-center gap-2.5 rounded-control px-2.5 text-table text-slate transition-colors hover:bg-sheet hover:text-ink"
              title={step.what}
            >
              <span className="w-3 shrink-0 text-meta tabular-nums">{step.number}</span>
              <span className="min-w-0 flex-1 truncate">{step.label}</span>
              <span className="shrink-0 text-ink tabular-nums">{formatCount(step.count)}</span>
            </Link>
          </li>
        ))}
      </ol>
    </nav>
  );
}
