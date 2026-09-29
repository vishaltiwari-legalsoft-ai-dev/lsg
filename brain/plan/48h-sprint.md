# 48-hour sprint

Solo + Claude. Assets: firm dataset export only.
**Scope:** lead acquisition → qualification → pain identification → the emails.
Sending and delivery are out of scope entirely.

**Target at hour 48:** a database of real, deduplicated, tier-classified law firms carrying
**live pain signals** · a ranked lead list where every row carries the sentence that proves
the pain · **the 9-touch journey with emails drafted**.

**Not in scope:** paid enrichment, bar-directory contacts, automated scoring runs, portal
suppression (no access yet), and anything to do with sending.

---

## Hour 0 — before any code (15 minutes, do not skip)

Lead times measured in days. Starting these at hour 0 rather than hour 47 is worth more than
anything else in this document.

- [ ] Request the **customer list export** (any format; domains alone are enough) —
      **the single biggest risk retired per unit of effort**
- [ ] Request **portal access**
- [ ] Enable the **Google Places API** key + billing

And one question for a person, needed before hour 14:

- [ ] **O3 — where did the firm dataset come from?** Team-built from real interactions /
      purchased from a vendor / unknown. This sets its reconciliation precedence, and it has
      to be decided **before the first load, not after the first conflict.**

---

# DAY 1 — Foundation and universe

## H0–2 · Scaffold

- [ ] `git init` — the project is not a repo yet
- [ ] `uv init`, Python 3.12, `pyproject.toml`
- [ ] `docker-compose.yml` — Postgres 16 (`pg_trgm`, `postgis`) + Redis
- [ ] `lge/db.py` — psycopg3 pool, migration runner
- [ ] `lge/cli.py` — `lge run <component>` skeleton
- [ ] ruff + pytest configured

**Build idempotency keying into the CLI runner now.** Every task keys on
`(component, entity_id, input_hash)`; a re-run with unchanged input is a no-op that logs and
exits. Retrofitting this is expensive and it is what makes every later re-run free.

**Exit:** `docker compose up` gives a Postgres with both extensions; `lge --help` runs.

---

## H2–6 · Schema + invariants

Reference: [context/30-data-model/01-schema-core.md](../context/30-data-model/01-schema-core.md)
· [05-invariants.md](../context/30-data-model/05-invariants.md)

- [ ] `sql/001_schema.sql` — all 13 tables, verbatim from the spec, plus indexes:
  - GIN trigram on `firm.name_stem`
  - **`UNIQUE (domain) WHERE domain IS NOT NULL`** ← makes the G1 gate query meaningful
  - `(tier, state) WHERE tier NOT LIKE 'DQ%'`
- [ ] Extension columns from doc 02: `has_hired_support_roles`, `support_roles_posted`,
      `last_known_hiring_attempt`, `repeat_role_count`, `bench_inventory.practice_exp`,
      `firm_track.track` including `'portal'`
- [ ] Extension tables from docs 03/04: `raw_posting`, `job_posting_rejected`, source registry
      (`source_state`, `crawl_delay_s`, `robots_checked`, `platform`)
- [ ] **Invariants as constraints and triggers, not application code:**

| | Enforce as |
|---|---|
| I1 one open lead per firm | `UNIQUE INDEX ON lead (firm_id) WHERE closed_at IS NULL` |
| I2 no touch to a suppressed domain | `BEFORE INSERT` trigger on `outreach_touch` |
| I3 grade B never emailed | `CHECK (grade='A' OR channel <> 'email')` |
| I4 no arming without bench | arming query **joins** `bench_inventory` |
| I5 every state change writes an event | `AFTER UPDATE` trigger on `lead.state` |
| I6 signal append-only | `REVOKE UPDATE, DELETE ON signal` |
| I7 every firm value traces to a claim | `reconcile()` is the only writer |

- [ ] `tests/test_invariants.py` — **each invariant gets a test that tries to violate it and
      asserts the database refuses.** Anything enforced only in application code will
      eventually be bypassed by a backfill script.

**Exit:** migrations apply clean; all seven violation tests fail to violate.

---

## H6–11 · Normalizers — the highest-leverage hours in the sprint

Reference: [context/30-data-model/02-normalization-contracts.md](../context/30-data-model/02-normalization-contracts.md)

Dedupe quality is decided here, not in the matching rules. Under-merging traces back to
these functions almost every time.

- [ ] `norm_domain` — lowercase → strip scheme/`www.`/`m.`/`amp.` → eTLD+1 via
      **tldextract** → drop if in `SHARED_HOST_BLOCKLIST`
      *(wixsite, squarespace, godaddysites, justia, avvo, findlaw)*
- [ ] `norm_phone` — **phonenumbers**, region US → E.164 → mark `shared` and exclude from
      matching at **≥4 distinct firm candidates**
