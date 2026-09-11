---
id: decisions.log
title: Decision log — resolved contradictions and standing rulings
answers: "What was decided, why, and what does it supersede?"
source: README, 01 §2, 01 §3, 02 §7
authority: canonical
stability: decided
depends_on: [orientation.document-map]
feeds: []
---

# Decision log

Decisions that superseded something. **These are settled — do not re-litigate them**, and do
not treat a rediscovery of one as a new finding.

---

## D-001 · Size threshold — disqualify at 50, penalise from 26

**Conflict.** Document 01 disqualified firms above **25** attorneys while also scoring a
**26–50** band at **−10**. Both could not be true — a disqualified firm never reaches scoring.

**Resolved to match 00:** disqualify above **50**, penalise **26–50**.

**Why.** Firms of 26–50 attorneys usually have an administrator and sometimes a recruiter, so
[need condition 4](../10-icp/01-need-model.md) is weaker and the cycle is longer — **but the
need is real.** A −10 fit penalty lets a strong signal still surface one, and **keeps a whole
band from disappearing on an assumption.**

**Effect:** `icp_tier()` → `WHEN f.attorney_count > 50 THEN 'DQ_SIZE'`. Fit → `26–50: −10`.

**Supersedes:** the `> 25` disqualifier in 01 §2.

---

## D-002 · Low-volume practices are disqualified — `DQ_NOVOLUME`

**Conflict.** Document 00 excluded appellate, patent prosecution and complex commercial work
— they fail [need condition 1](../10-icp/01-need-model.md), there is little procedural volume
to delegate. Document 01 had **no matching clause**, so those firms **fell through to tier 4.**

**Resolved:** added `DQ_NOVOLUME` to `icp_tier()`, evaluated with the other hard disqualifiers.

**Why.** Falling through to tier 4 is not a neutral outcome — it routes a firm with nothing to
delegate into an outreach track. A firm that fails condition 1 has no need at any tier.

**Effect:**
```sql
WHEN f.primary_practice IN ('appellate','patent_prosecution',
                            'complex_commercial') THEN 'DQ_NOVOLUME'
```

**Supersedes:** the absence of a clause in 01 §2.

---

## D-003 · Competitor customers are not suppressed — `firm_track`

**Conflict.** Document 00 said firms already using a named competitor are **not a
disqualifier** but a **separate, slower motion**. Document 01 listed `competitor` as a
**suppression reason**, which **silenced them entirely.**

**Resolved:** `competitor` **removed from suppression**. Added a `firm_track` table carrying
`cold | displacement | partner_intro | holdout`.

**Why.**

> A firm already buying from a rival is **category-educated with an approved budget — the
> strongest population there is.** It goes on a slower displacement track, **not into
> silence.**

Suppression is for firms that must never be contacted. A competitor's customer is a firm that
must be contacted **differently**. Conflating the two threw away the best population in the
market.

**Effect:** `suppression.reason ∈ {customer, optout, dq, bounce}` — no `competitor`.
`firm_track` created, defaulting to `cold`.

**Secondary benefit:** `firm_track` gives the **holdout slices a home** — the tier-4 hourly
firms and non-concentration geographies that exist to **test targeting assumptions rather than
to convert.** Without a track table those slices had nowhere to live.

**Supersedes:** `competitor` in the 01 §3 suppression enum.

---

## D-004 · The arming gate is supply-derived, not a fixed 60

**Source:** document 02 §6, extending 01 §10.

**Was:** `intent ≥ 60` and bench inventory exists (binary).

**Now:**
```
threshold(tier, sku) = 60 − bench_bonus + starvation_block
bench_bonus      = LEAST(15, available × 1.5)
starvation_block = 999 when available = 0 AND replenish_30d = 0
```

**Why.** The build spec used the bench as a **brake**. With a live feed from the portal it can
**steer**: a deep bench lowers the bar so borderline leads for a fillable role still get
worked; an empty bench with no pipeline raises it out of reach.

> The gate stops being binary and starts behaving like **inventory pressure.**

