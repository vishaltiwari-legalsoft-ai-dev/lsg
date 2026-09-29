# context/

The Lead Gen Engine knowledge base, chunked for retrieval.

The five PDFs in the project root are the human-readable artefacts. This folder is
the same knowledge reorganised by **the question each piece answers**, so a person
or an agent working on one part of the system can load two or three files instead
of a 6,000-word specification.

Nothing here is new. Every chunk traces to a section of a source document, named in
its `source:` field. Where the sources disagreed, the resolution is recorded in
[70-decisions/01-decision-log.md](70-decisions/01-decision-log.md) — not silently applied.

---

## Chunk format

Every chunk carries YAML frontmatter:

```yaml
---
id: icp.need-model           # stable address, referenced by other chunks
title: The four need conditions
answers: "Why would a law firm buy remote legal staff at all?"
source: 00 §1                # document number and section
authority: canonical         # canonical | derived | verification
stability: decided           # decided | seeded | unverified | dated
depends_on: [orientation.project-brief]
feeds: [icp.practice-areas, icp.fee-model, icp.size]
---
```

### `authority` — which chunk wins in a disagreement

| Value | Meaning |
|---|---|
| `canonical` | The source of the rule. Change it here first. |
| `derived` | Implements or restates a canonical rule. If it conflicts with its canonical chunk, this one is wrong. |
| `verification` | An observation about the world, not a decision. Can invalidate a plan but never overrides a rule. |

### `stability` — how much to trust the numbers

| Value | Meaning | How to treat it |
|---|---|---|
| `decided` | Settled. Reasoned through, contradictions resolved. | Build on it. Do not re-litigate. |
| `seeded` | A reasoned starting value with no measurement behind it. | Build on it, instrument it, expect to replace it. |
| `unverified` | Depends on an inspection or measurement not yet performed. | Do not plan around it. Run the check first. |
| `dated` | A point-in-time observation that decays. | Check the date before relying on it. |

**The `seeded` marker is load-bearing.** Every scoring weight, tier ranking, signal
ordering and yield estimate in this system is a hypothesis. The source documents say
so repeatedly and in their own words. A chunk marked `seeded` is a placeholder holding
the shape of an answer until outcome data arrives.

---

## Load recipes

Start from the task, not the tree.

| Working on | Load |
|---|---|
| Anything, first time | `00-orientation/*` (all three, ~1,400 words) |
| Deciding whether a firm qualifies | `10-icp/01`, `03`, `05`, `06` |
| Writing the schema | `30-data-model/01`, `05` |
| Writing normalizers | `30-data-model/02` |
| Dedupe / entity resolution | `30-data-model/02`, `03`, `04` |
| A discovery or profile scraper | `40-pipeline/02`, `30-data-model/02`, `20-signals/06` |
| The job-signal pipeline | `20-signals/*` (all five) |
| LLM extraction | `40-pipeline/03`, `30-data-model/04`, `10-icp/03` |
| Scoring or routing | `40-pipeline/04`, `20-signals/01`, `50-first-party/03` |
| The lead state machine | `40-pipeline/05`, `30-data-model/05` |
| Loading internal data | `50-first-party/*` (all five) |
| Sequencing the work | `60-execution/*`, `70-decisions/01` |
| Asking "why is this rule here?" | `10-icp/01` first, then `70-decisions/01` |

---

## The one rule that governs everything

Every targeting rule in this system traces back to one of four need conditions in
[10-icp/01-need-model.md](10-icp/01-need-model.md). A rule that cannot be traced back
to a reason a firm would buy is a rule that will quietly select the wrong firms.

When adding a filter, a score component or a disqualifier: name the condition it
serves. If you cannot, it does not belong.
