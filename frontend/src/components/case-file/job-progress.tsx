"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon, LoaderCircleIcon, XIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { queryKeys, useJob } from "@/lib/api/hooks";
import type { ActionJob, JobStep } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A step's outcome in words. The engine's note is a count ("processed=1
 * skipped=0 failed=0 -- ..."); a finished step needs none -- the tick says it.
 */
function stepWords(step: JobStep): string | null {
  if (step.status === "failed") return "Didn't finish";
  if (!step.note || step.status !== "done") return null;
  if (/inert|not configured|not set/i.test(step.note)) return "Switched off until its key is set";
  const m = /processed=(\d+) skipped=(\d+) failed=(\d+)/.exec(step.note);
  if (!m) return null;
  const [processed, skipped, failures] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (failures > 0) return "Finished, with a problem";
  if (processed === 0 && skipped > 0) return "Nothing new to read";
  return null;
}

function StepGlyph({ status }: { status: JobStep["status"] }) {
  if (status === "done") return <CheckIcon className="size-3.5 text-ledger" aria-hidden="true" />;
  if (status === "failed") return <XIcon className="size-3.5 text-redline" aria-hidden="true" />;
  if (status === "running")
    return <LoaderCircleIcon className="size-3.5 animate-spin text-cobalt" aria-hidden="true" />;
  return <span className="block size-1.5 rounded-full bg-rule" aria-hidden="true" />;
}

/**
 * A research job's progress, step by step, polled while it runs. When it
 * finishes, everything the case file shows is refetched once. Each step's
 * plain label comes from the engine, which reads the steps from the same
 * recipe the full run uses.
 */
export function JobProgress({ job: initial, leadId }: { job: ActionJob; leadId?: string }) {
  const active = initial.status === "queued" || initial.status === "running";
  const polled = useJob(active ? initial.id : null);
  const job = polled.data?.job ?? initial;
  const qc = useQueryClient();
  const seen = useRef(job.status);

  useEffect(() => {
    if (seen.current !== job.status && (job.status === "done" || job.status === "failed")) {
      if (leadId) {
        void qc.invalidateQueries({ queryKey: queryKeys.lead(leadId) });
        void qc.invalidateQueries({ queryKey: queryKeys.drafts(leadId) });
      }
      void qc.invalidateQueries({ queryKey: queryKeys.firm(job.firm_id) });
      void qc.invalidateQueries({ queryKey: ["leads"] });
    }
    seen.current = job.status;
  }, [job.status, job.firm_id, leadId, qc]);

  const done = job.steps.filter((s) => s.status === "done").length;
  const running = job.status === "queued" || job.status === "running";
  // A run fails two ways: a step broke, or the run stopped part-way because the
  // engine restarted under it. Calling the second "a failed step" sent a person
  // hunting for a step with a cross beside it, and there is none.
  const brokeAtAStep = job.steps.some((s) => s.status === "failed");
  const when = job.finished_at ? formatDateTime(job.finished_at) : "";
  const heading =
    job.status === "queued" ? "Research queued"
    : job.status === "running" ? `Researching — ${done} of ${job.steps.length} steps done`
    : job.status === "done" ? `Research finished ${when}`
    : brokeAtAStep ? `Research finished with a failed step ${when}`
    : `Research stopped after ${done} of ${job.steps.length} steps ${when}`;

  return (
    <section
      aria-live="polite"
      aria-busy={running || undefined}
      className={cn(
        "grid gap-2 rounded-panel border border-rule px-4 py-3",
        running ? "bg-cobalt-wash" : "bg-paper",
      )}
    >
      <p className="text-body font-medium text-ink">{heading}</p>
      {job.status === "failed" && job.error ? (
        <p className="text-table text-redline">{job.error}</p>
      ) : null}
      <ol className="grid gap-1">
        {job.steps.map((step, i) => (
          <li key={`${step.name}-${i}`} className="grid grid-cols-[1rem_minmax(0,1fr)] items-center gap-2 text-table">
            <span className="flex items-center justify-center">
              <StepGlyph status={step.status} />
            </span>
            <span className={cn("truncate", step.status === "pending" ? "text-slate" : "text-ink")}>
              {step.label}
              {stepWords(step) ? <span className="text-slate">: {stepWords(step)}</span> : null}
              {step.status === "failed" && step.note ? (
                <details className="text-meta text-slate">
                  <summary className="cursor-pointer">Details</summary>
                  <span className="block whitespace-normal">{step.note}</span>
                </details>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
