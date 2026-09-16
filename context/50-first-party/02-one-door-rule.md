---
id: firstparty.one-door
title: The one-door rule
answers: "Why does internal data go through the scraping pipeline instead of straight into firm?"
source: 02 §2
authority: canonical
stability: decided
depends_on: [datamodel.schema, datamodel.reconciliation]
feeds: [firstparty.firm-dataset, firstparty.job-history, firstparty.portal]
---

# The one-door rule

> **Internal data feels trustworthy, which makes it tempting to load it straight into `firm`
> and skip the pipeline. Do not.**

Every record enters through `observation` **with a source tag, exactly like a scraped one.**

---

## What breaks without it

| Reason | What breaks |
|---|---|
| **Provenance** | When a firm is scored into the wrong tier six weeks from now, there is no way to tell whether the cause was bad internal data, a bad match, or a bad extraction. **Every debugging session becomes archaeology** |
| **Reconciliation** | Internal data **will** disagree with the firm's own website about size, name and phone. Loaded directly, it **silently wins or silently loses**. Through `firm_attribute`, the precedence rules decide — and the decision is inspectable |
| **Reversibility** | If a bulk load turns out to be mismatched, an observation-sourced load **can be withdrawn by source tag**. A direct write cannot be separated from the rest |
| **Freshness** | Internal data has an age, often an unknown one. Through the normal path it **inherits the 90-day rules and gets re-verified.** Loaded directly it looks **permanently current** |

Freshness is the subtlest of the four. A direct write has no `observed_at` competing against
anything, so it never ages out — an eighteen-month-old phone number sits on the firm record
looking exactly like one verified yesterday.

Reversibility is the one that matters most in practice, because the specific risk with
internal data is a **mismatched bulk merge**, and the only cheap remedy is withdrawing it by
source tag.

---

## The one exception

**`bench_inventory` does not go through `observation`.**

It is:
- **not firm data** — no identity to resolve
- **a live mirror of internal state** — its own sync, its own freshness requirement
- **the only feed in the system that writes to a table directly**

The exception is exactly one feed wide, and it is justified by the absence of the thing
`observation` exists to provide: there is no other source claiming a different number of
available demand writers, so there is nothing to reconcile.

Its freshness requirement is handled separately and strictly: **hourly sync, an alert when
`as_of` falls behind, and a stale bench is treated as empty.** See
[firstparty.portal](03-portal-bench-and-supply.md).

---

## Where internal data ranks

Going through the door does **not** mean going in at the top. Rank depends on origin, and
**that determination has to be made before the first load rather than after the first
conflict.**

| Origin | Rank it | Because |
|---|---|---|
| Built by the team from real interactions | Above Places, below the firm's own site | Human-verified, but **ages without anyone noticing** |
| Purchased from a data vendor | **Directory tier — below Places** | Same staleness profile as Justia or Avvo |
| Unknown provenance | **Lowest, and flagged** | **Unknown age plus unknown method is not a source, it is a hint** |

See [datamodel.reconciliation](../30-data-model/04-attribute-reconciliation.md).

---

## Bad internal data is worse than none

> A mismatched merge **does not fail loudly**. It writes a plausible attribute onto the wrong
> firm, which then scores wrongly, routes wrongly, and gets contacted with a premise that is
> not true — **forever, because nothing downstream will ever question it.**

**Tag every attribute from an internal source and keep it withdrawable.** That single
discipline is what converts an unrecoverable contamination into a reversible load.
