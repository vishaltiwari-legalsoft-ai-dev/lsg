---
id: pipeline.observability
title: Observability — alerting on absence
answers: "What tells us the pipeline is broken, given that scrapers fail silently?"
source: 01 §12, 02 §8, 03 §8
authority: canonical
stability: seeded
depends_on: [pipeline.component-register, pipeline.lifecycle]
feeds: [execution.risk-register]
---

# Observability — alerting on absence

> Most of these alert on **absence**, which is the failure mode that silently kills scraping
> systems. A watcher that returns zero results **does not error** — it just quietly stops
> feeding the pipeline.

**Every alert here is a defect, not a metric to watch.** If it fires, something is broken.

---

| Signal | Condition | Why it is a defect |
|---|---|---|
| **Watcher silence** | JA1 finds **0 new postings** across all qualified firms | Across thousands of firms, zero is **statistically impossible**. The parser broke or the fetch is being blocked |
| **Platform parser silence** | A bar-board platform parser yields zero across **all** its boards | One board at zero is noise. All boards on one platform at zero is a broken parser |
| **Dedupe drift** | Count of firms sharing domain or phone **> 0** | Rules R1/R2 stopped firing. **Duplicate outreach follows within days** |
| **Extraction confidence drop** | Median `fee_model.confidence` falls **> 0.1** week over week | Site layouts changed, or a prompt revision regressed. **Tier assignment degrades silently** |
| **Tier distribution shift** | Any tier's share moves **> 15%** week over week | Either the classifier drifted or the harvest changed shape. **Both are bugs** |
| **Bounce rate** | **> 2%** on any sending domain | Verification is leaking. **Pause the domain; do not push through** |
| **Signal-to-contact latency** | p50 **> 48h** for STRIKE band | **The one metric the whole signal architecture exists to minimise** |
| **Bench starvation** | A wedge SKU at 0 availability for **> 7 days** | Leads for that tier are silently not arming. **Looks like a demand problem; is a supply problem** |
| **Bench staleness** | `bench_inventory.as_of` falls behind | Leads arm against inventory already placed. **Treat a stale bench as empty** |
| **Stale share** | **> 20%** of pool past 90d freshness | W7 is behind. The pool is degrading toward an unusable list |
| **Source yield zero** | A registered source returns nothing | **Check robots.txt before assuming the parser broke.** A newly added `Disallow` and a site redesign present identically |
| **Robots diff** | Monthly re-fetch shows a change touching job paths, crawl-delay, or agent rules | A permission checked once and never rechecked is an assumption again |
| **Agency rule-3 spike** | Sudden rise in geographic-spread rejects | **Usually a new agency has appeared**, not that the market changed |

---

## Why "alert on absence" is the organising idea

Every genuinely dangerous failure in this system is invisible from the inside:

| Failure | What it looks like |
|---|---|
| Broken dedupe | **More rows, better coverage** |
| Blocked crawler | An empty result set, no error |
| Regressed prompt | Confident answers that are wrong |
| Stale bench | A full arming queue |
| Name-only merge | A plausible attribute on a real firm |
| Closed-on-fetch-failure | Thousands of live signals quietly ending |

None of these throw. All of them are caught by noticing that a number went to zero, or moved
when it should not have.

---

## What each stage must emit

| Stage | Emits |
|---|---|
| **Every fetch** | url · status · bytes · content hash · duration · proxy used · **robots decision** |
| **Every extraction** | component · model · **prompt rev** · input tokens · **per-field confidence** |
| **Every state transition** | the `lead_state_event` row. **This table is the audit log; nothing else needs to be** |
| **Every send** | mailbox · step · **suppression check result** · delivery outcome |

`robots decision` on every fetch and `suppression check result` on every send are both there
so that a compliance question has an answer in the logs rather than in someone's memory.

`prompt rev` on every extraction is what makes the confidence-drop alert attributable to a
specific change.

---

## Attribution closes the loop

Every `WON` and `LOST` carries its `arming_signal`.

After ninety days, that join — **outcome by signal kind** — is what re-weights
[the scoring engine](04-scoring-engine.md).

> The weights in this document are a **seeded hypothesis**; the only thing that makes them
> correct is running that query and rewriting the table.

Building the attribution join is not a reporting nicety. It is the mechanism by which every
`seeded` value in this system becomes `measured`. Without it, the whole scoring layer stays a
guess indefinitely.
