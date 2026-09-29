"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";

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
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { describeError } from "@/lib/api/errors";
import { useRestoreJourneyTemplate, useSaveJourneyTemplate } from "@/lib/api/hooks";
import type { JourneyResponse, JourneyStep, JourneyTemplate } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { copyProblems, dayLabel, subjectHasCapitals, wordCount } from "@/lib/journey";
import { cn } from "@/lib/utils";

export function findTemplate(
  journey: JourneyResponse,
  id: string,
): { step: JourneyStep; template: JourneyTemplate } | null {
  for (const step of journey.steps) {
    const template = step.templates.find((t) => t.id === id);
    if (template) return { step, template };
  }
  return null;
}

/**
 * Change one template's wording for every lead. The fill-ins it may use are
 * offered as buttons that insert at the cursor; the engine's own checks run
 * as the person types and again when it saves.
 */
export function TemplateEditor({
  journey,
  templateId,
  onClose,
}: {
  journey: JourneyResponse;
  templateId: string | null;
  onClose: () => void;
}) {
  const found = templateId ? findTemplate(journey, templateId) : null;
  return (
    <Dialog open={found !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      {found ? (
        <DialogContent
          className="max-h-[calc(100dvh-2rem)] max-w-3xl overflow-y-auto"
          // Focusing the subject would select it, and the first key pressed would wipe it out.
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          <EditorBody
            key={`${found.template.id}:${found.template.edited_at ?? "original"}`}
            journey={journey}
            step={found.step}
            template={found.template}
            onDone={onClose}
          />
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

function EditorBody({
  journey,
  step,
  template,
  onDone,
}: {
  journey: JourneyResponse;
  step: JourneyStep;
  template: JourneyTemplate;
  onDone: () => void;
}) {
  const isEmail = template.kind === "email";
  const [subject, setSubject] = useState(template.subject ?? "");
  const [body, setBody] = useState(template.body);
  const [confirmRestore, setConfirmRestore] = useState(false);
  const subjectRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const lastField = useRef<"subject" | "body">("body");
  const save = useSaveJourneyTemplate();
  const restore = useRestoreJourneyTemplate();

  const problems = copyProblems(template, isEmail ? subject : null, body, journey.banned_phrases);
  const unchanged = subject === (template.subject ?? "") && body === template.body;
  const labels = new Map(journey.fill_ins.map((f) => [f.token, f]));

  function insert(token: string) {
    const text = `{${token}}`;
    const target = lastField.current === "subject" && isEmail ? subjectRef.current : bodyRef.current;
    const value = target === subjectRef.current ? subject : body;
    const set = target === subjectRef.current ? setSubject : setBody;
    const start = target?.selectionStart ?? value.length;
    const end = target?.selectionEnd ?? value.length;
    set(value.slice(0, start) + text + value.slice(end));
    requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(start + text.length, start + text.length);
    });
  }

  function onSave() {
    save.mutate(
      { id: template.id, edit: { subject: isEmail ? subject : null, body } },
      {
        onSuccess: () => {
          toast.success("Saved for every lead");
          onDone();
        },
      },
    );
  }

  function onRestore() {
    restore.mutate(template.id, {
      onSuccess: () => {
        toast.success("Restored the original");
        onDone();
      },
      onError: (error) => toast.error(describeError(error)),
    });
  }

  const what = isEmail ? `Email ${step.step}` : `The middle paragraph of email ${step.step}`;
  return (
    <>
      <DialogHeader>
        <DialogTitle>Change the wording</DialogTitle>
        <DialogDescription>
          {what}, {step.title.toLowerCase()}, sent on {dayLabel(step.day)}: {template.used_when.charAt(0).toLowerCase()}
          {template.used_when.slice(1)}. What you save here is what every lead gets from now on.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-4">
        {isEmail ? (
          <div className="grid gap-1.5">
            <Label htmlFor="journey-subject">Subject</Label>
            <Input
              id="journey-subject"
              ref={subjectRef}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              onFocus={() => (lastField.current = "subject")}
              className="quotation max-w-none text-quote"
              autoComplete="off"
              spellCheck
            />
          </div>
        ) : null}
        <div className="grid gap-1.5">
          <Label htmlFor="journey-body">{isEmail ? "Email" : "Paragraph"}</Label>
          <textarea
            id="journey-body"
            ref={bodyRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onFocus={() => (lastField.current = "body")}
            rows={isEmail ? 12 : 5}
            spellCheck
            className="quotation w-full max-w-none resize-y rounded-control border border-rule-strong/70 bg-sheet px-3 py-2.5 text-quote text-ink transition-colors hover:border-rule-strong aria-invalid:border-redline"
            aria-invalid={problems.length > 0}
            aria-describedby="journey-checks"
          />
        </div>

        <div className="grid gap-2">
          <p className="text-meta font-medium text-slate">Fill-ins this {isEmail ? "email" : "paragraph"} can use</p>
          <div className="flex flex-wrap gap-1.5">
            {template.fill_ins.map((token) => (
              <Button
                key={token}
                type="button"
                size="sm"
                variant="secondary"
                title={labels.get(token)?.meaning}
                onClick={() => insert(token)}
              >
                <span className="text-slate">{`{${token}}`}</span>
                {labels.get(token)?.label ?? token}
              </Button>
            ))}
          </div>
          {template.keeps ? (
            <p className="text-table text-slate">
              <span className="text-ink">{`{${template.keeps}}`}</span> is where the tier&apos;s own paragraph goes.
              Keep it once, on its own line.
            </p>
          ) : null}
        </div>

        <div id="journey-checks" aria-live="polite" className="grid gap-1.5 border-t border-rule pt-3">
          {problems.length > 0 ? (
            <ul className="grid gap-1 text-table text-redline">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : save.isError ? (
            <p className="text-table text-redline">{describeError(save.error)}</p>
          ) : (
            <p className="text-table text-slate">
              {isEmail ? `${wordCount(body)} words. ` : null}
              {isEmail && subjectHasCapitals(subject)
                ? "The other subject lines are lowercase. "
                : null}
              {unchanged ? "Nothing changed yet." : "Ready to save."}
            </p>
          )}
          {template.edited_at ? (
            <p className="text-meta text-slate">
              Changed {formatDateTime(template.edited_at)}. The original is kept and can come back at any time.
            </p>
          ) : null}
        </div>
      </div>

      <DialogFooter className="items-center justify-between max-sm:justify-end">
        <div>
          {template.edited_at ? (
            <Button type="button" variant="ghost" onClick={() => setConfirmRestore(true)} disabled={restore.isPending}>
              Restore the original
            </Button>
          ) : null}
        </div>
        <div className="flex gap-2">
          <DialogClose asChild>
            <Button type="button" variant="secondary">
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="button"
            variant="primary"
            onClick={onSave}
            disabled={problems.length > 0 || unchanged || save.isPending}
            className={cn(save.isPending && "cursor-progress")}
          >
            {save.isPending ? "Saving…" : "Save for every lead"}
          </Button>
        </div>
      </DialogFooter>

      <AlertDialog open={confirmRestore} onOpenChange={setConfirmRestore}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Restore the original wording?</AlertDialogTitle>
            <AlertDialogDescription>
              Every lead goes back to the words this email started with. The changed wording is not kept.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep my wording</AlertDialogCancel>
            <AlertDialogAction onClick={onRestore}>Restore the original</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
