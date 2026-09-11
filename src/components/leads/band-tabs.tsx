"use client";

import { useRef } from "react";

import type { LeadCounts, LeadView } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { VIEW_LABEL, VIEWS } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * The bands as tabs, each with its count. Phone list is its own tab — grade
 * B is a product, not a filter state of Excluded. Arrow keys move between
 * tabs (automatic activation), per the ARIA tabs pattern.
 */
export function BandTabs({
  value,
  counts,
  onChange,
  controls,
}: {
  value: LeadView;
  counts: LeadCounts | undefined;
  onChange: (view: LeadView) => void;
  controls: string;
}) {
  const refs = useRef<Partial<Record<LeadView, HTMLButtonElement | null>>>({});

  function move(delta: number) {
    const index = VIEWS.indexOf(value);
    const next = VIEWS[(index + delta + VIEWS.length) % VIEWS.length];
    onChange(next);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label="Bands"
      className="-mb-px flex gap-6 overflow-x-auto"
      onKeyDown={(event) => {
        if (event.key === "ArrowRight") {
          event.preventDefault();
          move(1);
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          move(-1);
        }
      }}
    >
      {VIEWS.map((view) => {
        const active = view === value;
        const count = counts?.[view];
        return (
          <button
            key={view}
            ref={(el) => {
              refs.current[view] = el;
            }}
            type="button"
            role="tab"
            id={`band-tab-${view}`}
            aria-selected={active}
            aria-controls={controls}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(view)}
            className={cn(
              "relative flex h-11 shrink-0 items-center gap-1.5 text-body whitespace-nowrap transition-colors outline-offset-[-2px]",
              active
                ? "font-medium text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-cobalt"
                : "text-slate hover:text-ink",
            )}
          >
            {VIEW_LABEL[view]}
            <span className={cn("text-table tabular-nums", active ? "text-slate" : "text-slate/80")}>
              {count === undefined ? "" : formatCount(count)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