**Supersedes:** the fixed threshold in 01 §10.

---

## D-005 · W1/W2 replaced by JA1–JA6

**Source:** document 03, extending 01 §6.

**Was:** two placeholder watchers — W1 (careers JobPosting watcher), W2 (job aggregator poller).

**Now:** six components across three lanes — JA1 (careers), JA2 (bar boards), JA3 (ATS), JA4
(licensed feed), JA5 (SERP discovery), JA6 (normaliser).

**Why.** The strongest signal in the system deserved more than a placeholder, and the source
analysis inverted the expected priority: **the sources with the best coverage of 2–25 attorney
firms are also the free, structured, publicly crawlable ones.**

**Supersedes:** W1 and W2 in the 01 §6 register.

---

## D-006 · Craigslist promoted from supplementary to lane 1

**Source:** document 04 §5, revising 03 §2.

**Was:** "light touch — low-volume supplementary feed."

**Now:** lane 1, per-city RSS by job category, metros first.

**Why.** The audit found it **more open than most association sites** — no blanket disallow,
job-category and search paths unrestricted, 30 sitemaps published. Only interaction endpoints
(`/reply`, `/flag`, `/suggest`) are blocked.

**Caveat carried forward:** expect **high agency noise**. The agency filter matters more here
than on any association board.

**Supersedes:** the "Light touch" verdict in 03 §2 Tier B.

---

## D-007 · Source state is an enum, not a boolean

**Source:** document 04 §4.

**Ruling:** the source registry carries
`source_state ∈ {open, rate_limited, policy_closed, edge_blocked, unreachable, auth_required}`
plus `crawl_delay_s`, `robots_checked`, `platform`.

**Why.** Three sources failed for reasons that **look identical from the client side and are
completely different in meaning**: a published rule, a WAF refusing our IP, and a network-layer
refusal.

> A single `blocked` boolean loses the distinction that matters: one is a decision to respect
> permanently, the others are conditions to retry. Conflated, the crawler either abandons
> reachable sources or keeps hammering ones that have said no.

---

## D-008 · Crawl-delay is read, not assumed

**Source:** document 04 §6, revising 03 §9.

**Was:** a uniform ≤1 request / 2s.

**Now:** the per-host token bucket takes its rate from the host's **declared `Crawl-delay`**
where one exists, falling back to 2s only where none is declared.

**Why.** LA County Bar declares `Crawl-delay: 5`. A 200-listing board then takes ~17 minutes;
across 60 metro bars that is **real scheduler time that has to be planned, not discovered on
the first slow night.**

---

# Build-time decisions — 11 Sep 2026

Made while executing the plan. Same rule as above: reconciled, not picked.

## D-009 · `signal` is immutable evidence, not append-only rows

