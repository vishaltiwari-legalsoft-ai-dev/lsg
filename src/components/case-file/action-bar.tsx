"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAddNote, useDecide, useResearch, useSetOwner } from "@/lib/api/hooks";
import type { DecisionAction, LeadDetail } from "@/lib/api/types";
import { toDateInputValue } from "@/lib/format";

// Which decisions the engine will accept from each state (the whitelist in
// sql/098_actions.sql). The API is the guard; this only hides what cannot apply.
const CAN: Record<DecisionAction, ReadonlySet<string>> = {
  qualify: new Set(["CLASSIFIED", "CONTACT_PENDING", "RESOLVED"]),
  disqualify: new Set([
    "DISCOVERED", "PROFILING", "NO_WEB", "PROFILED", "ESCALATED", "CLASSIFIED",
    "CONTACT_PENDING", "RESOLVED", "QUALIFIED_A", "QUALIFIED_B", "ARMED", "STALE",
  ]),
  hold: new Set(["CLASSIFIED", "CONTACT_PENDING", "RESOLVED", "QUALIFIED_A", "QUALIFIED_B", "ARMED"]),
  handoff: new Set(["QUALIFIED_A", "QUALIFIED_B", "ARMED", "ENGAGED", "RESPONDED"]),
  reopen: new Set(["DISQUALIFIED", "LOST"]),
};

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return toDateInputValue(d);
}

type DialogKind = "disqualify" | "hold" | "note" | null;

function ReasonDialog({
  kind,
  lead,
  onClose,
  onDecide,
  onNote,
}: {
  kind: DialogKind;
  lead: LeadDetail;
  onClose: () => void;
  onDecide: (action: DecisionAction, reason: string, until?: string) => void;
  onNote: (text: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState(inDays(30));
  const open = kind !== null;

  const title =
    kind === "disqualify" ? `Disqualify ${lead.firm.name}?`
    : kind === "hold" ? `Park ${lead.firm.name}`
    : "Add a note";
  const description =
    kind === "disqualify"
      ? "The lead leaves every band. It can be reopened later; the reason goes on the record."
      : kind === "hold"
        ? "Nothing happens to the lead until the date you pick. The reason goes on the record."
        : "Notes stay on the lead, newest first, with who wrote them.";

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (kind === "note") {
      if (reason.trim()) onNote(reason.trim());
    } else if (kind === "hold") {
      onDecide("hold", reason, until);
    } else if (kind === "disqualify") {
      onDecide("disqualify", reason);
    }
    setReason("");
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent>
        <form className="grid gap-5" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {kind === "hold" ? (
            <div className="grid gap-1.5">
              <Label htmlFor="hold-until">Until</Label>
              <Input
                id="hold-until"
                type="date"
                min={inDays(1)}
                value={until}
                onChange={(e) => setUntil(e.target.value)}
                className="w-44 tabular-nums"
                required
              />
            </div>
          ) : null}
          <div className="grid gap-1.5">
            <Label htmlFor="action-reason">
              {kind === "note" ? "Note" : "Reason"}
              {kind !== "note" ? <span className="font-normal text-slate"> (optional)</span> : null}
            </Label>
            <textarea
              id="action-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              maxLength={2000}
              required={kind === "note"}
              className="w-full rounded-md border border-rule bg-sheet px-3 py-2 text-body text-ink outline-none focus-visible:border-cobalt"
              placeholder={kind === "note" ? "What happened, what to do next" : "Why"}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant={kind === "disqualify" ? "danger" : "primary"}>
              {kind === "disqualify" ? "Disqualify" : kind === "hold" ? "Park the lead" : "Add note"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function OwnerField({ lead }: { lead: LeadDetail }) {
  const setOwner = useSetOwner(lead.id);
  const [value, setValue] = useState(lead.owner ?? "");
  return (
    <form
      className="flex items-center gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        const next = value.trim() || null;
        if (next !== (lead.owner ?? null)) setOwner.mutate(next);
      }}
    >
      <Label htmlFor={`owner-${lead.id}`} className="text-meta text-slate">
        Owner
      </Label>
      <Input
        id={`owner-${lead.id}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Nobody yet"
        className="h-7 w-32 text-table"
        aria-busy={setOwner.isPending || undefined}
      />
      {value.trim() !== (lead.owner ?? "") ? (
        <Button type="submit" size="sm" variant="secondary" disabled={setOwner.isPending}>
          Save
        </Button>
      ) : null}
    </form>
  );
}

/**
 * What a person can do to a lead from its case file: research the firm now,
 * decide (qualify, disqualify, park, hand off, reopen), own it, note it.
 */
export function ActionBar({ lead }: { lead: LeadDetail }) {
  const research = useResearch(lead.firm.id, lead.id);
  const decide = useDecide(lead.id);
  const addNote = useAddNote(lead.id);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const busy = research.isPending || decide.isPending;
  const jobRunning = lead.job?.status === "queued" || lead.job?.status === "running";
  const can = (action: DecisionAction) => CAN[action].has(lead.state);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-body">
          <span className="font-medium text-ink">{lead.stage_display}</span>
          <span className="text-slate"> — {lead.next_action}</span>
        </p>
        <OwnerField lead={lead} />
      </div>
      <div role="group" aria-label="Actions" className="flex flex-wrap gap-1.5">
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || jobRunning || !lead.firm.domain}
          title={lead.firm.domain ? "Crawl the site again and read everything on it" : "No website on record"}
          onClick={() => research.mutate("full")}
        >
          Research site
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || jobRunning}
          title="Read the team pages again, search for LinkedIn profiles and addresses"
          onClick={() => research.mutate("contacts")}
        >
          Find people &amp; emails
        </Button>
        <span className="mx-1 w-px self-stretch bg-rule" aria-hidden="true" />
        {can("qualify") ? (
          <Button size="sm" variant="primary" disabled={busy} onClick={() => decide.mutate({ action: "qualify" })}>
            Qualify
          </Button>
        ) : null}
        {can("handoff") ? (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => decide.mutate({ action: "handoff" })}>
            Hand off to sales
          </Button>
        ) : null}
        {can("hold") ? (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => setDialog("hold")}>
            Park…
          </Button>
        ) : null}
        {can("reopen") ? (
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => decide.mutate({ action: "reopen" })}>
            Reopen
          </Button>
        ) : null}
        {can("disqualify") ? (
          <Button size="sm" variant="danger" disabled={busy} onClick={() => setDialog("disqualify")}>
            Disqualify…
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" disabled={addNote.isPending} onClick={() => setDialog("note")}>
          Add note…
        </Button>
      </div>
      <ReasonDialog
        kind={dialog}
        lead={lead}
        onClose={() => setDialog(null)}
        onDecide={(action, reason, until) =>
          decide.mutate({ action, reason: reason || null, until: until ?? null })
        }
        onNote={(text) => addNote.mutate(text)}
      />
    </div>
  );
}
