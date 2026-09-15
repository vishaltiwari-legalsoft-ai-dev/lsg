"use client";

import type { Stage } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { OTHER_STAGES, QUEUE_STAGES, STAGE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * The work queue's tabs: one per stage a person works, in the order the
 * work comes, each with its live count. The closed and rarer stages sit in
 * a select at the end.
 */
export function StageTabs({
  value,
  counts,
  controls,
  onChange,
}: {
  value: Stage;
  counts: Record<string, number> | undefined;
  controls: string;
  onChange: (next: Stage) => void;
}) {
  const other = OTHER_STAGES.includes(value) ? value : "";
  return (
    <div className="flex items-end justify-between gap-4">
      <div role="tablist" aria-label="Stage" className="flex flex-wrap gap-1">
        {QUEUE_STAGES.map((stage) => {
          const active = stage === value;
          const n = counts?.[stage];
          return (
            <button
              key={stage}
              type="button"
              role="tab"
              id={`stage-tab-${stage}`}
              aria-selected={active}
              aria-controls={controls}
              tabIndex={active ? 0 : -1}
              onClick={() => onChange(stage)}
              className={cn(
                "-mb-px flex h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-body transition-colors",
                active
                  ? "border-cobalt font-medium text-ink"
                  : "border-transparent text-slate hover:border-rule-strong hover:text-ink",
              )}
            >
              {STAGE_LABEL[stage]}
              {n !== undefined ? (
                <span className={cn("text-meta tabular-nums", active ? "text-cobalt" : "text-slate")}>
                  {formatCount(n)}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <label className="flex shrink-0 items-center gap-2 pb-2 text-meta text-slate">
        Closed and other
        <select
          value={other}
          onChange={(e) => e.target.value && onChange(e.target.value as Stage)}
          className={cn(
            "h-8 rounded-control border border-rule bg-sheet px-2 text-table text-ink",
            other && "border-cobalt",
          )}
        >
          <option value="">Choose…</option>
          {OTHER_STAGES.map((stage) => (
            <option key={stage} value={stage}>
              {STAGE_LABEL[stage]}
              {counts?.[stage] !== undefined ? ` (${formatCount(counts[stage])})` : ""}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
