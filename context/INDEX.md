# Context index

39 chunks across 8 groups, from 5 source documents. Read
[README.md](README.md) first for the chunk format, the authority rules and the load recipes.

Each row: what the chunk answers · its source section · its stability marker.

---

## 00 — Orientation · *read all three first, ~1,400 words*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-project-brief](00-orientation/01-project-brief.md) | What are we building, and what is the one structural idea? | 00, 01 §1 | decided |
| [02-document-map](00-orientation/02-document-map.md) | Which document is authoritative for what? | README | decided |
| [03-glossary](00-orientation/03-glossary.md) | What does this term mean *here*? | all | decided |

## 10 — ICP · *who to target and why*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-need-model](10-icp/01-need-model.md) | **The root axiom.** Why would a firm buy at all? | 00 §1 | decided |
| [02-practice-areas](10-icp/02-practice-areas.md) | Which practices generate delegable volume? | 00 §2 | seeded |
| [03-fee-model](10-icp/03-fee-model.md) | **The primary axis.** Why does billing decide the sale? | 00 §3, 01 §2/§6 | decided |
| [04-size-and-need-proxies](10-icp/04-size-and-need-proxies.md) | What size, and what predicts overload better than headcount? | 00 §4, 01 §9 | decided |
| [05-tiers-and-wedge-skus](10-icp/05-tiers-and-wedge-skus.md) | `icp_tier()` and which role opens the conversation | 00 §5, 01 §2 | seeded |
| [06-disqualifiers-and-tracks](10-icp/06-disqualifiers-and-tracks.md) | Who is excluded vs merely routed differently? | 00 §6, 01 §2/§3 | decided |
| [07-decision-makers-and-lead-record](10-icp/07-decision-makers-and-lead-record.md) | Who do we need, and what is a shippable record? | 00 §10, §12 | decided |

## 20 — Signals · *who is in market right now*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-signal-catalog](20-signals/01-signal-catalog.md) | What signals exist, how strong, who else sees them? | 00 §9, 01 §9 | seeded |
| [02-job-source-register](20-signals/02-job-source-register.md) | Where do 2–25 attorney firms actually post? | 03 §1–§3 | decided |
| [03-agency-filter-and-resolution](20-signals/03-agency-filter-and-resolution.md) | How do we stop targeting recruiters and attach postings to firms? | 03 §4, §6 | decided |
| [04-dedupe-dates-and-closure](20-signals/04-dedupe-dates-and-closure.md) | One role on six boards; reposts; when a signal ends | 03 §5, §7, §8 | decided |
| [05-crawl-policy-and-audit](20-signals/05-crawl-policy-and-audit.md) | What may we crawl, at what rate, checked when? | 04 (all) | **dated 10 Sep 2026** |

## 30 — Data model · *the store*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-schema-core](30-data-model/01-schema-core.md) | The 13 tables + extension additions | 01 §3, 02 §5/§7 | decided |
| [02-normalization-contracts](30-data-model/02-normalization-contracts.md) | Canonical forms, and what breaks without each | 01 §4 | decided |
| [03-identity-resolution](30-data-model/03-identity-resolution.md) | **The hard gate.** Blocking → R1–R4 → union-find → verify | 01 §5 | decided |
| [04-attribute-reconciliation](30-data-model/04-attribute-reconciliation.md) | Four sources disagree — which wins, and why? | 01 §8, 02 §4 | seeded |
| [05-invariants](30-data-model/05-invariants.md) | I1–I7 and what enforces each | 01 §10 | decided |

