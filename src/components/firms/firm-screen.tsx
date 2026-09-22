"use client";

import { ArrowLeftIcon, ArrowUpRightIcon, ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { JobProgress } from "@/components/case-file/job-progress";
import { Field, SectionHeading } from "@/components/layout/panel";
import { PainAnalysis } from "@/components/record/pain-analysis";
import { ProofQuote } from "@/components/record/proof-quote";
import { EmailStatusBadge } from "@/components/record/status-badge";
import { TierMark } from "@/components/record/tier-mark";
import { isUnknownDisplay, Unknown, ValueOrUnknown } from "@/components/record/unknown";
import { TitleBar, TitlePlaceholder } from "@/components/shell/title-bar";
import { ErrorState } from "@/components/states/error-state";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useFirm, useFirmJobs, useResearch } from "@/lib/api/hooks";
import type { AttributeRow, FirmDetail } from "@/lib/api/types";
import { formatCount, formatDate, formatPlace, urlPath } from "@/lib/format";
import { PRIORITY_LABEL, ROLE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { AttributeTable } from "./attribute-table";

const th = "h-10 pr-4 font-medium text-meta text-slate text-left";

/* ── At a glance: the facts outreach needs, out of the claims ───────────── */

const GLANCE: string[] = [
  "primary_practice", "fee_model", "attorney_count", "staff_listed", "phone_e164", "address",
  "office_count", "general_email", "hiring_email", "live_chat_vendor", "online_intake_form",
  "cms_detected", "spanish_intake", "google_rating", "review_count", "social_links",
  "copyright_year",
];
const SITE_SAYS: string[] = ["site_gaps", "testimonials", "site_review_summary", "recent_posts", "growth_news"];

function byAttr(attributes: AttributeRow[]): Map<string, AttributeRow> {
  return new Map(attributes.map((a) => [a.attr, a]));
}

function Glance({ attributes }: { attributes: AttributeRow[] }) {
  const map = byAttr(attributes);
  const rows = GLANCE.map((k) => map.get(k)).filter((r): r is AttributeRow => Boolean(r));
  return (
    <section aria-labelledby="glance-heading" className="grid gap-4">
      <SectionHeading id="glance-heading">At a glance</SectionHeading>
      {rows.length === 0 ? (
        <p className="text-body text-slate">Nothing read yet. Research the site to fill this in.</p>
      ) : (
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => (
            <Field key={row.attr} label={row.label}>
              {isUnknownDisplay(row.display) ? (
                <Unknown />
              ) : (
                <span className={cn(row.state === "conflict" && "text-redline")}>{row.display}</span>
              )}
              {row.source_label ? (
                <span className="block truncate text-meta text-slate">From {row.source_label}</span>
              ) : null}
            </Field>
          ))}
        </dl>
      )}
    </section>
  );
}

function SiteSays({ attributes }: { attributes: AttributeRow[] }) {
  const map = byAttr(attributes);
  const rows = SITE_SAYS.map((k) => map.get(k)).filter((r): r is AttributeRow => Boolean(r));
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="site-says-heading" className="grid gap-4">
      <SectionHeading id="site-says-heading">What the site says</SectionHeading>
      <dl className="grid gap-4">
        {rows.map((row) => (
          <div key={row.attr} className="grid gap-1 border-l-2 border-rule pl-4">
            <dt className="text-meta text-slate">{row.label}</dt>
            <dd className={cn("text-body", isUnknownDisplay(row.display) ? "text-slate" : "text-ink")}>
              {row.display}
            </dd>
            {row.evidence && row.evidence !== row.display && row.attr !== "site_gaps" ? (
              <dd className="text-table text-slate">{row.evidence}</dd>
            ) : null}
          </div>
        ))}
      </dl>
    </section>
  );
}

/* ── Research: the buttons and the job ──────────────────────────────────── */

function ResearchBar({ data }: { data: FirmDetail }) {
  const research = useResearch(data.firm.id, data.lead?.id ?? null);
  const jobs = useFirmJobs(data.firm.id);
  const latest = jobs.data?.items[0];
  const running = latest?.status === "queued" || latest?.status === "running";
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-1.5">
        <Button
          size="sm"
          variant="primary"
          disabled={research.isPending || running || !data.firm.domain}
          title={data.firm.domain ? "Crawl the site again and read everything on it" : "No website on record"}
          onClick={() => research.mutate("full")}
        >
          Research the site
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={research.isPending || running}
          title="Read the team pages again, search for LinkedIn profiles and addresses"
          onClick={() => research.mutate("contacts")}
        >
          Find people &amp; emails
        </Button>
      </div>
      {latest ? <JobProgress job={latest} leadId={data.lead?.id} /> : null}
    </div>
  );
}

/* ── Sections ───────────────────────────────────────────────────────────── */