**Conflict.** Invariant I6 says `signal` is append-only (`REVOKE UPDATE, DELETE`; "correction is
a new row with a later `last_seen`"). But the same table carries
`UNIQUE (firm_id, kind, fingerprint)` — so a correction row cannot be inserted — and doc 03's
closure logic explicitly **sets** `closed_at` and **moves** `last_seen`.

**Resolved:** the *evidence* is immutable; the *lifespan* is not.
- Immutable after insert: `firm_id, kind, fingerprint, first_seen, evidence` — enforced by a
  trigger (which binds superusers too) plus column-level `REVOKE`.
- Narrowly mutable: `last_seen` (forward only), `closed_at` (set, or cleared only when
  `last_seen` also advances), `repost_count` (increase only). DELETE always raises.
- Every sighting goes to a new append-only `signal_sighting` table. `sources[]` and repost
  history derive from it, so nothing repost detection depends on is ever mutated.

**Why.** I6 exists because "a signal is evidence about a moment; mutating it destroys the history
repost detection depends on." That history is `first_seen` against the board's shifting date —
both preserved.

## D-010 · Fee-model conflicts: only cost-centre vs hourly is "mixed"

**Spec:** P6 patterns are precedence-ordered, first match wins; *"a firm matching BOTH contingency
and hourly is mixed."*

**Ruling:** contingency, fee-shifting and flat all make support staff overhead, so a conflict
among them is resolved by precedence. contingency > fee_shifting > flat, confidence 0.8. Any
cost-centre family **against hourly** is resolved by page real estate, and a tie is `mixed`.

**Why.** The mixed rule exists because contingency and hourly have *opposite arithmetic*. Flat vs
hourly has the same opposition; contingency vs flat does not. The first implementation treated
every pair as a conflict, so a PI firm that mentioned one flat-fee service dropped out of tier
1A — the beachhead.

## D-011 · Case-system fingerprints match hostnames only

**Ruling:** every P7 pattern is anchored to a domain (`cdn.filevine.com`, `app.goclio.com`),
never a bare word.

**Why.** The spec detects these from "script hosts, chat widgets, form endpoints". Bare-word
patterns fired on `/how-we-prevail` and a malpractice page about needles, reporting a case
system the firm does not run — and `{cms}` goes into the first line of the email.

## D-012 · Runtime environment deviations

| Spec | Built | Why |
|---|---|---|
| Postgres 16 + PostGIS | **Portable Postgres 16.10** in `.local/`, no admin install | No Docker or Postgres on the machine. PostGIS is not in the portable build; nothing in the schema uses geometry (`lat`/`lng` are numeric) |
| Python 3.12 | **System Python 3.14** | Windows Application Control blocks the DLLs of uv-downloaded Pythons |
| selectolax | **lxml** | selectolax's compiled module is blocked by the same policy |
| psycopg binary | **psycopg pure-Python + Postgres's own `libpq.dll`** | Bundled binary wheel will not initialise under the policy |
| Redis token bucket | **In-process per-host async bucket** | No Redis on Windows; per-host semantics preserved for single-process runs |
| Anthropic Batch API (P8) | **OpenRouter**, `anthropic/claude-haiku-4.5` / `anthropic/claude-opus-5`, `:batch` variants selectable | The user holds an OpenRouter key, not an Anthropic key. Same models, structured outputs supported |
| `icp_tier() IMMUTABLE` | **STABLE** | It calls `now()`; a clock-reading function cannot honestly be IMMUTABLE |
| I3 as a table CHECK | **Trigger** | `grade` lives on `lead`, `channel` on `outreach_touch`; a CHECK cannot span tables |
| `fit_score` 0..50 | **Clamped** to 0..50 | The raw sum of the spec's terms can exceed 50 or go negative |

## D-013 · First-party asset answers (closes O3, partly O2)

- **O3 — the firm dataset** (`LegalSoft Cold Email 37K`) **was purchased from a data vendor** →
  directory-tier precedence, below Places. Its `Employees Range` ("1 to 10" on every row) is
  headcount, not attorney count, and is visibly wrong for some domains (quarles.com: 58
  contacts). It is never used for `attorney_count`.
- **O2 — the job-history file** (`romeo-jobs`) carries **name + city + date, no links**. Match
  ladder rung "name + city": accepted **only when exactly one firm in that city clears the
  similarity threshold**; name-only rows are rejected. It writes fit attributes only — never a
  signal, never intent, never outreach copy. Its top posters include Robert Half, Adams & Martin,
  Upwork and "Confidential" — the agency filter runs first.

## D-014 · The G1 collapse-ratio band applies only to multi-source discovery

**Ruling:** the duplicate-domain and duplicate-phone queries are hard, always. The 2.0–3.3×
collapse band is enforced only when resolved observations come from **two or more** discovery
sources.

**Why.** The band is calibrated for three-way discovery — Places, bar directory and legal
directories naming one firm three times. A single contact-level vendor file has a different
expected ratio, and failing the gate on it would push someone to "fix" thresholds that are not
broken. The ratio is still reported.

## D-015 · Cross-firm components go to review, never auto-merge

**Ruling:** when a new observation links two firms that already exist, resolution writes an
`identity_review` row and merges nothing.

**Why.** Signals are immutable and carry `firm_id`, so a merged-away firm cannot be cleanly
unpicked. And the spec's asymmetry holds: *a false merge is invisible and unrecoverable; a false
split is visible and costs one duplicate.*

## D-016 · Vendor practice data is a crawl hint, never `primary_practice`

**Found on real data:** a keyword read of the purchased file's one-line descriptions set
`primary_practice` for 10,253 firms and **disqualified 508 as `DQ_NOVOLUME`**. They were false
positives like "representing employees in all aspects of employment" read as appellate (a tier-2
prospect), a criminal-defence firm read as complex commercial, and "a full service law firm"
read the same way.

**Ruling:** the description reading is stored as `vendor_practice_hint`, which has no firm column
and cannot set a tier. It only chooses which firms to crawl first.

**Why.** Doc 02 §4 already says it: vendor practice data is *"Coarse — site classification still
runs."* The firm dataset accelerates discovery; it does not qualify. After the change the tiers
are honest: 21,960 UNCLASSIFIED (never guessed) and 222 DQ_ENTITY.

## D-017 · An email domain keys a firm only when it visibly belongs to it

**Found on real data:** when a contact had no company URL, the loader used their email domain as
the firm's identity key. That filed "Faggiano & Associates" under **adlercohen.com** (another law
firm, which merged the two), "Bernice Lake PC" under **mattel.com**, and "Gursky Wiens" under
**umd.edu**.