- [ ] `norm_addr` — USPS abbreviations, **secondary unit split out and never in the hash**,
      `addr_hash = sha1(street_norm ‖ zip5)`
- [ ] `norm_name` — strip punctuation, remove the stopword set, **preserve token order**
      (trigram similarity depends on it)
- [ ] `norm_practice` — free text → the 15-slug closed vocabulary
- [ ] **`norm_version` column shipped alongside every canonical value, in this commit**

Write the tests first. Each one asserts the named failure mode cannot happen:

```
test_shared_host_never_becomes_a_key       # else every Wix firm merges into one
test_phone_stored_e164_not_formatted       # else R2 never fires, silently
test_suite_number_excluded_from_addr_hash  # else two floors become two firms
test_name_stem_preserves_token_order       # else everything becomes "smith"
test_shared_phone_flagged_at_4_candidates  # answering services and tracking pools
```

- [ ] `config/practice_areas.yml` — the 15 slugs
- [ ] `config/fee_patterns.yml` — P6 regex, **precedence-ordered, first match wins**
- [ ] `sql/002_functions.sql` — `icp_tier()`, `signal_weight()`, `decay()`

**Exit:** normalizer suite green. **Do not run a harvest before this point.**

---

## H11–15 · Load the firm dataset (I1) — and answer O4

Reference: [context/50-first-party/04-firm-dataset.md](../context/50-first-party/04-firm-dataset.md)
· [02-one-door-rule.md](../context/50-first-party/02-one-door-rule.md)

- [ ] Inspect the export. Which columns exist? **Domain is the field that decides its value** —
      it is rung 1 of every resolution ladder and the entry point to the crawl
- [ ] `lge/planes/i/i1_firm_loader.py` — **through `observation`**, source tag
      `internal_firms`, never straight into `firm`
- [ ] Set its precedence from the O3 answer — team-built → above Places, below the firm's own
      site · purchased → directory tier, below Places · unknown → lowest, and flagged
- [ ] **Guard: cross-check the size field against a sample of team pages.** Vendor size fields
      are frequently *total headcount*, not attorney count — a 12-attorney firm with 20 staff
      reads as 32 and takes the −10 penalty it should never have seen

**Coverage analysis, reported as part of the load:**

```sql
in dataset only      → firms the external harvest would miss
in Places only       → the dataset is not complete
in both              → overlap
dataset ∩ ICP tiers  → how much of it is even relevant
```

| Outcome | Means |
|---|---|
| High overlap, low ICP share | Broad but off-target. **Use for attributes, keep the full harvest** |
| Low overlap, high ICP share | **Genuinely additive.** Strong seed, harvest still needed |
| High overlap, high ICP share | **Discovery narrows to gap-fill. The biggest saving available** |

**Exit:** dataset loaded as observations, coverage numbers in hand.
**This is gate G7 — no discovery scope is reduced on anything but these numbers.**

---

## H15–18 · Buffer, or start D1

If the day ran clean, begin the D1 Places grid harvester scoped to **three metros, tier 1A
keywords only**. If it ran long, stop — day 2 is the harder day.

---

# DAY 2 — Identity, qualification, signal

## H18–22 · Identity resolution · **GATE G1**

Reference: [context/30-data-model/03-identity-resolution.md](../context/30-data-model/03-identity-resolution.md)

Runs **before** the site crawl, not after. Deduplicate first, or the most expensive stage in
collection runs three times on the same firm.

- [ ] **Block:** `norm_domain` · `norm_phone` (excluding shared) · `zip5`
- [ ] **Rules, in order, first match wins:**
  - `R1` domain equal, both non-null, neither blocklisted → **MERGE**
  - `R2` phone equal, both non-null, neither shared → **MERGE**
  - `R3` `addr_hash` equal **AND** `similarity(name_stem) > 0.55` → **MERGE**
  - `R4` same zip5 **AND** `similarity(name_stem) > 0.82` → **REVIEW, never auto-merge**
- [ ] **Union-find** → one firm per component; every collapsed variant written to `firm_alias`
      with its `merge_rule`, so a bad merge is unpickable rather than only re-runnable

**The gate — run it, do not report it:**

```sql
SELECT domain, count(*) FROM firm
 WHERE domain IS NOT NULL GROUP BY 1 HAVING count(*) > 1;   -- must be ~0

SELECT phone_e164, count(*) FROM firm
 WHERE phone_e164 IS NOT NULL GROUP BY 1 HAVING count(*) > 1;  -- must be ~0
```

Collapse ratio must land **2.0×–3.3×**.

| Symptom | Cause |
|---|---|
| Thousands of rows | R1/R2 never fired — phone stored formatted, or `www.`/trailing slash not stripped |
| Ratio > 3.3× | **Over-merging** — check R3/R4 thresholds |
| Ratio < 2.0× | **Under-merging** — check the **normalizers**, not the thresholds |

