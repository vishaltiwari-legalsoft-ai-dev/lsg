---
id: execution.collection-phases
title: The five collection phases
answers: "What do we collect, in what order, and what does each phase prove?"
source: 00 §11
authority: canonical
stability: decided
depends_on: [icp.tiers, execution.build-order]
feeds: [execution.gates]
---

# The five collection phases

> **Do not harvest the whole country and filter afterwards.**
>
> Collect one segment completely, prove the chain end to end on a set small enough to check by
> hand, then widen.

The alternative — harvest broadly, then discard most of it — **spends the majority of the
collection effort on firms that were never going to qualify, and hides errors until they are
expensive.**

**Each phase proves something before the next widens.**

---

| Phase | Collect | Proves | Move on when |
|---|---|---|---|
| **0 — Probe** | **Three metros, tier 1A only.** A few hundred firms, fully processed through every step | That the whole chain works, and **what each stage's real yield is.** Every number in a plan like this is an estimate until this phase replaces it | **A hand-checked sample of 50 records is accurate on every attribute** |
| **1 — Beachhead** | **Tier 1A nationally** — PI and mass tort, 2–25 attorneys, metros first by density | Coverage at scale, and that **identity resolution holds when the same firm appears in three sources across fifty states** | Duplicate check is clean and decision-maker coverage holds |
| **2 — Signals** | **No new firms.** Add the signal layer over the beachhead | That in-market detection **actually fires**, and how many firms light up in a given month | Signals fire at a stable weekly rate and **reply data starts distinguishing them** |
| **3 — Adjacent** | Tier 1B immigration, then tier 2 fee-shifting | That the profile **generalises beyond PI** — the first real test of the fee-model axis | Tier 2 converts within range of tier 1A |
| **4 — Breadth & holdouts** | Tier 3, plus **a deliberate slice of tier 4 hourly firms on a non-billable role** | **Whether the fee-model axis is a fact or a good story.** This is the only phase that can disprove it | — |

---

## Phase 0 is where estimates die

Every yield number, every collapse ratio, every conversion assumption in these five documents
is **reasoned, not measured**. Phase 0 exists specifically to replace them.

The gate is deliberately manual: **50 records, hand-checked on every attribute.** Not a
sampled accuracy metric, not a spot check — every attribute on fifty records. It is the
cheapest possible moment to discover that `fee_model` is wrong 30% of the time, and the last
moment before that error is multiplied across a national harvest.

## Phase 2 collects nothing

**No new firms.** This is worth stating twice because the instinct at that point is to keep
widening while the signal layer is built.

The phase exists to answer one question: **does in-market detection actually fire, and at
what weekly rate?** That number sizes everything downstream — SDR headcount, bench
requirements, send caps. It cannot be measured while the universe is still growing under it.

## Phase 4 exists to be disproved

Tier 4 hourly firms are the **weakest fit under the fee-model axis** — the axis this entire
ICP is built on.

Working a deliberate slice of them on a non-billable role is the **only mechanism in the
system that can produce contrary evidence.** Excluding them makes the axis unfalsifiable.

They are carried in `firm_track = 'holdout'`, alongside non-concentration geographies, which
test the density-not-demand assumption in the same way. See
[icp.disqualifiers](../10-icp/06-disqualifiers-and-tracks.md).

---

## The rule that spans all five phases

**Resolve identity before crawling, not after.**

> The same firm arrives from three sources under three names. Deduplicate before the site
> crawl, or the most expensive stage in collection runs **three times on the same firm** — and
> the same partner later receives three emails from three addresses, **which ends the
> programme faster than any technical failure.**

See [datamodel.identity](../30-data-model/03-identity-resolution.md).

---

## What makes the rankings correct

The tier ordering, the signal ordering and the proxy choices are **reasoned from how law
firms are structured and paid.** They are a **starting hypothesis.**

> The only thing that makes them correct is replacing them with what the outcomes say.

The mechanism is the `arming_signal` attribution join, run at ninety days. See
[pipeline.observability](../40-pipeline/07-observability.md).
