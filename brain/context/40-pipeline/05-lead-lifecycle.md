---
id: pipeline.lifecycle
title: The lead lifecycle — 16 states
answers: "What is the complete state machine, and what guards each transition?"
source: 01 §10, 00 §13
authority: canonical
stability: decided
depends_on: [datamodel.schema, datamodel.invariants, pipeline.scoring]
feeds: [pipeline.orchestration, pipeline.observability]
---

# The lead lifecycle — 16 states

> A firm is built **once**. A lead is armed, worked, and returned to the pool — **repeatedly,
> for years.**
>
> The loop is the system: most firms are not in market today, and the pipeline's job is to be
> holding a verified, current record **on the day they become in market**.

The **spine** runs once per firm. The **cycle** runs indefinitely.

---

## Transition table

Every transition names its **trigger**, its **guard**, and what it **writes**.

> A transition with no guard is a bug waiting to send mail to a suppressed domain.

**Guards are enforced in the DB, not the sequencer.**

| From | To | Trigger | Guard | Writes |
|---|---|---|---|---|
| — | `DISCOVERED` | Identity resolution assigns a firm id | Component has ≥1 observation | `firm` |
| `DISCOVERED` | `PROFILING` | P1 enqueued | `domain IS NOT NULL` | `crawl_job` |
| `DISCOVERED` | `NO_WEB` | No resolvable site | — | Held; D3 gap-fill may revive |
| `PROFILING` | `PROFILED` | P4–P8 complete | All required attrs present **or explicitly null** | `firm_attribute` |
| `PROFILED` | `CLASSIFIED` | `reconcile()` then `icp_tier()` | Tier ≠ `UNCLASSIFIED` | `firm.tier`, `fit_score` |
| `PROFILED` | `ESCALATED` | Tier is `UNCLASSIFIED` or confidence low | — | P9 queue |
| `ESCALATED` | `CLASSIFIED` | P9 returns | Tier resolved | `firm_attribute` |
| `CLASSIFIED` | `DISQUALIFIED` | Tier is `DQ_*` | — | `lead.close_reason`<br>**Revisitable — an attribute change re-runs the tier** |
| `CLASSIFIED` | `CONTACT_PENDING` | Tier passes | **Domain not suppressed** | R1/R2 queue |
| `CONTACT_PENDING` | `RESOLVED` | R1/R2/R3 return a named person | `role IN (owner, admin)` | `contact` |
| `RESOLVED` | `QUALIFIED_A` | R4 verifies | `status = 'valid'` | lead grade A |
| `RESOLVED` | `QUALIFIED_B` | R4 fails, phone present | `status IN (catch_all, risky)` | lead grade B<br>**Phone and LinkedIn motion only. Never emailed** |
| `QUALIFIED_*` | `ARMED` | Nightly scorer crosses band | `intent ≥ threshold` **and** not in cooldown **and** `bench_inventory` has the wedge SKU | `lead.arming_signal` |
| `ARMED` | `ENGAGED` | Sequence starts | **Suppression re-checked at send time, not arm time** | `outreach_touch` |
| `ENGAGED` | `RESPONDED` | Any inbound reply | — | **Automation halts immediately** |
| `ENGAGED` | `QUALIFIED_*` | Sequence exhausted, no reply | — | `cooldown_until = +90d`; **intent reset, contact retained** |
| `RESPONDED` | `HANDOFF` | Positive reply | — | Owner assigned |
| `RESPONDED` | `QUALIFIED_*` | "not now" | — | **Cooldown from the date the prospect named** |
| `RESPONDED` | `SUPPRESSED` | Opt-out | — | `suppression` at **domain scope** |
| `HANDOFF` | `WON` / `LOST` | Sales outcome | — | **Attribution back to `arming_signal`** |
| `LOST` | `QUALIFIED_*` | Cooldown elapses | Loss reason not permanent | **Re-pooled** |
| `QUALIFIED_*` | `STALE` | W7 detects content-hash change or 90d expiry | — | Re-queue P2 → `PROFILING` |
| **any** | `SUPPRESSED` | Opt-out, hard bounce, or customer-list load | — | **Sticky. Only a human clears it** |

---

## The three that matter most

**`ENGAGED → QUALIFIED_*` (the dashed return).** A lead that does not convert is **not lost,
it is re-pooled** — with its verified contact intact, waiting for the next signal.

Cooldown +90d, **intent reset, contact retained**. The expensive part of the record — the
verified person — survives. This is the mechanism the whole maintenance loop exists to serve.

**`ARMED → ENGAGED` suppression re-check.** A lead can sit armed for hours. A suppression can
land in between. Checking at arm time and trusting it at send time is exactly the bug
invariant I2 exists to make impossible.

**`RESPONDED` halts automation immediately.** Any inbound reply, regardless of sentiment. A
sequence that keeps sending after a human replied is the most visible failure a prospect can
see.

---

## `QUALIFIED_*` is the resting state

Note how many arrows return to it: sequence exhausted, "not now", cooldown elapsed after a
loss, re-profiled after `STALE`.

That is the point. **Most firms are not in market today.** The pool of `QUALIFIED_*` leads
holding verified contacts is the asset; arming is just the moment one of them lights up.

---

## Keeping the pool alive

A collected list is a **depreciating asset**. People leave firms, firms merge and rebrand,
sites are rebuilt, roles get filled. Collection is not a project that finishes — **the
maintenance loop is the product.**

| Loop | Cadence | What it does |
|---|---|---|
| **Signal sweep** | **Nightly** | Check every qualified firm for open roles. The loop that turns a static list into a pipeline, and **the one where lateness costs the most** — a role found on day two converts far better than the same role found on day twenty |
| Review sweep | Weekly | Tier 1A and 1B only. New reviews matched against the intake-failure phrase set |
| Advertising & tort sweep | Monthly | Tier 1A. Volume spikes and new mass tort campaigns |
| **Freshness sweep** | Rolling, whole list every 90 days | Re-check the site. If it changed, re-read the attributes. If a contact no longer appears on the team page, re-resolve the person |
| **Re-pooling** | Continuous | A firm that did not respond is not spent. It returns to the pool with its verified contact intact and waits for the next signal |

---

## What decides whether any of this was right

> **Every closed deal should be traceable to the signal that surfaced it.**

After a quarter, that one join — **outcome by signal type, and by tier** — is what tells you
which signals to invest in and whether the fee-model axis is real.

`lead.arming_signal` is the column that makes it possible. `lead_state_event` is the audit
log that makes it checkable. Nothing else needs to be.