## 40 — Pipeline · *the components*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-architecture](40-pipeline/01-architecture.md) | Five planes, one store, one invariant | 01 §1, 02 §1 | decided |
| [02-component-register](40-pipeline/02-component-register.md) | All 34 components: input, output, failure policy | 01 §6, 02 §7, 03 §10 | decided |
| [03-extraction-contract](40-pipeline/03-extraction-contract.md) | The P8/P9 schema, escalation, prompt versioning | 01 §7 | decided |
| [04-scoring-engine](40-pipeline/04-scoring-engine.md) | Fit, intent, contest, routing bands, arming threshold | 01 §9, 02 §6 | **seeded** |
| [05-lead-lifecycle](40-pipeline/05-lead-lifecycle.md) | 16 states, every transition and guard | 01 §10, 00 §13 | decided |
| [06-orchestration](40-pipeline/06-orchestration.md) | Flows, cron, idempotency, backfill, rate discipline | 01 §11, 03 §9 | decided |
| [07-observability](40-pipeline/07-observability.md) | Alerting on absence — every alert is a defect | 01 §12 | seeded |

## 50 — First-party · *our own three assets*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-asset-classification](50-first-party/01-asset-classification.md) | What is each asset *really*, vs what it looks like? | 02 §1 | decided |
| [02-one-door-rule](50-first-party/02-one-door-rule.md) | Why internal data goes through the scraping pipeline | 02 §2 | decided |
| [03-portal-bench-and-supply](50-first-party/03-portal-bench-and-supply.md) | The bench gate, and the highest-risk wiring in the system | 02 §5, §6 | decided |
| [04-firm-dataset](50-first-party/04-firm-dataset.md) | Accelerator, not universe. How much does it save? | 02 §4 | **unverified** |
| [05-job-history](50-first-party/05-job-history.md) | Why it is a fit attribute and never an intent signal | 02 §3 | **unverified** |

## 60 — Execution · *sequencing and risk*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-build-order](60-execution/01-build-order.md) | **Consolidated across all five documents** — supersedes the README's | README, 00 §11, 02 §9, 03 §11 | decided |
| [02-collection-phases](60-execution/02-collection-phases.md) | Five phases, each proving something before the next widens | 00 §11 | decided |
| [03-hard-gates](60-execution/03-hard-gates.md) | Every place the pipeline stops, and what must be true to pass | multiple | decided |
| [04-risk-register](60-execution/04-risk-register.md) | What goes wrong, how we notice, what guards it | multiple | decided |
| [05-open-questions](60-execution/05-open-questions.md) | Open vs unverified vs seeded — and what converts them | all | decided |

## 70 — Decisions · *settled, do not re-litigate*

| Chunk | Answers | Source | Stability |
|---|---|---|---|
| [01-decision-log](70-decisions/01-decision-log.md) | 8 decisions with reasoning and what each supersedes | README, 01–04 | decided |
| [02-deliberate-exclusions](70-decisions/02-deliberate-exclusions.md) | What is *deliberately* absent, so it is not re-proposed | 00 §7, 03 §2, 04 §3 | decided |

---

## Reading paths

**New to the project** → `00/*` → `10-icp/01` → `40-pipeline/01` → `60-execution/01`

**About to write code** → `60-execution/01` (build order) → `60-execution/03` (gates) → the
chunks for your stage

**Reviewing a design choice** → `70-decisions/01` → `10-icp/01` (does it trace to a need
condition?)

**Something is broken** → `40-pipeline/07` (alerts) → `60-execution/04` (risks)

**Deciding what to trust** → `60-execution/05` (open questions) → any chunk's `stability:` field

---

## The three things most likely to be got wrong

1. **Building one system for the universe and the in-market problem.** They have different
   cadences, sources and definitions of done. → [10-icp/01](10-icp/01-need-model.md)

2. **Advancing past the dedupe gate.** A broken dedupe presents as *success* — more rows,
   better coverage — and surfaces ten weeks later as one partner reporting four of your
   sending domains. → [30-data-model/03](30-data-model/03-identity-resolution.md)

3. **Sending anything before the portal suppression path exists.** Cold-emailing a firm that
   posted a role on our own portal contradicts the product in writing, to the person paying.
   → [50-first-party/03](50-first-party/03-portal-bench-and-supply.md)
