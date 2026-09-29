---
id: pipeline.architecture
title: Architecture — five planes, one store
answers: "What are the planes, what terminates, and what is the invariant that keeps it simple?"
source: 01 §1, 02 §1, 03 §3
authority: canonical
stability: decided
depends_on: [orientation.project-brief]
feeds: [pipeline.component-register, pipeline.orchestration]
---

# Architecture — five planes, one store

Planes write to one store. **Nothing reads across planes.**

| Plane | Purpose | Runs | Terminates? |
|---|---|---|---|
| **D** — Discovery | Creates firm candidates | Once per firm | Yes |
| **P** — Profile | Fills firm attributes | Once per firm | Yes |
| **W** — Watchers | Emit signals | Continuously | **Never** |
| **R** — Resolvers | People and verification | Once per qualified firm | Yes |
| **I** — First-party | Internal assets | Mixed — I1/I2 one-shot, I3/I4 hourly | Mixed |
| **JA** — Job acquisition | Sub-plane replacing W1/W2 | Nightly | **Never** |

---

## The distinction that shapes everything

**Discovery and profiling run once per firm and terminate. The signal plane never
terminates.**

Conflating them is how these systems end up **re-crawling the universe nightly**.

This is [the universe / in-market split](../10-icp/01-need-model.md) made structural. Need
conditions 1–3 are stable properties → D and P, breadth, terminate. Need condition 4 is a
transient state → W and JA, freshness, forever.

---

## The invariant that keeps this simple

> **No component reads another component's output directly. Everything is mediated by the
> store.**

A scraper that needs a firm's domain reads `firm.domain`; it **never calls the discovery
scraper**.

This buys three things:

1. **Independently re-runnable** — any component can be replayed from any point
2. **Independently testable** against a fixture, with no other component running
3. **Safe to backfill** — a component can be re-run over history without coordination

It is what makes the idempotency scheme in
[pipeline.orchestration](06-orchestration.md) possible at all.

---

## Scoring is a full scan, not a stream

Nightly, over the whole store.

**A scoring change is therefore a re-run, not a backfill.** Change the weights, run the
flow, done — there is no event history to replay and no partial state to reconcile.

Given that [every weight in the system is a seeded hypothesis to be replaced by
measurement](04-scoring-engine.md), this is not an incidental choice. Re-weighting is
expected to happen repeatedly, and it has to be cheap.

---

## The only feedback edge

Outreach affects targeting through exactly one path: **`arming_signal` → outcome
attribution → re-weighting**.

Every `WON` and `LOST` carries the signal that armed it. After ninety days, the join
`outcome × signal kind × tier` re-weights the scoring table. Nothing else in the system
lets outreach change targeting, and that narrowness is deliberate — it keeps the loop
measurable.

---

## The one component that bypasses a plane

`bench_inventory` (I4) writes **directly to its table**, without passing through
`observation`. It is not firm data, it has no identity to resolve, and it is a live mirror of
internal state with its own freshness requirement.

It is the **only** feed in the system that does this. See
[firstparty.one-door](../50-first-party/02-one-door-rule.md).

---

## Where the planes meet

Two places only:

**The arming gate** — the single point where supply and demand meet. Intent (from W/JA)
crosses a threshold that is itself a function of bench inventory (from I4). See
[firstparty.portal](../50-first-party/03-portal-bench-and-supply.md).

**`reconcile()`** — the single point where claims from D, P, R and I become one resolved
value on `firm`. See [datamodel.reconciliation](../30-data-model/04-attribute-reconciliation.md).

Everything else is a plane writing rows that some later plane reads out of the store.
