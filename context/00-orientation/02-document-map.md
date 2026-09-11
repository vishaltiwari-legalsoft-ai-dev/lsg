---
id: orientation.document-map
title: Source documents and authority order
answers: "Which document is authoritative for what, and what do I do when two disagree?"
source: README, all document footers
authority: canonical
stability: decided
depends_on: [orientation.project-brief]
feeds: []
---

# Source documents and authority order

Five documents in the project root. They were written in sequence and each one extends
or verifies the ones before it.

| # | Document | Answers | Role | Status |
|---|---|---|---|---|
| **00** | ICP + Collection Strategy | **Who to target and why.** Need model, tiers, source map, in-market signals, collection sequence, lead record. | Source of the *why* | Current |
| **01** | Pipeline Build Spec | **How to build it.** Schema, components, normalization, identity resolution, extraction contracts, scoring, lifecycle. | Source of the *how* | Current |
| **02** | First-Party Data Plane | **How internal assets enter.** Adds plane I, changes the arming gate, closes the bench supply gap. | Extension to 01 | Current |
| **03** | Job Signal Acquisition | **Where the strongest signal comes from.** Board register, three lanes, agency filter, dedupe, closure. | Extension to 01, expands signal 01 | Current |
| **04** | Crawlability Audit | **Whether 03's sources are actually reachable.** 16 sources checked live. | Verification of 03 | Dated 10 Sep 2026 |

`_source/` holds the HTML for all five plus the print wrapper.
`_archive/` holds three superseded documents. **Do not build from them** — they contain
commercial modelling built on published marketing claims rather than measured facts.

---

## Authority order

**On strategy — why a rule exists, who to target, what a signal means:** 00 wins.

**On implementation — schema, thresholds, component contracts, orchestration:** 01 wins.

**On anything 02 or 03 explicitly changes:** the extension wins over 01, because it was
written later and names what it is changing. Both do this explicitly:
- 02 changes the arming gate from a fixed 60 to a supply-derived threshold, and adds two
  fit attributes.
- 03 replaces the placeholder watchers W1 and W2 with JA1–JA6.

**On whether a source can be crawled:** 04 wins over 03, and only for the sixteen
sources it checked, and only as of 10 September 2026. It is `verification` authority —
it can invalidate a plan but it never sets a rule.

---

## When 00 and 01 disagree

> "If a rule in one disagrees with a rule in the other, reconcile them — do not pick one
> and move on."

Three such contradictions were found and resolved in the current revision. All three
are recorded, with their reasoning, in
[decisions.log](../70-decisions/01-decision-log.md). Read that before assuming a fourth
one is new.

---

## Known staleness

The root `README.md` describes the project as "the two documents" and lists only 00 and
01 in its table and its build order. Documents 02, 03 and 04 were added afterwards and
the README was not updated to cover them. Its build order is therefore incomplete — it
stops at the signal layer and does not include plane I, the JA components, or the
crawlability findings.

The consolidated, current sequence is
[execution.build-order](../60-execution/01-build-order.md). Prefer it over the README's.
