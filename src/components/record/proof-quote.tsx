"use client";

import { ArrowUpRightIcon } from "lucide-react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";
import type { Proof } from "@/lib/api/types";
import { formatDate, relativeDays } from "@/lib/format";
import { cn } from "@/lib/utils";

type QuoteSize = "proof" | "title" | "body" | "table";

const SIZE: Record<QuoteSize, string> = {
  proof: "text-quote-proof",
  title: "text-quote-title",
  body: "text-quote",
  table: "text-quote-table",
};

/**
 * The highlighter over a verbatim sentence. With `animate`, the mark draws
 * across the sentence once (~450ms) — the one motion nobody asked for —
 * unless the person prefers reduced motion, in which case it is simply there.
 */
export function Highlight({
  children,
  animate = false,
  className,
}: {
  children: React.ReactNode;
  animate?: boolean;
  className?: string;
}) {
  const reduced = useReducedMotion();
  return (
    <mark className={cn("proof-mark", className)} data-motion={animate && !reduced ? "sweep" : "static"}>
      {children}
    </mark>
  );
}

/** A verbatim sentence, set in Caslon, marked, with hanging quotation marks. */
export function Quotation({
  text,
  size = "body",
  animate = false,
  marked = true,
  className,
}: {
  text: string;
  size?: QuoteSize;
  animate?: boolean;
  /** Losing claims are quoted but not marked: the mark is for the proof that stands. */
  marked?: boolean;
  className?: string;
}) {
  return (
    <blockquote className={cn("quotation text-ink", SIZE[size], className)}>
      <p>
        <span aria-hidden="true" className="-ml-[0.45em] inline-block w-[0.45em] text-slate">
          “
        </span>
        {marked ? <Highlight animate={animate}>{text}</Highlight> : text}
        <span aria-hidden="true" className="text-slate">
          ”
        </span>
      </p>
    </blockquote>
  );
}

/**
 * The proof: the headline, the quotation and its pinpoint citation — where
 * it was read, and when *we* first saw it.
 */
export function ProofQuote({
  proof,
  size = "title",
  animate = false,
  showHeadline = true,
  className,
}: {
  proof: Proof;
  size?: QuoteSize;
  animate?: boolean;
  showHeadline?: boolean;
  className?: string;
}) {
  return (
    <figure className={cn("grid gap-4", className)}>
      {showHeadline ? <p className="text-body font-medium text-ink">{proof.headline}</p> : null}
      {proof.quote ? (
        // Keyed by signal so a different proof draws its own mark.
        <Quotation key={proof.signal_id} text={proof.quote} size={size} animate={animate} />
      ) : (
        <p className="text-body text-slate italic">
          No verbatim sentence was stored for this proof.
        </p>
      )}
      <figcaption>
        <SourceCite proof={proof} />
      </figcaption>
    </figure>
  );
}

function CiteItem({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-meta text-slate">{term}</dt>
      <dd className="text-table text-ink">{children}</dd>
    </div>
  );
}

function repostWords(count: number): string {
  if (count === 1) return "Once";
  if (count === 2) return "Twice";
  return `${count} times`;
}

/** The citation, as separate labelled values — never a dot-joined string. */
export function SourceCite({ proof, now }: { proof: Proof; now?: Date }) {
  const boardDiffers =
    proof.board_posted_date !== null &&
    proof.board_posted_date.slice(0, 10) !== proof.first_seen.slice(0, 10);
  const otherSources = proof.sources.filter((s) => s !== proof.source_label);

  return (
    <dl className="flex flex-wrap gap-x-7 gap-y-3">
      <CiteItem term="Read on">
        {proof.source_url ? (
          <a
            href={proof.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-cobalt hover:underline"
          >
            {proof.source_label}
            <ArrowUpRightIcon className="size-3" aria-hidden="true" />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        ) : (
          proof.source_label
        )}
      </CiteItem>
      <CiteItem term="First seen by us">
        <time dateTime={proof.first_seen}>
          {formatDate(proof.first_seen)}, {relativeDays(proof.first_seen, now)}
        </time>
      </CiteItem>
      {boardDiffers ? (
        <CiteItem term="Board says posted">
          <time dateTime={proof.board_posted_date!}>{formatDate(proof.board_posted_date!)}</time>
        </CiteItem>
      ) : null}
      {proof.repost_count > 0 ? (
        <CiteItem term="Reposted">{repostWords(proof.repost_count)}</CiteItem>
      ) : null}
      {otherSources.length > 0 ? (
        <CiteItem term="Also seen on">{otherSources.join(", ")}</CiteItem>
      ) : null}
      {proof.closed_at ? (
        <CiteItem term="Closed">
          <time dateTime={proof.closed_at}>{formatDate(proof.closed_at)}</time>
        </CiteItem>
      ) : null}
    </dl>
  );
}
