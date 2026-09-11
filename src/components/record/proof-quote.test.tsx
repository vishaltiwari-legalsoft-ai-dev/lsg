import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { setReducedMotion } from "@/test/setup";
import type { Proof } from "@/lib/api/types";
import { ProofQuote, SourceCite } from "./proof-quote";

const proof: Proof = {
  signal_id: 1,
  kind: "job_posting_open",
  headline: "Paralegal role open 26 days",
  quote: "We are seeking an experienced personal injury paralegal.",
  source_label: "Careers page",
  source_url: "https://harbor.example/careers",
  first_seen: "2026-08-16T09:10:00Z",
  board_posted_date: "2026-08-12",
  days_open: 26,
  repost_count: 1,
  sources: ["Careers page", "Indeed"],
  closed_at: null,
  weight: 0.9,
  decay: 0.82,
  contest: "LOW",
};

afterEach(() => setReducedMotion(false));

describe("ProofQuote", () => {
  it("sets the verbatim sentence as a marked quotation with its headline", () => {
    render(<ProofQuote proof={proof} />);
    expect(screen.getByText("Paralegal role open 26 days")).toBeInTheDocument();
    const mark = screen.getByText(proof.quote!);
    expect(mark.tagName).toBe("MARK");
    expect(mark.closest("blockquote")).not.toBeNull();
  });

  it("carries its citation: where it was read, and when we first saw it", () => {
    const now = new Date("2026-09-11T12:00:00Z");
    render(<SourceCite proof={proof} now={now} />);
    const source = screen.getByRole("link", { name: /Careers page/ });
    expect(source).toHaveAttribute("href", "https://harbor.example/careers");
    expect(screen.getByText("First seen by us")).toBeInTheDocument();
    expect(screen.getByText(/16 Aug 2026, 26 days ago/)).toBeInTheDocument();
    // The board's own date is shown separately, because it differs from ours.
    expect(screen.getByText("Board says posted")).toBeInTheDocument();
    expect(screen.getByText("12 Aug 2026")).toBeInTheDocument();
    expect(screen.getByText("Once")).toBeInTheDocument();
    expect(screen.getByText("Indeed")).toBeInTheDocument();
  });

  it("draws the highlighter when motion is allowed", () => {
    setReducedMotion(false);
    render(<ProofQuote proof={proof} animate />);
    expect(screen.getByText(proof.quote!)).toHaveAttribute("data-motion", "sweep");
  });

  it("shows the highlight statically under prefers-reduced-motion", () => {
    setReducedMotion(true);
    render(<ProofQuote proof={proof} animate />);
    expect(screen.getByText(proof.quote!)).toHaveAttribute("data-motion", "static");
  });

  it("never animates unless asked — the sweep is the one unprompted motion", () => {
    render(<ProofQuote proof={proof} />);
    expect(screen.getByText(proof.quote!)).toHaveAttribute("data-motion", "static");
  });

  it("says so when no verbatim sentence was stored", () => {
    render(<ProofQuote proof={{ ...proof, quote: null }} />);
    expect(screen.getByText(/No verbatim sentence was stored/)).toBeInTheDocument();
    expect(document.querySelector("mark")).toBeNull();
  });
});
