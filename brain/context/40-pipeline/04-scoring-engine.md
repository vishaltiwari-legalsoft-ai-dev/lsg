---
id: pipeline.scoring
title: The scoring engine — fit, intent, contest, routing
answers: "How does a firm become a lead worth working today, and who decides?"
source: 01 §9, 02 §6, 03 §7
authority: canonical
stability: seeded
depends_on: [icp.tiers, icp.size, signals.catalog, firstparty.portal]
feeds: [pipeline.lifecycle, pipeline.observability]
---

# The scoring engine

**Two scores, computed differently, never merged before routing.**

| | **Fit** | **Intent** |
|---|---|---|
| Is | A pure function of firm attributes | A windowed aggregation over signals |
| Range | 0–50 | 0–50 |
| Recomputed | On attribute change | Nightly, full scan |
| Behaviour | Deterministic | Decaying |
| Answers | Could this firm buy? | Is it trying to solve this now? |

This is the [universe / in-market split](../10-icp/01-need-model.md) expressed as arithmetic.

---

## FIT — pure, 0..50, recomputed on attribute change

```
fee_model IN (contingency, fee_shifting, flat)   +15   ← the primary axis
practice 1A / 1B / 2 / 3                         +10 / +8 / +8 / +5
attorney_count 2–12 / 13–25 / 1                  +12 / +8 / +5
country = US                                      +6
review_count > 40          -- case-volume proxy   +4
staff_ratio < 1.0          -- understaffed        +4
paid_ads_active            -- cash stability      +3
spanish_intake                                    +5
attorney_count 26–50                             −10   ← penalise, not disqualify

-- added by 02 §3, from internal job history
has_hired_support_roles                           +5
repeat_role_count >= 2                            +8   ← strongest of the four
```

`repeat_role_count >= 2` is worth more than `has_hired_support_roles` for a specific reason:

> A firm that has posted "paralegal" three times in two years has **churn in that seat**. The
> need is not occasional, it is **chronic** — and chronic need in a seat we can fill
> permanently is a better prospect than a firm hiring for the first time.

That pattern is only visible with historical data. It is the single best reason to keep the
internal job file. See [firstparty.job-history](../50-first-party/05-job-history.md).

---

## INTENT — 0..50, nightly, weight derived at score time

**Weight is not stored on the signal row.** An open job posting gains weight as it ages —
the same event, re-weighted, not a second event.

```
FUNCTION signal_weight(kind, first_seen, closed_at) →
  CASE kind
    WHEN 'job_posting_open' THEN
      CASE WHEN closed_at IS NOT NULL        THEN 0
           WHEN age(first_seen) > 21 days    THEN 40   -- hiring has failed
           WHEN age(first_seen) >  7 days    THEN 34
           ELSE                                   30 END
    WHEN 'partner_intro'          THEN 35
    WHEN 'pricing_page_visit'     THEN 25
    WHEN 'review_unreturned_call' THEN 15
    WHEN 'multi_opening'          THEN 10
    WHEN 'paid_ads_spike'         THEN 10
    WHEN 'mass_tort_campaign'     THEN 10
    WHEN 'new_office_or_lateral'  THEN  8
    WHEN 'cms_implemented'        THEN  8
  END

-- repost variants (03 §7) sit above the 40:
--   repost_count >= 1  → 44
--   repost_count >= 2  → 48

FUNCTION decay(days_since_last_seen) →
  ≤7d → 1.00    ≤30d → 0.70    ≤90d → 0.35    >90d → 0

intent = LEAST(50, SUM(signal_weight × decay)) GROUP BY firm_id
```

---

## CONTEST — a routing input, not a score component

**How many competitors see this signal.** It never changes the intent number.

```
job_posting_open        → HIGH
paid_ads_spike          → HIGH
mass_tort_campaign      → MED
review_unreturned_call  → LOW
cms_implemented         → LOW
partner_intro           → NONE
```

> A job posting is the strongest intent signal **and** the one every rival sees the same day.
> A review-mined signal is weaker but uncontested.
>
> **Spend human SDR time on high-intent, LOW-contest leads.**

Keeping contest out of the score is deliberate. Folding it in would suppress genuinely
in-market firms just because they are contested — they should still be worked, just
automatically.

---

## Routing bands

```
fit + intent ≥ 80 AND contest ≤ MED  → STRIKE     (human, same day)
fit + intent ≥ 80                    → SEQUENCE   (automated, 9 touches)
fit + intent ≥ 60                    → SEQUENCE
fit + intent ≥ 40                    → NURTURE
otherwise                            → HOLD
```

**STRIKE is the only band that consumes a person.** Its target is p50 signal-to-contact
latency **under 48 hours** — the one metric the whole signal architecture exists to minimise.

---

## The arming threshold is supply-derived, not fixed

The build spec used a fixed 60. **02 §6 replaces it.**

```
threshold(tier, sku) =
    BASE                                    -- 60
  − bench_bonus(available, replenish_30d)   -- deep bench: arm earlier
  + starvation_block(available)             -- empty: do not arm at all

bench_bonus     = LEAST(15, available × 1.5)
starvation_block= CASE WHEN available = 0 AND replenish_30d = 0
                       THEN 999 ELSE 0 END
```

A deep bench **lowers the bar**, so borderline leads for a role we can comfortably fill still
get worked. An empty bench with no pipeline **raises it out of reach**.

> The gate stops being binary and starts behaving like **inventory pressure**.

This inverts the standard model. Instead of generating demand and hoping delivery can match
it, the bench becomes an **input to targeting**:

- 14 Spanish-speaking legal assistants with immigration experience available → **this week's
  outbound weights Tier 1B up**
- 6 demand writers with PI experience → Tier 1A on the demand-writer wedge gets priority
- 0 lien negotiators, none replenishing → **that wedge is paused in messaging**, not merely
  gated at the end

See [firstparty.portal](../50-first-party/03-portal-bench-and-supply.md).

---

## Every number on this page is a hypothesis

The weights, the bands, the decay curve, the thresholds — all **seeded values**, reasoned but
unmeasured. The source documents say so explicitly and repeatedly.

**The mechanism that replaces them:** every `WON` and `LOST` lead carries its
`arming_signal`. After ninety days, the join **outcome × signal kind × tier** re-weights this
table.

> The weights in this document are a seeded hypothesis; the only thing that makes them
> correct is running that query and rewriting the table.

Scoring is a nightly **full scan, not a stream** — specifically so that re-weighting is a
re-run rather than a backfill. The architecture assumes these numbers will change.
