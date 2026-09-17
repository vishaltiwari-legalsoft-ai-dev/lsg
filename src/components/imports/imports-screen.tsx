"use client";

import { useRef, useState } from "react";

import { Panel, SectionHeading } from "@/components/layout/panel";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useImport, useImports, useStartLoad, useUpdateMapping, useUploadImport } from "@/lib/api/hooks";
import type { ImportBatch, ImportColumn, ImportDetail, ImportSummary } from "@/lib/api/types";
import { formatCount, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const EXTRA = "__extra";
const BATCH_SIZES = [250, 500, 1000, 2000] as const;

const STATUS_TONE: Record<string, string> = {
  mapped: "text-slate",
  loading: "text-cobalt",
  loaded: "text-ledger",
  failed: "text-redline",
};

// ── Upload ──────────────────────────────────────────────────────────────────

function UploadPanel({ onUploaded }: { onUploaded: (id: string) => void }) {
  const upload = useUploadImport();
  const [batchSize, setBatchSize] = useState<number>(500);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <Panel aria-labelledby="upload-heading" className="grid gap-4 px-6 py-5">
      <SectionHeading id="upload-heading">Upload a sheet</SectionHeading>
      <p className="text-body text-slate">
        Any layout, CSV or XLSX. The engine reads the headers and the values to work out
        which column is which, then shows you before anything loads.
      </p>
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const file = fileRef.current?.files?.[0];
          if (!file) return;
          upload.mutate(
            { file, batchSize },
            {
              onSuccess: (detail) => {
                onUploaded(detail.id);
                if (fileRef.current) fileRef.current.value = "";
              },
            },
          );
        }}
      >
        <label className="grid gap-1 text-meta text-slate">
          File
          <input
            ref={fileRef}
            type="file"
            name="file"
            required
            accept=".csv,.tsv,.txt,.xlsx,.xlsm"
            className="block w-full rounded-control border border-rule bg-sheet px-3 py-2 text-body text-ink file:mr-3 file:rounded-control file:border-0 file:bg-paper file:px-3 file:py-1 file:text-meta file:text-ink"
          />
        </label>
        <label className="grid gap-1 text-meta text-slate">
          Rows per batch
          <Select value={String(batchSize)} onValueChange={(v) => setBatchSize(Number(v))}>
            <SelectTrigger aria-label="Rows per batch" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BATCH_SIZES.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {formatCount(n)} rows
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <div>
          <Button type="submit" variant="primary" disabled={upload.isPending}>
            {upload.isPending ? "Reading the sheet…" : "Upload and read columns"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

// ── The list of sheets ──────────────────────────────────────────────────────

function ImportRow({
  item,
  selected,
  onSelect,
}: {
  item: ImportSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "grid w-full gap-0.5 rounded-control px-3 py-2.5 text-left transition-colors duration-75 hover:bg-paper",
          selected && "bg-cobalt-wash shadow-[inset_3px_0_0_var(--color-cobalt)]",
        )}
      >
        <span className="truncate text-body font-medium text-ink">{item.file_name}</span>
        <span className="text-meta text-slate">
          {formatCount(item.row_count)} rows, {item.batches_loaded} of {item.batches_total} batches
          loaded{item.health_score !== null ? `, health ${item.health_score}/100` : ""}
        </span>
        <span className={cn("text-meta", STATUS_TONE[item.status] ?? "text-slate")}>
          {item.status_display}
          {item.missing.length > 0 ? ` — missing ${item.missing.length} mandatory` : ""}
        </span>
      </button>
    </li>
  );
}

// ── Detail ──────────────────────────────────────────────────────────────────

function MandatoryLine({ detail }: { detail: ImportDetail }) {
  const readBy = detail.reader === "llm" ? "Read by the AI, checked against the values." : "Read by the rules.";
  return (
    <div className="grid gap-1">
      {detail.missing.length === 0 ? (
        <p className="text-body text-ledger">
          Found what it needs: a firm name and a way to reach each firm. {readBy}
        </p>
      ) : (
        <p className="text-body text-redline">
          Missing: {detail.missing.join("; ")}. Pick the right column below, or the sheet cannot load.
        </p>
      )}
      {detail.research_fills.length > 0 ? (
        <p className="text-meta text-slate">
          Not on the sheet, filled by research: {detail.research_fills.join(" · ")}.
        </p>
      ) : null}
    </div>
  );
}

