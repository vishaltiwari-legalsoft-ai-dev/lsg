---
id: firstparty.job-history
title: Internal job data — a seed, not a signal
answers: "Why is our own historical job data forbidden from setting intent, and what is it good for instead?"
source: 02 §3
authority: canonical
stability: unverified
depends_on: [firstparty.one-door, datamodel.identity, signals.catalog]
feeds: [pipeline.scoring, execution.open-questions]
---

# Internal job data — a seed, not a signal

The file lists companies that posted roles. **No post link, no company URL.**

> A job posting with no link **cannot be verified.** We cannot tell whether the role is still
> open, and **"still open after three weeks" is the entire reason that signal is the strongest
> one on the board.**
>
> Treating unverifiable history as live intent would send outbound at firms that filled the
> role months ago.

So it does **not** enter as a signal. It does two other things, **and the second is more
valuable than the first.**

---

## Use one — seed the crawl queue

Every company name in the file is a candidate that may or may not already be in the universe.

- **Resolve it.** If it is new → enters discovery.
- If it resolves to a firm we already have → adds nothing to the universe, **but everything
  to use two.**

## Use two — structural hiring behaviour

**This is the durable value.**

A firm that has posted support roles in the past has **proved it has that work and has had
budget for it.** That is a **fit** attribute, not an intent one, and **it survives
indefinitely.**

```sql
-- new fit attributes derived from historical job data
has_hired_support_roles     bool      -- ever posted a support role
support_roles_posted        text[]    -- which ones: paralegal, intake…
last_known_hiring_attempt   date
repeat_role_count           int       -- same role posted N times

-- FIT contribution
has_hired_support_roles     +5
repeat_role_count >= 2      +8        ← strongest of the four
```

### Why `repeat_role_count` is worth the most

> A firm that has posted "paralegal" **three times in two years** has **churn in that seat.**
> The need is not occasional, it is **chronic** — and chronic need in a seat we can fill
> **permanently** is a better prospect than a firm hiring for the first time.
>
> This pattern is **only visible with historical data.** It is the single best reason to keep
> this file.

Note the shape of the argument: the asset is most valuable at exactly the thing it looked
least like. As "intent" it was wrong and dangerous. As a multi-year churn record it is
something no competitor working from live postings can compute at all.

---

## What it must NOT do

```
never sets intent_score   -- unverifiable
never arms a lead         -- arming needs a LIVE signal
never appears in outreach copy
   -- "you posted a role in March" is a liability, not a first line
```

The third rule is the one most likely to be broken by someone writing sequences, and it is
the one with the most visible consequence: opening with a role the firm filled eight months
ago **reads as careless and kills the reply.**

---

## Whether it can be matched at all

Everything above depends on **resolving a company name to a firm entity.** Without a URL that
is the **weakest match rule in the system.**

**Run this triage on the file before planning around it** — the answer determines whether the
asset is usable, partly usable, or a trap.

| Fields present | Confidence | Handling |
|---|---|---|
| Name + any URL or email domain | **Decisive** | Auto-merge on rule R1. **Fully usable** |
| Name + phone | **Decisive** | Auto-merge on rule R2 |
| Name + full street address | Strong | Rule R3 — address hash plus name similarity. **Usable** |
| Name + city/state only | Probabilistic | **Rule R4 territory. Never auto-merge.** Route to the review queue, or accept only where **exactly one** candidate exists in that city above the similarity threshold |
| **Name only** | **Unusable** | **Do not attempt.** "Smith Law" resolves to dozens of firms nationally, and **a wrong merge writes a false hiring history onto a real firm permanently** |

This is the same ladder as [datamodel.identity](../30-data-model/03-identity-resolution.md)
and the [posting resolution ladder](../20-signals/03-agency-filter-and-resolution.md). Three
contexts, one rule: **a decisive key or nothing.**

---

## Bad internal data is worse than none

> A mismatched merge **does not fail loudly.** It writes a plausible attribute onto the wrong
> firm, which then **scores wrongly, routes wrongly, and gets contacted with a premise that is
> not true — forever, because nothing downstream will ever question it.**

**Tag every attribute from this source and keep it withdrawable.**

I2 rejects at name-only confidence rather than guessing. That is not conservatism, it is the
only recoverable option: a false split costs one duplicate; a false merge is invisible and
permanent.

---

## Why this is last in the build order

Its value is a **fit-score refinement rather than a gate**, and it depends on the triage
verdict above. Do the triage early — it is one inspection and it is cheap — but build the
loader last.
