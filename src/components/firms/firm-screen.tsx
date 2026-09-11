"use client";

import { ArrowUpRightIcon } from "lucide-react";
import Link from "next/link";

import { Field, Panel, SectionHeading } from "@/components/layout/panel";
import { ProofQuote } from "@/components/record/proof-quote";
import { EmailStatusBadge } from "@/components/record/status-badge";
import { TierMark } from "@/components/record/tier-mark";
import { Unknown, ValueOrUnknown } from "@/components/record/unknown";
import { TitleBar, TitlePlaceholder } from "@/components/shell/title-bar";
import { ErrorState } from "@/components/states/error-state";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useFirm } from "@/lib/api/hooks";
import type { FirmDetail } from "@/lib/api/types";
import { formatCount, formatDate, formatPlace, urlPath } from "@/lib/format";
import { BAND_LABEL, ROLE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { AttributeTable } from "./attribute-table";

const th = "h-9 font-normal text-meta text-slate text-left";

function Documents({ documents }: { documents: FirmDetail["documents"] }) {
  return (
    <section aria-labelledby="documents-heading" className="grid gap-3">
      <SectionHeading id="documents-heading" aside={`${formatCount(documents.length)} pages`}>
        Documents crawled
      </SectionHeading>
      {documents.length === 0 ? (
        <p className="text-body text-slate">
          Nothing crawled yet. Pages appear here after the probe reads the firm&apos;s site.
        </p>
      ) : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-table">
            <thead>
              <tr className="border-b border-rule">
                <th scope="col" className={cn(th, "pl-6")}>Page</th>
                <th scope="col" className={th}>Status</th>
                <th scope="col" className={cn(th, "text-right")}>Words</th>
                <th scope="col" className={cn(th, "pl-6")}>Robots</th>
                <th scope="col" className={cn(th, "pr-6 text-right")}>Fetched</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.url} className="border-b border-rule last:border-b-0">
                  <td className="py-2.5 pr-4 pl-6">
                    <ValueOrUnknown
                      value={doc.page_kind}
                      unknown="Page kind not recorded"
                      className="block text-ink"
                    />
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
                  <td className="pr-6 text-right text-slate tabular-nums">{formatDate(doc.fetched_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </section>
  );
}

function Contacts({ contacts }: { contacts: FirmDetail["contacts"] }) {
  return (
    <section aria-labelledby="contacts-heading" className="grid gap-3">
      <SectionHeading id="contacts-heading">Contacts</SectionHeading>
      {contacts.length === 0 ? (
        <p className="text-body text-slate">
          No one found yet. Contacts appear when the engine reads a team page or a firm list names someone.
        </p>
      ) : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[44rem] border-collapse text-table">
            <thead>
              <tr className="border-b border-rule">
                <th scope="col" className={cn(th, "pl-6")}>Name</th>
                <th scope="col" className={th}>Role</th>
                <th scope="col" className={th}>Email</th>
                <th scope="col" className={th}>Phone</th>
                <th scope="col" className={cn(th, "pr-6")}>Source</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id} className="border-b border-rule align-top last:border-b-0">
                  <td className="py-2.5 pr-4 pl-6">
                    <span className="block text-body text-ink">{c.full_name}</span>
                    {c.title ? <span className="block text-meta text-slate">{c.title}</span> : null}
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
                  <td className="py-2.5 pr-6 text-slate">{c.source_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </section>
  );
}

function Aliases({ aliases }: { aliases: FirmDetail["aliases"] }) {
  return (
    <section aria-labelledby="aliases-heading" className="grid gap-3">
      <SectionHeading id="aliases-heading">Merged records</SectionHeading>
      {aliases.length === 0 ? (
        <p className="text-body text-slate">No other record was merged into this firm.</p>
      ) : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-table">
            <thead>
              <tr className="border-b border-rule">
                <th scope="col" className={cn(th, "pl-6")}>Name</th>
                <th scope="col" className={th}>Domain</th>
                <th scope="col" className={th}>Phone</th>
                <th scope="col" className={th}>Merged because</th>
                <th scope="col" className={cn(th, "pr-6")}>Source</th>
              </tr>
            </thead>
            <tbody>
              {aliases.map((a, i) => (
                <tr key={i} className="border-b border-rule last:border-b-0">
                  <td className="py-2.5 pr-4 pl-6 text-ink">
                    <ValueOrUnknown value={a.name} unknown="No name" />
                  </td>
                  <td className="pr-4 text-ink">
                    <ValueOrUnknown value={a.domain} unknown="No domain" />
                  </td>
                  <td className="pr-4 text-ink tabular-nums">
                    <ValueOrUnknown value={a.phone} unknown="No phone" />
                  </td>
                  <td className="pr-4 text-ink">{a.merge_rule ?? <span className="text-slate">The original record</span>}</td>
                  <td className="pr-6 text-slate">{a.source_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
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
          <p className="max-w-[48ch] text-title leading-snug text-ink">{data.tier_reason}</p>
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
          {lead ? (
            <Field label="Band">{lead.band ? BAND_LABEL[lead.band] : <Unknown>Not scored</Unknown>}</Field>
          ) : null}
        </dl>
      </div>

      <section aria-labelledby="record-heading" className="grid gap-3">
        <SectionHeading id="record-heading" aside="Expand an attribute to see every claim">
          The record
        </SectionHeading>
        <Panel className="overflow-hidden">
          <AttributeTable attributes={data.attributes} />
        </Panel>
      </section>

      <section aria-labelledby="signals-heading" className="grid gap-3">
        <SectionHeading id="signals-heading">Signals</SectionHeading>
        {data.signals.length === 0 ? (
          <p className="text-body text-slate">
            No signal yet. A signal appears when the engine reads an open role, a campaign or a change on the
            firm&apos;s own site.
          </p>
        ) : (
          <div className="grid gap-4">
            {data.signals.map((signal) => (
              <Panel key={signal.signal_id} className="px-8 py-7">
                <ProofQuote proof={signal} size="body" />
              </Panel>
            ))}
          </div>
        )}
      </section>

      <Contacts contacts={data.contacts} />
      <Documents documents={data.documents} />
      <Aliases aliases={data.aliases} />
    </div>
  );
}

function FirmSkeleton() {
  return (
    <div className="grid gap-10" aria-busy="true" aria-label="Loading the firm's record">
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

export function FirmScreen({ id }: { id: string }) {
  const firm = useFirm(id);
  const title = firm.data?.firm.name ?? (firm.isPending ? "" : "Firm");

  return (
    <>
      <TitleBar
        title={title || <TitlePlaceholder />}
        actions={
          <Link href="/firms" className={buttonVariants({ variant: "ghost", size: "md" })}>
            All firms
          </Link>
        }
      />
      <div className="max-w-[72rem] px-8 pt-8 pb-16">
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
