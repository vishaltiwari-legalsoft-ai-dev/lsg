---
id: pipeline.orchestration
title: Orchestration — flows, cron, idempotency, backfill
answers: "What runs when, and how is any of it safely re-run?"
source: 01 §11, 03 §9, 02 §7
authority: canonical
stability: decided
depends_on: [pipeline.architecture, pipeline.component-register]
feeds: [execution.gates, execution.build-order]
---

# Orchestration

**Prefect flows on Cloud Run Jobs.** Two shapes:

- **One-shot** — walk a work queue until empty, then terminate
- **Cron** — never terminate

That split is the plane split from [pipeline.architecture](01-architecture.md) made
operational.

---

## One-shot — run once per firm, resumable, idempotent

```
harvest_universe      D1 → D2 → D3            (parallel by state/cell)
        ↓
resolve_identity      §5, full-set operation   ← GATE: verify queries
        ↓
profile_firms         P1 → P2 → P3? → P4       (fan-out, 1 req/2s per domain)
        ↓
extract_attributes    P5 → P6 → P7 → P8 → P9?  (P8 batched)
        ↓
reconcile_and_class   §8 → icp_tier()          ← GATE: tier distribution sane
        ↓
resolve_contacts      R2 → R1 → R3 → R4        (tier-gated: qualified only)
        ↓
emit_leads            §10  QUALIFIED_A / QUALIFIED_B
```

Two gates, both hard. See [execution.gates](../60-execution/03-hard-gates.md).

Note `resolve_identity` sits **between** discovery and profiling. That placement is the whole
point: deduplicate before the expensive per-firm stage, not after.

Note `resolve_contacts` is **tier-gated**. R1 is a paid enricher; running it on the whole
universe is the largest avoidable cost in the system.

---

## Cron — never terminate

```
02:00   JA1/JA2/JA3   job sweep            all qualified firms, board registry, ATS
02:30   JA4           licensed feed        daily delta pull
02:45   JA6           normaliser           agency filter → dedupe → resolve → signal
03:00   score_nightly fit + intent + band  FULL SCAN
03:30   arm_leads     band crossings → ARMED   (bench-gated)
04:00   sequence_dispatch  ARMED → ENGAGED     (respects send caps)

hourly  I3            portal demand → firm_track + suppression
hourly  I4            talent pool → bench_inventory
Sun     W3            review poller        tier 1A + 1B
weekly  JA5           SERP discovery       rotating query set
1st     W4/W5         ads + mass tort      tier 1A
Qtr     W6            tech delta           all qualified
rolling W7            liveness             1/90th of universe per day
monthly robots re-audit  all registered sources, diff against stored copy
```

The hourly cadence on **I3 and I4** is not about latency. I3 wrong means cold-emailing a
customer; I4 stale means arming against inventory that is already placed. Both are
correctness, not freshness.

W7 at **1/90th of the universe per day** is what makes the 90-day freshness guarantee a
steady load rather than a quarterly spike.

---

## Idempotency

```
every task keys on (component, entity_id, input_hash)
a re-run with unchanged input is a no-op that logs and exits
→ any flow can be replayed from any point without duplication
```

This is only possible because of the plane invariant: **no component reads another
component's output directly.** With everything mediated by the store, a component's inputs
are fully described by rows, so they can be hashed.

---

## Backfill — the rule that pays for the raw HTML

> **A prompt or normalizer version bump does NOT re-crawl.**
>
> It re-reads stored HTML from GCS and re-runs the affected component only.

**This is the single reason P2 stores raw HTML.**

The same pattern appears three times, and they should be understood as one decision:

| Stored | Lets you re-run | Without |
|---|---|---|
| Raw HTML in GCS (P2) | P4–P9, any extraction change | Re-crawling the site |
| `raw_posting` rows (JA1–JA5) | JA6 — agency filter, title map, resolution rules | Re-crawling the boards |
| `norm_version` per value | Recomputing canonical forms | A full re-harvest |
| `llm:p8:v3` per attribute row | Re-extracting at a new prompt rev | Re-crawling anything |

Every version-bump in this system is a re-parse. **Never a re-harvest.**

---

## Rate discipline

```
per-DOMAIN token bucket in Redis, NOT global.
one firm's site sees ≤1 request / 2s regardless of worker count.
paid APIs get a separate bucket sized to the plan's QPS.
```

**Per-host, not global** is the important word. A global bucket either throttles the whole
crawler to protect one small server, or protects nothing.

**Declared `Crawl-delay` overrides the 2s default.** LA County Bar declares 5s; a 200-listing
board then takes ~17 minutes, and across 60 metro bars that is real scheduler time that has
to be **planned, not discovered on the first slow night**. See
[signals.crawl-policy](../20-signals/05-crawl-policy-and-audit.md).

**Change detection** cuts the nightly load: store a content hash per listing page; unchanged
hash → **skip parse entirely**. Most nights, most pages are unchanged. This is what makes a
nightly full sweep feasible at all.

---

## The gate that must not be advisory

`resolve_identity` is followed by the [verification
queries](../30-data-model/03-identity-resolution.md) as a **hard gate**. If firms share a
domain or a phone, **the flow stops**.

> Everything downstream — crawling, extraction, enrichment, verification — is **spent
> per-firm**, so advancing past a broken dedupe multiplies the cost of the error by every
> subsequent stage.
