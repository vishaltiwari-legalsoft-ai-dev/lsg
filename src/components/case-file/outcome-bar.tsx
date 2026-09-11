"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useImperativeHandle, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
import { useRecordOutcome } from "@/lib/api/hooks";
import type { LeadDetail, OutcomeAction } from "@/lib/api/types";
import { toDateInputValue } from "@/lib/format";
import { OUTCOMES } from "@/lib/labels";
import { cn } from "@/lib/utils";

export interface OutcomeBarHandle {
  /** Start an outcome — used by the 1–7 keys. */
  trigger: (action: OutcomeAction) => void;
}

function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return toDateInputValue(d);
}

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return toDateInputValue(d);
}

const notNowSchema = z.object({
  until: z
    .string()
    .min(1, "Pick the date to revisit this lead.")
    .refine((v) => v >= tomorrow(), "Pick a date after today."),
  note: z.string().max(500, "Keep the note under 500 characters.").optional(),
});
type NotNowValues = z.infer<typeof notNowSchema>;

function NotNowDialog({
  open,
  onOpenChange,
  firmName,
  onSubmit,
  returnFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  firmName: string;
  onSubmit: (values: NotNowValues) => void;
  returnFocus: () => void;
}) {
  const form = useForm<NotNowValues>({
    resolver: zodResolver(notNowSchema),
    defaultValues: { until: inDays(30), note: "" },
  });
  const error = form.formState.errors.until?.message;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) form.reset({ until: inDays(30), note: "" });
        onOpenChange(next);
      }}
    >
      <DialogContent
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocus();
        }}
      >
        <form
          noValidate
          className="grid gap-5"
          onSubmit={form.handleSubmit((values) => {
            onSubmit(values);
            onOpenChange(false);
          })}
        >
          <DialogHeader>
            <DialogTitle>Not now</DialogTitle>
            <DialogDescription>
              {firmName} stays quiet until the date you pick. The outcome is recorded either way.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="not-now-until">Revisit on</Label>
            <Input
              id="not-now-until"
              type="date"
              min={tomorrow()}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "not-now-until-error" : undefined}
              className="w-44 tabular-nums"
              {...form.register("until")}
            />
            {error ? (
              <p id="not-now-until-error" className="text-table text-redline">
                {error}
              </p>
            ) : null}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="not-now-note">
              Note <span className="font-normal text-slate">(optional)</span>
            </Label>
            <Input id="not-now-note" placeholder="Why not now" {...form.register("note")} />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Mark as not now
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function OptOutDialog({
  open,
  onOpenChange,
  lead,
  onConfirm,
  returnFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead: LeadDetail;
  onConfirm: () => void;
  returnFocus: () => void;
}) {
  const domain = lead.firm.domain;
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>Opt out {lead.firm.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            {domain ? (
              <>
                This suppresses the whole domain, <span className="text-ink">{domain}</span>. Nobody at the
                firm will be emailed again, and only an admin can reverse it.
              </>
            ) : (
              "This suppresses the firm. Nobody there will be emailed again, and only an admin can reverse it."
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Opt out firm</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/**
 * Sent · Replied · Meeting · Won · Lost · Not now · Opt out. Each click (or
 * 1–7 while the case file has focus) records immediately; the pending entry
 * appears in the record at once and the API's own message becomes the toast.
 */
export function OutcomeBar({
  lead,
  ref,
}: {
  lead: LeadDetail;
  ref?: React.Ref<OutcomeBarHandle>;
}) {
  const mutation = useRecordOutcome(lead.id);
  const [dialog, setDialog] = useState<"not_now" | "opt_out" | null>(null);
  // A dialog opened by a number key has no trigger to return to; hand focus
  // back to its button so the case file — and its keys — stay live.
  const buttons = useRef<Partial<Record<OutcomeAction, HTMLButtonElement | null>>>({});
  function focusButton(action: OutcomeAction) {
    buttons.current[action]?.focus();
  }

  function trigger(action: OutcomeAction) {
    if (action === "not_now") setDialog("not_now");
    else if (action === "opt_out") setDialog("opt_out");
    else mutation.mutate({ action });
  }

  useImperativeHandle(ref, () => ({ trigger }));

  const pendingAction = mutation.isPending ? mutation.variables?.action : undefined;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span id={`outcome-label-${lead.id}`} className="text-meta text-slate">
        Record outcome
      </span>
      <div role="group" aria-labelledby={`outcome-label-${lead.id}`} className="flex flex-wrap gap-1">
        {OUTCOMES.map((outcome) => (
          <Button
            key={outcome.action}
            ref={(el) => {
              buttons.current[outcome.action] = el;
            }}
            type="button"
            size="sm"
            variant={outcome.action === "opt_out" ? "danger" : "secondary"}
            aria-label={outcome.verb}
            aria-keyshortcuts={outcome.key}
            aria-busy={pendingAction === outcome.action || undefined}
            onClick={() => trigger(outcome.action)}
            className={cn(
              "gap-1.5 px-[7px]",
              outcome.action === "not_now" && "ml-1.5",
              pendingAction === outcome.action && "border-cobalt bg-cobalt-wash",
            )}
          >
            <span
              aria-hidden="true"
              className="text-meta text-slate tabular-nums transition-colors group-focus-within/casefile:text-cobalt"
            >
              {outcome.key}
            </span>
            {outcome.label}
          </Button>
        ))}
      </div>

      <NotNowDialog
        open={dialog === "not_now"}
        onOpenChange={(open) => setDialog(open ? "not_now" : null)}
        firmName={lead.firm.name}
        returnFocus={() => focusButton("not_now")}
        onSubmit={(values) =>
          mutation.mutate({ action: "not_now", until: values.until, note: values.note || undefined })
        }
      />
      <OptOutDialog
        open={dialog === "opt_out"}
        onOpenChange={(open) => setDialog(open ? "opt_out" : null)}
        lead={lead}
        returnFocus={() => focusButton("opt_out")}
        onConfirm={() => mutation.mutate({ action: "opt_out" })}
      />
    </div>
  );
}
