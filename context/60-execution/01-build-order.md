---
id: execution.build-order
title: Consolidated build order
answers: "What do we build, in what order, across all five documents?"
source: README, 00 §11, 02 §9, 03 §11
authority: canonical
stability: decided
depends_on: [orientation.document-map]
feeds: [execution.gates, execution.collection-phases]
---

# Consolidated build order

The root `README.md` carries a build order that predates documents 02, 03 and 04 — it stops
at the signal layer. **This is the consolidated sequence.**

Ordering principle, stated differently in each source document but consistently:
**risk retired per unit of effort, not data volume.** Each stage is gated; a failed gate
stops the flow, because everything downstream is spent per-firm and an upstream error
multiplies through every later stage.

---

## Stage 0 — Before anything outbound exists

These two are small, and both must land **before the first outbound email is ever sent.**

| # | Build | Why first |
|---|---|---|
| **0.1** | **I3 — portal demand → `firm_track` + suppression** | Retires the only failure here that **damages an existing customer.** Small job, and nothing outbound should run before it exists |
| **0.2** | **I4 — talent pool → `bench_inventory`** | Closes the supply gate the build spec left open. Also small |

**Sending-domain warmup starts now and runs in parallel from day one** — four weeks of
calendar time that cannot be compressed at the end.

---

## Stage 1 — Foundation

| # | Build | Notes |
|---|---|---|
| 1.1 | Postgres 16, `pg_trgm` + `postgis` | |
| 1.2 | `sql/001_schema.sql` — all 13 tables + indexes | [datamodel.schema](../30-data-model/01-schema-core.md) |
| 1.3 | **Invariants I1–I7 as constraints and triggers** | **Not application code.** Anything enforced only in application code will eventually be bypassed by a backfill script |

---

## Stage 2 — Normalizers

| # | Build | Notes |
|---|---|---|
| 2.1 | `norm_domain`, `norm_phone`, `norm_addr`, `norm_name`, `norm_practice` | [datamodel.normalization](../30-data-model/02-normalization-contracts.md) |
| 2.2 | **Ship the `norm_version` column with them** | **Retrofitting it later costs a full re-harvest** |
| 2.3 | `config/practice_areas.yml` — the 15-slug closed vocabulary | |
| 2.4 | `config/fee_patterns.yml` — P6 regex set, precedence-ordered | |
| 2.5 | **Unit tests before any harvest runs** | These functions decide whether dedupe works |

---

## Stage 3 — Cheap inspections that change the plan

Do these before committing scope. Each is one inspection and each can change what gets built.

| # | Do | Changes |
|---|---|---|
| **3.1** | **Triage the job data against the match ladder** | Determines whether the asset is usable at all. **Prevents planning around data that cannot be matched.** [firstparty.job-history](../50-first-party/05-job-history.md) |
| **3.2** | **Determine which reading of portal Feed B is correct** | Decides whether it is a suppression source or a live signal source. [firstparty.portal](../50-first-party/03-portal-bench-and-supply.md) |
| **3.3** | **Robots audit as a script, not a task** | ~110 sources. A hand-built table is a document; a generated one is infrastructure. [signals.crawl-policy](../20-signals/05-crawl-policy-and-audit.md) |

---

## Stage 4 — Probe

**Three metros, tier 1A only. A few hundred firms, all the way through every step.**

- **Hand-check 50 records on every attribute.**
- This is where the estimated yields in these documents get **replaced by measured ones**.

Nothing widens until a hand-checked sample of 50 is accurate on every attribute.

---

## Stage 5 — Identity resolution · **HARD GATE**

| # | Build |
|---|---|
| 5.1 | Blocking → rules R1–R4 → union-find |
| 5.2 | Run the two verification queries: firms sharing a domain or a phone must be **~zero** |
| 5.3 | Collapse ratio between **2.0× and 3.3×** |

> **If this gate fails, stop.** A broken dedupe presents as success — more rows, better
> coverage — and surfaces later as one managing partner receiving several emails from several
> of your sending domains.

---

## Stage 6 — I1 firm dataset load + coverage analysis

Placed here deliberately: **it may materially shrink the discovery plane**, which is the
largest and most expensive stage in the whole system. Do it **early enough to influence that
scope rather than after it has been built to full size.**

---

## Stage 7 — Beachhead collection

- Tier 1A nationally, **metros first by density**
- **P2 must store raw HTML to object storage** — the single reason a later schema change
  becomes a re-parse instead of a re-crawl

Move on when the duplicate check is clean and decision-maker coverage holds.

---

## Stage 8 — Job signal layer

**No new firms.** Prove in-market detection over the beachhead.

| # | Build | Why here |
|---|---|---|
| **8.1** | **JA1 — careers page watcher** | Best ICP coverage, **zero resolution problem**, free, stable. Also the source of truth for closure detection, so everything else leans on it |
| **8.2** | **JA6 — normaliser, agency filter first** | Even with one source, agency noise must be filtered **before signals are written.** Build the filter before the second source multiplies the noise |
| **8.3** | JA2 — bar boards, **top 10 metros** | Highest-value addition after careers pages. **Prove the platform-parser approach on ten before writing forty** |
| **8.4** | JA3 — ATS endpoints | Small effort, clean data, no parser maintenance |
| **8.5** | Craigslist (promoted to lane 1 by the audit) | Per-city RSS, metros first. **Expect high agency noise** |
| **8.6** | JA5 — SERP discovery | Reveals which sources are being missed — **and that answer should inform whether lane 2 is worth buying** |
| **8.7** | **JA4 — licensed feed. LAST** | **It costs money.** By this point there is a **measured coverage gap** to size it against instead of an assumption |

> Run lane 1, measure what share of firms produce postings there, **then buy against a
> number.**

Then the remaining watchers: W3 (weekly), W4/W5 (monthly), W6 (quarterly), W7 (rolling).

---

## Stage 9 — I2 job history load

**Last**, because its value is a fit-score refinement rather than a gate, and it depends on
the stage 3.1 triage verdict.

---

## Stage 10 — Widen

Phases 3 and 4 of [execution.collection-phases](02-collection-phases.md): tier 1B, then tier
2, then tier 3 and the tier-4 holdout.

---

## What is decided and what is not written

> Everything in the documents is decided. **Almost none of it is written.**

The specific gap named in the README, still open:

```
sql/001_schema.sql          13 tables + indexes + invariant constraints
sql/002_functions.sql       icp_tier(), signal_weight(), decay(), reconcile()
config/practice_areas.yml   the 15-slug closed vocabulary
config/fee_patterns.yml     P6 regex set, precedence-ordered
config/sources.yml          per-source rate limits and blocklists
```

To which documents 02–04 add:

```
config/agency_blocklist.yml   legal-staffing agencies, maintained not static
config/title_synonyms.yml     normalize_title() canonical role map
config/board_registry.yml     ~110 sources + source_state + crawl_delay_s + platform
```
