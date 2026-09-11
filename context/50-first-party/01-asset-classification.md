---
id: firstparty.assets
title: What we actually have — three assets, correctly classified
answers: "We own three data assets. What is each one really, as opposed to what it looks like?"
source: 02 §1
authority: canonical
stability: decided
depends_on: [pipeline.architecture]
feeds: [firstparty.one-door, firstparty.portal, firstparty.firm-dataset, firstparty.job-history]
---

# What we actually have

Three assets already exist. **None of them is what its name suggests** — the job data is not
a signal, the firm data is not a universe, and the portal is not just a product.

Placed correctly, one of them closes a gap the build spec had left open.

> Each asset has an obvious use and a correct use, and for two of the three **they are not
> the same**. Getting this classification wrong is what turns useful internal data into
> contamination.

---

| Asset | Looks like | Actually is | Enters as |
|---|---|---|---|
| **Job-posting data**<br>companies that posted roles — *no post link, no company URL* | An intent signal. "These firms were hiring" | **A seed list plus a fit attribute.** Without a link there is no way to know whether the role is still open, and **an unverifiable posting is not a signal — it is a lead on where to look.** Its durable value is different and better: it shows which firms *structurally* hire support staff | crawl seed<br>+ fit attribute |
| **Firm dataset**<br>firm records, size, attributes | A ready-made universe. "We already have the list" | **A universe accelerator and an attribute source — not a universe.** It cannot contain the field the whole ICP turns on, because **no commercial dataset carries fee model.** It shortens discovery; it does not replace qualification | observation<br>+ firm_attribute |
| **Portal**<br>talent pool + daily job postings | The product | **Two feeds that belong at opposite ends of the funnel.** The talent pool is the **supply side of the arming gate** — the table the build spec specified but had no source for. The role requests are **first-party demand**, and they must reach suppression before they reach outreach | bench_inventory<br>+ firm_track |

---

## The shape of the correction, in each case

**Job data:** demoted from intent to fit — *and gains value in the process*. As intent it
would be wrong and dangerous. As fit history it is something no competitor has: a multi-year
record of which firms have **chronic churn** in a support seat.

**Firm dataset:** demoted from universe to accelerator. It can carry a firm most of the way
through **discovery** but cannot carry it through **qualification**, because `fee_model`
cannot be bought at any price.

**Portal:** promoted. It is the only genuinely proprietary asset here — everything else could
in principle be reconstructed from public sources; **this could not.** It also carries the
highest risk of an embarrassing failure if it is wired in late.

---

## Three of four feeds go through the same door

I1, I2 and I3 enter through `observation` **exactly like every external source**, so nothing
bypasses resolution or reconciliation.

I4 (talent pool → `bench_inventory`) runs down a separate path and rejoins at **the arming
gate — the only place in the system where supply and demand meet.**

See [firstparty.one-door](02-one-door-rule.md) for why the exception is exactly one feed
wide.
