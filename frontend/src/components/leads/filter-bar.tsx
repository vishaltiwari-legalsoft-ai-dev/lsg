"use client";

import { SearchIcon, SlidersHorizontalIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Band, Contest } from "@/lib/api/types";
import { CONTEST_LABEL, PRIORITY_HINT, PRIORITY_LABEL, SIGNAL_OPTIONS, TIER_OPTIONS } from "@/lib/labels";
import { cn } from "@/lib/utils";

export interface LeadFilters {
  tier?: string;
  city?: string;
  signal?: string;
  contest?: Contest;
  verified?: boolean;
  q?: string;
}

const ANY = "any";
const PRIORITIES: Band[] = ["STRIKE", "SEQUENCE", "NURTURE", "HOLD"];
const CONTESTS: Contest[] = ["NONE", "LOW", "MED", "HIGH"];

function FilterSelect({
  label,
  anyLabel,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  anyLabel: string;
  value: string | undefined;
  options: { value: string; label: string; hint?: string }[];
  onChange: (value: string | undefined) => void;
  className?: string;
}) {
  return (
    <Select value={value ?? ANY} onValueChange={(v) => onChange(v === ANY ? undefined : v)}>
      <SelectTrigger
        aria-label={label}
        className={cn(value ? "border-cobalt bg-cobalt-wash font-medium" : "text-slate", className)}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ANY}>{anyLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value} hint={option.hint}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** A text filter that writes to the URL a beat after typing stops. */
function useDebouncedField(value: string | undefined, onCommit: (v: string | undefined) => void) {
  const [draft, setDraft] = useState(value ?? "");
  const commit = useRef(onCommit);
  useEffect(() => {
    commit.current = onCommit;
  });
  useEffect(() => {
    const trimmed = draft.trim() || undefined;
    if (trimmed === (value || undefined)) return;
    const timer = setTimeout(() => commit.current(trimmed), 220);
    return () => clearTimeout(timer);
  }, [draft, value]);
  return [draft, setDraft] as const;
}

/**
 * One row of filters over the queue: search first, then priority, tier and
 * pain; competition, email and city behind "More filters". A filter that is
 * on is set in cobalt, so a narrowed queue never looks like the whole one.
 */
export function FilterBar({
  filters,
  band,
  onChange,
  onBandChange,
}: {
  filters: LeadFilters;
  band: Band | undefined;
  onChange: (patch: Partial<Record<keyof LeadFilters, string | undefined>>) => void;
  onBandChange: (band: Band | undefined) => void;
}) {
  const [q, setQ] = useDebouncedField(filters.q, (v) => onChange({ q: v }));
  const [city, setCity] = useDebouncedField(filters.city, (v) => onChange({ city: v }));
  const active = band !== undefined || Object.values(filters).some((v) => v !== undefined && v !== "");
  // The three used least sit behind one button, which says how many are on.
  const moreOn = [filters.contest, filters.verified, filters.city].filter((v) => v !== undefined && v !== "").length;

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
      <div className="relative w-52">
        <SearchIcon
          className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-slate"
          aria-hidden="true"
        />
        <Input
          type="search"
          aria-label="Search leads by firm name or domain"
          placeholder="Firm or domain"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="pl-8 text-table"
        />
      </div>
      <FilterSelect
        label="Priority"
        anyLabel="Any priority"
        value={band}
        options={PRIORITIES.map((p) => ({ value: p, label: PRIORITY_LABEL[p], hint: PRIORITY_HINT[p] }))}
        onChange={(v) => onBandChange(v as Band | undefined)}
        className="w-36"
      />
      <FilterSelect
        label="Tier"
        anyLabel="Any tier"
        value={filters.tier}
        options={TIER_OPTIONS}
        onChange={(v) => onChange({ tier: v })}
        className="w-28"
      />
      <FilterSelect
        label="Pain"
        anyLabel="Any pain"
        value={filters.signal}
        options={SIGNAL_OPTIONS}
        onChange={(v) => onChange({ signal: v })}
        className="w-40"
      />
      <Popover>
        <PopoverTrigger asChild>
          <Button
            variant="secondary"
            size="md"
            className={cn("text-table", moreOn > 0 && "border-cobalt bg-cobalt-wash font-medium")}
          >
            <SlidersHorizontalIcon aria-hidden="true" />
            {moreOn > 0 ? `More filters (${moreOn})` : "More filters"}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="grid w-72 gap-4">
          <div className="grid gap-1.5">
            <span className="text-meta font-medium text-slate">Competition</span>
            <FilterSelect
              label="Competition"
              anyLabel="Any competition"
              value={filters.contest}
              options={CONTESTS.map((c) => ({
                value: c,
                label: c === "NONE" ? "No competition" : `${CONTEST_LABEL[c]} competition`,
              }))}
              onChange={(v) => onChange({ contest: v })}
              className="w-full"
            />
          </div>
          <div className="grid gap-1.5">
            <span className="text-meta font-medium text-slate">Email</span>
            <FilterSelect
              label="Email"
              anyLabel="Any email"
              value={filters.verified === undefined ? undefined : String(filters.verified)}
              options={[
                { value: "true", label: "Verified email" },
                { value: "false", label: "Not verified" },
              ]}
              onChange={(v) => onChange({ verified: v })}
              className="w-full"
            />
          </div>
          <label className="grid gap-1.5">
            <span className="text-meta font-medium text-slate">City</span>
            <Input
              placeholder="Any city"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              className={cn("text-table", city && "border-cobalt bg-cobalt-wash")}
            />
          </label>
        </PopoverContent>
      </Popover>
      {active ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setQ("");
            setCity("");
            onBandChange(undefined);
            onChange({ q: undefined, city: undefined, tier: undefined, signal: undefined, contest: undefined, verified: undefined });
          }}
        >
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