function People({ contacts }: { contacts: FirmDetail["contacts"] }) {
  return (
    <section aria-labelledby="people-heading" className="grid gap-3">
      <SectionHeading
        id="people-heading"
        aside={
          contacts.length
            ? `${formatCount(contacts.length)} ${contacts.length === 1 ? "person" : "people"}`
            : undefined
        }
      >
        People
      </SectionHeading>
      {contacts.length === 0 ? (
        <p className="text-body text-slate">
          No one named yet. People appear when the engine reads a team page or a list names someone.
        </p>
      ) : (
        <div className="overflow-x-auto border-y border-rule">
          <table className="w-full min-w-[44rem] border-collapse text-table">
            <thead>
              <tr className="border-b border-rule">
                <th scope="col" className={th}>Name</th>
                <th scope="col" className={th}>Role</th>
                <th scope="col" className={th}>Email</th>
                <th scope="col" className={th}>Phone</th>
                <th scope="col" className={th}>Found by</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id} className="border-b border-rule align-top last:border-b-0">
                  <td className="py-2.5 pr-4">
                    <span className="block text-body text-ink">{c.full_name}</span>
                    {c.title ? <span className="block text-meta text-slate">{c.title}</span> : null}
                    {c.linkedin_url ? (
                      <a
                        href={c.linkedin_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-0.5 text-meta text-cobalt hover:underline"
                      >
                        LinkedIn profile
                        <ArrowUpRightIcon className="size-3" aria-hidden="true" />
                        <span className="sr-only"> (opens in a new tab)</span>
                      </a>
                    ) : null}
                    {c.linkedin_headline ? (
                      <span className="block text-meta text-slate">{c.linkedin_headline}</span>
                    ) : null}
                  </td>
                  <td className="py-2.5 pr-4 text-ink">{ROLE_LABEL[c.role]}</td>
                  <td className="py-2.5 pr-4">
                    <span className="grid justify-items-start gap-1">
                      {c.email ? <span className="text-ink">{c.email}</span> : <Unknown>No email found</Unknown>}
                      <EmailStatusBadge contact={c} />
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 tabular-nums">
                    <ValueOrUnknown value={c.phone} unknown="No direct line" />
                  </td>
                  <td className="py-2.5 text-slate">{c.source_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Pages({ documents }: { documents: FirmDetail["documents"] }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-labelledby="pages-heading" className="grid gap-3">
      <SectionHeading id="pages-heading" aside={`${formatCount(documents.length)} pages`}>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1.5 rounded-[4px] hover:underline"
        >
          <ChevronRightIcon className={cn("size-4 text-slate transition-transform", open && "rotate-90")} aria-hidden="true" />
          Pages read
        </button>
      </SectionHeading>
      {!open ? null : documents.length === 0 ? (
        <p className="text-body text-slate">Nothing read yet. Pages appear here after the site is researched.</p>
      ) : (
        <div className="overflow-x-auto border-y border-rule">
          <table className="w-full min-w-[40rem] border-collapse text-table">
            <thead>
              <tr className="border-b border-rule">
                <th scope="col" className={th}>Page</th>
                <th scope="col" className={th}>Status</th>
                <th scope="col" className={cn(th, "text-right")}>Words</th>
                <th scope="col" className={th}>Robots</th>
                <th scope="col" className={cn(th, "text-right")}>Read</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.url} className="border-b border-rule last:border-b-0">
                  <td className="py-2.5 pr-4">
                    <ValueOrUnknown value={doc.page_kind} unknown="Page kind not recorded" className="block text-ink" />
                    <a
                      href={doc.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-0.5 text-meta text-cobalt hover:underline"
                    >
                      {urlPath(doc.url)}
                      <ArrowUpRightIcon className="size-3" aria-hidden="true" />
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  </td>
                  <td className="pr-4 tabular-nums">
                    {doc.status_code === null ? (
                      <Unknown>No response</Unknown>
                    ) : (
                      <span className={doc.status_code >= 400 ? "text-redline" : "text-ink"}>{doc.status_code}</span>
                    )}
                  </td>
                  <td className="pr-4 text-right tabular-nums">
                    {doc.words === null ? <Unknown>Not counted</Unknown> : formatCount(doc.words)}
                  </td>
                  <td className="pr-4 pl-6 text-ink">
                    <ValueOrUnknown value={doc.robots_decision} unknown="Not checked" />
                  </td>
                  <td className="text-right text-slate tabular-nums">{formatDate(doc.fetched_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EveryClaim({ attributes }: { attributes: AttributeRow[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-labelledby="claims-heading" className="grid gap-3">
      <SectionHeading id="claims-heading" aside="Every source, and which one won">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1.5 rounded-[4px] hover:underline"
        >
          <ChevronRightIcon className={cn("size-4 text-slate transition-transform", open && "rotate-90")} aria-hidden="true" />
          Every claim
        </button>
      </SectionHeading>
      {open ? (
        <div className="overflow-hidden border-y border-rule">
          <AttributeTable attributes={attributes} />
        </div>
      ) : null}
    </section>
  );
}

function Aliases({ aliases }: { aliases: FirmDetail["aliases"] }) {
  if (aliases.length === 0) return null;
  return (
    <section aria-labelledby="aliases-heading" className="grid gap-3">
      <SectionHeading id="aliases-heading">Merged records</SectionHeading>
      <div className="overflow-x-auto border-y border-rule">
        <table className="w-full min-w-[40rem] border-collapse text-table">
          <thead>
            <tr className="border-b border-rule">
              <th scope="col" className={th}>Name</th>
              <th scope="col" className={th}>Domain</th>
              <th scope="col" className={th}>Phone</th>
              <th scope="col" className={th}>Merged because</th>
              <th scope="col" className={th}>Source</th>
            </tr>
          </thead>
          <tbody>
            {aliases.map((a, i) => (
              <tr key={i} className="border-b border-rule last:border-b-0">
                <td className="py-2.5 pr-4 text-ink"><ValueOrUnknown value={a.name} unknown="No name" /></td>
                <td className="pr-4 text-ink"><ValueOrUnknown value={a.domain} unknown="No domain" /></td>
                <td className="pr-4 text-ink tabular-nums"><ValueOrUnknown value={a.phone} unknown="No phone" /></td>
                <td className="pr-4 text-ink">{a.merge_rule ?? <span className="text-slate">The original record</span>}</td>
                <td className="text-slate">{a.source_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FirmRecord({ data }: { data: FirmDetail }) {
  const { firm, lead } = data;
  return (
    <div className="grid gap-12">
      <div className="grid gap-5">
        <div className="flex items-start gap-3">
          <TierMark firm={firm} className="mt-1" />
          <p className="max-w-[52ch] text-subtitle leading-snug text-ink">{data.tier_reason}</p>
        </div>
        <dl className="flex flex-wrap gap-x-10 gap-y-3 pl-10">
          <Field label="Website">
            {firm.domain ? (
              <a
                href={`https://${firm.domain}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 text-cobalt hover:underline"
              >
                {firm.domain}
                <ArrowUpRightIcon className="size-3" aria-hidden="true" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : (
              <Unknown />
            )}
          </Field>
          <Field label="Place">
            <ValueOrUnknown value={formatPlace(firm.city, firm.state)} />
          </Field>
          <Field label="Lead">
            {lead ? (
              <Link href={`/leads/${lead.id}`} className="text-cobalt hover:underline">
                {lead.state_display}
              </Link>
            ) : (
              <span className="text-slate">No lead for this firm</span>
            )}
          </Field>
          {lead?.band ? <Field label="Priority">{PRIORITY_LABEL[lead.band]}</Field> : null}
        </dl>
        <div className="pl-10">
          <ResearchBar data={data} />
        </div>
      </div>

      <Glance attributes={data.attributes} />

      <section aria-labelledby="why-heading" className="grid gap-3">
        <SectionHeading id="why-heading">Why now</SectionHeading>
        {data.signals.length === 0 ? (
          <p className="text-body text-slate">
            No live signal yet. One appears when the engine reads an open role, a gap in the site, a
            growth headline, or a complaint in the firm&apos;s reviews.
          </p>
        ) : (
          <div className="grid divide-y divide-rule border-y border-rule">
            {data.signals.map((signal) => (
              <ProofQuote key={signal.signal_id} proof={signal} size="title" className="py-6" />
            ))}
          </div>
        )}
      </section>

      {data.pain ? <PainAnalysis pain={data.pain} id="firm-pain-heading" /> : null}
      <People contacts={data.contacts} />
      <SiteSays attributes={data.attributes} />
      <EveryClaim attributes={data.attributes} />
      <Pages documents={data.documents} />
      <Aliases aliases={data.aliases} />
    </div>
  );
}

function FirmSkeleton() {
  return (
    <div className="grid gap-10" aria-busy="true" aria-label="Loading the firm">
      <div className="grid gap-3">
        <Skeleton className="h-6 w-2/3 max-w-[36rem]" />
        <div className="flex gap-10 pl-10">
          <Skeleton className="h-9 w-36" />
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-9 w-48" />
        </div>
      </div>
      <Skeleton className="h-72 w-full rounded-panel" />
    </div>
  );
}

/** A firm: what the engine read, who is there, why now, and the record behind it. */
export function FirmScreen({ id }: { id: string }) {
  const firm = useFirm(id);
  const title = firm.data?.firm.name ?? (firm.isPending ? "" : "Firm");

  return (
    <>
      <TitleBar
        caption={Boolean(firm.data)}
        title={title || <TitlePlaceholder />}
        meta={firm.data?.firm.domain ?? undefined}
        actions={
          <Link href="/firms" className={buttonVariants({ variant: "ghost", size: "md" })}>
            <ArrowLeftIcon aria-hidden="true" />
            All firms
          </Link>
        }
      />
      <div className="max-w-[76rem] px-8 pt-8 pb-16 max-md:px-4">
        {firm.isPending ? (
          <FirmSkeleton />
        ) : firm.isError ? (
          <ErrorState error={firm.error} onRetry={() => void firm.refetch()} />
        ) : (
          <FirmRecord data={firm.data} />
        )}
      </div>
    </>
  );
}