> A broken dedupe presents as success: more rows, better coverage, better-looking counts. It
> surfaces later as one managing partner receiving four near-identical approaches from what
> looks like four different companies.

- [ ] Encode both queries as `tests/test_gates.py::test_g1`

**Exit: the gate passes. If it does not, stop here — day 2 does not continue.**

---

## H22–28 · Profile crawl (P1–P7)

Reference: [context/40-pipeline/02-component-register.md](../context/40-pipeline/02-component-register.md)

Scope: **200–500 firms**, tier 1A candidates, three metros. Enough to hand-check, small
enough to finish.

- [ ] `P1` site mapper — robots.txt → sitemap.xml → path probe
      (`/about`, `/attorneys`, `/our-team`, `/practice-areas`, `/contact`, `/careers`, `/fees`)
- [ ] `P2` page fetcher — content-hash keyed, **raw HTML to object storage, always**
- [ ] `P3` render fallback — Playwright, **gated to <500 words of static text**. Expect 5–8%
- [ ] `P4` boilerplate stripper — trafilatura. **An accuracy fix**: the footer listing every
      practice area the firm ever mentioned will wreck `primary_practice`
- [ ] `P5` JSON-LD — `LegalService`, `Attorney`, `JobPosting`. **Highest confidence of any source**
- [ ] `P6` fee-model regex — precedence-ordered. **Both contingency and hourly → `mixed`,
      never `contingency`.** Resolve by page real estate; still tied → `UNCLASSIFIED` → P9
- [ ] `P7` tech fingerprint — Filevine, Clio, CASEpeer, MyCase, Litify, SmartAdvocate.
      *This names their tooling in the first line*

**Rate discipline: per-host token bucket in Redis, not global.** ≤1 req/2s per domain
regardless of worker count. Honest, contactable User-Agent. Honour declared `Crawl-delay`.

**Store the raw HTML.** It is why every later prompt or normalizer change is a re-parse rather
than a re-crawl.

**Exit:** ~300 firms with attributes and stored HTML.

---

## H28–33 · Extract, reconcile, classify

Reference: [context/40-pipeline/03-extraction-contract.md](../context/40-pipeline/03-extraction-contract.md)
· [context/30-data-model/04-attribute-reconciliation.md](../context/30-data-model/04-attribute-reconciliation.md)

- [ ] `P8` — `claude-haiku-4-5`, Batch API, **structured outputs enforcing the schema**, not a
      prompt instruction. Every field carries confidence + the evidence span
- [ ] **`unknown` must be reachable.** A model forced to choose between contingency and hourly
      will choose — confidently, sometimes wrongly — and a wrong `fee_model` routes a firm into
      the wrong segment with the wrong SKU and **no error anywhere**
- [ ] `P9` escalation — `claude-opus-5` — on confidence `<0.60` fee/count, `<0.70` practice,
      `mixed`/`unknown`, **or tier 1A regardless of confidence**
- [ ] Tag every row `llm:p8:v1` — model + component + prompt rev, so a revision is re-runnable
      from stored HTML
- [ ] `reconcile()` — precedence per field. **Never silently resolve `fee_model`,
      `primary_practice` or `attorney_count`** — those three decide the tier. Low-confidence
      winner → NULL + escalate
- [ ] `icp_tier()` → real tiers

**Gate G3 — tier distribution sane.** Not a formal week-over-week check yet with one run, but
eyeball it: a 1A share near zero or near everything means the classifier or the harvest is
wrong, and both are bugs.

**Exit:** firms carrying tiers and fit scores, every value traceable to a claim.

---

## H33–40 · Job signals (JA1 + JA6) · **GATE G8**

Reference: [context/20-signals/02-job-source-register.md](../context/20-signals/02-job-source-register.md)
· [03-agency-filter-and-resolution.md](../context/20-signals/03-agency-filter-and-resolution.md)

JA1 first: **best ICP coverage, zero resolution problem** (a posting on a firm's own careers
page is already attached to a domain), free, stable — and the source of truth for closure
detection that everything else leans on.

- [ ] `JA1` careers page watcher → `raw_posting`. Parse order: JSON-LD → microdata → ATS JSON
      → per-template selectors → LLM last, flagged
- [ ] **`JA6` agency filter — build it now, with one source.** Agency noise must be filtered
      before signals are written; build the filter before a second source multiplies it:
  - known-agency blocklist *(maintained, not static)*
  - client language — `/\bour client\b|\bconfidential client\b/i`
  - **≥5 distinct metros in 90 days** ← the behavioural tell, catches agencies no list knows
  - ≥20 open legal support roles
  - blind posting → drop, never guess
