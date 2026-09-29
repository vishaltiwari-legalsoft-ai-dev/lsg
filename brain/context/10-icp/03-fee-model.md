---
id: icp.fee-model
title: Fee model — the primary axis
answers: "Why does how a firm bills decide whether it will buy? How do we detect it?"
source: 00 §3, 01 §2, 01 §6 (P6), 01 §7
authority: canonical
stability: decided
depends_on: [icp.need-model]
feeds: [icp.tiers, pipeline.scoring, pipeline.extraction, datamodel.reconciliation]
---

# Fee model — the primary axis

Serves **need condition 3**. This is the strongest single filter in the profile, and the
axis most targeting misses.

Two firms can look identical — same practice, same size, same city — and have **opposite
economics** on this purchase, because of how they bill.

---

## The arithmetic

**Hourly firm.** A paralegal is *inventory*. The firm pays them a wage and resells their
time to the client at a multiple. That person is a **profit centre**. Replacing their
hours with cheaper hours that cannot be resold at the same rate **removes revenue**.

**Contingency or flat-fee firm.** The same paralegal is *pure overhead*. Nobody is billed
for their time. The fee is fixed at the outcome or agreed up front, so every hour of
support labour is subtracted from the firm's own margin. Move that hour to a cheaper
resource and **the difference goes straight to the partners**.

Same product, same role, opposite arithmetic.

---

## The four models

| Fee model | Support staff is | What can be sold | Detect it by |
|---|---|---|---|
| **Contingency**<br>PI, mass tort, some employment | Overhead carried for months against a fee that arrives at settlement | **Everything.** Lead with roles that *accelerate the fee* — demand writing, lien negotiation — not roles that merely reduce cost | "no fee unless we win", "no recovery no fee", "contingency fee" |
| **Fee-shifting**<br>employment, lemon law, consumer, some civil rights | Overhead. The losing party pays fees, so the firm's own labour is still an unbilled input | **Everything.** Economically identical to contingency and *far less contested by competitors* | "fees paid by the defendant / manufacturer / employer" |
| **Flat fee**<br>immigration, bankruptcy, criminal, estate | A direct subtraction from a fee already fixed. Every extra hour on a matter reduces the margin on *that specific matter* | **Everything.** The margin effect is immediate and per-case rather than deferred, which makes the case easy to make | "flat fee", "flat rate", a published price per service |
| **Hourly**<br>business, real estate, tax, IP, defence-side | Billable inventory resold at a markup | **Only the unbillable** — bookkeeping, marketing, intake, document collection. *Never* lead with a paralegal: that asks the firm to convert revenue into cost | "hourly rate", "billed hourly", "retainer" |

---

## Keep hourly firms in the database

They are the weakest fit, **not a zero**.

Excluding them at collection time makes this whole axis **impossible to verify** — they
are never contacted, so evidence that contradicts it can never arrive. Collect them,
classify them as `4_NONBILLABLE`, and put a deliberate `holdout` slice into outreach on a
non-billable role so the assumption gets tested against real outcomes rather than repeated.

Phase 4 of [collection](../60-execution/02-collection-phases.md) is the only phase that
can disprove the fee-model axis. That is its purpose.

---

## Detection — P6 regex, precedence-ordered, first match wins

```
contingency   \bno\s+(?:fee|win|recovery)\b.{0,24}\b(?:unless|until|if)\b
            | \bcontingen(?:cy|t)[\s-]?fee\b
            | \byou\s+(?:pay|owe)\s+nothing\s+unless\b

fee_shifting  \bfees?\b.{0,20}\bpaid\s+by\s+(?:the\s+)?(?:defendant|employer|manufacturer)\b
            | \bfee[\s-]shifting\b
            | \b(?:they|the\s+other\s+side)\s+pay(?:s)?\s+(?:my|our|your)\s+fees\b

flat          \bflat[\s-](?:fee|rate)\b
            | \$[\d,]+\s+(?:flat|total|all[\s-]inclusive)\b

hourly        \bhourly\s+rate\b | \bbilled\s+(?:hourly|by\s+the\s+hour)\b
            | \bper\s+hour\b
```

Target file: `config/fee_patterns.yml`, precedence-ordered. Not yet written.

---

## Ambiguity is resolved, never guessed

A firm matching **both** contingency and hourly is `mixed`, not `contingency`.

1. Resolve by **page real estate** — whichever fee language appears on the practice pages
   with the most content wins.
2. Still tied → `mixed` → tier `UNCLASSIFIED` → P9 escalation.

**Never guess this field.**

`fee_model` precedence in reconciliation is `regex(site) > llm(site)` — a deterministic
match on explicit fee language beats inference. Disagreement escalates rather than
resolving silently, because this field decides the tier. See
[datamodel.reconciliation](../30-data-model/04-attribute-reconciliation.md).

## Why `unknown` must be reachable

A model forced to choose between contingency and hourly **will** choose — confidently, and
sometimes wrongly. Fee model is the primary tier axis, so a confident wrong value silently
routes a firm into the wrong segment with the wrong wedge SKU **and no error anywhere**.

Making `unknown` a legitimate answer converts a silent misclassification into an escalation.
See [pipeline.extraction](../40-pipeline/03-extraction-contract.md).

## No commercial dataset carries this field

It cannot be bought. Site crawl, always, no shortcut. This is the single reason the firm
dataset in [firstparty.firm-dataset](../50-first-party/04-firm-dataset.md) is an
*accelerator* and not a universe.
