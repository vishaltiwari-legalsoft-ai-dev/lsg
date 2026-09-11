---
id: icp.tiers
title: The tiers and their wedge SKUs
answers: "Given a firm's attributes, what tier is it and which role opens the conversation?"
source: 00 §5, 01 §2
authority: canonical
stability: seeded
depends_on: [icp.need-model, icp.fee-model, icp.practice-areas, icp.size]
feeds: [pipeline.scoring, pipeline.lifecycle, firstparty.portal]
---

# The tiers and their wedge SKUs

Everything in [need-model](01-need-model.md), [fee-model](03-fee-model.md),
[practice-areas](02-practice-areas.md) and [size](04-size-and-need-proxies.md), resolved
into tiers.

**Fee model gates first; practice area refines.** Each tier carries the role that should
open the conversation.

| Tier | Profile | Why the need is acute | Wedge SKU | Client-facing? | Second SKU |
|---|---|---|---|---|---|
| **1A** | PI & mass tort<br>contingency · 2–25 attorneys | Every case requires chasing records from providers who are slow, then drafting a demand. All of it unbilled, all of it standing between the firm and its fee. Case volume scales with advertising; payroll does not | `demand_writer` | No | `document_collector` |
| **1B** | Immigration<br>flat fee · bilingual need | Fixed fee per matter against enormous form and evidence volume, plus a client base that frequently needs Spanish. Every hour saved on a matter is margin on that matter | `legal_assistant_es` | Partly | `document_collector` |
| **2** | Fee-shifting litigation<br>employment, lemon law, workers' comp, SSDI, consumer | Identical overhead economics to contingency, with heavy third-party records work. **Far less crowded than PI** — almost every competitor targets PI first | `case_manager` | Yes | `legal_assistant` |
| **3** | Flat-fee volume<br>bankruptcy, criminal, estate, family | Predictable fee, repetitive document assembly, thin margins per matter. Buys one role readily; expands slowly | `legal_assistant` | Partly | `bookkeeper` |
| **4** | Hourly practices<br>business, real estate, tax, IP | Support staff is billable, so only genuinely unbillable functions are sellable. Narrow but not zero — **and the segment that tests whether the fee-model axis is real** | `bookkeeper` | No | `marketing_specialist` |

The tier → SKU mapping is a **lookup table, not logic**, so it can be tuned from outcome
data without a deploy.

---

## `icp_tier()` — deterministic, recomputed on any attribute change

The ICP is not a description, it is a function from firm attributes to a tier.

```sql
CREATE FUNCTION icp_tier(f firm) RETURNS tier_t AS $$
SELECT CASE
  -- hard disqualifiers, evaluated first
  WHEN f.entity_kind <> 'private_firm'                    THEN 'DQ_ENTITY'
  WHEN f.country <> 'US'                                  THEN 'DQ_GEO'
  WHEN f.attorney_count > 50                              THEN 'DQ_SIZE'
  WHEN f.has_inhouse_recruiter                            THEN 'DQ_SELFSERVE'
  -- no delegable procedural volume — fails need condition 1
  WHEN f.primary_practice IN ('appellate','patent_prosecution',
                              'complex_commercial')       THEN 'DQ_NOVOLUME'
  WHEN f.first_seen_bar_admission > now() - interval '24 months'
       AND f.attorney_count = 1
       AND NOT f.paid_ads_active                          THEN 'DQ_NOBUDGET'

  -- tiers. fee_model gates before practice_area is consulted.
  WHEN f.fee_model IN ('contingency','fee_shifting')
       AND f.primary_practice IN ('personal_injury','mass_tort')      THEN '1A'

  WHEN f.fee_model = 'flat'
       AND f.primary_practice = 'immigration'                         THEN '1B'

  WHEN f.fee_model IN ('contingency','fee_shifting')
       AND f.primary_practice IN ('employment','lemon_law',
                                  'workers_comp','ssdi','consumer')   THEN '2'

  WHEN f.fee_model = 'flat'
       AND f.primary_practice IN ('bankruptcy','criminal',
                                  'estate','family')                  THEN '3'

  -- hourly firms: only non-billable SKUs are sellable. narrow, not excluded.
  WHEN f.fee_model = 'hourly'                                         THEN '4_NONBILLABLE'

  ELSE 'UNCLASSIFIED'  -- routes to P9 escalation, never to outreach
END
$$ LANGUAGE sql IMMUTABLE;
```

Target file: `sql/002_functions.sql`. Not yet written.

**`UNCLASSIFIED` never routes to outreach.** It routes to P9 escalation. A firm the
classifier could not place is not a firm to guess about.

---

## Open with the role that touches no client

Roles that speak to clients — intake, case management — carry accent concerns, trust
concerns and professional-responsibility anxiety. They are a **hard first sale** into a
firm that has never outsourced.

Roles that touch no client — document collection, demand writing, lien negotiation,
bookkeeping — carry almost none of that.

**Open there.** Client-facing roles become easy once the firm has watched the arrangement
work for a quarter, and that expansion is *the firm's own idea* rather than ours.

This is why 1A opens on `demand_writer` and not `case_manager` despite both being
plausible, and why the `Client-facing?` column above is part of the table rather than a
note.

---

## This table is a guess that has a source of truth waiting

The tier → wedge-SKU mapping is a set of **reasoned guesses**. The portal's daily role
requests are ground truth for it: what kind of firm actually asks for what role, *first*,
in their own words. No amount of outbound testing produces that as cleanly.

Replace this table from portal data when I3 is running. See
[firstparty.portal](../50-first-party/03-portal-bench-and-supply.md).
