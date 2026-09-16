---
id: datamodel.identity
title: Identity resolution — the hard gate
answers: "How do we merge one firm appearing under four names without silently deleting prospects?"
source: 01 §5, 01 §11
authority: canonical
stability: decided
depends_on: [datamodel.normalization]
feeds: [execution.gates, pipeline.orchestration, signals.filter-resolve]
---

# Identity resolution — the hard gate

One firm appears in Places, two bar directories and Justia under four different names. Two
genuinely different firms in one city are called "Smith Law" and "Smith Legal".

> Getting this wrong in the **safe** direction produces duplicates.
> Getting it wrong in the **unsafe** direction silently deletes prospects.

**This runs before the site crawl, not after.** The same firm arrives from three sources
under three names; deduplicate first, or the most expensive stage in collection runs three
times on the same firm.

---

## Step 1 — Block

Candidate pairs are generated **only within blocks**. Never O(n²) over 300k records.

```
block_by_domain : exact norm_domain
block_by_phone  : exact norm_phone (excluding shared)
block_by_zip    : zip5

→ reduces ~320k records to ~4M candidate pairs, not 51 billion
```

## Step 2 — Rules, evaluated in order, first match wins

```
R1  norm_domain equal, both non-null, neither blocklisted        → MERGE
R2  norm_phone  equal, both non-null, neither shared             → MERGE
R3  addr_hash equal AND similarity(name_stem) > 0.55             → MERGE
R4  same zip5   AND similarity(name_stem) > 0.82                 → REVIEW
```

**R3 requires both conditions.** Address alone merges every firm in an office tower.

**R4 never auto-merges.** A false merge is invisible and unrecoverable; a false split is
visible and costs one duplicate. The asymmetry is the whole design.

## Step 3 — Union-find

```
merge edges from R1–R3 → connected components → one firm per component
canonical_name = the variant from the highest-precedence source (§8)
every other variant → firm_alias with its merge_rule
```

Writing every collapsed variant to `firm_alias` with the rule that merged it is what makes
a bad dedupe **unpickable rather than only re-runnable**.

## Step 4 — Verify, **before the pipeline advances, not after**

```sql
SELECT domain, count(*) FROM firm
 WHERE domain IS NOT NULL GROUP BY 1 HAVING count(*) > 1;

SELECT phone_e164, count(*) FROM firm
 WHERE phone_e164 IS NOT NULL GROUP BY 1 HAVING count(*) > 1;
```

**Both must return ~zero rows.**

Thousands means R1/R2 never fired — almost always because **phone was stored formatted
rather than E.164**, or **`www.`/trailing slash was not stripped before hashing**. Check the
normalizers, not the rules.

## Acceptance

```
collapse ratio (raw ÷ resolved)   expected 2.0 – 3.3×

above 3.3×  → OVER-merging.  check R3/R4 thresholds
below 2.0×  → UNDER-merging. check NORMALIZERS, not thresholds
```

The asymmetry in that diagnosis is deliberate. Under-merging is nearly always a canonical-form
failure upstream, not a threshold that is too tight.

---

## A broken dedupe presents as success

More rows, more coverage, better-looking counts.

> It surfaces ten weeks later when **one managing partner has received four emails from four
> of your sending domains** and reported all of them.

The verification query above is the **only cheap moment** to catch it.

**Run it as a gate, not as a report.** `resolve_identity` is followed by these queries as a
hard gate; if firms share a domain or a phone, **the flow stops**. Everything downstream —
crawling, extraction, enrichment, verification — is spent per-firm, so advancing past a
broken dedupe multiplies the cost of the error by every subsequent stage.

See [execution.gates](../60-execution/03-hard-gates.md).

---

## The same ladder appears three times

The "decisive key or nothing" principle recurs, and the three should stay consistent:

| Context | Decisive | Probabilistic | Never |
|---|---|---|---|
| **Firm dedupe** (here) | domain, phone | addr + name > 0.55 | zip + name alone → review only |
| **Posting → firm** ([signals](../20-signals/03-agency-filter-and-resolution.md)) | apply-email domain, outbound link, phone, ATS slug | addr + name | name alone → **reject** |
| **Internal job data** ([firstparty](../50-first-party/05-job-history.md)) | domain, phone | addr + name | name alone → **reject** |

In all three, a name-only match is refused. Not because it never works, but because when it
fails it **fails silently and permanently**.
