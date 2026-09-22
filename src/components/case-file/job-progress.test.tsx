import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { ActionJob, JobStep } from "@/lib/api/types";
import { JobProgress } from "./job-progress";

function step(name: string, status: JobStep["status"], note: string | null = null): JobStep {
  return { name, label: name, status, note };
}

function job(over: Partial<ActionJob>): ActionJob {
  return {
    id: "job-1", kind: "research", firm_id: "firm-1", lead_id: "lead-1", status: "failed",
    steps: [], error: null, created_at: "2026-09-19T00:49:00Z", started_at: "2026-09-19T00:49:01Z",
    finished_at: "2026-09-19T00:49:53Z", ...over,
  };
}

function show(j: ActionJob) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <JobProgress job={j} />
    </QueryClientProvider>,
  );
}

describe("JobProgress", () => {
  it("says a run stopped part-way, and why, when no step failed", () => {
    show(job({
      steps: [step("read the site", "done"), step("find people", "done"), step("score", "pending")],
      error: "interrupted: the API restarted while this job was waiting or running -- run it again",
    }));
    expect(screen.getByText(/Research stopped after 2 of 3 steps/)).toBeInTheDocument();
    expect(screen.getByText(/the API restarted while this job was waiting/)).toBeInTheDocument();
    expect(screen.queryByText(/failed step/)).toBeNull();
  });

  it("still names a failed step when one really failed", () => {
    show(job({ steps: [step("read the site", "failed", "boom")], error: "read the site: boom" }));
    expect(screen.getByText(/Research finished with a failed step/)).toBeInTheDocument();
    expect(screen.getByText("read the site: boom")).toBeInTheDocument();
  });
});
