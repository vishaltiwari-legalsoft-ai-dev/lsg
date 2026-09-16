---
id: firstparty.firm-dataset
title: The firm dataset — accelerator, not universe
answers: "How much discovery work does the internal firm dataset actually save?"
source: 02 §4
authority: canonical
stability: unverified
depends_on: [firstparty.one-door, icp.fee-model, datamodel.reconciliation]
feeds: [execution.build-order, execution.open-questions]
---

# The firm dataset — accelerator, not universe

**The strongest of the three assets and the one most likely to be over-trusted.**

It can carry a firm most of the way through **discovery**, but it cannot carry it through
**qualification**, because the field the entire ICP turns on is not in any commercial dataset.

---

## What it can and cannot replace

| Attribute | Dataset | Still required |
|---|---|---|
| Firm name, address, phone | Usable | Reconciled against site and Places by precedence |
| **Domain** | **Usable — the key field.** The strongest match key and the entry point to the crawl | — |
| Firm size | Usable | **Cross-check against team page.** Vendor size fields are often **headcount, not attorney count** — a material difference here |
| Practice area | Coarse | Site classification still runs. **Vendor taxonomies do not distinguish PI from general litigation** |
| **Fee model** | **Absent** | **Site crawl, always. No shortcut exists** |
| Staff ratio, languages, case system | Absent | Site crawl |
| Named decision-maker | Sometimes | Verify against bar records and the team page. **Commercial data on small firms goes stale fast** |

**Domain is the field that makes this asset worth having.** It is rung 1 of every resolution
ladder in the system and the entry point to P1. A dataset that supplies domains for firms we
would otherwise have had to discover through D1's grid harvest is doing the most expensive
part of discovery for free.

**Fee model is the field that stops it being a universe.** It cannot be bought. See
[icp.fee-model](../10-icp/03-fee-model.md).

---

## First task: coverage analysis

**Before deciding how much discovery work this saves, measure the overlap.** This is one
query and it changes the plan.

```sql
-- run after loading the dataset as observations and resolving

in dataset only     → firms the external harvest would miss
in Places only      → the dataset is not complete
in both             → the overlap
dataset ∩ ICP tiers → how much of it is even relevant
```

### What each outcome means

| Outcome | Meaning |
|---|---|
| **High overlap, low ICP share** | Dataset is broad but off-target. **Use it for attributes, keep the full harvest** |
| **Low overlap, high ICP share** | **Genuinely additive.** Harvest still needed for coverage, but this is a strong seed |
| **High overlap, high ICP share** | **Discovery can be narrowed to gap-fill. The biggest possible saving** |

This analysis runs **as part of the I1 load and reports itself** — it is not a separate
manual task that might be skipped.

---

## Why this is item 4 in the build order and not item 6

> Step 4 may **materially shrink the discovery plane** — which is the largest and most
> expensive stage in the whole system — so it is worth doing early enough to **influence that
> scope rather than after it has been built to full size.**

The coverage number is an input to the D-plane build decision, not a retrospective on it.

---

## The risk: over-trusting it

> Discovery is narrowed on the assumption the dataset is complete, and **a segment quietly
> never gets collected.**

**Guard: coverage analysis before any scope reduction. Numbers, not assumption.**

The failure is silent in the usual way — a narrowed harvest produces fewer firms, which is
exactly what a successful narrowing also produces. Only the overlap query distinguishes them.

---

## The second risk: vendor size fields

> Total headcount taken as attorney count. Firms land in the wrong band and **the 26–50
> penalty misfires.**

A 12-attorney firm with 20 support staff is a **core tier-1A prospect**. Read as "32
headcount" it lands in the deprioritised band and takes a −10.

**Guard: cross-check against team page on a sample before trusting the field.** See
[icp.size](../10-icp/04-size-and-need-proxies.md).

---

## Precedence

Rank depends on origin, decided **before the first load**:

- Built by the team from real interactions → above Places, below the firm's own site
- Purchased from a vendor → **directory tier, below Places**
- Unknown provenance → **lowest, and flagged**

See [firstparty.one-door](02-one-door-rule.md).