function ColumnsTable({ detail }: { detail: ImportDetail }) {
  const update = useUpdateMapping(detail.id);
  const editable = detail.status === "mapped";
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left">
        <caption className="sr-only">How each column of {detail.file_name} was read</caption>
        <thead>
          <tr className="border-b border-rule">
            <th scope="col" className="w-[22%] py-2 pr-3 text-meta font-normal text-slate">Column</th>
            <th scope="col" className="w-[24%] py-2 pr-3 text-meta font-normal text-slate">Read as</th>
            <th scope="col" className="w-14 py-2 pr-3 text-right text-meta font-normal text-slate">Sure</th>
            <th scope="col" className="w-[26%] py-2 pr-3 text-meta font-normal text-slate">Why</th>
            <th scope="col" className="py-2 text-meta font-normal text-slate">Sample values</th>
          </tr>
        </thead>
        <tbody>
          {detail.columns.map((c: ImportColumn) => (
            <tr key={c.column} className="border-b border-rule align-top">
              <td className="py-2 pr-3 text-table text-ink">{c.column}</td>
              <td className="py-2 pr-3">
                <Select
                  value={c.field ?? EXTRA}
                  disabled={!editable || update.isPending}
                  onValueChange={(v) => update.mutate({ [c.column]: v === EXTRA ? null : v })}
                >
                  <SelectTrigger aria-label={`Read ${c.column} as`} className="h-8 w-full text-table">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={EXTRA}>Keep as extra data</SelectItem>
                    {detail.fields.map((f) => (
                      <SelectItem key={f.name} value={f.name}>
                        {f.label}
                        {f.mandatory_group ? " *" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </td>
              <td className="py-2 pr-3 text-right text-table text-slate tabular-nums">
                {c.field ? `${Math.round(c.confidence * 100)}%` : "—"}
              </td>
              <td className="py-2 pr-3 text-meta text-slate">{c.reason}</td>
              <td className="truncate py-2 text-meta text-slate" title={c.samples.join(" | ")}>
                {c.samples.join(" | ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HealthPanel({ detail }: { detail: ImportDetail }) {
  const h = detail.health as Record<string, number | string[] | undefined> | null;
  if (!h) return null;
  const num = (k: string) => (typeof h[k] === "number" ? (h[k] as number) : 0);
  const rows = num("rows");
  const line = (label: string, n: number) =>
    n > 0 ? (
      <li key={label} className="text-table text-ink">
        {formatCount(n)} <span className="text-slate">{label}</span>
      </li>
    ) : null;
  return (
    <div className="grid gap-2">
      <p className="text-body text-ink">
        Health <span className="font-medium tabular-nums">{num("score")}/100</span>
        <span className="text-slate"> on the first {formatCount(rows)} rows</span>
      </p>
      <ul className="grid gap-0.5">
        {line("rows with no firm name", num("firm_name_missing"))}
        {line("rows with no website", num("website_missing"))}
        {line("websites that are not usable addresses", num("website_malformed"))}
        {line("rows with no location", num("location_missing"))}
        {line("rows with no firm size", num("size_missing"))}
        {line("rows with no firm type", num("type_missing"))}
        {line("contact names that are not people", num("junk_person_names"))}
        {line("email values that are not addresses", num("invalid_emails"))}
        {line("extra rows at a firm already in the sheet", num("duplicate_domain_rows"))}
        {line("rows marked contacted before", num("contacted_before"))}
        {line("rows with a job post", num("job_posts"))}
      </ul>
    </div>
  );
}

function BatchList({ batches }: { batches: ImportBatch[] }) {
  return (
    <ul className="grid gap-1">
      {batches.map((b) => (
        <li key={b.batch_no} className="grid grid-cols-[4rem_1fr_auto] items-baseline gap-3 text-table">
          <span className="text-slate tabular-nums">#{b.batch_no}</span>
          <span className="text-ink">
            rows {formatCount(b.row_start)}–{formatCount(b.row_end)}
            {b.status === "loaded"
              ? ` — ${formatCount(b.rows_loaded)} loaded${b.rows_skipped ? `, ${formatCount(b.rows_skipped)} already known` : ""}`
              : ""}
            {b.error ? <span className="text-redline"> — {b.error}</span> : null}
          </span>
          <span className={cn("text-meta", STATUS_TONE[b.status] ?? "text-slate")}>{b.status}</span>
        </li>
      ))}
    </ul>
  );
}

function ImportDetailView({ id }: { id: string }) {
  const query = useImport(id);
  const start = useStartLoad(id);
  const detail = query.data;

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!detail) {
    return (
      <div className="grid gap-3 px-6 py-5">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const canLoad = detail.status === "mapped" && detail.missing.length === 0 && !start.isPending;
  const loading = detail.status === "loading";
  const pct = detail.batches_total ? (detail.batches_loaded / detail.batches_total) * 100 : 0;

  return (
    <div className="grid gap-6 px-6 py-5">
      <div className="grid gap-1">
        <h2 className="text-section font-medium text-ink">{detail.file_name}</h2>
        <p className="text-meta text-slate">
          {formatCount(detail.row_count)} rows, {detail.format.toUpperCase()}, uploaded{" "}
          {formatDateTime(detail.created_at)}
        </p>
        <p className={cn("text-body", STATUS_TONE[detail.status] ?? "text-slate")}>{detail.status_display}</p>
      </div>

      <section aria-labelledby="mandatory-heading" className="grid gap-2">
        <SectionHeading id="mandatory-heading" level={3}>
          Mandatory data
        </SectionHeading>
        <MandatoryLine detail={detail} />
      </section>

      <section aria-labelledby="columns-heading" className="grid gap-3">
        <SectionHeading id="columns-heading" level={3} aside={`${detail.columns.length} columns`}>
          How the columns were read
        </SectionHeading>
        <ColumnsTable detail={detail} />
      </section>

      <section aria-labelledby="health-heading" className="grid gap-2">
        <SectionHeading id="health-heading" level={3}>
          Data health
        </SectionHeading>
        <HealthPanel detail={detail} />
      </section>

      <section aria-labelledby="load-heading" className="grid gap-3">
        <SectionHeading id="load-heading" level={3}>
          Loading
        </SectionHeading>
        {detail.status === "mapped" ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={!canLoad} onClick={() => start.mutate()}>
              Load {formatCount(detail.row_count)} rows in {detail.batches_total} batch
              {detail.batches_total === 1 ? "" : "es"}
            </Button>
            {detail.missing.length > 0 ? (
              <span className="text-meta text-slate">Map the missing columns first.</span>
            ) : null}
          </div>
        ) : null}
        {loading || detail.status === "loaded" || detail.status === "failed" ? (
          <div className="grid gap-3">
            <div
              role="progressbar"
              aria-label="Batches loaded"
              aria-valuemin={0}
              aria-valuemax={detail.batches_total}
              aria-valuenow={detail.batches_loaded}
              className="h-1.5 w-full overflow-hidden rounded-[2px] bg-rule"
            >
              <div
                className={cn("h-full", detail.status === "loaded" ? "bg-ledger" : "bg-cobalt")}
                style={{ width: `${pct}%` }}
              />
            </div>
            <BatchList batches={detail.batches} />
          </div>
        ) : null}
        {detail.notes.length > 0 ? (
          <ul className="grid gap-0.5">
            {detail.notes.map((n, i) => (
              <li key={i} className="text-meta text-slate">
                {n}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}

// ── Screen ──────────────────────────────────────────────────────────────────

export function ImportsScreen() {
  const imports = useImports();
  const [chosenId, setSelectedId] = useState<string | null>(null);
  // Until a sheet is chosen, the newest one is open.
  const selectedId = chosenId ?? imports.data?.items[0]?.id ?? null;

  return (
    <>
      <TitleBar
        title="Lists"
        meta={
          imports.data
            ? `${formatCount(imports.data.items.length)} sheets — upload, check how it was read, load`
            : "Upload a sheet, check how it was read, load it"
        }
      />
      <div className="grid gap-6 px-8 py-6 lg:grid-cols-[minmax(18rem,30%)_1fr]">
        <div className="grid content-start gap-6">
          <UploadPanel onUploaded={setSelectedId} />
          <Panel aria-labelledby="sheets-heading" className="grid gap-3 px-3 py-4">
            <SectionHeading id="sheets-heading" className="px-3">
              Sheets
            </SectionHeading>
            {imports.isError ? (
              <ErrorState error={imports.error} onRetry={() => void imports.refetch()} />
            ) : imports.data && imports.data.items.length === 0 ? (
              <EmptyState title="No sheets yet" className="px-3 py-4">
                Upload the first one above. The purchased list is already loaded from the
                command line.
              </EmptyState>
            ) : (
              <ul className="grid gap-1">
                {(imports.data?.items ?? []).map((item) => (
                  <ImportRow
                    key={item.id}
                    item={item}
                    selected={item.id === selectedId}
                    onSelect={() => setSelectedId(item.id)}
                  />
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <Panel aria-label="Selected sheet" className="min-w-0">
          {selectedId ? (
            <ImportDetailView id={selectedId} />
          ) : (
            <EmptyState title="Pick a sheet" className="px-6">
              The mapping, the data health and the batches show here.
            </EmptyState>
          )}
        </Panel>
      </div>
    </>
  );
}
