---
id: icp.practice-areas
title: Practice areas — which generate delegable volume
answers: "Which practice areas produce work we can actually take on, and which do not?"
source: 00 §2
authority: canonical
stability: seeded
depends_on: [icp.need-model]
feeds: [icp.tiers, icp.disqualifiers, pipeline.scoring, datamodel.normalization]
---

# Practice areas — which generate delegable volume

Serves **need condition 1**. Practice area is a *proxy* for what the daily work actually
consists of. The question is not "is this a big practice area" but "does this practice
generate large amounts of procedural work that a trained remote person can do".

| Practice | The repetitive work it generates | Volume | Verdict |
|---|---|---|---|
| **Personal injury** | Medical records requests to dozens of providers per case, bill collection, lien negotiation, demand letter drafting, treatment follow-up calls, intake screening | Very high | **Core** |
| **Mass tort** | Same as PI, multiplied by claimant count. Four to six provider requests per claimant, thousands of claimants, all on a filing deadline | Extreme | **Core** |
| **Immigration** | Form preparation at volume (family petitions, adjustment, naturalisation), evidence collection, translation, case status checks, scheduling. Heavy Spanish-language need | Very high | **Core** |
| **Social security disability** | Medical records from every treating provider, agency forms, hearing prep packets, status chasing across a multi-year timeline | High | Strong |
| **Workers' compensation** | Medical records, employer records, state board forms, benefit tracking | High | Strong |
| **Consumer / lemon law** | Repair-order collection, manufacturer correspondence, statutory notice letters, document assembly | High | Strong |
| **Employment** | Personnel file requests, wage statement analysis, charge filings, document review | Medium-high | Strong |
| **Bankruptcy** | Schedules and statements, means-test data entry, creditor lists, document collection from the debtor | High | Good |
| **Family** | Financial disclosure assembly, document collection, scheduling, client status updates | Medium | Good |
| **Criminal defence** | Discovery organisation, records requests, client and family communication | Medium | Good |
| **Estate planning** | Intake questionnaires, document assembly from templates, funding follow-up | Medium | Good |
| **Real estate, tax, business** | Some document assembly, but much of it is billed to the client and volume is transaction-dependent | Low-medium | Narrow |
| **Appellate, complex commercial, M&A, IP prosecution** | Research and drafting *are* the work, both judgment-heavy at low volume. Little to delegate that a trained non-lawyer can absorb | Low | **Exclude** |

---

## The pattern underneath

Every practice at the top of this table shares one trait:

> **The firm must gather documents from third parties who are slow.**
> Medical providers, employers, manufacturers, government agencies.

That chasing is high-volume, low-judgment, entirely remote, and it **directly delays the
firm getting paid**.

That single characteristic is a better predictor of need than the practice label, and it
is why PI, mass tort, immigration and SSDI cluster at the top despite being unrelated
areas of law.

When classifying an ambiguous firm, ask that question rather than matching the label.

---

## Implementation

The bottom row is a hard disqualifier — `DQ_NOVOLUME` in `icp_tier()`, covering
`appellate`, `patent_prosecution`, `complex_commercial`. It was **added in the current
revision**; before that these firms fell through to tier 4. See
[decisions.log](../70-decisions/01-decision-log.md).

`norm_practice` maps free text onto a **closed vocabulary of 15 slugs**. Multi-area firms
get an ordered array; `primary_practice` is the area with the **most page real estate**,
not the first listed. See [datamodel.normalization](../30-data-model/02-normalization-contracts.md).

The 15-slug vocabulary is specified in 01 §4 but **not yet extracted as a config file** —
it is a build-order item. See [execution.build-order](../60-execution/01-build-order.md).
