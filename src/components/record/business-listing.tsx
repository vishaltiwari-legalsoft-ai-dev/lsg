import { ArrowUpRightIcon } from "lucide-react";

import { SectionHeading } from "@/components/layout/panel";
import type { ListingSummary, ReviewRow } from "@/lib/api/types";
import { formatCount, formatDate } from "@/lib/format";

const STAR_WORDS = ["No", "One", "Two", "Three", "Four", "Five"] as const;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

/**
 * The firm's Google Business Profile and its reviews (r_listing, D-062), as
 * the licensed API returned them: the rating as a figure, the listing's
 * facts, where it disagrees with the firm's own record, and every review
 * kept word for word. The section is always on the page: when there is no
 * listing it says why (never looked up, no match, a failed lookup), because
 * a blank cannot be told from "Google has nothing on this firm".
 */
export function BusinessListing({
  listing,
  listingNote,
  reviews,
  id = "listing-heading",
}: {
  listing: ListingSummary | null;
  listingNote: string | null;
  reviews: ReviewRow[];
  id?: string;
}) {
  return (
    <section aria-labelledby={id} className="grid gap-4">
      <SectionHeading id={id} aside={listing ? `Read ${formatDate(listing.at)}` : undefined}>
        On Google
      </SectionHeading>

      {listing ? (
        <div className="grid gap-5 sm:grid-cols-[auto_minmax(0,1fr)] sm:gap-x-10">
          <Rating rating={listing.rating} count={listing.review_count} />
          <dl className="grid content-start gap-x-8 gap-y-3 sm:grid-cols-2">
            <Fact label="Listed as">
              {listing.url ? (
                <a
                  href={listing.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`${listing.name}, opens in Google Maps`}
                  className="inline-flex items-center gap-1 underline decoration-rule underline-offset-4 hover:decoration-ink"
                >
                  {listing.name}
                  <ArrowUpRightIcon aria-hidden="true" className="size-3.5 shrink-0" />
                </a>
              ) : (
                listing.name
              )}
            </Fact>
            {listing.category ? <Fact label="Category">{listing.category}</Fact> : null}
            {listing.address ? <Fact label="Address">{listing.address}</Fact> : null}
            {listing.phone ? <Fact label="Phone">{listing.phone}</Fact> : null}
            {listing.status && listing.status !== "operational" ? (
              <Fact label="Google marks it">{listing.status}</Fact>
            ) : null}
          </dl>
        </div>
      ) : (
        <p className="max-w-[68ch] text-body text-slate">{listingNote ?? "No Google listing on file."}</p>
      )}

      {listing && listing.notes.length > 0 ? (
        <ul className="grid gap-1 border-l-2 border-rule pl-4">
          {listing.notes.map((note) => (
            <li key={note} className="text-body text-ink">
              {note}
            </li>
          ))}
        </ul>
      ) : null}

      {reviews.length > 0 ? (
        <ol className="grid gap-4 border-t border-rule pt-4">
          {reviews.map((r, i) => (
            <li key={`${i}-${r.author ?? ""}-${r.date ?? ""}`} className="grid gap-1">
              <p className="text-meta text-slate">
                <Stars rating={r.rating} />
                <span>{reviewLine(r)}</span>
              </p>
              <p className="quotation max-w-[66ch] border-l-2 border-rule pl-4 text-quote text-ink">
                {r.text}
              </p>
            </li>
          ))}
        </ol>
      ) : listing ? (
        <p className="text-meta text-slate">No reviews came back with the listing.</p>
      ) : null}

      {listing ? (
        <p className="text-meta text-slate">
          From {listing.source_label}. Reviews are the customers&apos; own words, unedited.
        </p>
      ) : null}
    </section>
  );
}

/** "Two stars, 18 Jul 2026, by D. Nguyen" -- words, never a dot-joined string. */
function reviewLine(r: ReviewRow): string {
  const parts: string[] = [];
  parts.push(r.rating === null ? "Unrated" : `${STAR_WORDS[clampStars(r.rating)]} stars`);
  if (r.date) parts.push(ISO_DATE.test(r.date) ? formatDate(r.date) : r.date);
  if (r.author) parts.push(`by ${r.author}`);
  return parts.join(", ");
}

function clampStars(rating: number): number {
  return Math.max(0, Math.min(5, Math.round(rating)));
}

function Rating({ rating, count }: { rating: number | null; count: number | null }) {
  const reviews =
    count === null ? null : count === 1 ? "from one review" : `from ${formatCount(count)} reviews`;
  return (
    <div className="grid content-start gap-0.5">
      {rating !== null ? (
        <>
          <p className="type-narrow text-figure font-semibold text-ink tabular-nums">
            {rating.toFixed(1)}
          </p>
          <p className="text-meta text-slate">of 5{reviews ? `, ${reviews}` : ""}</p>
        </>
      ) : (
        <>
          <p className="text-body text-slate">No rating shown</p>
          {reviews ? <p className="text-meta text-slate">{reviews}</p> : null}
        </>
      )}
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-meta text-slate">{label}</dt>
      <dd className="min-w-0 text-body text-ink">{children}</dd>
    </div>
  );
}

function Stars({ rating }: { rating: number | null }) {
  if (rating === null) return null;
  const n = clampStars(rating);
  return (
    <span aria-hidden="true" className="mr-1.5 tracking-[0.05em]">
      <span className="text-ink">{"★".repeat(n)}</span>
      <span className="text-slate/50">{"★".repeat(5 - n)}</span>
    </span>
  );
}