**Ruling:** the email fallback is accepted only when a name-stem token of 4 or more characters, or
the stem's initials, appear in the domain label. Otherwise the firm stays domainless. Re-keyed
under `i1_domain_rule` v2 via the norm_version mechanism, with derived data re-built from the
untouched `observation` audit floor: 13 observations re-keyed, one false merge split.

**Why.** It is the spec's asymmetry again: a false merge is invisible and unrecoverable; a
domainless firm is visible and cheap.

## D-018 · Entity classification by name and domain; `entity_kind` gains `nonprofit`

**Found on real data:** the vendor file tags government offices and legal aid as "law practice".
Examples: usdoj.gov, a District Attorney on **orleansda.com**, Legal Aid of NW Texas, ACLU
chapters, university clinics. A `.gov`-only rule caught 36.

**Ruling:** a deterministic `classify_entity(name, domain)` with high-precision patterns (DA,
public defender, attorney general, legal aid, volunteer lawyers, `.edu`, and more) now catches
**222**. The `entity_kind` vocabulary gains `nonprofit` (migration 005), because the disqualifier
table names "non-profit legal aid" but the enum had no value for it. "Smith Legal Services" on a
`.com` gets no verdict: absence of evidence is not a verdict.

## D-019 · Probe findings: practice-word traps and homepage link discovery

**Practice vocabulary v2.** In the live probe, two personal-injury firms were classified as estate
planning from *"attorneys who **will** work…"*. `\bwills?\b` and `\btrusts?\b` match the commonest
words in legal copy, `\bvisas?\b` matches "we accept Visa", and `\broundup\b` matches a blog's "news
roundup". All four now need service phrases ("wills and trusts", "revocable trust", "work visa",
"Roundup weed killer"). `norm_practice` is bumped to v2.

