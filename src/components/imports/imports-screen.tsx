"use client";

import { FileSpreadsheetIcon, UploadIcon } from "lucide-react";
import { useId, useRef, useState } from "react";

import { SectionHeading } from "@/components/layout/panel";
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
// Rows per loading batch: how a sheet is read in, not the enrichment batches of
// the brief -- one fixed size, so the two are never confused on screen.
const LOAD_BATCH_ROWS = 500;
const ACCEPT = ".csv,.tsv,.txt,.xlsx,.xlsm";

const STATUS_TONE: Record<string, string> = {
  mapped: "text-slate",
  loading: "text-cobalt",
  loaded: "text-ledger",
  failed: "text-redline",
};

// ── Upload: drop a sheet, or choose one ─────────────────────────────────────

function UploadPanel({ onUploaded }: { onUploaded: (id: string) => void }) {
  const upload = useUploadImport();
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  return (
    <section aria-labelledby="upload-heading" className="grid gap-4">
      <SectionHeading id="upload-heading">Upload a sheet</SectionHeading>
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!file) return;
          upload.mutate(
            { file, batchSize: LOAD_BATCH_ROWS },
            {
              onSuccess: (detail) => {
                onUploaded(detail.id);
                setFile(null);
                if (fileRef.current) fileRef.current.value = "";
              },
            },
          );
        }}
      >
        <label
          htmlFor={inputId}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            const dropped = event.dataTransfer.files?.[0];
            if (dropped) setFile(dropped);
          }}
          className={cn(
            "grid cursor-pointer justify-items-center gap-2 rounded-panel border-2 border-dashed px-5 py-7 text-center transition-colors duration-100",
            over ? "border-cobalt bg-cobalt-wash" : "border-rule-strong bg-sheet hover:border-cobalt/60",
          )}
        >
          {file ? (
            <FileSpreadsheetIcon className="size-6 text-cobalt" aria-hidden="true" />
          ) : (
            <UploadIcon className="size-6 text-slate" aria-hidden="true" />
          )}
          <span className="text-body font-semibold text-ink">
            {file ? file.name : "Drop a sheet here, or choose a file"}
          </span>
          <span className="text-meta text-slate">
            {file ? `${formatCount(Math.max(1, Math.round(file.size / 1024)))} KB` : "CSV or Excel, any layout of columns"}
          </span>
          <input
            ref={fileRef}
            id={inputId}
            type="file"
            name="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <div>
          <Button type="submit" variant="primary" disabled={!file || upload.isPending}>
            {upload.isPending ? "Reading the sheet…" : "Upload and read columns"}
          </Button>
        </div>
        <p className="text-meta text-slate">
          Nothing loads yet: the engine reads the headers and a sample of rows, says which column is which, and
          waits for you to check it.
        </p>
      </form>
    </section>
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
    <li className="border-b border-rule last:border-b-0">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "grid w-full gap-0.5 px-3 py-3 text-left transition-colors duration-75 hover:bg-sheet",
          selected && "bg-sheet shadow-[inset_3px_0_0_var(--color-cobalt)]",
        )}
      >
        <span className="truncate text-body font-semibold text-ink">{item.file_name}</span>
        <span className="text-meta text-slate">
          {formatCount(item.row_count)} rows, {item.batches_loaded} of {item.batches_total} batches loaded
        </span>
        <span className={cn("text-meta", STATUS_TONE[item.status] ?? "text-slate")}>
          {item.status_display}
          {item.missing.length > 0
            ? `, ${item.missing.length} required ${item.missing.length === 1 ? "field" : "fields"} not found`
            : ""}
        </span>
      </button>
    </li>
  );
}

// ── Detail ──────────────────────────────────────────────────────────────────

function MandatoryLine({ detail }: { detail: ImportDetail }) {
  const readBy = detail.reader === "llm" ? "Read by the AI, checked against the values." : "Read by the rules.";
  return (
    <div className="grid gap-1.5">
      {detail.missing.length === 0 ? (
        <p className="text-body text-ledger">
          Found what it needs: a firm name and a way to reach each firm. {readBy}
        </p>
      ) : (
        <p className="text-body text-redline">
          Not found: {detail.missing.join("; ")}. Pick the right column below, or the sheet cannot load.
        </p>
      )}
      {detail.research_fills.length > 0 ? (
        <p className="text-table text-slate">
          Not on the sheet, and filled by research: {detail.research_fills.join(", ")}.
        </p>
      ) : null}
    </div>
  );
}

