---
id: datamodel.reconciliation
title: Attribute reconciliation and source precedence
answers: "Four sources disagree about one field. Which wins, and can we explain why?"
source: 01 §8, 02 §4
authority: canonical
stability: seeded
depends_on: [datamodel.schema, icp.fee-model]
feeds: [pipeline.scoring, pipeline.lifecycle, firstparty.firm-dataset]
---

# Attribute reconciliation and source precedence

Places says the phone is X, the website says Y, the bar directory says Z. All three are
stored in `firm_attribute`; **`reconcile()` materializes one winner into `firm` and can
always explain why.**

`reconcile()` is the **only writer** of those columns (invariant I7).

---

## Source precedence by field — highest first

| Attribute | Precedence | Rationale |
|---|---|---|
| `canonical_name` | site > bar > places > directory | The firm's own masthead is what they call themselves; Places carries stale DBA names |
| `phone_e164` | site > places > bar | Site contact page is current. **Bar records lag by years** |
| `address` | **places** > site > bar | Places is geocoded and structured; site addresses are free text in a footer |
| `primary_practice` | llm(site) > directory category > places category | Places categories are coarse and **self-selected at listing time** |
| `attorney_count` | **llm(team page) only** | No other source is even approximately right. Absent team page → **null, not a guess** |
| `fee_model` | **regex(site) > llm(site)** | Deterministic match on explicit fee language beats inference. Disagreement → escalate |
| `contact identity` | **bar** > site > enrichment vendor | Bar records are authoritative on who actually practises at the firm |

Note that precedence **is not uniform** — Places wins on address and loses on name and
practice. Each row is a judgment about what that specific source is authoritative *for*.
That mapping is set out in [icp source map](../10-icp/01-need-model.md) terms: every source
is authoritative for something and blind to everything else.

---

## The function

```
FUNCTION reconcile(firm_id, attr):
  claims ← firm_attribute WHERE firm_id=? AND attr=?
                            AND observed_at > now() - freshness_window(attr)

  IF claims is empty     → NULL, mark attr stale
  IF one source only     → that value
  IF sources agree       → that value, confidence = max
  IF sources disagree:
      winner ← highest precedence source for this attr
      IF winner.confidence < 0.6 AND attr is tier-determining
          → emit reconcile_conflict, set NULL, queue P9
      ELSE → winner.value
```

> **Conflicts are never silently resolved for `fee_model`, `primary_practice` or
> `attorney_count`. Those three decide the tier.**

A low-confidence winner on a tier-determining field produces **NULL plus an escalation**,
not a best guess. This is the same principle as making `unknown` reachable in the extraction
contract: convert a silent misclassification into a visible escalation.

---

## The trigger chain

```
TRIGGER: any INSERT on firm_attribute
  → reconcile(that attr)
  → if value changed  → recompute fit_score
                      → re-evaluate tier
  → if tier changed   → emit lead state transition (§10)
```

This is why `icp_tier()` is `IMMUTABLE` and why the tier is *stored* rather than computed on
read: the recomputation is event-driven off attribute change, not a query-time expression.

It is also why a `DQ_*` firm is never deleted. An attribute change re-runs the tier, and a
firm disqualified today can qualify tomorrow without being re-collected.

---

## Where first-party data ranks

Internal data does **not** automatically outrank external data. Its rank depends on **where
it came from**, and that determination must be made **before the first load**, not after the
first conflict.

| Origin | Rank it | Because |
|---|---|---|
| Built by the team from real interactions | **Above Places, below the firm's own site** | Human-verified, but ages without anyone noticing |
| Purchased from a data vendor | **Directory tier — below Places** | Same staleness profile as Justia or Avvo |
| Unknown provenance | **Lowest, and flagged** | Unknown age plus unknown method is not a source, it is a hint |

This is the entire reason internal data enters through `observation` like everything else.
Loaded directly into `firm`, it would **silently win or silently lose** with no record of
which. See [firstparty.one-door](../50-first-party/02-one-door-rule.md).

---

## Freshness windows

`freshness_window(attr)` is per-attribute and is why internal data cannot look permanently
current: through the normal path it **inherits the 90-day rules and gets re-verified**.

A claim older than its window is not used. If no claim survives the window, the attribute is
NULL and marked stale — which is what feeds the `STALE` lifecycle state and the
`>20% of pool past 90d freshness` alert.
