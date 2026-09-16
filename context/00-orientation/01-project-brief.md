---
id: orientation.project-brief
title: What this system is
answers: "What are we building, for whom, and what is the one structural idea behind it?"
source: 00 preamble, 01 §1, README
authority: canonical
stability: decided
depends_on: []
feeds: [orientation.document-map, icp.need-model, pipeline.architecture]
---

# What this system is

**Product** — dedicated remote legal staff, placed into law firms.
**Market** — US private law firms.
**This system** — the lead generation engine that finds them, qualifies them, detects
when they are in market, and hands a worked lead to a human.

Scope is the **data layer**. Commercial modelling — funnel projections, CAC, cost
estimates — is deliberately out of scope and was removed from the current documents.
See [decisions.exclusions](../70-decisions/02-deliberate-exclusions.md).

---

## The structural idea

Two problems, deliberately kept apart. Conflating them is the most common way projects
like this fail.

| | **Universe** | **In-market** |
|---|---|---|
| Question | Which firms *could* buy | Which of them needs staff *right now* |
| Nature | Stable properties — practice area, fee model, size, staffing shape | A transient state lasting weeks — an unfilled role, a capacity failure, a volume spike |
| Cadence | Determined once, stored, re-verified quarterly | Detected continuously, forever |
| Solved by | Breadth and accuracy | Freshness and latency |
| Success is | Coverage | A signal reaching a human in under 48 hours |

This split appears everywhere downstream. In the pipeline it is the difference between
planes that terminate and planes that do not ([pipeline.architecture](../40-pipeline/01-architecture.md)).
In the data model it is the difference between `firm` and `lead`
([datamodel.schema](../30-data-model/01-schema-core.md)). In scoring it is the difference
between fit and intent ([pipeline.scoring](../40-pipeline/04-scoring-engine.md)).

---

## Shape of the build

- Postgres 16 as the single store. `pg_trgm` + `postgis`.
- Prefect flows on Cloud Run Jobs. One-shot flows that drain a queue and terminate;
  cron flows that never terminate.
- Raw HTML to object storage, always — this is the single reason a later schema change
  becomes a re-parse instead of a re-crawl.
- ~34 components across five planes: D (discovery), P (profile), W (watchers),
  R (resolvers), I (first-party), plus the JA sub-plane that replaces W1/W2.
- A lead lifecycle of 16 states.

---

## The invariant that keeps it simple

**No component reads another component's output directly.** Everything is mediated by
the store. A scraper that needs a firm's domain reads `firm.domain`; it never calls the
discovery scraper.

This makes every component independently re-runnable, independently testable against a
fixture, and safe to backfill.

---

## Two things easy to get wrong

**Resolve identity before crawling, not after.** The same firm arrives from three
sources under three names. Deduplicate first, or the most expensive stage in collection
runs three times on the same firm — and the same partner later receives three emails
from three of your sending domains, which ends the programme faster than any technical
failure. See [datamodel.identity](../30-data-model/03-identity-resolution.md).

**Do not harvest broadly and filter afterwards.** Collect one segment completely, prove
the chain end to end on a set small enough to check by hand, then widen. Broad-then-filter
spends most of the collection effort on firms that were never going to qualify, and
hides errors until they are expensive to fix. See
[execution.collection-phases](../60-execution/02-collection-phases.md).
