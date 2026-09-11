"use client";

import { SearchIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Contest } from "@/lib/api/types";
import { CONTEST_OPTIONS, SIGNAL_OPTIONS, TIER_OPTIONS } from "@/lib/labels";
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
  options: { value: string; label: string }[];
  onChange: (value: string | undefined) => void;
  className?: string;
}) {
  return (
    <Select value={value ?? ANY} onValueChange={(v) => onChange(v === ANY ? undefined : v)}>
      <SelectTrigger aria-label={label} className={cn(value && "border-rule-strong", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ANY}>{anyLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
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

export function FilterBar({
  filters,
  onChange,
}: {
  filters: LeadFilters;
  onChange: (patch: Partial<Record<keyof LeadFilters, string | undefined>>) => void;
}) {
  const [q, setQ] = useDebouncedField(filters.q, (v) => onChange({ q: v }));
  const [city, setCity] = useDebouncedField(filters.city, (v) => onChange({ city: v }));
  const active = Object.values(filters).some((v) => v !== undefined && v !== "");

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
      <div className="relative w-52">
        <SearchIcon
          className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-slate"
          aria-hidden="true"
        />
        <Input
          type="search"
          aria-label="Search leads by firm name or domain"
          placeholder="Firm or domain"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="h-8 pl-8 text-table"
        />
      </div>
      <FilterSelect
        label="Tier"
        anyLabel="Any tier"
        value={filters.tier}
        options={TIER_OPTIONS}
        onChange={(v) => onChange({ tier: v })}
        className="w-28"
      />
      <Input
        aria-label="City"
        placeholder="City"
        value={city}
        onChange={(e) => setCity(e.target.value)}
        className="h-8 w-28 text-table"
      />
      <FilterSelect
        label="Pain"
        anyLabel="Any pain"
        value={filters.signal}
        options={SIGNAL_OPTIONS}
        onChange={(v) => onChange({ signal: v })}
        className="w-36"
      />
      <FilterSelect
        label="Contest"
        anyLabel="Any contest"
        value={filters.contest}
        options={CONTEST_OPTIONS}
        onChange={(v) => onChange({ contest: v })}
        className="w-32"
      />
      <FilterSelect
        label="Email verified"
        anyLabel="Any email"
        value={filters.verified === undefined ? undefined : String(filters.verified)}
        options={[
          { value: "true", label: "Verified email" },
          { value: "false", label: "Not verified" },
        ]}
        onChange={(v) => onChange({ verified: v })}
        className="w-34"
      />
      {active ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setQ("");
            setCity("");
            onChange({ q: undefined, city: undefined, tier: undefined, signal: undefined, contest: undefined, verified: undefined });
          }}
        >
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
