---
id: icp.decision-makers
title: Decision-makers and what a collected lead contains
answers: "Who at the firm do we need, and what is the bar for a shippable record?"
source: 00 §10, 00 §12
authority: canonical
stability: decided
depends_on: [icp.need-model, icp.size]
feeds: [pipeline.component-register, datamodel.schema, pipeline.lifecycle]
---

# Decision-makers and what a collected lead contains

## Three people, one of whom can quietly kill it

In a firm of this size there is **no committee**. There is one person who signs, one who
feels the pain, and one who can quietly kill it.

| Role | Who | Why they matter | Findable via |
|---|---|---|---|
| **Signs** | Owner or managing partner — usually the name on the door | Decides alone, in days. Motivated by taking home more and reclaiming time, **not by cost-per-hour tables** | Bar directory + team page |
| **Champions** | Firm administrator, office manager, director of operations — appears above roughly eight staff | **The single best first contact where one exists.** They are the person who posted the job nobody applied to. They forward a relevant email the same day | Team page — *not* in bar records, they are not attorneys |
| **Blocks** | Senior in-house paralegal, or the partner's own risk instinct | Fears replacement, or fears being the partner who put client information somewhere it should not be. **Often reads the owner's inbox** | Team page |

### Two things this dictates about collection

**Capture both people, not one.** Owner *and* administrator. A record with only a generic
inbox is not a lead, and a record with only the owner misses the person most likely to act.

**Frame as capacity, never replacement — from the very first line.** The blocker is
frequently the person who opens the mail. A message that reads as "replace your staff"
dies in that inbox without ever reaching the owner.

---

## The bar directory is the differentiated move

Generic B2B contact databases are thin on small law firms — they cover companies with
LinkedIn presence and marketing departments, which most 4-attorney firms are not.

Bar directories are **public records that name every practising attorney and tie them to a
firm**. That is how the decision-maker gets found for firms no commercial database covers
properly, and almost nobody doing outbound into this market bothers with it.

This is why `contact.bar_number` exists as a column — it is the join key generic B2B data
does not have — and why R2 (bar record joiner) runs *before* R1 (paid contact enricher) in
the resolver order. Free, authoritative names first; paid enrichment for the remainder.

---

## What a collected lead contains

The bar for a usable record. **Anything missing means the record is held back, not shipped
with a gap** — and the reason is recorded so it can be filled later.

```
FIRM      name · website · phone · city · state
          practice_areas · primary_practice
          fee_model              ← the tier axis. never guessed.
          attorney_count · staff_ratio
          review_count           ← case-volume proxy
          paid_ads_active        ← volume + cash signal
          case_system            ← names their tooling in the first line
          languages · spanish_intake
          tier · opening_role

PEOPLE    owner          name · title · email · direct line
          administrator  name · title · email · direct line
          both where they exist. a generic inbox is not a contact.

SIGNAL    kind · first_seen · still_open
          evidence  ← the actual sentence: the job title, the review
                      quote, the tort name. this is what the first line
                      is built from. without it the outreach is generic
                      and the whole targeting effort is wasted.

STATUS    grade   A = verified email, B = phone-first
          collected_at · last_verified
          suppressed · reason
```

**`evidence` is the point of the entire system.** Every extraction carries the span it was
read from; every signal carries the quote. Without it, all this targeting produces generic
outreach, which is what the targeting existed to avoid.

---

## Grade B is a product, not a reject pile

A meaningful share of small firms will yield a named partner, a working phone and a live
signal — but **no verifiable personal email address**.

Those records are not failures. They are a **phone-and-research list, worked by a different
motion**.

- **Deleting them** throws away a large slice of the collection effort.
- **Emailing them anyway**, on a guessed address, damages the ability to email anyone.

Enforced structurally: invariant I3, `CHECK (grade='A' OR channel <> 'email')`. Grade B
leads may never be emailed — by constraint, not by convention. See
[datamodel.invariants](../30-data-model/05-invariants.md).
