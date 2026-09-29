---
id: firstparty.portal
title: The portal — two feeds, opposite ends of the funnel
answers: "How does the talent pool gate arming, and why is the demand feed the highest-risk wiring in the system?"
source: 02 §5, 02 §6
authority: canonical
stability: decided
depends_on: [firstparty.assets, datamodel.schema, icp.disqualifiers]
feeds: [pipeline.scoring, pipeline.lifecycle, execution.build-order]
---

# The portal — two feeds, opposite ends

The portal is the **only genuinely proprietary asset** here. Everything else could in
principle be reconstructed from public sources; **this could not.**

It also carries the highest risk of an embarrassing failure if it is wired in late.

---

## Feed A — the talent pool → `bench_inventory`

**The build spec specified this table and the gate that reads it, but had no source for it.**
The portal is the source, which turns a hypothetical constraint into a live one.

```
sku          demand_writer | paralegal | intake | case_manager | …
language     en | es | pt | …
practice_exp personal_injury | immigration | family | …    ← matters
available    int
replenish_30d int
as_of        timestamptz
```

### `practice_exp` is what makes it useful rather than decorative

> *"12 case managers available"* tells the arming gate almost nothing.
>
> *"12 case managers, 4 of them Spanish-speaking with immigration experience"* tells it
> **exactly which tier to arm.**

Without that dimension the gate can only answer "is the bench empty", which is a brake.
With it, the gate can answer "which tier should we be working this week", which is steering.

---

## Supply steers demand

The build spec used the bench as a **brake** — do not arm a lead for a role we cannot fill.
With a live feed it does something more useful: **decide what to go looking for this week.**

The standard model generates demand and then hopes delivery can match it. **Inverted, the
bench becomes an input to targeting** rather than a constraint discovered at the end:

- 14 Spanish-speaking legal assistants with immigration experience available → **this week's
  outbound weights Tier 1B up**
- 6 demand writers with PI experience → **Tier 1A on the demand-writer wedge gets priority**
- 0 lien negotiators, none replenishing → **that wedge is paused in messaging**, not merely
  gated at the end

```
threshold(tier, sku) =
    BASE                                    -- 60
  − bench_bonus(available, replenish_30d)   -- deep bench: arm earlier
  + starvation_block(available)             -- empty: do not arm at all

bench_bonus      = LEAST(15, available × 1.5)
starvation_block = CASE WHEN available = 0 AND replenish_30d = 0
                        THEN 999 ELSE 0 END
```

A deep bench **lowers the bar**, so borderline leads for a role we can comfortably fill still
get worked. An empty bench with no pipeline **raises it out of reach**.

> The gate stops being binary and starts behaving like **inventory pressure**.

### The bench is also a message

Because the talent pool is first-party and current, outreach can **name real inventory**:

> *"We have a paralegal with three years of personal injury experience available this week"*

That is a materially different opening from *"we place paralegals"* — it is **specific, it is
checkable, and it implies immediacy** that a generic pitch cannot.

> No competitor working from public job-posting data can write that line, because none of
> them knows what is on their bench at the moment they send.

**This is the one place where an internal asset produces an advantage that is not merely
operational.**

---

## Feed B — the daily role requests

Whatever these turn out to be, **they resolve to firms, and firms that appear here must not
be treated as cold.** The handling differs by which of two things the feed actually is.

| If the feed is… | Then those firms are | Route to |
|---|---|---|
| **Law firms posting roles they want filled**<br>*the likely reading* | Either existing customers or self-identified prospects. Either way **they have raised their hand.** The hottest population in the system — **and the one it would be most damaging to cold-email** | `firm_track = 'portal'`<br>**suppress from cold sequences**<br>route to the human who owns the account |
| **Externally aggregated postings collected for internal use** | The same class of data as the job-history file — **and if these carry links and dates, they are a genuine live signal** rather than a seed | `signal kind='job_posting_open'`<br>**only where a URL and date exist** |

**Which reading is correct is an open question.** See
[execution.open-questions](../60-execution/05-open-questions.md).

**The suppression path is required under either reading.**

---

## Wire suppression before anything else

> If the first reading is right, a cold sequence reaching a firm that already posted a role
> on our own portal is **the worst single failure this system can produce.**
>
> It is visible to the customer, it contradicts the product **in writing, to the person
> paying**, and it costs an account.

**The portal-to-suppression path should be connected before the first outbound email is ever
sent — ahead of scoring, ahead of signals, ahead of everything.**

I3 is item 1 in [execution.build-order](../60-execution/01-build-order.md) for exactly this
reason. It is a small job, and nothing outbound should run before it exists.

---

## Feed B has a third use

The role requests are **ground truth for the tier → wedge-SKU table.**

That mapping in the build spec is a set of **reasoned guesses**. Portal data replaces it with
fact: **what kind of firm actually asks for what role, first, in their own words.**

> No amount of outbound testing produces that as cleanly.

See [icp.tiers](../10-icp/05-tiers-and-wedge-skus.md).

---

## Stale bench data is worse than none

I4 syncs hourly, with an **alert when `as_of` falls behind**, and a **stale bench is treated
as empty**.

> Leads arm against inventory that is already placed. The three-day promise breaks on
> **exactly the leads the system worked hardest to find.**

A stale bench re-opens the precise failure the gate exists to prevent, while looking like the
gate is working.
