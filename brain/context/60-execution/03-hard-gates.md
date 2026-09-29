---
id: execution.gates
title: Every hard gate in one place
answers: "Where does the pipeline stop, and what must be true to pass?"
source: 01 §5, 01 §11, 00 §11, 02 §9, 01 §12
authority: canonical
stability: decided
depends_on: [datamodel.identity, pipeline.orchestration, execution.collection-phases]
feeds: []
---

# Every hard gate in one place

A gate is not a report. **If it fails, the flow stops.**

The reason is uniform across all of them: **everything downstream is spent per-firm**, so an
upstream error is multiplied by every subsequent stage.

---

## G1 — Identity resolution verification · **the one that must not be advisory**

**Where:** after `resolve_identity`, before `profile_firms`.

```sql
SELECT domain, count(*) FROM firm
 WHERE domain IS NOT NULL GROUP BY 1 HAVING count(*) > 1;

SELECT phone_e164, count(*) FROM firm
 WHERE phone_e164 IS NOT NULL GROUP BY 1 HAVING count(*) > 1;
```

**Pass:** both return ~zero rows.
**And:** collapse ratio (raw ÷ resolved) between **2.0× and 3.3×**.

| Failure | Diagnosis |
|---|---|
| Thousands of rows returned | R1/R2 never fired. Usually **phone stored formatted rather than E.164**, or **`www.`/trailing slash not stripped before hashing** |
| Collapse ratio > 3.3× | **Over-merging** — check R3/R4 thresholds |
| Collapse ratio < 2.0× | **Under-merging** — check the **normalizers**, not the thresholds |

> A broken dedupe presents as success. More rows, more coverage, better-looking counts. It
> surfaces ten weeks later when one managing partner has received four emails from four of
> your sending domains and reported all of them.
>
> **This is the only cheap moment to catch it.**

---

## G2 — Probe hand-check

**Where:** end of collection phase 0, before phase 1 widens.

**Pass:** a hand-checked sample of **50 records is accurate on every attribute.**

Not a sampled metric. Fifty records, every attribute, by hand. This is where the estimated
yields in these documents get replaced by measured ones.

---

## G3 — Tier distribution sanity

**Where:** after `reconcile_and_class`, before `resolve_contacts`.

**Pass:** the tier distribution is plausible and has not moved **> 15% week over week** for
any tier.

A shift means either the classifier drifted or the harvest changed shape. **Both are bugs.**

This gate protects the most expensive stage: R1 is a paid enricher, and it runs only on firms
that passed the tier gate. A drifted classifier spends enrichment budget on the wrong firms.

---

## G4 — Nothing outbound before I3

**Where:** before the first outbound email is ever sent.

**Pass:** the portal → suppression path exists and is running hourly.

> A cold sequence reaching a firm that already posted a role on our own portal is the **worst
> single failure this system can produce.** It is visible to the customer, it contradicts the
> product in writing, to the person paying, and it costs an account.

**Ahead of scoring, ahead of signals, ahead of everything.**

---

## G5 — Bench inventory before arming

**Where:** every `QUALIFIED_* → ARMED` transition. Invariant **I4**.

**Pass:** the arming query **joins** `bench_inventory` and finds a row for the wedge SKU.

No join, no row. Enforced as a join rather than a check so that absence of inventory produces
*no lead*, which cannot be overridden by a flag.

**A stale bench is treated as empty.** `as_of` falling behind is an alert.

---

## G6 — Suppression at send time

**Where:** every `outreach_touch` insert. Invariant **I2**.

**Pass:** the firm's domain is not in `suppression`.

**Re-checked at send, not at arm.** A lead can sit armed for hours; a suppression can land in
between. The `BEFORE INSERT` trigger is the enforcement — the sequencer is not trusted.

---

## G7 — Coverage analysis before narrowing discovery

**Where:** before any reduction in discovery scope based on the internal firm dataset.

**Pass:** the overlap query has been run and the numbers support the narrowing.

> Discovery is narrowed on the assumption the dataset is complete, and **a segment quietly
> never gets collected.**
>
> **Numbers, not assumption.**

---

## G8 — Agency filter before the second job source

**Where:** before JA2 is switched on.

**Pass:** JA6's agency filter is running against JA1 output.

> Even with one source, agency noise must be filtered before signals are written. **Build the
> filter before the second source multiplies the noise.**

---

## G9 — Lane 1 measured before lane 2 is bought

**Where:** before contracting a licensed job-data provider.

**Pass:** lane 1 is running, and there is a **measured coverage gap** to size the purchase
against.

> The instinct is to start with a licensed provider because it arrives as clean JSON. But
> until lane 1 is running there is no way to know what it adds — and given that small firms
> largely avoid the paid boards, the honest expectation is that **its incremental coverage of
> this ICP is smaller than it looks.**

---

## G10 — Terms of use before a source becomes load-bearing

**Where:** before any source the pipeline depends on.

**Pass:** the site's **terms of use** have been read, not only its robots.txt.

> The two are separate documents and **the terms are the binding one.** A permissive
> robots.txt is not a licence.

---

## The two-sweep grace, which is a gate in reverse

Closure detection requires a posting to be absent from **every** source across **two
consecutive sweeps**, and distinguishes *fetched successfully and absent* from *fetch failed*.

**One failed fetch must never close a live signal.** Without that distinction, one bad night
silently closes thousands of them.
