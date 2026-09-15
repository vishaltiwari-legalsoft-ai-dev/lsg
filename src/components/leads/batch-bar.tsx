"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useBatch } from "@/lib/api/hooks";
import type { BatchAction } from "@/lib/api/types";
import { toDateInputValue } from "@/lib/format";

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return toDateInputValue(d);
}

/**
 * The same action for every selected lead: research, find people and
 * addresses, park, disqualify, assign. Appears above the docket while a
 * selection exists; each lead's own answer comes back in the toast.
 */
export function BatchBar({ ids, onClear }: { ids: string[]; onClear: () => void }) {
  const batch = useBatch();
  const [pending, setPending] = useState<BatchAction | null>(null);
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState(inDays(30));
  const [owner, setOwner] = useState("");
  const n = ids.length;

  function run(action: BatchAction) {
    batch.mutate(
      {
        lead_ids: ids,
        action,
        reason: reason.trim() || null,
        until: action === "hold" ? until : null,
        owner: action === "assign" ? owner.trim() || null : null,
      },
      {
        onSuccess: () => {
          setPending(null);
          setReason("");
          onClear();
        },
      },
    );
  }

  return (
    <div
      role="region"
      aria-label={`${n} selected`}
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-rule bg-cobalt-wash px-8 py-2.5"
    >
      <span className="text-body font-medium text-ink tabular-nums">
        {n} selected
      </span>
      {pending === null ? (
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="secondary" disabled={batch.isPending} onClick={() => run("research")}>
            Research sites
          </Button>
          <Button size="sm" variant="secondary" disabled={batch.isPending} onClick={() => run("find_contacts")}>
            Find people &amp; emails
          </Button>
          <Button size="sm" variant="secondary" disabled={batch.isPending} onClick={() => setPending("assign")}>
            Assign…
          </Button>
          <Button size="sm" variant="secondary" disabled={batch.isPending} onClick={() => setPending("hold")}>
            Park…
          </Button>
          <Button size="sm" variant="danger" disabled={batch.isPending} onClick={() => setPending("disqualify")}>
            Disqualify…
          </Button>
        </div>
      ) : (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            run(pending);
          }}
        >
          {pending === "assign" ? (
            <Input
              aria-label="Owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="Owner's name (blank to unassign)"
              className="h-8 w-56 text-table"
              autoFocus
            />
          ) : null}
          {pending === "hold" ? (
            <Input
              aria-label="Park until"
              type="date"
              min={inDays(1)}
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className="h-8 w-40 text-table tabular-nums"
              required
              autoFocus
            />
          ) : null}
          {pending !== "assign" ? (
            <Input
              aria-label="Reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason (optional)"
              className="h-8 w-64 text-table"
              autoFocus={pending === "disqualify"}
            />
          ) : null}
          <Button type="submit" size="sm" variant={pending === "disqualify" ? "danger" : "primary"} disabled={batch.isPending}>
            {pending === "assign" ? `Assign ${n}` : pending === "hold" ? `Park ${n}` : `Disqualify ${n}`}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setPending(null)}>
            Back
          </Button>
        </form>
      )}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear}>
        Clear selection
      </Button>
    </div>
  );
}
