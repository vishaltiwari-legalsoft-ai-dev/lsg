---
id: pipeline.extraction
title: The LLM extraction contract
answers: "What schema do P8 and P9 share, when does escalation fire, and how are prompts versioned?"
source: 01 §6 (P8/P9), 01 §7
authority: canonical
stability: decided
depends_on: [icp.fee-model, icp.practice-areas, datamodel.reconciliation]
feeds: [pipeline.observability, datamodel.reconciliation]
---

# The LLM extraction contract

P8 (`claude-haiku-4-5`, Batch API) and P9 (`claude-opus-5`) share **one schema**.

Three rules make the output trustworthy:

1. **Every field carries a confidence**
2. **`unknown` is a first-class value**
3. **Every value carries the span it was read from**

Rule 3 turns QA from *re-reading pages* into *sampling evidence strings*.

---

## The schema

Enforced via `output_config.format` — **a schema, not a prompt instruction.**

```jsonc
{
  "primary_practice": { "value": enum15, "confidence": float, "evidence": string },
  "practice_areas":   [ { "area": enum15, "weight": float } ],

  "fee_model": {
    "value": "contingency"|"fee_shifting"|"flat"|"hourly"|"mixed"|"unknown",
    "confidence": float,
    "evidence": string          // the exact sentence. required if != unknown
  },

  "attorney_count": {
    "value": int|null,
    "confidence": float,
    "method": "team_page_count"|"stated"|"inferred",
    "excluded": int             // staff bios NOT counted as attorneys
  },

  "staff_ratio":     { "value": float|null, "confidence": float },
  "decision_makers": [ { "name": string, "title": string,
                         "role": "owner"|"admin"|"attorney", "evidence": string } ],
  "languages":       [ iso639 ],
  "spanish_intake":  { "value": bool, "evidence": string },
  "entity_kind":     { "value": "private_firm"|"inhouse"|"gov"|"directory_stub" },
  "has_inhouse_recruiter": { "value": bool, "evidence": string }
}
```

`attorney_count.excluded` exists because a team page lists staff bios alongside attorney
bios, and counting both is the most common way this field goes wrong. The model reports what
it excluded so the number can be checked.

---

## Escalation to P9 — any of

```
fee_model.confidence        < 0.60
attorney_count.confidence   < 0.60
primary_practice.confidence < 0.70
fee_model.value IN ('mixed','unknown')
icp_tier(firm) = '1A'          -- ALWAYS, regardless of confidence
```

The first four are quality triggers. **The fifth is a value decision**: tier 1A is the
beachhead and the highest-value segment, so it gets the better model unconditionally rather
than only when the cheap model admits doubt.

The three confidence thresholds map exactly onto the three tier-determining fields in
[datamodel.reconciliation](../30-data-model/04-attribute-reconciliation.md). Same three
fields, guarded twice: once at extraction, once at reconciliation.

---

## Why `unknown` must be reachable

> A model forced to choose between contingency and hourly **will** choose — confidently, and
> sometimes wrongly.

Fee model is the primary tier axis. A confident wrong value silently routes a firm into the
wrong segment with the wrong wedge SKU **and no error anywhere**.

Making `unknown` a legitimate answer **converts a silent misclassification into an
escalation.**

This is the same design move as: `attorney_count` → null rather than a guess when there is
no team page; `reconcile()` → NULL plus escalation rather than a low-confidence winner on a
tier field; the resolution ladder → reject rather than a name-only match.

**Everywhere a wrong answer would be invisible, refusing to answer is the correct behaviour.**

---

## Prompt versioning

```
firm_attribute.source = 'llm:p8:v3'   -- model + component + prompt rev
```

**A prompt change bumps the rev.** Rows at the old rev are **re-runnable from stored HTML
without re-crawling anything.**

This is the same mechanism as `norm_version` on the normalizers and the same reason P2 stores
raw HTML: every version-bump in this system is a re-parse, never a re-harvest. See
[pipeline.orchestration](06-orchestration.md).

It is also what makes the extraction-confidence alert meaningful — a drop in median
`fee_model.confidence` can be attributed to a specific prompt revision because the rev is on
every row.

---

## What extraction must emit

Per [pipeline.observability](07-observability.md), every extraction emits:

`component · model · prompt rev · input tokens · per-field confidence`

The **median `fee_model.confidence`, week over week** is a monitored defect signal. A drop
greater than 0.1 means site layouts changed or a prompt revision regressed — and **tier
assignment degrades silently** unless it is caught here.
