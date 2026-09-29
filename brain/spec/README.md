# The source documents

Written 10 Sep 2026, before any code existed. Kept as the original framing, and as the guide to the five PDFs in this folder.

For where the project actually stands, read `../REPORT.md`. For why anything is the way it is now, read `../context/70-decisions/01-decision-log.md` — several rules below have since been superseded by numbered decisions.

`_source/` and `_archive/` mentioned below are now both in `../archive/`.

---

## The two documents

| File | Answers | Status |
|---|---|---|
| `00 - ICP + Collection Strategy.pdf` | **Who to target and why.** Need model, tiers, source map, in-market signals, collection sequence, lead record. | Current |
| `01 - Pipeline Build Spec.pdf` | **How to build it.** Schema (13 tables), 24 components, normalization, identity resolution, extraction contracts, scoring, 16-state lead lifecycle. | Current |

`00` is the source of the *why*. `01` is the source of the *how*. If a rule in one disagrees with a rule in the other, reconcile them — do not pick one and move on.

`_source/` holds the HTML for both, plus the print wrapper for re-rendering.
`_archive/` holds three earlier documents that are superseded. They contain commercial modelling — funnel projections, cost estimates, CAC — that is out of scope and was built on published marketing claims rather than measured facts. Do not build from them.

---

## The structural idea

Two problems, deliberately kept apart. Conflating them is the most common way projects like this fail.

**Universe** — which firms *could* buy. Stable properties: practice area, fee model, size, staffing shape. Determined once, stored, re-verified quarterly. Success is coverage and accuracy.

**In-market** — which of them needs staff *right now*. A transient state lasting weeks: an unfilled role, a capacity failure visible in reviews, a volume spike. Success is freshness and latency.

Different cadences, different sources, different definitions of done.

---

## What changed in this revision

Three contradictions between the two documents were found and resolved.

1. **Size threshold.** `01` disqualified firms above 25 attorneys while also scoring a 26–50 band at −10. Both could not be true. Resolved to match `00`: **disqualify above 50, penalise 26–50**. Those firms have a real need and a longer cycle; a strong signal should still be able to surface one.

2. **Low-volume practices.** `00` excluded appellate, patent prosecution and complex commercial work — they fail need condition 1, there is little procedural volume to delegate. `01` had no matching clause, so those firms fell through to tier 4. Added `DQ_NOVOLUME`.

3. **Competitor customers.** `00` said these are not a disqualifier but a separate, slower motion. `01` listed `competitor` as a suppression reason, which silenced them. Removed from suppression; added a `firm_track` table carrying `cold | displacement | partner_intro | holdout`.

`firm_track` also gives the holdout slices a home — the tier-4 hourly firms and non-concentration geographies that exist to test targeting assumptions rather than to convert.

---

## Build order

Each stage is gated. Do not advance past a failed gate — everything downstream is spent per-firm, so an upstream error multiplies through every later stage.

**1 — Foundation**
- Postgres 16, extensions `pg_trgm` + `postgis`
- Schema from `01` §3, all 13 tables
- Invariants I1–I7 as constraints and triggers, not application code

**2 — Normalizers** (`01` §4)
- `norm_domain`, `norm_phone`, `norm_addr`, `norm_name`, `norm_practice`
- Ship the `norm_version` column with them. Retrofitting it later costs a full re-harvest.
- Unit tests before any harvest runs. These functions decide whether dedupe works.

**3 — Probe** (`00` §11, phase 0)
- Three metros, tier 1A only. A few hundred firms, all the way through every step.
- Hand-check 50 records on every attribute.
- This is where the estimated yields in these documents get replaced by measured ones.

**4 — Identity resolution** (`01` §5) — **HARD GATE**
- Blocking → rules R1–R4 → union-find
- Run the two verification queries: firms sharing a domain or a phone must be ~zero
- Collapse ratio between 2.0× and 3.3×
- **If this gate fails, stop.** A broken dedupe presents as success — more rows, better coverage — and surfaces later as one managing partner receiving several emails from several of your sending domains.

**5 — Beachhead collection** (`00` §11, phase 1)
- Tier 1A nationally, metros first by density
- P2 must store raw HTML to object storage — this is the single reason a later schema change becomes a re-parse instead of a re-crawl

**6 — Signal layer** (`00` §9, `00` §11 phase 2)
- No new firms. Prove in-market detection over the beachhead.

Sending-domain warmup runs in parallel from day one — four weeks of calendar time that cannot be compressed at the end.

---

## Two things easy to get wrong

**Resolve identity before crawling, not after.** The same firm arrives from three sources under three names. Deduplicate first, or the most expensive stage in collection runs three times on the same firm.

**Do not harvest broadly and filter afterwards.** Collect one segment completely, prove the chain, then widen. Broad-then-filter spends most of the collection effort on firms that were never going to qualify, and hides errors until they are expensive to fix.

---

## Next action

The schema, the normalizer contracts, the practice-area vocabulary and the fee-model patterns are currently specified inside `01` but not extracted as runnable files. Step 1 of the build is to pull them out into:

```
sql/001_schema.sql          13 tables + indexes + invariant constraints
sql/002_functions.sql       icp_tier(), signal_weight(), decay(), reconcile()
config/practice_areas.yml   the 15-slug closed vocabulary
config/fee_patterns.yml     P6 regex set, precedence-ordered
config/sources.yml          per-source rate limits and blocklists
```

Everything above that point is decided. Nothing below it is written yet.

---

## Re-rendering the PDFs

Sources are in `_source/`. Each document is an HTML fragment; `_head.html` and `_tail.html` wrap it with a forced light theme and print CSS.

```bash
cat _head.html legalsoft-pipeline-spec.html _tail.html > out.html
```

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --headless --disable-gpu --no-sandbox `
  --user-data-dir="$env:TEMP\cr-pdf-profile" --no-first-run `
  --virtual-time-budget=30000 --no-pdf-header-footer `
  --print-to-pdf="out.pdf" "file:///full/path/to/out.html"
```

`--user-data-dir` is required. Without it a running Chrome instance swallows the invocation and it exits silently without producing a file.

---

## Live versions

- ICP + Collection Strategy — https://claude.ai/code/artifact/6b66828b-ccee-4175-bbc1-3e4b9d6d982e
- Pipeline Build Spec — https://claude.ai/code/artifact/032bb22e-9405-4981-9d92-b363e873e4e3

Archived: [Plan + Red Team](https://claude.ai/code/artifact/87862362-94ca-4214-957d-cfd96b5abd8b) · [Lead Engine ICP](https://claude.ai/code/artifact/9daeebed-dc4c-465b-ae40-4b45fc42fa67) · [Scraper Build Plan](https://claude.ai/code/artifact/165dfe7a-0c74-4c57-8342-e7570a232997)

---

## Excluded sources

Two are deliberately not used anywhere in this system: direct job-board scraping, and automated professional-network extraction. Both carry terms-of-service and legal exposure.

The job signal is obtained instead from firms' own careers pages, with a licensed aggregator as backfill. The signal is not lost, only the exposure.