- [ ] **Rejects → `job_posting_rejected` with the rule that fired.** The reject stream is how
      the blocklist grows, and a rule-3 spike means a new agency appeared
- [ ] **Record our own `first_seen`.** Board dates are untrusted — "30+ days ago" covers a
      month to a year, and employers refresh listings to stay near the top. Our `first_seen` is
      what makes *"open more than 21 days"* computable at all
- [ ] `signal` rows carrying `evidence` — **the actual job title and posting date**

**Exit:** live signals against real firms, with the quote the first line gets built from.

---

## H40–44 · The ranked list

- [ ] `sql/003_views.sql` — fit + intent + contest, ordered
- [ ] Fit: fee model +15 · practice +10/+8/+8/+5 · size +12/+8/+5 · US +6 · reviews>40 +4 ·
      staff_ratio<1.0 +4 · ads +3 · spanish +5 · **26–50 attorneys −10**
- [ ] Intent: `signal_weight × decay`, weight derived at score time from kind + age
- [ ] Export: firm · partner name · tier · wedge SKU · signal kind · **evidence string** ·
      contest level

Sort by **high intent, LOW contest** — a job posting is the strongest signal *and* the one
every rival sees the same morning.

---

## H44–48 · The journey and the emails

Logic: [outreach-journey.md](outreach-journey.md) · Copy: [email-drafts.md](email-drafts.md)

- [ ] `journey/sequences.yml` — **9 touches**, branched by tier, fee model and signal kind
- [ ] `journey/copy/` — touch 1 in all four signal variants, touch 3 in all four fee-model
      variants. Those two carry most of the value; touches 4–9 can be thinner on day 2
- [ ] **Every personalization token maps to a real column.** A token that cannot resolve means
      the lead does not export — `Hi {first_name}` reaching a managing partner costs more than
      the lead is worth
- [ ] `lge/export/` + `sql/003_views.sql` export view, filtering **at export time**:

```sql
grade = 'A'                              -- B is a phone list, never an email list (I3)
AND tier NOT LIKE 'DQ%'
AND firm_track NOT IN ('portal','displacement')
AND NOT EXISTS (suppression on domain | email | firm_id)
AND (cooldown_until IS NULL OR cooldown_until < now())
AND signal.evidence IS NOT NULL
```

- [ ] `tests/test_export_filter.py` — **suppressed rows and grade-B rows must never appear.**
      Assert it, do not assume it
- [ ] Load the customer list into `suppression` if it arrived
- [ ] **STRIKE band excluded from the sequence list** — high-intent *low-contest* leads are the
      rarest thing the system produces. A human writes those, same day
- [ ] Export **one small batch**, not a list. Suppression is checked at export, so a large list
      drip-fed for weeks will mail firms that opted out on day three

---

## Exit criteria for the 48 hours

| # | | Gate |
|---|---|---|
| 1 | Schema live, all 7 invariants provably enforced | |
| 2 | Normalizer test suite green | |
| 3 | Firm dataset loaded through `observation`, coverage numbers in hand | **G7** |
| 4 | Dedupe verification returns ~zero, collapse ratio 2.0–3.3× | **G1** |
| 5 | ~300 firms classified into tiers, every value traceable to a claim | G3 |
| 6 | Live job signals with evidence strings | **G8** |
| 7 | Journey v1 — 9 touches, every token resolving to a column | |
| 8 | Lead list produced, suppression + grade filter asserted by test | |
| 9 | `lead.arming_signal` populated on every row | |

**Item 9 costs nothing now and cannot be reconstructed later.** It records which pain surfaced
each lead. Nothing reads it yet — but it is the only thing that could ever turn the seeded
scoring weights into measured ones.

---

## What is deliberately not in these 48 hours

| Deferred | Why |
|---|---|
| Prefect | The plane invariant makes the orchestrator late-binding. CLI now, Prefect at M10 |
| D2 bar directories | Highest-value contact source, but R2 is a day-3 win, not a day-2 one |
| R1/R3/R4 contacts | Needs paid accounts. R2 (free, and better) comes first |
| JA2 bar boards | **Prove the platform-parser approach on 10 metros before writing 40** |
| JA4 licensed feed | **G9 — buy against a measured number, not an assumption** |
| I2 job history | File not in hand, and it was last in the order anyway |
| I3/I4 portal | No access. `bench_inventory` runs off a hand-maintained CSV meanwhile |
| Sending and delivery | **Out of scope entirely.** Not modelled, not planned for |
| The 50-record hand-check | **Gate G2, and it gates *widening*, not building.** Day 3–4 |

**The one that matters most is the last.** Nothing widens beyond three metros until 50 records
are hand-checked accurate on every attribute. That is where the estimates in these documents
get replaced by measured numbers, and it is the cheapest moment to discover `fee_model` is
wrong 30% of the time.