**Link discovery.** On small-firm sites without a sitemap, the site mapper found only the homepage:
every guessed path (`/our-team`, `/practice-areas`) returned 404. The one site with full coverage
classified perfectly (contingency at 0.95, personal injury, Spanish intake), and the three with
homepage-only coverage all came back `fee_model: unknown`. P1 now reads the homepage's own
navigation (URL path, then anchor text, then the practice vocabulary for pages like "Car
Accidents") before any blind probe. The spec lists `discovered_via: 'link'`; it had not been built.

## D-020 · Contingency patterns extended from measured phrasings

**Found:** 29 of 150 "unknown" personal-injury firms stated contingency plainly, in words the
spec's three P6 patterns miss. Examples: "No **Fees** Unless We Win" (plural), "on a contingency
**basis**", "You **won't** pay anything unless you win", "We **don't get paid** unless you are
paid", "no **legal** fees, unless and until".

**Ruling:** the spec's patterns stay first, verbatim. Five extensions follow them, each annotated
with a real example, in `config/fee_patterns.yml`. Four traps are pinned as tests and must stay
`unknown`: "free consultation", "percentage of fault", "we accept Visa", "contingency plans".
Generic statements about lawyers in general ("most PI lawyers typically work on contingency") are
capped at 0.6 and never used as proof when the firm's own voice is available. P6 now also reads
contact, attorneys and team pages. **Effect on the probe: tier 1A grew from 48 to 71 firms, with
zero new requests** — all re-derived from stored HTML.

## D-021 · Careers parser v2, and the parser version joins the skip rule

**Found:** Dressie Law Firm listed three open roles as `<h3>` headings under "Employment
Opportunities". The v1 heuristic required the job word inside each heading, so it missed all
three. Two more defects: soft-404 pages (a 200 status with "page not found" content), and bare
`/employment` tagging employment-*law* practice pages as careers.

**Ruling:** v2 recognises page-level job context for section headings, while list items keep v1's
strict rule, since a qualification bullet like "experience as a paralegal" must not become a
posting. It detects soft 404s, drops `/employment` from careers paths, and adds missing titles
("front desk", "file clerk"). `careers_sweep.parser_version` (migration 091) now joins the
content hash in the skip-unchanged rule; otherwise a parser fix would never re-parse a page
already swept. **Effect: 1 posting → 7 postings at 3 firms.**

## D-022 · Charset-aware decoding, visible in every downstream version

**Found:** a hard-coded `decode("utf-8", errors="replace")` stored "won't" as "won�t". That
corrupted evidence quotations and blocked fee patterns.

**Ruling:** `lge/fetch/decode.py` tries the BOM, then the declared charset, then strict UTF-8, then
Windows-1252, and replaces characters only as the last resort. It is used by P4, the claim
readers and the careers watcher. The decoder and extractor versions are folded into P4's
`EXTRACTOR` string and into the claim writers' fingerprint, so a text-level change re-derives
everything downstream. Affected pages: 8 → 1.

## D-023 · A posting on the firm's own careers page is exempt from the agency rules

**Found (integration):** the careers watcher never sets `company_name`, because the firm is known
from `firm_id`. The agency filter's blind-posting rule rejected all 8 real careers postings, so
**zero signals** were created. Each builder's unit tests passed, because the test helper defaulted
a company name the real watcher never sets.

**Ruling:** per the spec, the firm's own careers page is "the one place the posting is
unambiguously tied to the firm". It cannot be an agency hiding its client. For `source='careers'`
with a `firm_id`, the agency rules are skipped; the support-role filter still applies. Pinned by
three integration tests using the real record shape.

---

## Standing rulings that were never in dispute

Recorded here because they are load-bearing and easy to erode:

| Ruling | Where |
|---|---|
| **Every targeting rule must trace to one of the four need conditions** | [icp.need-model](../10-icp/01-need-model.md) |
| **Never guess `fee_model`** — `unknown` is a first-class value | [icp.fee-model](../10-icp/03-fee-model.md) |
| **Resolve identity before crawling, not after** | [datamodel.identity](../30-data-model/03-identity-resolution.md) |
| **Invariants are DB constraints, not application code** | [datamodel.invariants](../30-data-model/05-invariants.md) |
| **Internal data enters through `observation` like everything else** — one exception | [firstparty.one-door](../50-first-party/02-one-door-rule.md) |
| **A name-only match is rejected, never merged** — in all three resolution contexts | [datamodel.identity](../30-data-model/03-identity-resolution.md) |
| **Store raw HTML and raw postings** — every version bump is a re-parse, never a re-harvest | [pipeline.orchestration](../40-pipeline/06-orchestration.md) |
| **Grade B is a product, not a reject pile** — and is never emailed | [icp.decision-makers](../10-icp/07-decision-makers-and-lead-record.md) |
| **Keep tier 4 and holdouts in the system** so the fee-model axis stays falsifiable | [icp.fee-model](../10-icp/03-fee-model.md) |
