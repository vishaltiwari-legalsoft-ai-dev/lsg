"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Stage } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { OTHER_STAGES, QUEUE_STAGES, STAGE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * The work queue's tabs: one per stage a person works, in the order the
 * work comes, each with its live count. The closed and rarer stages sit in
 * one menu at the end, and it reads as the active tab when one is chosen.
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
      <div role="tablist" aria-label="Stage" className="-mb-px flex min-w-0 gap-1 overflow-x-auto">
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
                "flex h-12 shrink-0 items-center gap-2 border-b-2 px-3 text-body whitespace-nowrap transition-colors",
                active
                  ? "border-cobalt font-semibold text-ink"
                  : "border-transparent text-slate hover:border-rule-strong hover:text-ink",
              )}
            >
              {STAGE_LABEL[stage]}
              {n !== undefined ? (
                <span
                  className={cn(
                    "min-w-5 rounded-full px-1.5 text-center text-meta leading-5 tabular-nums",
                    active ? "bg-cobalt text-white" : n > 0 ? "bg-paper text-ink" : "text-slate",
                  )}
                >
                  {formatCount(n)}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="shrink-0 pb-2">
        <Select value={other} onValueChange={(v) => onChange(v as Stage)}>
          <SelectTrigger
            aria-label="Closed and other stages"
            className={cn("w-44", other && "border-cobalt bg-cobalt-wash font-medium")}
          >
            <SelectValue placeholder="Closed and other" />
          </SelectTrigger>
          <SelectContent align="end">
            {OTHER_STAGES.map((stage) => (
              <SelectItem key={stage} value={stage}>
                {STAGE_LABEL[stage]}
                {counts?.[stage] !== undefined ? ` (${formatCount(counts[stage])})` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
