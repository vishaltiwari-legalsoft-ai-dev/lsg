---
id: datamodel.normalization
title: Normalization contracts
answers: "What canonical forms must exist before anything is compared, and what breaks without each?"
source: 01 §4
authority: canonical
stability: decided
depends_on: [datamodel.schema]
feeds: [datamodel.identity, pipeline.component-register]
---

# Normalization contracts

**Identity resolution is only as good as the canonical forms it compares.**

Each function is **pure, deterministic, versioned**, and must be applied **at write time —
never at query time**, or the indexes are useless.

Target file: `sql/002_functions.sql` + `config/practice_areas.yml`. **Not yet written.**
Unit tests before any harvest runs — these functions decide whether dedupe works.

---

| Function | Rule | Failure mode if skipped |
|---|---|---|
| **`norm_domain`** | Lowercase → strip scheme, `www.`/`m.`/`amp.` → reduce to eTLD+1 via the **Public Suffix List** → **drop if in `SHARED_HOST_BLOCKLIST`** (wixsite, squarespace, godaddysites, justia, avvo, findlaw) | **Every firm on a shared host merges into one entity.** Silent and catastrophic |
| **`norm_phone`** | Parse with libphonenumber, region US → E.164. Then: **if one number resolves to ≥4 distinct firm candidates, mark it `shared` and exclude from matching** — it is an answering service or a tracking pool | Stored formatted → rule R2 never fires → dedupe silently degrades to name matching only |
| **`norm_addr`** | USPS canonical abbreviations, **secondary unit split into its own field and never in the hash** (suites differ within one firm), ZIP+4 where available. `addr_hash = sha1(street_norm ‖ zip5)` | Suite numbers in the hash means **one firm's two floors become two firms** |
| **`norm_name`** | Lowercase → strip punctuation → remove tokens `{law, laws, legal, office, offices, attorney, attorneys, firm, group, associates, pllc, pc, llp, llc, ltd, and, the}` → collapse whitespace. **Token order preserved** — trigram similarity depends on it | **Everything becomes "smith"** and rule R4 matches every firm in the ZIP |
| **`norm_practice`** | Map free text to a **closed vocabulary of 15 slugs**. Multi-area firms get an ordered array; `primary_practice` is the area with the **most page real estate**, not the first listed | **Tier assignment becomes non-deterministic across re-runs** |

---

## The two blocklists are load-bearing

`SHARED_HOST_BLOCKLIST` and the shared-phone rule inside `norm_phone` both exist for the
same reason: **a value that many unrelated firms share is not an identity key.**

A Wix subdomain and an answering-service number both look like perfectly good join keys.
Both merge hundreds of unrelated firms into one entity, and both do it **silently** — the
counts go down, which looks like dedupe working.

The `≥4 distinct candidates` rule is the generalisation: any key with too many claimants is
disqualified as a key, without needing to know *why*.

---

## Version every normalizer

**Store `norm_version` alongside each canonical value.**

When `norm_name` changes — and it will, the first time a firm called *"The Law Offices of
Law & Law"* breaks it — you need to know which rows were computed under the old rule so
they can be recomputed **without re-crawling**.

> This is a one-column decision that saves a full re-harvest.

**Ship `norm_version` with the normalizers, in the first commit.** Retrofitting it later
costs exactly the re-harvest it exists to prevent. It is called out as step 2 of the build
order for this reason.

It also pairs with the raw-HTML rule: a normalizer version bump does **not** re-crawl. It
re-reads stored HTML from object storage and re-runs the affected component only. See
[pipeline.orchestration](../40-pipeline/06-orchestration.md).

---

## Write time, not query time

Applying a normalizer in a `WHERE` clause defeats the GIN trigram index on `name_stem` and
the unique index on `domain`. At 320k records that is the difference between a blocking
strategy and a full scan.

The canonical forms are **columns**, not expressions.