function ColumnsTable({ detail }: { detail: ImportDetail }) {
  const update = useUpdateMapping(detail.id);
  const editable = detail.status === "mapped";
  return (
    <div className="overflow-x-auto border-y border-rule">
      <table className="w-full min-w-[46rem] table-fixed border-collapse text-left">
        <caption className="sr-only">How each column of {detail.file_name} was read</caption>
        <thead>
          <tr className="border-b border-rule">
            <th scope="col" className="w-[22%] py-2.5 pr-3 text-meta font-medium text-slate">Column</th>
            <th scope="col" className="w-[24%] py-2.5 pr-3 text-meta font-medium text-slate">Read as</th>
            <th scope="col" className="w-14 py-2.5 pr-3 text-right text-meta font-medium text-slate">Sure</th>
            <th scope="col" className="w-[26%] py-2.5 pr-3 text-meta font-medium text-slate">Why</th>
            <th scope="col" className="py-2.5 text-meta font-medium text-slate">Sample values</th>
          </tr>
        </thead>
        <tbody>
          {detail.columns.map((c: ImportColumn) => (
            <tr key={c.column} className="border-b border-rule align-top last:border-b-0">
              <td className="py-2.5 pr-3 text-table font-medium text-ink">{c.column}</td>
              <td className="py-2 pr-3">
                <Select
                  value={c.field ?? EXTRA}
                  disabled={!editable || update.isPending}
                  onValueChange={(v) => update.mutate({ [c.column]: v === EXTRA ? null : v })}
                >
                  <SelectTrigger
                    aria-label={`Read ${c.column} as`}
                    className={cn("h-8 w-full text-table", !c.field && "text-slate")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={EXTRA}>Keep as extra data</SelectItem>
                    {detail.fields.map((f) => (
                      <SelectItem key={f.name} value={f.name} hint={f.mandatory_group ? "Needed to load" : undefined}>
                        {f.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </td>
              <td className="py-2.5 pr-3 text-right text-table text-slate tabular-nums">
                {c.field ? `${Math.round(c.confidence * 100)}%` : <span className="sr-only">Not read</span>}
              </td>
              <td className="py-2.5 pr-3 text-meta text-slate">{c.reason}</td>
              <td className="truncate py-2.5 text-meta text-slate" title={c.samples.join(" | ")}>
                {c.samples.length > 0 ? c.samples.join(", ") : <span className="italic">No values in the sample</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The five fields every row is asked for -- firm name, website, location, job
 * post, firm size -- and how many rows of the sheet carry each. What else the
 * reading found (names that are not people, emails that are not addresses)
 * follows, one line each.
 */
function FiveFields({ detail }: { detail: ImportDetail }) {
  const h = detail.health as Record<string, number | string[] | undefined> | null;
  if (!h) return null;
  const num = (k: string) => (typeof h[k] === "number" ? (h[k] as number) : 0);
  const rows = num("rows");
  if (rows === 0) return <p className="text-body text-slate">No rows were read from this sheet.</p>;
  const fields: [string, number][] = [
    ["Firm name", rows - num("firm_name_missing")],
    ["Website", rows - num("website_missing") - num("website_malformed")],
    ["Location", rows - num("location_missing")],
    ["Job post", num("job_posts")],
    ["Firm size", rows - num("size_missing")],
  ];
  const notes = (
    [
      ["websites that are not usable addresses", num("website_malformed")],
      ["contact names that are not people", num("junk_person_names")],
      ["email values that are not addresses", num("invalid_emails")],
      ["extra rows at a firm already in the sheet", num("duplicate_domain_rows")],
      ["rows marked contacted before", num("contacted_before")],
    ] as [string, number][]
  ).filter(([, n]) => n > 0);
  return (
    <div className="grid gap-5">
      <ul className="grid gap-3" aria-label="Rows that carry each field">
        {fields.map(([label, n]) => {
          const share = Math.max(0, Math.min(1, n / rows));
          return (
            <li key={label} className="grid grid-cols-[6.5rem_minmax(0,1fr)_9rem] items-center gap-4">
              <span className="text-body font-medium text-ink">{label}</span>
              <span aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-rule">
                <span
                  className={cn("block h-full rounded-full", share === 1 ? "bg-ledger" : "bg-cobalt")}
                  style={{ width: `${share * 100}%` }}
                />
              </span>
              <span className="text-table text-ink tabular-nums">
                {n === 0 ? (
                  <span className="text-slate">Not on this sheet</span>
                ) : (
                  `${formatCount(n)} of ${formatCount(rows)}`
                )}
              </span>
            </li>
          );
        })}
      </ul>
      {notes.length > 0 ? (
        <ul className="grid gap-1 border-t border-rule pt-3">
          {notes.map(([label, n]) => (
            <li key={label} className="text-table text-ink">
              <span className="font-semibold tabular-nums">{formatCount(n)}</span>{" "}
              <span className="text-slate">{label}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function BatchList({ batches }: { batches: ImportBatch[] }) {
  return (
    <ul className="grid divide-y divide-rule border-y border-rule">
      {batches.map((b) => (
        <li key={b.batch_no} className="grid grid-cols-[4rem_1fr_auto] items-baseline gap-3 py-2 text-table">
          <span className="text-slate tabular-nums">Batch {b.batch_no}</span>
          <span className="text-ink">
            Rows {formatCount(b.row_start)} to {formatCount(b.row_end)}
            {b.status === "loaded"
              ? `: ${formatCount(b.rows_loaded)} loaded${b.rows_skipped ? `, ${formatCount(b.rows_skipped)} already known` : ""}`
              : ""}
            {b.error ? <span className="block text-redline">{b.error}</span> : null}
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
      <div className="grid gap-3" aria-busy="true" aria-label="Loading the sheet">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const canLoad = detail.status === "mapped" && detail.missing.length === 0 && !start.isPending;
  const loading = detail.status === "loading";
  const pct = detail.batches_total ? (detail.batches_loaded / detail.batches_total) * 100 : 0;

  return (
    <div className="grid gap-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <h2 className="text-subtitle font-semibold text-ink">{detail.file_name}</h2>
          <p className="text-table text-slate">
            {formatCount(detail.row_count)} rows in {detail.format.toUpperCase()}, uploaded{" "}
            {formatDateTime(detail.created_at)}
          </p>
          <p className={cn("text-body font-medium", STATUS_TONE[detail.status] ?? "text-slate")}>
            {detail.status_display}
          </p>
        </div>
        {detail.status === "mapped" ? (
          <div className="grid justify-items-end gap-1">
            <Button variant="primary" size="lg" disabled={!canLoad} onClick={() => start.mutate()}>
              Load {formatCount(detail.row_count)} rows
            </Button>
            <span className="text-meta text-slate">
              {detail.missing.length > 0
                ? "Pick the columns it needs first."
                : `In ${detail.batches_total} ${detail.batches_total === 1 ? "batch" : "batches"}; the columns are fixed once it starts.`}
            </span>
          </div>
        ) : null}
      </div>

      <section aria-labelledby="mandatory-heading" className="grid gap-2">
        <SectionHeading id="mandatory-heading" level={3}>
          What it needs
        </SectionHeading>
        <MandatoryLine detail={detail} />
      </section>

      <section aria-labelledby="columns-heading" className="grid gap-3">
        <SectionHeading id="columns-heading" level={3} aside={`${detail.columns.length} columns`}>
          How the columns were read
        </SectionHeading>
        <ColumnsTable detail={detail} />
      </section>

      <section aria-labelledby="fields-heading" className="grid gap-3">
        <SectionHeading
          id="fields-heading"
          level={3}
          aside={
            typeof (detail.health as Record<string, unknown> | null)?.rows === "number"
              ? `on the first ${formatCount((detail.health as Record<string, number>).rows)} rows`
              : undefined
          }
        >
          The five fields
        </SectionHeading>
        <p className="max-w-[70ch] text-body text-slate">
          How many rows carry each of the five fields a lead is built from. Research fills in what a sheet lacks.
        </p>
        <FiveFields detail={detail} />
      </section>

      {loading || detail.status === "loaded" || detail.status === "failed" || detail.notes.length > 0 ? (
        <section aria-labelledby="load-heading" className="grid gap-3">
          <SectionHeading
            id="load-heading"
            level={3}
            aside={`${detail.batches_loaded} of ${detail.batches_total} batches`}
          >
            Loading
          </SectionHeading>
          {loading || detail.status === "loaded" || detail.status === "failed" ? (
            <div className="grid gap-3">
              <div
                role="progressbar"
                aria-label="Batches loaded"
                aria-valuemin={0}
                aria-valuemax={detail.batches_total}
                aria-valuenow={detail.batches_loaded}
                className="h-2 w-full overflow-hidden rounded-full bg-rule"
              >
                <div
                  className={cn("h-full rounded-full", detail.status === "loaded" ? "bg-ledger" : "bg-cobalt")}
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
      ) : null}
    </div>
  );
}

/** Before any sheet: what happens to one, in the order it happens. */
function FirstSheet() {
  const steps = [
    ["It reads the columns", "The AI reads the header and a dozen rows and says which column is which, and what the sheet lacks."],
    ["You check the reading", "Correct any column with one click. Nothing loads until you say so."],
    ["It loads, batch by batch", "Rows become firms, the same firm from two rows becomes one, and every website is checked."],
  ];
  return (
    <div className="grid max-w-[46rem] gap-8 py-4">
      <div className="grid gap-3">
        <h2 className="type-narrow text-headline font-semibold text-ink">Start with a sheet of law firms</h2>
        <p className="text-section leading-relaxed text-slate">
          Any layout works: a vendor export, a conference list, last quarter&apos;s outreach. A firm name, and a
          website, email or location for each, is all it needs; research fills in the rest.
        </p>
      </div>
      <ol className="grid border-t border-rule">
        {steps.map(([title, what], i) => (
          <li key={title} className="grid grid-cols-[3rem_minmax(0,1fr)] gap-2 border-b border-rule py-4">
            <span aria-hidden="true" className="type-narrow text-headline leading-none font-semibold text-cobalt tabular-nums">
              {i + 1}
            </span>
            <span className="grid gap-0.5">
              <span className="text-body font-semibold text-ink">{title}</span>
              <span className="text-body text-slate">{what}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

// ── Screen ──────────────────────────────────────────────────────────────────

/**
 * Sheets: step one of the brief. Upload and the list of sheets on the left,
 * the chosen sheet on the right -- how its columns were read, its health,
 * and its batches as they load.
 */
export function ImportsScreen() {
  const imports = useImports();
  const [chosenId, setSelectedId] = useState<string | null>(null);
  // Until a sheet is chosen, the newest one is open.
  const selectedId = chosenId ?? imports.data?.items[0]?.id ?? null;
  const count = imports.data?.items.length;

  return (
    <>
      <TitleBar
        title="Sheets"
        meta={
          count !== undefined
            ? `${formatCount(count)} ${count === 1 ? "sheet" : "sheets"} uploaded`
            : "Upload a sheet, check how it was read, load it"
        }
      />
      <div className="grid flex-1 lg:grid-cols-[minmax(20rem,26rem)_minmax(0,1fr)]">
        <aside
          aria-label="Upload and sheets"
          className="grid content-start gap-9 border-rule bg-paper/70 px-7 pt-7 pb-12 max-lg:border-b lg:border-r"
        >
          <UploadPanel onUploaded={setSelectedId} />
          <section aria-labelledby="sheets-heading" className="grid gap-3">
            <SectionHeading id="sheets-heading" aside={count ? formatCount(count) : undefined}>
              Sheets
            </SectionHeading>
            {imports.isError ? (
              <ErrorState error={imports.error} onRetry={() => void imports.refetch()} />
            ) : imports.isPending ? (
              <div className="grid gap-2" aria-busy="true" aria-label="Loading sheets">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : imports.data.items.length === 0 ? (
              <p className="text-body text-slate">None yet. The first one you upload appears here.</p>
            ) : (
              <ul className="grid border-y border-rule">
                {imports.data.items.map((item) => (
                  <ImportRow
                    key={item.id}
                    item={item}
                    selected={item.id === selectedId}
                    onSelect={() => setSelectedId(item.id)}
                  />
                ))}
              </ul>
            )}
          </section>
        </aside>
        <section aria-label="Selected sheet" className="min-w-0 px-8 pt-7 pb-16 max-md:px-4">
          {selectedId ? (
            <ImportDetailView id={selectedId} />
          ) : imports.isPending ? null : imports.data && imports.data.items.length === 0 ? (
            <FirstSheet />
          ) : (
            <EmptyState title="Pick a sheet">How its columns were read, its health and its batches show here.</EmptyState>
          )}
        </section>
      </div>
    </>
  );
}
