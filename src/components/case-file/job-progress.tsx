"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon, LoaderCircleIcon, XIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { queryKeys, useJob } from "@/lib/api/hooks";
import type { ActionJob, JobStep } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const STEP_LABEL: Record<string, string> = {
  p1_site_map: "Map the site",
  p2_fetch: "Read the pages",
  p3_render: "Render JavaScript pages",
  p4_text: "Extract the text",
  p5_jsonld: "Read structured data",
  p6_fee: "Read the fee model",
  p7_tech: "Fingerprint the software",
  px_site_rules: "Practice areas and rules",
  px_site_facts: "People, offices, testimonials, news, gaps",
  reconcile: "Reconcile the record",
  r_site_contacts: "People into contacts",
  r_site_emails: "Addresses printed on the site",
  r_search_links: "Search for LinkedIn profiles and reviews",
  r_search_emails: "Search for addresses",
  r3_email_pattern: "Learn the address pattern, mint the rest",
  ja1_careers: "Read the careers page",
  ja6_normalise: "Normalise the postings",
  ja6_closure: "Close filled postings",
  ja7_pain_signals: "Pain into intent",
  score: "Score",
};

function StepGlyph({ status }: { status: JobStep["status"] }) {
  if (status === "done") return <CheckIcon className="size-3.5 text-ledger" aria-hidden="true" />;
  if (status === "failed") return <XIcon className="size-3.5 text-redline" aria-hidden="true" />;
  if (status === "running")
    return <LoaderCircleIcon className="size-3.5 animate-spin text-cobalt" aria-hidden="true" />;
  return <span className="block size-1.5 rounded-full bg-rule" aria-hidden="true" />;
}

/**
 * A research job's progress, step by step, polled while it runs. When it
 * finishes, everything the case file shows is refetched once.
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
  const heading =
    job.status === "queued" ? "Research queued"
    : job.status === "running" ? `Researching — ${done} of ${job.steps.length} steps done`
    : job.status === "done" ? `Research finished ${job.finished_at ? formatDateTime(job.finished_at) : ""}`
    : `Research finished with a failed step ${job.finished_at ? formatDateTime(job.finished_at) : ""}`;

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
      <ol className="grid gap-1">
        {job.steps.map((step, i) => (
          <li key={`${step.name}-${i}`} className="grid grid-cols-[1rem_minmax(0,1fr)] items-center gap-2 text-table">
            <span className="flex items-center justify-center">
              <StepGlyph status={step.status} />
            </span>
            <span className={cn("truncate", step.status === "pending" ? "text-slate" : "text-ink")}>
              {STEP_LABEL[step.name] ?? step.name}
              {step.note && step.status !== "pending" ? (
                <span className="text-slate"> — {step.note}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
