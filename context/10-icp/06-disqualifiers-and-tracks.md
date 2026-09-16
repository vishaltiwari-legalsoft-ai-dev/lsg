---
id: icp.disqualifiers
title: Disqualifiers, suppression and tracks
answers: "Who do we exclude, who do we merely route differently, and what is the difference?"
source: 00 §6, 01 §2, 01 §3
authority: canonical
stability: decided
depends_on: [icp.need-model, icp.size, icp.practice-areas]
feeds: [pipeline.lifecycle, datamodel.schema, firstparty.portal]
---

# Disqualifiers, suppression and tracks

Three different mechanisms that are easy to confuse. Confusing them is how the strongest
population in the market gets silenced by accident.

| Mechanism | Effect | Reversible? |
|---|---|---|
| **Disqualifier** (`DQ_*` tier) | Not contacted. Still collected and stored | **Yes** — an attribute change re-runs `icp_tier()` |
| **Suppression** | Hard stop on sending, checked before every send | **No** — sticky, only a human clears it |
| **Track** | Which *motion* a firm belongs to | Yes — it is a routing decision |

---

## Disqualifiers

Each fails one of the four need conditions. **Collect them into the database anyway** — a
disqualification you can explain is reusable; a firm you never collected is invisible
forever.

| Disqualifier | Code | Fails | Detectable from |
|---|---|---|---|
| 50+ attorneys | `DQ_SIZE` | Condition 4 — they can hire, and they buy through procurement | Team page count |
| In-house recruiter on staff | `DQ_SELFSERVE` | Condition 4 — hiring is explicitly not blocked | Team page, careers page |
| In-house legal dept, government, non-profit legal aid | `DQ_ENTITY` | Not a private firm — different budget mechanics entirely | Entity classification |
| Appellate-only, patent prosecution, complex commercial | `DQ_NOVOLUME` | Condition 1 — little procedural volume to delegate | Practice classification |
| Non-US | `DQ_GEO` | Out of market | Address |
| Directory listing with no real firm behind it | `DQ_ENTITY` (`directory_stub`) | Not an entity | No independent website, no bar record match |
| Brand-new solo, no advertising, no case volume | `DQ_NOBUDGET` | Condition 1 — no volume yet | Bar admission date, zero reviews, no ads |

`DQ_NOVOLUME` was **added in the current revision**. Previously these firms fell through
to tier 4 because 01 had no clause matching 00's exclusion. See
[decisions.log](../70-decisions/01-decision-log.md).

A `DQ_*` tier is **revisitable**. `CLASSIFIED → DISQUALIFIED` writes a close reason, and
an attribute change re-runs the tier. Being disqualified today is not permanent.

---

## Competitor customers are NOT a disqualifier

> A firm already buying from a rival is **category-educated with an approved budget — the
> strongest population there is.**

01 originally listed `competitor` as a suppression reason, which silenced them. **Removed.**
They go on a slower `displacement` track, not into silence. This was the third resolved
contradiction. See [decisions.log](../70-decisions/01-decision-log.md).

They need a displacement approach and a longer cycle, not the cold sequence.

---

## Suppression — the only true silence

```sql
CREATE TABLE suppression (
  scope     text NOT NULL,   -- domain | email | firm_id
  value     text NOT NULL,
  reason    text NOT NULL,   -- customer | optout | dq | bounce
  added_at  timestamptz NOT NULL,
  PRIMARY KEY (scope, value)
);
-- NOTE: 'competitor' is deliberately NOT a suppression reason.
```

**Domain scope is the important one: one partner opting out silences the whole firm.**

Checked before **every** send, at **send time, not arm time** (invariant I2). A lead can
sit armed for hours; a suppression can land in between.

---

## `firm_track` — routing, not silencing

```sql
CREATE TABLE firm_track (
  firm_id uuid PRIMARY KEY REFERENCES firm,
  track   text NOT NULL DEFAULT 'cold',
  -- cold | displacement | partner_intro | holdout | portal
  reason  text, set_at timestamptz
);
```

| Track | Population | Motion |
|---|---|---|
| `cold` | Default | The standard 9-touch sequence |
| `displacement` | Already buying from a named competitor | Slower, displacement-framed, longer cycle |
| `partner_intro` | Reached via a partner | Warm. Carries a `partner_intro` signal at weight 35, contest NONE |
| `holdout` | **Deliberate test slices** — tier 4 hourly firms, non-concentration geographies | Worked to test a targeting assumption, not to convert |
| `portal` | Firms appearing in the portal's role-request feed | **Suppressed from cold sequences.** Routed to the human who owns the account |

`holdout` is what makes the fee-model axis and the geography assumption falsifiable. It
exists to produce contrary evidence, and its close rate is a finding either way.

`portal` is the severest risk in the system if it is not wired: a cold sequence reaching a
firm that already posted a role on our own portal is visible to the customer, contradicts
the product in writing, and costs an account. See
[firstparty.portal](../50-first-party/03-portal-bench-and-supply.md).
