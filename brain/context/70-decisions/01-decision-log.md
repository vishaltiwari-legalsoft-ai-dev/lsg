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

## D-024 · Duplicates found after crawling are merged by retirement

**Found (gate G1):** "Seelig, Dressler, & Ochani, LLC" arrived as two vendor firms,
`sdonylaw.com` and `dresslerlawllp.com`. The firms' own sites share a name and the phone
`+12122391061`, identity keys the discovery sources never carried.

**Ruling:** signals are immutable and carry `firm_id`, so firms are never physically merged. The
duplicate gets `merged_into = survivor`. Its open lead closes as a duplicate, and its contacts
move to the survivor. Its name, domain and phone become aliases, and its signals count toward
the survivor's intent. Merged firms leave lists, scoring and G1. A person decides each merge in
the identity review queue, and every decision is written to `review_decision`. **Status:**
specified in `plan/api-contract.md` Revision 2; migration 093 and `merge_firms` not built yet
(092 went to the NO_WEB re-check, D-026).

## D-025 · Precedence ranks the AI tier, not the prompt revision

**Found (before the first paid P8 run):** `config/precedence.yml` named `llm:p8:v1` and
`llm:p9:v1`, while P8/P9 write `llm:p8:v2` and `llm:p9:v2` after the prompt bump. Reconcile matched
tags exactly, so every AI attorney count would have been discarded (an exclusive attribute). AI
practice answers would have ranked below the purchased list. And a P9 answer could never break
the fee-model escalation loop. Every unit test used `v1` tags, so all passed.

**Ruling:** precedence lists the tier (`llm:p8`, `llm:p9`), and `reconcile.source_family()` maps
a tag onto it. Within a tier the newest observation wins; at the same observation the higher
prompt revision wins. Pinned by four tests using `v2` tags.

## D-026 · The basics audit: reach the site, find the careers page, read the fee promise

**Found (14 Sep 2026, on the 242-firm probe, before anything downstream is touched):**

1. **38 firms were "no website" without a single page fetch.** P1 sent a lead to NO_WEB
   whenever robots.txt was blocked at the edge (20) or unreachable (18). No policy was read
   in either case, and NO_WEB had no way back. One of those sites answered 200 the next day.
2. **44 crawled firms (22%) got 403 on every page.** Cloudflare rejects Python's TLS
   fingerprint on those hosts; plain `curl` with the identical honest User-Agent gets 301/200.
   HTTP/2 and standard Accept headers change nothing.
3. **Careers discovery guessed.** 191 of 205 careers URLs were blind `/careers` probes and 126
   of those were 404s. 14 of the 31 pages that answered 200 had redirected to the homepage or
   a "not found" page and were counted as careers pages. A real opening linked from a homepage
   ("B|K is Hiring a Personal Injury Paralegal") was never mapped.
4. **Fee promises live in the site chrome.** Of 57 unclassified firms, 8 said "No fees unless
   we win" / "No Recovery, No Fee" / "Contingency-Based" only in the header, footer or title,
   which the main-text extractor strips as boilerplate. P6 and the AI reader both saw main text
   only.

**Rulings:**

- **NO_WEB is a verdict, not a network condition.** P1 assigns it only when there is no domain
  or a published robots rule closes the site. Blocked-at-edge and unreachable hosts get no
  verdict: nothing is written, the lead stays DISCOVERED, and the run does not mark the firm
  done, so the next run tries again. Migration 092 adds NO_WEB → DISCOVERED for the 38 already
  parked.
- **We do not get around Cloudflare.** No browser impersonation and no swapping the transport
  to dodge a fingerprint rule. Those hosts are recorded as `edge_blocked`, truthfully, and the
  firms need another source. This keeps the standing rule "never defeat bot management".
- **The careers page is found, not guessed, where possible.** Hiring anchors and paths read
  off real homepages join the mapper (`MAPPER_VERSION` 2 re-maps every firm). A probe that
  redirects to the site root or an error page is treated as 404 and the cascade continues.
  The watcher sweeps only URLs the site published or linked (up to 3 per firm); when the map
  holds nothing but guesses it runs the full probe cascade. Before this, the alphabetically
  first map row — the guessed `/careers` — beat butlerfirm.com's real posting URL and a 404 on
  it ended the search.
- **P6 reads the whole visible page (v2):** title, meta description, nav, body and footer, one
  line per block, from the stored HTML. Slogan patterns ("No Recovery, No Fee", "No Win No
  Fee", "Contingency-Based", "doesn't collect a fee unless") join the config.

**Found on the re-run (15 Sep 2026), same audit:**

5. **A page that is itself the posting parsed to nothing.** butlerfirm.com's h1 "We are Hiring
   a Paralegal" has no heading or list item naming a role, so the listing heuristic found no
   openings. **Ruling:** the announcing phrase names the role when it has a subject ("we are",
   "is", "now" hiring …) and the role is a support role; the page is that one posting. Parser
   v3.
6. **The same two open roles minted a second `multi_opening` signal** the first time a sweep
   crossed a week boundary, and the first never closed. **Ruling:** a multi_opening is keyed by
   the set of open role signals it is derived from, not by the week; a changed set is a new
   signal and the superseded one closes in the same write.
7. **One host held the whole batch.** cavanaghlawgroup.com declares `Crawl-delay: 600`; honouring
   it made one firm's 13 pages a two-hour tail behind every other host. **Ruling:** the delay is
   still honoured, never shortened, but a host gets a per-run budget: P2 fetches what fits five
   minutes, most valuable pages first (home, careers, practice, …), and records the rest as not
   fetched this run. Above a 60-second delay the mapper probes only and the careers watcher makes
   one request.
8. **"Per hour" read speed.** With the whole page in view, the spec's bare `per hour` pattern
   matched "must slow to 10 miles per hour" and "e-bikes travel up to 28 miles per hour" on
   accident-law articles, and put Dressie Law Firm (a personal-injury firm with two open support
   roles) on the hourly, non-billable tier. **Ruling:** hourly needs money or a billing word next
   to it, and a match inside a negated clause ("we never charge hourly rates", "we do not work on
   a contingency basis") counts for nothing. The clause ends at the last comma, dash or
   conjunction, so a promise after the dash still stands. P6 v3.

## D-027 · The band tabs show the pipeline; the export keeps the hygiene

**Found (15 Sep 2026):** with the basics fixed, butlerfirm.com was Tier 1A, had an open paralegal
role and a named owner, and was invisible: the Sequence tab showed only leads that already pass
every email-list check (grade A, verified email, tiered, draft renders), and everything else sat
under "Excluded" with a raw code. The user could not see the leads being worked on.

**Ruling:** `category` stays the email list's verdict and `build_list` / the CSV export stay
strict. The screen gets a second reading of the same classification: `pipeline_band` (the lead's
band unless it is out — score too low, disqualified, suppressed, cooling down, a portal or
displacement customer, or on the phone list) and `blockers` (what still keeps it off the list,
as plain words). Not tiered yet because the fee model is unknown counts as in play. The API's
band tabs select on `pipeline_band`; Excluded is only what is actually out; every list-hygiene
code has a plain-word label (`reason_display`). Also found here: `days_open` compared a +05:30
timestamp's date with a UTC date and showed "open -1 days" — one calendar (UTC) now.

## D-028 · Emails printed on the firm's site are read; a contact must be a person

**Found (15 Sep 2026):** every email on file came from the purchased list. 100 of the 157 reached
firms print an address on their own pages, 52 a personal one (michelle@dressielaw.com,
dfried@friedbonder.com), and none was captured. Separately, 73 `contact` rows were not people —
"Chicago Injury Attorneys Near Northwestern Memorial Hospital", "Lawyers With An Edge", "Beattie
Law Firm", "Administrator" — from structured data, AI reads and the vendor list alike, and R3 had
minted email addresses for them.

**Rulings:**
- **`r_site_emails` (Plane R)** reads the stored HTML, never re-fetches: `mailto:` links, visible
  text and "[at]" spelling, on the firm's own domain only. A personal address attaches to the
  one contact whose name renders to that local part under R3's patterns; an ambiguous or
  unmatched local part is never guessed onto a person. General inboxes become the
  `general_email` claim, hiring inboxes `hiring_email`, everything found `site_emails`
  (source `site:page`). Rows are `unverified`; R4 verifies. Cloudflare's `data-cfemail`
  obfuscation is deliberately not decoded — it is an anti-harvesting measure.
- **`lge.classify.people.person_name`** gates every contact source: title suffixes (" -
  Personal Injury Lawyer"), credentials (", J.D., Ph.D.", "Esq.", "Jr.") and honorifics are
  stripped; a name is a person when it has two to four tokens, no digits, no "&", and no
  practice or firm words. The vendor loader, P5's people and the AI's decision makers all pass
  through it. The 73 existing non-persons were removed (2 leads re-pointed to another
  decision-maker, 1 left without one) and 261 names cleaned.

**Effect on the probe:** 17 site-printed addresses now sit on named owners/office managers at 13
firms; 54 firms have a general inbox on record; 65 of 157 reached firms have a first-party
(non-vendor) email for a decision-maker.

## D-029 · Step 1 rebuilt: any sheet, in batches, with the website verified

**Asked for (15 Sep 2026):** inputs are whatever the team has, not the one vendor layout; find
firm name, website, location, size, type (mandatory) and the rest (job post, contacted before and
when) intelligently; process in batches; verify every website and search for the real one when
the sheet's is wrong; re-check data health after.

**Rulings:**
- **`lge.ingest`** owns the sheet: reader (CSV in any encoding/delimiter, XLSX), a fixed field
  vocabulary, a sniffer that reads headers *and* values (a typed value shape beats a misleading
  header; an exact header for an untyped field keeps its meaning; the more specific synonym wins,
  so "Company City" beats "City"), a normaliser to one canonical row, batches of 500 by default,
  and a health report per batch. Every downstream step reads canonical keys only; the vendor
  loader is a caller of the same path, and the 36,814 rows already stored were rewritten into the
  canonical shape with the original kept under `_raw`.
- **Tables:** `import_file` (the sheet, its confirmed column map, what mandatory data it lacks),
  `import_batch` (one row per batch with status, counts, health, error), `website_check`,
  and `observation.import_id/batch_no`. Migration 093.
- **Website check:** missing/malformed → search; robots.txt unreachable → dead → search;
  blocked at the edge → recorded, never searched (the site exists); answers → the page must
  name the firm, else mismatch → search. A search hit is a *candidate*: it is adopted only
  after its own homepage passes the same name check. The first live run adopted eight
  directories on a snippet alone (w9ein.com, lawyerguide.com, datanyze.com); those were
  reverted and re-checked. A correction writes a `search:ddg` observation, the old domain as
  an alias, and the firm's domain under the `resolve` writer; a found domain that already
  belongs to another firm opens an identity review instead.
- **API and UI:** upload → mapping with confidence and reasons, editable → load in the
  background with the identity, claims and contacts steps chained → progress per batch.

## D-030 · Step 2, part A: the crawler reads the whole firm, not eleven guessed paths

**Asked for (15 Sep 2026):** "we have piss poor weak scrappers" -- from the site, read the
careers landing page, the contact page, the locations, the important names and designations,
recent developments and testimonials; extract emails, names and links for outreach; then search
for the LinkedIn profiles and the Google Business reviews; then read intent from the pain.
Part A is the reading; parts B-D (per-page facts, searches, intent signals) build on it.

**Rulings:**
- **Three new page kinds:** `locations`, `testimonials`, `news` -- where the firm sits, what
  clients say, what it has been up to. Migration 094 widens the `page_kind` checks and adds
  `'crawl'` to `discovered_via`.
- **P2 crawls, it does not only fetch the map.** Every page P2 reads is parsed for its own
  links; same-host links of a wanted kind are queued up to the per-kind cap (config
  `caps`) and a total of 30 per firm, two levels deep from the map. Pages found this way are
  written to `site_map` as `discovered_via='crawl'` and are excluded from P2's input hash, so
  a re-run stays a no-op unless the map or the caps change. Slow hosts (Crawl-delay > 60s)
  get the map only.
- **A fetched page is not always a page.** A body under 250 words that says "not found" is
  recorded as `document.soft_404 = true` and ignored by P4 and every claim reader; a body that
  is byte-identical to a page already stored for the firm is skipped (`duplicate_of`); the
  reason a fetch failed is kept in `document.fetch_error` instead of being lost in a log line.
- **The renderer is the system Chrome**, `--headless=new --dump-dom` under our own honest
  User-Agent, found via `LGE_CHROME` or the usual install paths. Playwright's browser download
  is blocked by Windows Application Control on this machine; the installed Chrome is not. A
  rendered DOM replaces the document's bytes, hash and word count and its extracted text is
  dropped so P4 reads it again. No browser: the gate still flags, the note still counts.
- **Caps:** home 1, practice 6, careers 3, contact 2, about 2, attorneys 3, team 3,
  locations 2, testimonials 3, news 4, fees 1, other 2, total 30 (was 14). The mapper is
  `MAPPER_VERSION=3`, so every firm is re-mapped once.
- **Not changed:** robots.txt is still obeyed, the per-host interval is still max(2s,
  Crawl-delay), the edge block is still not circumvented (D-026). A robust scraper is one that
  reads more of what it is allowed to read, not one that reads what it is not.

## D-031 · Step 2, part B: the site's facts are read, not guessed

**Asked for (15 Sep 2026):** from the site, the careers landing page, the contact page, the
locations, the important names and their designations, recent developments and testimonials;
the emails, names and links that outreach needs.

**Rulings:**
- **`px_site_facts`** (source `site:page`) reads every stored page once, contact page first:
  `phone_e164`, `address`, `city` (reconciled onto the firm after `site:jsonld`);
  `office_locations`/`office_count`; `site_people` (name, printed title, profile URL) and
  `staff_listed` (attorneys / support / other); `testimonials` and `site_review_summary`;
  `social_links`, `review_profiles`, `google_maps_url`; `recent_posts`, `latest_post_date`,
  `growth_news`; `live_chat_vendor`, `online_intake_form`, `copyright_year`; and `site_gaps`.
  Config in `config/site_facts.yml`; a config edit re-reads every firm.
- **A person on a page is a Title-Case name with no job word in it.** `person_name()` alone
  let "Learn more" and "Senior Litigation Paralegal" through; the page rule (`name_like`)
  does not. The title is the first job-looking line after the name and before the next
  person's name in the smallest container that holds both. A profile link whose label is not
  a name takes its name from the slug.
- **`r_site_contacts` consumes `site_people`** the way it consumes P5's `jsonld_people`: role
  from the printed title via `classify_role`, source `site:page`, upgrade-not-duplicate
  against the vendor row. A person named without a title is kept at the extractor's own
  confidence so a printed email can still attach to them.
- **A gap is claimed only where the page that would carry the thing was read.** No home
  page fetched, no gap list. The gaps: no careers page, no online intake form, no live chat,
  no Spanish, stale copyright (two years or older), no testimonials, no or stale blog (a year),
  no support staff listed among the people named, no social profile, no review link. Part D
  reads these as pain.
- **A previous office's zip is never the next office's house number**: the street name in an
  address is words, never a bare number. Found on the fixture, would have been found on the
  first real contact page.

## D-032 · Step 2, part C: two web searches, logged once, LinkedIn never fetched

**Asked for (15 Sep 2026):** with a name, search `<firm> + <person name> + linkedin profile`;
without one, `<firm> + Location + Google business reviews`.

**Rulings:**
- **`r_search_links`** (Plane R) runs both under `live=1`, through the same throttled
  DuckDuckGo call the website check uses. Per firm: at most four people without a LinkedIn
  URL, owners first, then admins, then attorneys; then one reviews query.
- **A profile is adopted only when the result names the person**: a `linkedin.com/in/`
  result whose title or slug carries both name tokens. The firm's name in the title breaks
  ties between namesakes -- minus the person's own surname, since an eponymous firm proves
  nothing. Only the URL is written (`contact.linkedin_url`); LinkedIn is never fetched.
- **Reviews are read off the snippets**, never off Google itself: the Maps result's
  "4.9 (312)" when there is one, otherwise the largest "N reviews" printed anywhere. Claims
  under `search:ddg`: `google_business_url`, `google_rating`, `review_count` (now with a
  precedence entry, so the fit score's `review_count > 40` reads it) and
  `search_review_snippets` for Part D.
- **`search_log`** (migration 095) records every query with the results considered and the
  outcome; a person or firm is not searched again for 90 days, a failed search is retried
  next run. The adopted URL or claim can always be traced to the result that produced it.

## D-033 · Step 2, part D: pain is read into intent

**Asked for (15 Sep 2026):** intent-to-buy signals from pain -- testimonials, Google reviews,
anything lacking in the website.

**Rulings:**
- **`ja7_pain_signals`** writes ordinary `signal` rows, so the intent score, the proof panel
  and closure need nothing new. Three kinds from the gap list (migration 096):
  `no_intake_channel` (no intake form AND no live chat; weight 6, contest NONE),
  `no_support_staff_listed` (people named, none with a support title; 8, LOW),
  `stale_site` (copyright two years old OR blog a year quiet; 4, NONE). One per firm and
  kind, first seen when the gap was first read; a gap the next crawl finds filled closes it.
- **A closed signal of any kind weighs nothing.** Only `job_posting_open` zeroed on closure
  before; a closed `multi_opening` kept its 10. A gap that is filled must stop counting the
  way a filled posting does.
- **Review pain comes from search snippets, not from the firm's own testimonials.** A
  testimonial is praise by construction, and the complaint in "the other firm never called
  me back, then I found X" is about the other firm. A snippet that names the firm and says
  it was unreachable ("never called me back", "no communication", "took months to") becomes
  `review_unreturned_call` with the sentence as the quote; "never failed to call me back"
  and "no communication issues" do not.
- **Growth headlines from the last year** ("opens new Marietta office", "joins the firm")
  become `new_office_or_lateral`, first seen on the post's date. Older posts are history.
- **Not done here:** journey copy for the new kinds. `select_touch1_variant` maps them to no
  touch-1 variant, so they raise the intent score and show as proof but do not, on their
  own, start a sequence -- that is Step 3's revamp.

## D-034 · The probe crawl at thirty pages: what broke, what was fixed

**Found (15 Sep 2026)** running the rebuilt crawler over the 242 probe firms (2,838 pages OK
across 200 firms, 441 found by crawling, 723 not fetched behind an edge block):

- **The per-host time budget bounded the map, not the crawl.** A host asking Crawl-delay 30s
  got its thirty pages in fifteen minutes. Pages found by crawling now count against the same
  budget (`page_budget = min(caps.total, 300s / Crawl-delay)`).
- **The render gate would have rendered every thin page.** With contact and office pages in
  the map, 1,037 pages were under 500 words; 29 were JavaScript shells. P3 renders only a
  shell (a root element and scripts, almost no text); a thin static page is left alone.
- **P7's fingerprints backtracked on minified JavaScript.** Every pattern opens with
  `(?:[\w-]+\.)*`, and the haystack was the whole inline script; 300 KB of `a.b.c.d(...)` cost
  minutes per page. Inline scripts now contribute only their URL- and host-shaped tokens.
- **`once()` masked the real error.** A unique violation inside a body aborted the
  transaction, and the 'failed' mark failed in turn. The body runs under a savepoint now.
- **A render can produce a DOM already on file** for the same URL (`(url, content_hash)` is
  unique). P3 marks the row rendered and leaves it as it was.

## D-035 · The people's addresses come from search; the pattern mints the rest

**Asked for (15 Sep 2026):** "for every firm you were able to actually get only one email ...
if you do it seriously using the DuckDuckGo library ... you will be able to get a lot of details."

**Rulings:**
- **`r_search_emails`** asks `"@<domain>"` for the firm and `"<person>" "<firm>" email` for up
  to four decision-makers without an address, and reads addresses off the result snippets
  (bar directories, Avvo/Justia, filings, PDFs) -- never the pages behind them. An address on
  the firm's domain attaches to the contact it renders from, or to the person the snippet
  names beside it (exactly one personal address in a snippet that carries both name tokens);
  general and hiring inboxes become claims; off-domain addresses are recorded, never attached.
- **`r3_email_pattern` recognises eleven schemes**, not five: first.last, flast, first,
  firstl, last, firstlast, first_last, lastf, f.last, last.first, lastfirst. What search and
  the site attach is the evidence it learns from; it then mints an address for every other
  named person at the firm, `status='unverified'`, pattern recorded.
- **Result on the probe** (before any search results landed): average addresses per firm
  2.7 → 8.9; firms with five or more 32 → 105; 2,319 of 2,745 named contacts carry an
  address. Every minted address is unverified and says so; R4 verification is a later step.
- **Searches survive a bad network.** The search helper retries a dropped connection, a
  timeout or a rate limit after 15s and 45s; the search components stop after five
  consecutive failures and leave the rest for the next run; a failed query is asked again
  next run while a found/not-found answer stands for 90 days. (Found the hard way: 458
  ConnectErrors in one night, none retried.)

## D-036 · The user can act

**Asked for (15 Sep 2026):** "as of now interface is just an outlet to see what is happening
it does not give any power to the user" and "prepare a better lead life cycle journey".

**Rulings:**
- **The engine's sixteen states stay the truth; a person sees a stage.** `stage_of()`
  (`lge/api/stage.py`) derives one of fourteen task-shaped stages -- researching, no website,
  needs a decision, needs a person, ready to reach, parked, in outreach, replied, handed off,
  won, lost, disqualified, do not contact, needs a refresh -- and a next action ("Find an email
  for Jane Doe") from the state, the cooldown and the primary contact. Never stored.
- **Research on demand** (`POST /api/firms/{id}/research`, scope full or contacts): the
  engine's own components run for one firm in the background, in flow order, under live=1,
  each step's outcome written to the job row as it goes (migration 098, `action_job`). The
  screen polls the job and refetches the case file when it finishes.
- **Decisions move a lead only through whitelisted transitions.** Migration 098 adds the ones
  a person needs: disqualify from any working state, reopen a disqualification (to
  CLASSIFIED) or a loss (to the pool), qualify on judgement (grade B until an email is
  verified), hand a warm lead to sales, send a stale record back for research. Every decision
  writes the state event with actor `ui` and a note; a refused one says why.
- **People are corrected, never silently overwritten.** A person can be added (source
  `user`), corrected, chosen as the primary contact, or struck out -- `removed_at` keeps the
  row so the engine does not re-add the same name and the history stays.
- **Batch** (`POST /api/leads/batch`, up to 100): research, find people and addresses,
  disqualify, park, assign -- one answer per lead.
- **Not done here:** authentication (actor is always `ui`), journey copy for the new signal
  kinds, and a stage-grouped work queue screen. The band tabs still lead.

## D-037 · The pipeline is the interface

**Asked for (15 Sep 2026):** "redesign the whole UI ... make a landing page for this what it
does and everything, as of now I'm too confused."

**Rulings:**
- **The screens are organised around the five steps the team thinks in** -- Lists, Research,
  Qualify, People, Outreach -- not around the engine's internals. `GET /api/overview` tells
  that story with live counts; the home page renders it as five stations on one track, then
  what needs a person, what the engine is doing, and a glossary. The rail carries the same
  five counts on every screen.
- **The work queue groups leads by what they need next**, not by band. `GET /api/leads?stage=`
  pages every open lead at one of the fourteen stages (`stage_sql`, the same rule as
  `stage_of`), with the band as a "priority" filter in plain words. The band views and the
  CSV exports still exist; they are no longer the primary navigation.
- **Every engine word gets a plain name on screen** and the engine's own label is kept where
  it is precise: Band → Priority (Strike / Sequence / Nurture / Hold, each with a one-line
  meaning), Proof → Why now, Case file → Lead, Docket → Work queue, Hand-check → Accuracy
  check, Imports → Lists, Fit / Intent / Contest → Fit / Urgency / Competition, The record →
  History. The contract's fields are unchanged; only the copy moved.
- **The firm page opens with what outreach needs**: at a glance (practice, fee model, size,
  staff listed, phone, address, offices, inboxes, chat, intake form, software, reviews, social),
  the research buttons with the job's progress, why now, people, what the site says; every
  claim and every page read fold away. A list fact read and found empty says "none on the
  pages read", never "unknown".
- **Visual language kept, extended**: the brand base (Rubik, cobalt, the yellow evidence mark)
  stays; a display type step and a live-number step were added for the home page, and one new
  hue -- signal amber -- is reserved for urgency. No card grids; ruled sections and one panel
  style.

## D-038 · Every named person gets a LinkedIn profile; LinkedIn is still never fetched

**Asked for (15 Sep 2026):** "create a LinkedIn profile scraper so the list of individuals we are
getting from every website ... we will try to find their LinkedIn accounts."

**Rulings:**
- **Every named person is searched**, not only four decision-makers: `r_search_links` asks
  `"<firm>" "<person>" linkedin` for each contact without a profile, owners first, up to
  `max_people` per firm (12) and `max_queries` per run (600); the rest wait for the next run.
- **The profile is read off the search result, never off LinkedIn.** The result's title is
  "Name - Headline | LinkedIn" and its snippet carries "Experience: … · Location: … · 500+
  connections"; the headline and location are kept on the contact (migration 099), and a
  title the site never printed is filled from the headline ("Partner at X" → "Partner", role
  classified from it). Fetching LinkedIn pages would breach its terms and get the crawler
  banned, which would cost the search route too; the standing rule stands. Full profile data,
  when it is wanted, comes through LinkedIn's own APIs or a licensed provider, as an adapter.
- **The firm's company page** is found the same way (`"<firm>" linkedin company`), with the
  headcount the snippet prints ("51-200 employees") as `linkedin_headcount` -- a second
  reading of firm size beside the sheet's and the site's.

## D-039 · A bot check is not "no results"; the search backs off and stops

**Seen (15 Sep 2026):** twenty minutes into the LinkedIn pass at one query every 2 s,
DuckDuckGo began answering HTTP 202 -- its anomaly page -- instead of results. The `ddgs`
library folds that into "No results found.", so 251 people, company pages and review
listings were logged `not_found`, which the planes do not ask again for 90 days.

**Rulings:**
- **The wrapper reads the status itself.** `webcheck._raw_search` sends the one request
  through the library's DuckDuckGo engine and raises `SearchBlocked` on 202/403/429; a 200
  with no result nodes is the only thing that counts as an empty answer.
- **A bot check means slow down and stop, never work around.** On the first check the
  wrapper waits 90 s and asks once more; on the second it fails every later query for
  20 minutes, so the planes' five-failure breaker halts the run and its note says why.
  No identity rotation, no proxies, no solving the page -- the standing rule.
- **One query every 5 s**, not 2: the rate that tripped the check is not a rate we run at.
- **Tonight's empty `not_found` rows were re-marked `failed`** (241 LinkedIn, 47 company,
  27 reviews, 4 emails) so the next run asks again; a false "not found" hides a person for
  90 days, a retry costs one query.
- **Headlines end at the first "LinkedIn" or ellipsis**: the engine glues several page
  titles into one ("... | LinkedInJoe Bloggs posted on LinkedIn ..."), and the glued tail
  was landing on the contact.

## D-040 · A research job runs on its own thread, after its row is committed

**Seen (16 Sep 2026):** every research job the screen asked for since D-036 stayed
"queued" forever. FastAPI 0.141 runs a background task *before* the dependency exit that
commits the request connection, so the worker, on a fresh connection, looked for a job row
that was not committed yet, found nothing, and returned without a word.

**Rulings:**
- **The route commits the job rows itself, then starts one thread per job** (`_launch_jobs`).
  Not a Starlette background task: besides the visibility race, a task that runs for
  minutes would keep the pooled request connection checked out for the whole job.
- **Tests replace `_launch_jobs`**, never `commit`: the API tests share one transaction
  per test, and nothing under it may commit.
- **A worker that finds no row says so** in the log instead of returning silently.
- **At startup the API fails every job still queued or running** -- they belonged to the
  process that died -- with an error that says to run it again, so the screen stops
  waiting and the firm is not locked behind a ghost job.
- **The email search asks only about live people**: struck-out contacts and headings the
  site parser once took for names ("REAL ESTATE MATTERS") are skipped, as the LinkedIn
  search already did.

## D-041 · One search per firm finds its people; the engine is asked a tenth as often

**Asked for (16 Sep 2026):** "ddg ko optimize nhi kr skte?" -- after D-039 the LinkedIn
pass was one query per person at a pace DuckDuckGo would not tolerate for long: about
250,000 queries for the full list, and a bot check within twenty minutes.

**Rulings:**
- **A sweep per firm first**: `site:linkedin.com "<firm>"`. Every profile on the results
  page is matched against the firm's named people without a profile (up to 60, owners
  first; both name tokens required, one result per person). The company page and its
  headcount ride along in the same results. A second page is asked for only when the
  first was full (8+ profiles) and people are still unmatched. This supersedes D-038's
  `"<firm>" linkedin company` query, which is gone.
- **A query of their own only for decision-makers the sweep missed** (owners and
  administrators, `max_people` per firm, default 4). Attorneys and unknowns are found by
  the sweep or not at all. The email search trims the same way: per-person email queries
  only for decision-makers the firm query and the pattern left without an address.
- **The pace of one careful person**: a query every 8-12 s (jittered) and a rest once
  fifty have gone out within ten minutes. That honours the engine's limit; rotating
  addresses or fingerprints would dodge it and stays off the table (D-039).
- **What it adds up to**: roughly 30,000 queries for all 22,000 firms instead of
  250,000, about three days of background running, free. Coverage is bounded by what
  DuckDuckGo indexes; a paid search API (Brave, Google CSE) would drain the same queue in
  hours and slots in as an adapter when a key exists.
- **The run's note is one string** for both stop reasons, so "the rest wait for the next
  run" is never dropped (the review finding on bc8b4a2).

## D-042 · Scraping, web search and LinkedIn first; outreach refinement last

**Asked for (17 Sep 2026):** "don't jump on the conclusion that you have to build this ...
if we crack down the scraping part, the web search part and the LinkedIn part, we are at
90% of the job. Then refining what you have to send comes after." Also: the sheet reader
must be flexible and AI-operated, the ICP strict, DuckDuckGo replaced, and the interface
made presentable and reusable by a team.

**Rulings:**
- **The order of work is `plan/plan-v2.md`**: sheet in → scrape → search → LinkedIn, each
  measured on the 242-firm probe before the full list; the strict ICP alongside the scrape;
  the team interface as data lands; outreach copy last. `PLAN.md`'s milestone sequence is
  superseded; its scope is not.
- **No field on a sheet is hard-required except a firm name plus a website or a location.**
  The AI reads the header and sample rows and says what the sheet has and lacks; every other
  field is research-fillable, and the sheet's value is one source among several. The site's
  own headcount and LinkedIn's headcount become valid sources of firm size (today only the
  sheet and the LLM team-page reading may set it).
- **The crawl reads six page kinds** — home, about, contact, team/attorneys, testimonials,
  careers — capped around 12 pages, not 12 kinds and 30 pages. Google Business Profile comes
  from search, not the site.
- **Search runs behind one adapter with interchangeable engines.** DuckDuckGo stays only for
  a keyless machine; a paid engine (Serper first, Brave as fallback) is the production path.
  Every people query carries the firm's city. LinkedIn is still never fetched (D-032, D-038);
  a licensed enrichment provider for decision-makers is an adapter, not a scraper.
- **Plan before build.** A change of direction is written here and in `plan/` before any
  code moves; the user reads the plan, not the diff.

## D-043 · Chunk 1: the AI reads the sheet, the values check it, the rows stream

**Built (17 Sep 2026)** as plan-v2 workstream 1, on the seams in `lge/settings.py`.

**Rulings:**
- **Two mandatory groups, not five.** `firm_name`, and `reach` = any of website, email,
  city, state, zip, address, location. Size and type left the mandatory list; each
  research-fillable field says where research gets it (`Field.filled_by`), the column map
  lists what the sheet lacks as `research_fills`, and the import screen shows "filled by
  research", never "missing". The health score is coverage of the two groups only.
- **`ColumnReader` is the seam** (`lge/ingest/columns.py`): `rules` is the sniffer,
  `llm` asks the model once per sheet (`lge/llm/sheet_reader.py`, strict schema, twelve
  sample rows, cells trimmed to 60 chars) and then reconciles: a typed field the values do
  not look like keeps the rules' reading with the disagreement in the reason; a column the
  AI left null is rescued by a rule guess of 0.9 or better; an unknown field name is noted
  and ignored; a model that cannot be reached means the rules read the sheet and the map
  says so. The map records its `reader`; a map stored before this loads with `rules`.
- **Measured on the real probe sheet:** all ten columns right, 8.9 s, five useful notes on
  the sheet's gaps. On a generated 100,000-row CSV: head 0.03 s, count 0.67 s, 200 batches
  streamed in 0.76 s, 25 MB peak. `register_import` reads a 2,000-row head and counts the
  rest; `load_import` walks only the pending batches in one pass; `upload_import` is a
  plain `def` so the parse and the model call run on the threadpool.
- **Tests never reach a provider.** `tests/conftest.py` pins every seam to its keyless
  implementation before settings are first read.
- **Found on the way:** the frontend's `api:types` still pointed at the sibling path from
  before the repo move. Fixed; the contract and the generated types carry
  `research_fills`, `reader` and `filled_by`.

## D-044 · Chunk 2: six page kinds from one config line; the site's own count is a size

**Built (17 Sep 2026)** as plan-v2 workstream 2. The user's brief: the landing page, about,
testimonials, careers and the Google Business Profile -- "not more than that". Contact and
the attorneys/team pages stay because that is where the emails and the names come from.

**Rulings:**
- **`config/crawl.yml` `caps` is the one list of what the engine reads.** A kind above zero
  is mapped by P1, crawled into by P2 and read by every claim reader; a kind at zero is
  still classified (a link to it is recognised) but never fetched, probed for, or read.
  `lge/fetch/config.py` answers `wanted_kinds()`, `crawl_into_kinds()`, `only_wanted()`
  and `kind_cap()`; the fetcher's `WANTED_KINDS`, its `_KIND_PRIORITY` table and the
  mapper's `_OTHER_KINDS` are gone. Six kinds, twelve pages: home 1, contact 1, about 1,
  attorneys 3, team 2, careers 2, testimonials 2. Practice, news, locations, fees and
  other are at zero. `MAPPER_VERSION` is 4.
- **A gap about a page kind is claimed only when that kind is read.** With news at zero,
  "no news page" would have fired on every firm; it and "no careers page" and "no
  testimonials" are gated on the kind being wanted. `stale_site` now comes from the
  copyright year alone.
- **The attorneys the site names are a source of firm size.** `px_site_facts` writes
  `attorney_count` = the attorneys counted on the attorneys/team page at confidence 0.65
  -- above reconcile's 0.6 bar so it can tier, below the LLM's stated count, which
  outranks it in `config/precedence.yml`. Only from a page that lists the team; two names
  in a footer say nothing. The vendor sheet's employee range still never sets it.
- **The wanted kinds are part of every reader's version** (`kinds_version()`), so a
  change to the list re-derives every firm even where its pages did not change. Found
  because the first re-run skipped 84 firms and left their gap lists as they were.
- **A reader's run is the complete set of its claims for a firm.** Claims are keyed by
  observed_at and reconcile prefers the freshest within a source, so a gap list or a fee
  reading taken off a news or practice page fetched *later* than the home page stood as
  the freshest word after those kinds stopped being read -- two probe firms still said
  "no news page", and 617 claims on the probe came from pages the engine no longer reads.
  `claim_run(conn, firm_id, *sources)` (`lge/planes/p/_claims.py`) wraps one firm's
  derivation: every `write_claim` under it is recorded (a context variable, so the
  readers' helpers did not change), and on a clean exit the reader's other claims for
  that firm are deleted. A firm with no page of a wanted kind keeps no claims from that
  reader at all. An exception leaves everything as it was. The HTML is the audit trail,
  not the row (write_claim's own rule). Applied to `px_site_facts`, `p6_fee` and
  `px_site_rules`; their versions are v6, v4 and v2 so the rule ran once over every firm.
- **Measured on the 232-firm probe**, re-deriving from pages already on file: pages the
  crawl reads 3,611 -> 1,954 (-46%; practice pages alone were 1,151); firms with a known
  size 75 -> 112 (+49%, 57 of them from the site's count); fee model known 105 -> 100
  (five firms' fee promise lived only on a practice or fees page); practice areas
  147 -> 146; people 148 -> 148. One firm moved to `DQ_SIZE`: Tanenbaum Keale lists 51
  attorneys on its people page and the LLM had returned null -- the right answer. Open
  pain signals: `stale_site` 37 -> 25 (no `stale_news` any more), `no_support_staff_listed`
  97 -> 78; `new_office_or_lateral` stays at 7 -- those headlines are on the home pages.
- **Not done here:** LinkedIn's headcount as a further size source waits for the search
  chunk (3), where it is read. The probe's `site_map` still holds its old practice and news
  rows; P2 ignores them, and the next P2 run over the probe re-fetches the twelve pages once.
- **Reading a practice page is one config line away** (`practice: 1`) if the four lost fee
  readings turn out to matter at scale; the code does not change.

## D-045 · Chunk 3: one search seam, three engines, the city in every people query

**Built (17 Sep 2026)** as plan-v2 workstream 3. The user's call: "go with Serper"; keep
the possibility to switch.

**Rulings:**
- **`lge/search` is the only way the engine searches the web.** `search(query, n, page=)`
  returns rows of {title, href, body} -- the shape the DuckDuckGo path always returned, so
  no consumer changed what it reads. Which engine answers is `settings.search_engine_name()`:
  `serper` when its key exists, else `brave`, else `ddg`; `LGE_SEARCH_ENGINE` forces one.
  `website_check`, `r_search_links` and `r_search_emails` default to it and still take an
  injected `search`, so tests never reach an engine.
- **The engine that answered is on the record.** Every claim from a search is tagged
  `search:<engine>` (`lge.search.source()`), `search_log.engine` says which engine ran the
  query (migration 101; earlier rows are `ddg`), and `config/precedence.yml` ranks
  `search:serper` above `search:brave` above `search:ddg` for `review_count`.
- **Pacing is per engine, in `config/search.yml`, one pacer for all** (`lge/search/pace.py`):
  the steady gap with jitter, the rest once a window's worth went out, the retry after a
  dropped connection, the one patient second try on a bot check and then the cooldown
  (D-039's rules, no longer DuckDuckGo-specific). Serper runs at a query every quarter
  second; DuckDuckGo keeps its 8-12 s.
- **Google Business Profile comes from the engine's listings endpoint when it has one.**
  Serper's `/places` returns the listing itself -- rating, review count, phone, website,
  the Maps URL -- and `r_search_links` reads it at confidence 0.85 before falling back to
  the snippets of a "google business reviews" query (0.6). The listing chosen is the one
  whose name best overlaps the firm's once law words are set aside ("Hartley Injury Law,
  P.C.", not "Hartley Dental"), and never one whose category is not a law practice.
- **Every people query carries the firm's city** (D-042): `site:linkedin.com "<firm>" <city>`,
  `"<firm>" "<person>" <city> linkedin`, `"<person>" "<firm>" <city> email`. The Recorder
  tests match on the query's stem, so a firm without a city asks the old query.
- **Not verified live.** No `SERPER_API_KEY` is in `.env` yet; the Serper and Brave adapters
  are tested against recorded responses only. The first live run over the probe is the
  measurement for this chunk: profiles found per firm, queries per firm, failure rate.
- **Bing is not an option**: Microsoft retired its Web Search API in August 2025.

## D-046 · Chunk 4: Hunter finds and verifies decision-makers' addresses; NeverBounce stays a switch

**Built (17 Sep 2026)** as plan-v2 workstream 4. The user's call: Hunter, with the
possibility to switch the verifier to NeverBounce, which they have used and found expensive.

**Rulings:**
- **Two seams, both chosen by the settings.** `r1_enrich` is the email *finder*
  (`settings.email_finder_name()`: `hunter` when its key exists, else inert) and `r4_verify`
  the *verifier* (`settings.email_verifier_name()`: `hunter`, else `neverbounce`, else
  inert). `config/resolvers.yml` says `auto` for both; a name there or `--opt provider=`
  forces one. Keys come from the environment first, then `.env` through the settings --
  r4 used to read only the environment, so a key kept in `.env` was invisible to it.
- **Who gets looked up.** A tiered, non-DQ firm with no owner/admin contact, or with one who
  has no address. For a known decision-maker Hunter's Email Finder is asked (domain + first
  + last), up to four per firm; for a firm with nobody, the Domain Search, from which only
  owners and administrators are taken (the position through `classify_role`, or Hunter's
  `executive` seniority), added as contacts with source `hunter`, never duplicating a name
  already on file.
- **Hunter's verdict is mapped onto OUR vocabulary, never trusted upward.** `valid` ->
  'valid'; `accept_all` -> 'catch_all' (a failure, as everywhere); `invalid`/`disposable` ->
  'invalid'; `webmail`/`unknown` -> 'risky'; an address the finder returned without a
  verification stays 'unverified' for R4. An existing row is upgraded only from
  'unverified'. A verifier answer with no data (Hunter's 222 "still checking") writes no
  attempt row, so it is asked again next run and never billed twice.
- **Idempotency follows the people, not the firm**: the once-key is the domain plus the
  decision-makers still without an address, so a person found later gets a lookup and the
  same people are never paid for twice.
- **Cost guard**: `price_per_request_usd.hunter: 0.049` (Starter, ~$49/1,000 requests -- a
  placeholder) for `--opt max_usd`.
- **Not verified live**: no `HUNTER_API_KEY` yet; both adapters are tested against recorded
  answers. The first live run over the probe's qualified firms is the measurement.

## D-047 · The Qualified leads panel: seven checks, and only all seven is ready

**Asked for (17 Sep 2026):** "a panel called qualified leads that will contain the leads on
which all kind of work has been done and they are ready to be outreach."

**Rulings:**
- **A qualified lead is one on which every step is done**, and each step is a check with the
  evidence it read: the site was read (a page of a kind the engine reads), the firm fits the
  profile (tiered, not disqualified), a decision-maker is named (owner or office manager), an
  address is on file, the address passed OUR verification (`valid` -- nothing less), a LinkedIn
  profile is on the person, and the nine-touch journey renders. The pain signal is shown, not
  required: a nurture journey renders without one.
- **Almost is four or more of the six checks the database answers**; the journey is rendered
  only for leads that pass the other six, so the list never pays for drafts it will not show.
  The panel's second tab lists the almost-ready with exactly what is missing, and a strip says
  what is holding them back in aggregate ("Address verified · 41") -- which is the work list.
- **`GET /api/qualified`** (`lge/api/routes/qualified.py`) returns `QualifiedRow` = the work
  queue's `LeadRow` plus `checks`, `ready`, `missing`, `why_now`; `counts` carry ready, almost,
  checked and `missing_by_check`. Paged by offset (the set is small and ordered by
  completeness in Python). **`/api/qualified/export.csv`** is the ready leads only -- the sheet
  for the sending vendor, never the almost-ready.
- **Nothing is recomputed.** The drafts endpoint's body became `drafts_for_row`, shared with
  the panel; the checks read the store. The screen (`frontend/src/components/qualified/`) is
  the fourth rail entry, with the fixture server deriving the same checks off its lead rows.
- **On the real data today: 0 ready, 96 almost, of 21,948 checked.** What holds the 96 back:
  a verified address (all 96), the journey (all 96 -- none is on the email list yet), a
  LinkedIn profile (30), a tier (20), an address at all (5). That is the work list the two
  keys unlock, in order; the panel shows the gap rather than lowering the bar.

## D-048 · The store starts empty; the purchased list is a sheet like any other

**Asked for (17 Sep 2026):** "remove every kind of data that you have actually gathered, just
focus on the capabilities of the platform, and then we will start testing" -- the user will
upload a sheet with their leads.

**Rulings:**
- **Everything gathered was removed**: the database was dropped and recreated from the
  migrations (45 tables; only the seeds remain -- the lifecycle whitelist and the tier SKUs),
  and `.local/objects` (raw pages), `.local/imports` (staged uploads), `.local/jobs`, the run
  logs and `data/in` (the vendor list, the job history, the probe lists) were moved out.
  `data/out` was cleared. Nothing under `tests/` changed: fixtures are tests, not data.
- **A compressed copy sits in `.local/backups/2026-09-17-reset/`** (291 MB, git-ignored: the
  `pg_dump`, the object store, the imports, the sheets). It exists so the wipe is reversible,
  not because anything will be restored; the user may delete it.
- **The purchased list is no longer special.** It enters, if it ever does, through the Lists
  screen like any sheet. `config/flows.yml`'s `load_first_party` flow, which read
  `data/in/vendor_firms_37k.csv` by path, is legacy and will report the missing file rather
  than load anything.
- **Every number in D-042..D-047 was measured on the probe, which is gone.** Future
  measurements are on the sheet the user uploads; the panel and the pipeline counts start
  at zero.

## D-049 · The home page is the manual: how to use it, the tabs, how long, and the questions

**Asked for (17 Sep 2026):** "beautify the home landing page ... a section on how a user can
actually use this platform, what the different tabs are about, how to access it, how much time
it will take to work on a thousand leads -- answer these as an FAQ."

**Rulings:**
- **The page keeps its shape** (D-037: five stations with live numbers, what needs a person,
  the engine, the glossary -- ruled sections, no card grids, one panel style) and gains four
  things in the same language: **How to use it** (six steps from a sheet to a ready lead,
  each with what you do, what the engine does, where, and how long), **The tabs** (one line per
  rail entry, linked), **Questions** (ten, collapsible, plain words) and a "Filled by research"
  glossary entry. The hero's first button becomes *Upload a list* while the store is empty.
- **Every answer is the engine's own truth, not a promise.** How to get in is localhost and the
  README's three commands, with no login yet; a sheet needs a firm name and one way to reach
  the firm; research over a list is batches of up to a hundred from the work queue (or `lge
  flow profile_probe` from the command line); the three keys and what stops without them;
  "ready" is the seven checks; it does not send, scrape LinkedIn or job boards; every number
  carries its source; a wrong website is searched for and adopted only when its homepage names
  the firm.
- **The thousand-lead timing comes from the engine's settings**, step by step: reading the
  sheet under a minute; website check ~10 min (twelve hosts at once, 2 s per host); reading
  the sites 40-60 min (twelve pages a firm at that pace); facts and rules 10-20 min; search
  15-20 min on Serper at a quarter second a query (~4,000 queries) versus ~11 hours on
  DuckDuckGo at 8-12 s; Hunter minutes. About two hours with the keys, the better part of a
  day without. These are estimates from pacing, to be replaced by measured runs on the
  user's sheet.
- **Second pass, the same day** ("make it interactive; this is basic and tasteless"). The
  page's one bold thing is **a case file that builds itself** (`case-file-demo.tsx`): an
  invented firm goes from a sheet row to a verified site, the people and the proof sentence
  -- with the highlighter sweep, the system's one unprompted motion, as the climax -- to the
  tier and urgency, every check green, and the first subject line. It plays once on load in
  the hero (Replay to see it again; reduced motion shows the finished file at once), and the
  same file is the instrument of the walkthrough: the six steps are a stepper, and picking
  one shows what that step leaves behind. The questions became an index with the answer
  beside it. Nothing else moves unless clicked; no new colours, faces or shapes. Found and
  fixed on the way: a `div` inside a `p` (a hydration error), a state set inside an effect,
  and a first paint that flashed the finished file before the play.

---

## D-050 · Addresses are found by our own scraping; a vendor only verifies them

**Asked for (17 Sep 2026):** "Hunter does the same thing we are trying to make ... we are
building this in-house, for our own company. We have data that needs to be cleaned, it gives
direction, then we run scraping jobs. Why are you sending me to Hunter?"

**Rulings:**
- **No lead-generation product in the pipeline.** The engine finds decision-makers' addresses
  itself: printed on the site (`r_site_emails`), in search-result snippets
  (`r_search_emails`), and by the firm's own address pattern learned from one real address
  (`r3_email_pattern`) -- 2,319 of 2,745 named people on the probe, with no vendor. The Hunter
  finder built in D-046 stays in the code as an adapter that is never selected:
  `LGE_EMAIL_FINDER` defaults to `none` in practice because no key will be added.
- **Verification is the one thing scraping cannot do**, and it stays rented: it is an SMTP
  conversation with the firm's mail server, which a residential connection cannot hold and
  which gets an IP blacklisted when done at volume. A *verification-only* service is a
  utility, not a competitor: NeverBounce (known to the user, dearer) or ZeroBounce, about a
  cent an address. Both adapters exist in `r4_verify`; the settings pick whichever key is
  present. If neither is bought, addresses stay `unverified`, the sending vendor's bounce
  check is the last line, and nothing reaches "ready" inside the engine -- shown, not hidden.
- **Serper stays**: Google's results through an API is infrastructure for our own search
  jobs, not a lead product.
- **The ask to the manager is therefore two utilities**: Serper credits (~$50 for the whole
  list) and a verification balance (~$10-20 for the first thousand decision-makers).

## D-051 · A decision-maker's address from their name and the domain, confirmed by the verifier

**Asked for (17 Sep 2026):** "take the decision-maker's first name and last name with the
domain, make the combinations, one of them will be the real address, then check it with
NeverBounce -- why were you sending me to Hunter?" The gap was real: r3 learns a firm's
pattern only once *one* real address is known; a firm with none stayed empty.

**Rulings:**
- **`r_email_guess`** (Plane R) fills that gap. For a decision-maker with no address at a
  tiered firm where nobody has an on-domain address yet, it builds the eleven schemes'
  candidates -- first.last, first, flast, firstlast, first_last, firstl, f.last, last,
  lastf, last.first, lastfirst, in the order the probe saw them -- and asks the verifier
  about each until one comes back `valid`. The hit is the person's address, scheme recorded,
  `verified_at` set; r3 then learns the firm's pattern from it and mints the rest of the
  firm's people on its next run.
- **A catch-all domain ends the spending for the whole firm**: the first `catch_all` answer
  puts the most common scheme on file for every decision-maker there with status
  `catch_all` -- on file, never sent to -- and no further call is made for that domain.
- **Never paid for twice**: every candidate is logged in `verify_attempt`; a prior answer is
  read back instead of bought again. `max_candidates` (6) caps a person, `--opt max_usd` caps
  a run, five failures in a row stop it. About a cent a candidate, two or three on average.
- **Wired in** after `r3_email_pattern` in research-on-demand (full and contacts scopes) and in
  the `profile_probe` flow, before `r4_verify`. Inert without a verifier key, like R4. The
  home page's key question no longer names Hunter.

## D-052 · The review of the day's changes: four findings, four fixes, one new guard

**Asked for (18 Sep 2026):** "invoke the senior software agent, analyze the whole code base
from raw leads in through enrichment, find bugs, make the system more robust." Two read-only
reviews ran: a bug review of everything changed on 17 Sep, and an end-to-end systems review.
This entry records the first; the second follows as it lands.

**Findings and rulings:**
- **Critical, and mine.** The chunk-3 patch slid `_write_listing` in between the `@component`
  decorator and `run()` in `r_search_links`, so the registry held the helper: every research
  job's LinkedIn step and the whole-list flow would have died with a `TypeError` at that step,
  and the flow runner has no per-step guard, so the nightly run would have stopped there. The
  per-component tests call `module.run` directly and the job tests fake the registry, so
  nothing caught it. The decorator is back on `run()`, and **`tests/test_registry_steps.py`
  now asserts that every step named in `config/flows.yml` and in the research jobs' step
  lists is registered as a function whose first parameter is `ctx`** -- the path the CLI,
  the flow runner and the API actually call. A patch that lands a decorator on the wrong
  function fails that test.
- **The address claim carried its printed text.** `px_site_facts` popped `raw` off the address
  dict and put it straight back on the same object, so `site:page` wrote seven keys where
  `site:jsonld` writes six, and reconcile's "two sources agree" branch (D-031) never fired for
  the very case it was written for. The claim is a copy without the text; the text stays in
  `evidence`.
- **`/api/qualified` did every lead's work on every page load.** The database now returns only
  leads at least four checks along, counts the rest, and the journey is rendered for at most
  500 candidates per request (the rest say "not checked in this view" and count as almost).
  A universe of a hundred thousand leads is one filtered pass, not a round-trip per lead.
- **Batch decisions could not qualify, reopen or hand off**, though the single-lead endpoint
  could; the batch action list now carries every decision action.
- **Not bugs, checked:** the streaming reader's batch arithmetic, the search pacer's state
  machine and client lifetimes, the claim-run retirement on exceptions, the verifier and
  finder idempotency.

## D-053 · The three-step engine: triage the rows, enrich by priority batch, hand over on record

**Asked for (18 Sep 2026):** the user's handwritten brief. "Law Firm Name, Website, Location,
Job Post, Firm Size → bare minimum ... All 5 cols present → Make Batch 1. Law Firm name absent
→ Discard the lead ... Make Batch 2 ... If the batch size > 250 rows, then the batch will be
made into sub-batches of 250 ... Priority to process Batch 1 is always higher than Batch 2 ...
Pain Point Analyzer: it is not a scraper, this is just an LLM ... All the enriched leads will
land in a dump called Actual Leads ... create a Handover Lead Base document ... leads that have
been handed over to the vendor will have a status." And: "do not write code first; be thorough,
review, and make a plan." The engine was read against the brief (three read-only sweeps, the
load-bearing claims checked by hand), the cross-check and the build order written as
`plan/plan-v3.md`, and four of its six questions settled the same evening.

**Rulings:**
- **The order of the next work is `plan/plan-v3.md`**: mend what drifted → triage the rows →
  the enrichment queue → enrichment to the brief → the pain analyzer and the enrichment report
  → Actual Leads and the handover. It does not replace plan-v2: v2's seams, search, address
  finding and verification are what v3 wires together. Plan before build still holds (D-042).
- **Five fields make a row complete; a firm name makes it workable.** The five are firm name,
  website, location, job post, firm size, each counted only when usable (a website that yields
  no domain is missing). All five → Batch 1. No firm name → discarded before the store, onto a
  rejects list the screen shows and the user can download; today such a row becomes a firm
  called "Unknown Firm". A name with anything missing → Batch 2. This loosens D-043's second
  mandatory group: "a way to reach the firm" stops blocking the load; completeness now decides
  the order rows are worked in, not whether they enter.
- **A sheet missing one of the five columns loads, with a warning, every row in Batch 2** (the
  user's choice over refusing it, or judging rows on the columns present). A sheet with no
  firm-name column is refused, since every row would be discarded.
- **Sub-batches are 250 firms for both batches** (the brief's "1000 (?)" for Batch 2 was settled
  at 250), counted after duplicates merge. Batch 1 always goes before Batch 2, across sheets;
  the rule applies between sub-batches, so new Batch 1 work waits at most one running
  sub-batch. The queue starts itself when a sheet finishes loading.
- **Batch 2 opens with identify**: the existing website finder, wired in at last. It checks the
  place as well as the name when the sheet gave one; a firm with a name and no place is adopted
  only when the answer is unambiguous. A firm that cannot be identified is parked with its
  reason, never enriched blind.
- **The crawl reads five pages**: landing, about, careers, testimonials, one staff page. The
  contact page goes; phone and address come from the Google Business Profile, now kept whole.
  The loss in addresses found is measured on the first sheet and contact comes back (one config
  line) if it hurts. Supersedes D-044's six kinds and twelve pages.
- **Pain is analysed by the AI over everything the store holds**, each pain carrying the
  sentence that proves it and its source; a pain with no evidence in the store is dropped.
  `ja7`'s rules become inputs to it. The prompt and model go through the AI-engineering review
  before they change.
- **Everything that finishes enrichment lands in Actual Leads, with its checklist; only a lead
  passing every check can be handed over** (the user's choice over admitting ready leads only).
  One definition of ready, shared by the panel and every export, list hygiene always applied.
- **A handover is on record**: vendor, leads, time, who. The Handover Lead Base document is
  generated locally on request; a lead handed to one vendor is not handed to a second by
  accident; outcomes come back through the existing outcome buttons. Sending stays out of scope.
- **Found in the cross-check, fixed first:** the Research button's step list has drifted from
  the flow. It skips the AI's reading of the site, the verification of any address found on the
  site or in search (only a predicted address gets checked, by the predictor itself), and
  `classify`. A lead researched from the screen therefore stays at PROFILING, "Researching" in
  the work queue, however much was found. And `/api/qualified/export.csv` skips the list
  hygiene `build_list` applies, so a customer's or a cooling-off domain can reach the vendor
  sheet.
- **Still open:** whether the sheet's firm size becomes the lowest-ranked source of size
  (reverses part of D-016 and D-044, which kept a purchased list's employee range out on
  purpose); and the two keys. Without a NeverBounce or ZeroBounce key the email predictor skips
  every person; without a Serper key Batch 2's search is DuckDuckGo, and a bot check stops it.

## D-054 · Phase 0: one research recipe, one set of list rules, lights that ask the engine

**Asked for (18 Sep 2026):** "start karo bhai" -- begin plan-v3, phase 0: mend what drifted
before building on it.

**Rulings:**
- **The research recipe lives in `config/flows.yml` alone.** A flow step may now be
  `{flow: <name>}`, replaced by that flow's steps where it stands (`lge/ops/config.py:
  load_flows`); an include that loops, names no flow, or carries options is refused at load
  time. `research` = read_site → G3 → find_people → classify → read_openings → reconcile →
  score; `find_contacts` = px_site_facts → find_people → reconcile → classify → score;
  `profile_probe` = research + build_list; `nightly` opens with read_openings. Expanded,
  nightly is exactly what it was; profile_probe gains one reconcile before the score (the
  hiring facts the careers pages write reach the score in the same run, as the button's list
  already did).
- **The Research button runs the flow's components** (`research_steps(scope)` in
  `lge/api/routes/actions.py`), gates left out -- a gate judges the whole universe, and one
  firm is not a distribution. It now includes the four its own list had lost: the AI reading
  (p8, p9), address verification (r4) and classify, so a lead researched from the screen moves
  through its states instead of sitting at PROFILING. `tests/test_registry_steps.py` holds the
  button to the flow, every step to a plain label, and the research flows to carrying no
  per-step options a job would not pass.
- **A firm list narrows P9's trigger, never replaces it.** `firm_ids_file` used to bypass the
  trigger query, so every firm researched from the screen would have been sent to Opus 5. A
  listed firm is now escalated only when a trigger fires for it (low confidence, fee model
  mixed or unknown, tier 1A, an open conflict); `--opt force=1` keeps the old override for a
  deliberate re-run. The docstring always said this; the code did not.
- **One set of list rules for every list and sheet.** `lge/export/list.py` names each rule once
  (parked, portal or competitor's customer, suppressed firm, suppressed domain) and exports
  `HYGIENE_EXCLUSION_SQL`; the Qualified panel and `/api/qualified/export.csv` read it. A lead
  a rule holds back is neither ready nor almost, and the panel says how many were held back
  and why ("Do not contact 2 · Parked 1"). Until now the vendor sheet applied none of them: a
  paying customer's firm could reach it. An address on the do-not-contact list (scope
  `email`) is not an address any list carries -- nothing writes that scope yet, but the
  send-time guard expects it and the sheet is now the last gate.
- **Found by the new tests, and fixed:** a decision-maker with no address at all made the
  Qualified query's "address verified" check NULL rather than false, the sum of the checks
  NULL, and the lead vanished from the panel instead of showing as one step away. Introduced
  by D-052's move of the filter into the database; `IS TRUE` closes it, with a test.
- **The provider lights ask the seams.** `email_verification` is `r4_verify.configured_provider`
  (the verifier a run would use, key and all); `places` is `lge.search.has_listings` (the
  search engine in use has a listings endpoint -- Serper -- and its key is set). The old
  `places` read a `GOOGLE_PLACES_API_KEY` nothing reads. The inert list says "Google Business
  Profile lookup".
- **Job steps carry their label from the engine** (`lge.api.labels.step_label`); the screen's
  own map, which had already missed the email predictor, is gone.
- **Measured:** 1,273 backend tests pass (26 of them new); the frontend typechecks, lints and passes 56
  tests, and the live contract check passes against the running engine. On this machine today:
  AI reading on, email verification off, Business Profile lookup off -- the two keys of D-053.

## D-055 · The interface redesigned: the blue back, the three steps as the spine

**Asked for (18 Sep 2026):** "I'm giving you an authority, use the design skill, the UI UX
revamping skill, and redesign the whole UI of this platform." Every screen was screenshotted
with sample data first (headless Chrome over the DevTools protocol), a UX audit ran alongside,
and the system was rebuilt screen by screen with a screenshot after each. The spec is
`plan/ui-design-system.md` ("Blue-back"), which replaces "The Record".

**Rulings:**
- **The rail is the brief.** Navigation is Home, then the three steps of plan-v3 -- *1 Raw
  leads* (Sheets), *2 Enrichment* (Work queue, Firms, Accuracy check), *3 Handover* (Actual
  leads) -- with counts only where something waits for a person. The separate five-step
  "pipeline" list in the rail is gone (one navigation model, not two). The screen you are on is
  a white tab joined to the sheet.
- **Names follow the user's words.** "Lists" is **Sheets**, "Qualified leads" is **Actual leads**
  (the URL stays `/qualified`), the queue's "Contact" column is **Decision-maker**, "Gate G2" is
  **Before the list widens**, "in the universe" is **on file**. Stale route titles and loading
  states ("Imports", "Leads", "Hand-check", a not-found page offering "Go to Today") were fixed.
- **Blue-back frame, one sheet per screen, no card grids.** Pale legal blue desk and rail, each
  screen a white sheet (18px corners, no shadow); tables ruled across the sheet; proof unboxed;
  a frame only for a specimen or the item under review.
- **Type: Archivo and Caslon.** Archivo replaces Rubik for the interface; its narrow cut carries
  the Legal Soft wordmark's condensed voice into titles and live figures. Libre Caslon Display
  sets a firm's name as a caption; Libre Caslon Text keeps the record. This departs from the
  brand kit's Rubik on purpose: the wordmark itself is a heavy condensed grotesque, and Rubik's
  rounded terminals were the least legal thing on screen.
- **Home opens on the work, then teaches.** The strongest proof in the system (with who to write
  to and "Copy first email") or, before there is any, the self-building demo; the three steps
  with live numbers and their screens; what is waiting and what the engine is doing; then, under
  a heavy rule, the manual the user asked for on 17 Sep (how to use it, the questions, the
  words). The unused Today screen and band tabs were deleted.
- **The lead page is two columns.** The reading (proof, people, drafts with touch 1 open) and a
  pinned working side (next step, decisions, outcome buttons, notes, history, numbers): 3,953px
  became about 1,800. The case file beside the queue keeps one column with its outcome bar pinned.
- **The work queue lost its chrome.** Search, priority, tier and pain inline, the rest behind
  "More filters (n)"; Radix menus instead of native selects; a real "Export a list" menu; a row
  shows its next step and owner, not the stage its tab already names; the proof runs to two lines.
- **Sheets explains itself when empty.** A drop zone, the upload button waiting for a file, and
  "Start with a sheet of law firms" with the three things that happen to one.
- **Found on the way:** the dev server refused `127.0.0.1` (only `localhost` hydrated), so a
  screen opened by IP sat on its skeletons forever -- `allowedDevOrigins` now lists it; the
  "couldn't reach the engine" error told people to run `uv run lge serve`, which Application
  Control blocks here -- it now gives `.venv\Scripts\python.exe -m lge serve`; "1 people".
- **From the UX audit, applied:** a setup notice where a switched-off provider would look like a
  fault -- Actual leads says "Address checking is off, so no lead can be ready to hand over" and
  which key to add, and Home lists every switched-off key under the hero; the Actual leads tab
  is **Ready to hand over**, so "ready" no longer means two things (the queue's "Ready to reach"
  stays); the lead page's blue button is the lead's own next step (Find people and emails for a
  lead that needs a person, Qualify for one that needs a decision, Research for one still being
  read); a Strike lead says it is written by hand instead of "no touches"; research steps say
  "Nothing new to read" or "Switched off until its key is set" instead of
  `processed=1 skipped=0 failed=0`, with the raw text only under Details on a failure; Sheets
  shows how many rows carry each of the five fields of the brief instead of a health score out of
  100, and loses its rows-per-batch picker (its 250 read as the brief's enrichment batch); one
  address badge everywhere; no count on the rail's Accuracy check (the engine's is 50 minus what
  was checked, so it read "50 waiting" on an empty store); no "checks waiting" on Home for queues
  with no screen; the priority beside urgency on each queue row.
- **From the audit, not applied, and why:** hiding the outcome buttons before a lead is ready (an
  opt-out can come at any stage); renaming Home to Overview (the user's word is Home); "Hand off
  to sales" to "Pass to sales" and "Unknown -- not guessed" to other words (the backend sends the
  same strings; a frontend-only change would mix two vocabularies -- a backend copy pass, best
  done with the handover work of plan-v3 phase 5); a live "ready" count on the rail (it would
  run the Actual leads query on every screen).
- **Unchanged on purpose:** every API shape, every keyboard shortcut, the highlighter's single
  sweep, the plain-words and write-the-unknowns rules, and the backend's own display strings
  (a few still carry "word -- fragment" labels such as "Catch-all -- failure"; changing them
  is a backend copy pass). Backend gaps the audit found, for later: the sample fixtures carry
  urgency above the engine's cap of 50, and a Strike lead in them has drafts the engine never
  writes.

## D-056 · Ports: the screens on 5000, the engine on 8100, both on this machine only

**Asked for (18 Sep 2026):** "launch this on the local host 5000 ... there's one more website
that is running on the local host 3000, so do not disturb those servers ... for the backend
also use some other port."

**Rulings:**
- **The screens run on 5000, the engine on 8100.** `npm run dev`, `dev:fixtures` and `start`
  take `-p 5000`; `lge serve` defaults to `--port 8100`; the screens' `/api` proxy defaults
  `LGE_API_ORIGIN` to `http://127.0.0.1:8100`. Port 3000 belongs to another project on this
  machine (a Next app in `ghi-worktrees`) and is never stopped, reused or trusted; 8000 and
  3100 are simply no longer used.
- **CORS names our own screens only:** `http://localhost:5000` and `http://127.0.0.1:5000`. It
  used to name 3000 -- written when these screens were meant to run there -- which on this
  machine meant the *other* project's pages could read our contacts. A test now refuses both
  3000 origins by name. The screens never need CORS (the proxy makes them same-origin); the list
  is for a page calling the engine directly.
- **The screens bind to `127.0.0.1` too (`-H 127.0.0.1`).** Next's default is every interface:
  the dev server announced `http://192.168.0.208:5000`, and its proxy would have handed anyone
  on the same network what the engine keeps to `127.0.0.1` -- contacts included. The old 3100
  server had the same hole. `localhost:5000` still works (the browser falls back from `::1` to
  `127.0.0.1`); the network address is now refused on both ports.
- **Measured:** engine health direct and through the proxy on both hostnames; every screen
  hydrates on `localhost:5000` and `127.0.0.1:5000`; the live contract check passes against 8100;
  91 API tests, the frontend's 56 and its typecheck and lint pass; port 3000 kept its process
  throughout. The live database is empty -- created 17 Sep 22:54 and never written to (no
  insert or delete on any table), and the raw-page store holds no files -- so the screens show
  their empty states until a sheet is loaded.

## D-057 · The Email journey screen: the lifecycle day by day, its wording and days editable

**Asked for (19 Sep 2026):** while the NeverBounce and Serper credits are arranged, "work on the
last stage that is the handover ... draft emails the whole life cycle, what we will be sending
on the day one, day two and day three ... Can you create that panel also?" Plan-v3 phase 5,
started ahead of phases 1–4.

**What existed:** nine touches over 28 days, rendered per lead from `journey/copy/` by
`build_journey` (plan/outreach-journey.md, plan/email-drafts.md), shown only at the foot of a
lead's page; no way to see the journey as a whole, and no way to change a word of it.

**Rulings:**
- **A screen in step 3, `/journey` ("Email journey"),** beside Actual leads. A day line (a
  numbered square per email on its day, dashed when this firm would not get it; to scale where
  the days allow, evenly on a phone), then each email as the engine writes it, for an example
  firm or one lead (`?lead=`, linked from the lead's drafts). The example firm is invented
  (Dana Whitfield at "Harbor & Vale Law", Atlanta) and rendered by `build_journey` itself
  (`GET /api/journey/example`), so the screen shows real emails before any lead exists; its
  tier, pain, case system and track are in the URL. When the firm would get nothing, the
  reason is given in words and every version is still listed. The working side: the schedule,
  the tracks, what to record when a firm answers (the outcome buttons' own names), the rules.
- **Days are counted from Day 1** on every screen (`Day {day + 1}`); the API keeps days after
  email 1. The pieces are *emails*, not *touches* (the lead page follows).
- **Edits sit beside the originals, never over them.** `journey_copy_edit` (template path →
  subject, body) and `journey_day_edit` (email → day), migration 102. The copy files and
  `sequences.yml` stay the originals the golden tests pin; "Restore the original" deletes the
  row; saving the original wording back is a restore. Chosen over rewriting the files because
  a screen edit would otherwise break the test suite and live only as an uncommitted diff.
- **One read path for every renderer:** `lge.export.list.fetch_journey_edits`, passed to
  `build_journey(lead, edits)` by the lead's drafts, the work queue's classification (and so
  `build_list` and the vendor sheet), Actual leads' journey check (read once per request, up
  to 500 renders) and Home's first draft. No two places can show different words.
- **What an edit may not do, checked by the engine and, word for word, by the screen as the
  person types:** use a banned phrase (sequences.yml); use a fill-in the template's original did
  not use, other than `{first_name}` and `{firm_name}` -- a detail some firms lack would drop
  those leads instead of sending a gap (outreach-journey.md: "a token that cannot resolve means
  the lead does not go out"); drop or double the tier's paragraph slot; leave a stray brace;
  an empty or multi-line subject. Advice only: the word count, capitals in a subject.
- **The days move as one schedule:** email 1 always on Day 1, each later email after the one
  before, by Day 91; an email left out of a save goes back to its own day; Nurture keeps its
  pace (`JourneyTrack.pace`) over the new days.
- **Found and fixed:** the days were written twice -- in `sequences.yml` and again in
  `build.py` -- so the config file's promise that "tuning a day offset never needs a code
  change" was false. `build.py` now reads the file. The journey's refusal codes
  (`unresolved_token:cms`, `fee_model_unresolved:…`, `no_touch1_variant:…`) reached the work
  queue and Actual leads almost raw ("Unresolved token:cms"), and the lead page showed them
  raw; `reason_display` now words them ("An email needs the case system, and it is not
  known") and a lead's drafts carry the words as `excluded_display`.
- **Contract (Revision 4, additive):** `Touch.templates` (which templates built each email),
  `DraftsResponse.excluded_display`, `GET /api/journey`, `PUT/DELETE /api/journey/templates/{id}`, `PUT/DELETE /api/journey/days`,
  `GET /api/journey/example`. The catalogue of templates, with each one's plain "used when",
  is `lge/journey/catalogue.py`; a test renders every tier × pain × case system × track and
  holds every file the renderer used to its place in the catalogue, and every catalogued file
  to being reachable.
- **Found, not fixed, and why:** (1) the copy files are hard-wrapped at ~70 characters and the
  breaks survive into every rendered and copied email -- ragged on a phone once pasted. Joining
  the lines of each paragraph at render is a line of code, but it changes every email's layout
  and the golden tests pin the wrapped text: the user's call. (2) Email 8's `{days_open}` is
  counted on the day the draft is rendered, not the day it goes (Day 26) -- right only if copied
  on the day; belongs with saving each lead's journey when it is handed over (phase 5). (3) Tiers
  2 and 3 share touch 2's personal-injury paragraph (a known gap a test already names).
- **Measured:** 22 catalogue tests and 19 API tests new; the whole engine suite passes (1,316,
  one skipped); the frontend passes 70 tests, typecheck and lint, and the live contract
  check (7) against the running engine; photographed at 1440 and 390 wide, the Nurture track
  (Day 1, 15, 57), a firm that would get nothing, and the editor refusing "replace" as it was
  typed. The live database had migration 102 applied; the engine was restarted by PID on 8100.


## D-058 · The Pain Point Analyzer: an AI reads the record, and must prove every pain

**Asked for (22 Sep 2026):** the user, looking at nine researched firms, said the
brief's enrichment was not there -- "no Google business profile ... no reviews ...
no email that you verify from NeverBounce ... a lot of things we discussed have not
been implemented." True, and the answer was to start phase 4 of plan-v3 with the
part that needs no new key: the analyser the brief calls "an AI, not a scraper",
plus the per-lead enrichment report it feeds (the report is the next piece).

**Where the rest stands, measured on their own nine firms:** the business profile
is never read (it needs Serper; four firms hold only a maps link found in search),
review text is never read (counts and profile links only, from 92 DuckDuckGo
searches), and all 52 addresses on file are unverified because no verifier key is
set -- the predictor that invents an address for a person who has none is
deliberately inert without one. Two firms' sites cannot be read at all
(`aroldlawfirm.com` does not resolve; `hohlaw.com` has an invalid certificate), and
four more were read in full by all three readers with no statement of how the firm
charges, so they stay untiered by the standing "never guess fee_model" rule.

**Rulings:**
- **One call per firm over the whole record, never a crawl.** `ja8_pain` assembles
  ten labelled blocks from claims already in the store -- the firm, what the site
  lacks and shows, the people, the testimonials, the reviews, the listing, the open
  roles, the news, and what the fixed rules already flagged -- and asks the cheap
  tier for the pains. `ja7_pain_signals` stays as a cheap input to it, not as the
  analysis, exactly as the phase describes.
- **A pain must quote ONE line of the record.** Grounding is per line, per block,
  with punctuation folded (curly quotes, long dashes) and a floor of three words,
  and a whole line always counts however short. The first draft's flat "is it
  somewhere in the record" check let a hallucination be proved by welding the tail
  of one block to the head of another, and threw away true pains the moment the
  model retyped an apostrophe -- both measured by the AI-engineering review, both
  closed. `source` is corrected to the block that actually holds the line.
- **What is thrown away leaves a trace.** Dropped pains are stored with the claim
  as [kind, reason], counted in the run's notes and recorded on the `llm_call` row.
  Three pains were dropped on the first live run over the user's firms.
- **The summary is marked unverified.** Nothing can check free text, so when every
  pain is dropped the summary is replaced with a fixed line, and the claim carries
  `summary_grounded: false` so no one quotes it as evidence. A model that found
  nothing and said so keeps its own words.
- **Cost and blast radius.** Haiku 4.5, about a cent a firm (~$1.15 for 250),
  `--opt max_usd` and `--opt dry_run=1` before any spend, and idempotent on
  `task_run.input_hash`, so an unchanged record costs nothing. The step sits in the
  `research` flow after `reconcile`, **not** in `nightly`: nightly + a record that
  shifts slightly would re-pay for every firm every night. `continue_on_fail: true`
  and a per-firm `try/except`, so one firm cannot take a run of 250 with it, and a
  broken answer raises rather than marking the firm done for good.
- **Visible where the work is:** a "What hurts" section on the lead page and the
  firm record -- the summary, then each pain with its quoted line, the block it came
  from, and what it costs the firm; and a closing line naming everything that was
  read. It is kept out of the raw claims table, where it would be a wall of JSON.
- **Found in the data while building:** Fuchsberg's attorney count says 2 while 28
  people are on file, and Duron's "business listing" is a Google Maps link to
  Manhattan for a Chicago firm -- both upstream, both worth fixing when the listing
  is read properly in phase 3.
- **Disproved by evidence:** the AI-engineering review predicted the API would
  reject the schema outright, because strict structured outputs are documented as
  not supporting `minimum`/`maximum`. Six live calls through OpenRouter returned
  valid answers, so the stripping fix it proposed was not made; the same keywords
  have been in p8's schema all along. Everything else it found was adopted.
- **Measured:** 18 tests on the schema, the record and the grounding, including the
  welded-line, fragment, retyped-punctuation and forged-header cases; the whole
  engine suite passes; the frontend typechecks, lints, passes 72 tests and the live
  contract check. On the user's nine firms: 6 analysed, 3 pains dropped for want of
  proof, and three firms honestly reporting that the record proves nothing.


## D-059 · Home says what is built, what is half built, and what it waits on

**Asked for (22 Sep 2026):** "mention this on home page what parts are built and
how much is needed from api tools -- my team will need a tour soon so i want to be
clear from the start."

**Rulings:**
- **The engine states its own build status.** `config/capabilities.yml` holds the
  three steps of the brief and every part of them, each marked `built`, `partial`
  or `planned` with a line of plain words, and `GET /api/meta/capabilities` serves
  it. The screen renders what the engine says; it keeps no list of its own. A part
  is `built` only when a person can use it from the screen today.
- **Whether a key is present is never written in that file.** Each part names the
  outside service it needs, and the endpoint asks the engine's own seams whether
  that service is on -- so a key arriving turns "Idle until Address checking is
  switched on" into a finished part with nobody editing anything.
- **Three outside services, named with what they unlock and what they cost:** the
  AI reader (OpenRouter, on), address checking (NeverBounce, no key) and search and
  business listings (Serper, no key). Only the setting's name is ever shown, never
  a value. What the AI has cost is read from its own call log, so the number on
  screen is the real one ($0.52 over 29 readings today), not an estimate.
- **Hunter is not among them.** Finding an address stays in-house by the user's
  standing decision -- our own scraping plus the predictor -- and a vendor only
  verifies. Hunter remains wired in the settings as a verifier option and still
  sits first in that order; removing it is offered and not yet done.
- **Where it sits:** on Home, directly under the three steps with their live
  numbers and above the manual, because the first thing a visitor on a walk-through
  should get is an honest map. It says 12 of 23 parts built, 4 partly there, 7 to
  come, and 5 built parts idle for want of a key.
- **It has to be kept honest.** A part that ships moves in that file in the same
  session, the way a decision that changes behaviour gets an entry here; the rule
  is written into the backend's CLAUDE.md so it is not forgotten.
- **Measured:** 5 tests, including one that a planned part never claims to be
  waiting on a key, one that a built part stops waiting the moment its key is set,
  and one that no key value can reach the response; the whole engine suite passes;
  the frontend typechecks, lints, passes 73 tests and the live contract check
  against the running engine.


## D-060 · The journey's emails rewritten, and every email signed

**Asked for (22 Sep 2026):** "in email journey sample emails looks junk make
sample email journey ... like a cold emailing expert for legalsoft.com."

**What was actually wrong.** Two things, and only one of them was the words.
Every email ended after its question: no sender, no company, no reply address,
no postal address and no way to say stop. An email like that reads as a
circular whatever it says, and in the United States a commercial one owes the
reader an address and an opt-out (CAN-SPAM). Nothing in the engine had ever
handled any of it. The copy itself also never used what Legal Soft actually
sells -- read from legalsoft.com: pre-vetted people, free to interview, someone
working in under three days, HIPAA-trained, 2,500 placed across 1,000+ firms --
and asked a managing partner for "a short call", the one thing they have least
of.

**Rulings:**
- **Every email carries a signature**, appended by the renderer from
  `config/sender.yml`: who it is from, Legal Soft and the site, the reply
  address, then the postal address and the line telling people how to stop.
  What is not configured is left out, never invented -- `sender_missing` names
  each blank in plain words and the Email journey screen shows them as **Not
  ready to send** until they are filled in. The file ships with the name, reply
  address and postal address blank, because those are the user's to give.
- **The copy is rewritten, the strategy untouched.** The pain sentence still
  opens, capacity never replacement, the opening seat still touches no client,
  touch 3 is still the fee model's own arithmetic, and 5, 6 and 7 still answer
  the blocker, admit the wrong guess and look for the administrator. What
  changed: the ask is now small and concrete (two candidate profiles, free to
  interview, someone starting in under three days) instead of a call; the
  offer's real facts carry the claims; the throat-clearing is gone; and the
  emails read as a person wrote them, contractions and all.
- **`journey/copy/*.md` is the copy; `plan/email-drafts.md` keeps the
  reasoning.** The doc now says so at the top rather than pretending to be the
  words. The five rules in outreach-journey.md did not change, and the banned
  phrases still cannot appear -- the check runs over every file.
- **The golden tests pin the new words**, and a new one asserts every rendered
  email ends with the signature, names Legal Soft and says how to stop.
- **Measured:** 113 journey tests, 117 API tests, the whole engine suite, and
  the frontend's 73 with its live contract check. Read end to end on screen for
  a 1A firm with an open role, the same firm with the post gone back up, and
  the hourly tier.


## D-061 · Proper emails: a subject that earns the open, a body, and a sign-off

**Asked for (22 Sep 2026), after the first rewrite:** "make impact full mail
subject catchy professional and do proper mail body not an half ass job."

**What was still wrong.** The emails were terse by rule -- 50 to 90 words, a
lowercase fragment for a subject, an opening that began "Dana —" with no
greeting and ended on a question with nothing under it. That reads as a note
scribbled between meetings, not as a firm writing to a firm.

**Rulings, and the two standing rules they change:**
- **Subjects are sentence case and specific.** "Your paralegal opening, and a
  faster way to fill it"; "The {role} role at your firm, posted a second time";
  "Two seats open at {firm_name}, which one first?"; "{tort} intake, and the
  records volume behind it"; "Confidentiality, supervision, and how this
  actually works". They name the thing the firm already knows about itself,
  which is what earns the open -- never a teaser.
- **Bodies are 90 to 130 words** with a shape: "Hi {first_name}," then the
  observation, what it usually means, what we would do about it, why we are
  worth an hour (pre-vetted, free to interview, starting in under three days,
  HIPAA-trained), and one ask. outreach-journey.md rule 5 is rewritten to say
  so; the old 50–90 and "lowercase subject lines" are gone.
- **Every email signs off.** `config/sender.yml` gained `sign_off` ("Best
  regards,"), and the signature now reads sign-off, name and title, Legal Soft
  and the site, the reply address, then a rule and the legal footer. The name,
  reply address and postal address are still deliberately blank, and the screen
  still says **Not ready to send** until they are filled in.
- **One wrapping for the copy, 74 characters**, applied to all thirty files.
  Which exposed the wrap problem properly: `{role}` and `{posted_date}` expand
  when they are filled in, so the sent lines are not the file's lines and never
  can be. Joining each paragraph at render is the fix, and it is still the
  user's call -- now with a second reason to take it.
- **Contractions restored.** "It is possible I have been writing" is not how
  anyone types; the pass that formalised them was mine, and it was wrong.
- **Measured:** the 113 journey tests re-pinned to the new words -- every
  variant assertion keeps its purpose (this variant was selected, this token
  resolved, a review is never quoted back, tier 4 is never pitched a paralegal)
  and only the words it looks for changed; the two full-body goldens now pin
  the rendered text, signature stripped by asking the renderer for it. The
  whole engine suite, the frontend's 73 tests, lint, typecheck and the live
  contract check all pass, and the journey was read end to end on screen.

---

## D-062 · The Google Business Profile and its reviews, through a licensed API, never a scraped page

**Asked for (23 Sep 2026):** "create a Google Business Profile scraper, a review
collector, and make this available in my enrichment engine ... this is a high
priority." The brief had asked for both since the start (plan-v3 phase 3) and
D-058 measured that neither existed: the listing was read only when Serper's
key was present, and review text was never read at all. What was missing was
a way to get them that does not break the standing rule against defeating bot
management -- Google Maps is exactly the kind of page the crawler may not read.

**Rulings:**
- **A listings seam, like the search seam** (`lge/listings`, `LGE_LISTINGS`):
  the Google Business Profile and its reviews come from a licensed API and
  nothing else. Google's own Places API (New) is the first choice --
  `GOOGLE_PLACES_API_KEY`, one `searchText` call per firm returning the listing
  and up to five reviews, on a SKU Google's pricing page lists at 1,000 free
  calls a month, so a 250-firm batch costs nothing -- and Serper's `/places` +
  `/reviews` on the search key is the second. No key, no lookup: the step says
  so and skips. Nothing in the engine reads a maps.google.com page, and a 429
  is a block the pacer backs off from (config/listings.yml), never worked
  around.
- **The listing is kept whole** as `business_listing` -- name, category,
  address, phone, website, rating, review count, Maps URL, status -- under
  `listing:<provider>`, and its phone and address become claims that
  config/precedence.yml ranks (address first; phone after the site's
  structured data), so the firm row's phone and address now come from the
  listing where the site had none, as phase 3 asked. `review_count` from the
  listing outranks every search-snippet reading.
- **Reviews are kept word for word**, one line each (`google_reviews`), never
  summarised or rewritten: the pain analyser reads them as lines of the record
  and can only quote one whole, and the lead page shows them as quotations. Two
  new pain kinds, `review_complaint` and `low_rating`, name what a listing can
  prove; a five-star review is praise, not a pain. The listing block also
  carries the one disagreement the engine can see itself: a listing whose
  website is not the firm's domain (Duron's Manhattan listing, D-058).
- **One lookup per firm per month**, logged in `search_log` as kind `listing`
  with the answer as it came back (migration 103), so a rule change re-derives
  from the stored answer; r_search_links skips its snippet query for reviews
  while that row is fresh. The step sits in `find_people` before the search
  step, so the screen's Research button runs it.
- **Visible where the work is:** an "On Google" section on the lead page and
  the firm record; the claims table shows the profile in words; Home lists the
  service ("The Google Business Profile and its reviews", free tier named) and
  the two parts it unlocks moved from partial and planned to built.
- **Not verified live.** No Google Places or Serper key is in `.env`; both
  providers are tested against recorded answers. The first live run over the
  user's nine firms is the measurement: listings matched, reviews per firm,
  the address and phone filled where the site had none.
- **Found by the review (24 Sep 2026), and fixed:** the listing's address claim
  carried a seventh key, the printed text, so it could never "agree" with the
  site's address in reconcile -- the same defect D-052 fixed in the site reader;
  the standalone `city` precedence had not been given the listing sources, so a
  purchased-list city outranked Google's; a refetch whose reviews call failed
  wrote an empty review list over the reviews already on file (now the reviews
  are left standing, and the lookup is logged failed so it is asked again);
  Serper's cap counted star-only reviews, hiding ones with words; and the
  docstring promised re-derivation from the stored answer with no path to do
  it -- `--opt replay=1` now re-derives every claim from `search_log` without
  a call. The design review then made the section say why there is no listing
  (never looked up and what that needs, no match, a failed lookup) instead of
  vanishing, say where the listing disagrees with the firm's own record (a
  website that is not the domain, an address the site does not print), set the
  rating as a figure, and write dates and review lines in the sheet's words.
- **Measured:** 41 new tests (both providers, the seam, the matcher, the step
  and its replay, the record, the API and its notes, the provider lights); the
  engine suite passes; the frontend typechecks, lints and passes 73 tests.


## D-063 · The AI reads every page the crawler stored; a model is switched only after a bake-off

**Asked for (23 Sep 2026):** "the scrapers ... do a very poor job. I want the
content that is actually scraped to be passed to an LLM ... really good quality
but relatively free LLMs ... even the ChatGPT 6 is really cheap." Measured by the
AI-engineering review on the six firms with stored text: the reader was shown
24,000 characters of seven page kinds, and the careers and testimonials pages
the crawler had fetched never reached it.

**Rulings:**
- **Every stored page kind goes to the reader** (`prompt_rev` v3 for p8 and p9):
  the eleven kinds of config/crawl.yml, in a display order the prompt explains,
  with news and testimonials trimmed first and careers last of the trimmable
  (it is the only page where an in-house recruiter is visible); attorneys and
  team are still never trimmed. The budget is 120,000 characters, so nothing in
  the store is trimmed today; the output cap is 3,000 tokens, because a
  truncated answer is invalid JSON, not a shorter answer. Measured: 75,341
  characters reach the model over the six firms, 53% more than before, and on
  the one firm read at both widths three named people came with the extra
  text. Note the crawl caps: practice, locations, news and fees are capped at
  zero in config/crawl.yml (D-044), so the widening buys careers and
  testimonials today; raising `fees` is worth reconsidering, since the fee
  axis is the reader's first output and the page named after it is off.
- **No model line changes without measurement.** The bake-off harness exists
  (scratchpad, read-only against the store, `--models` list, a spend cap) and
  could not run: every paid slug answered HTTP 402 -- the OpenRouter key is
  about two cents past its purchased credit. The three free models that could
  be tried showed the failure that matters: two of three regularly answered
  in a shape that is not the strict schema (prose, a doubled brace, a wrong
  type), which loses every claim for that firm rather than weakening one.
  OpenRouter's "structured outputs" flag is a claim, not a guarantee. So Haiku
  4.5 stays on p8, ja8 and the sheet reader, Opus 5 on p9, and the user's
  candidate -- `openai/gpt-6-luna`, at a tenth of Haiku's input price and a
  million-token window -- is written into config/llm.yml commented, with its
  real price, next to a free-tier block that names the rate limit and the
  training-data caveat. Topping up the key and running the harness is the
  next step; the widened prompt on gpt-6-luna would land near a tenth of a
  cent a firm if it measures out.
- **A provider fault is one firm's failure, not the run's.** Found by the
  harness: OpenRouter answers 200 with a bare error body and no `choices` for
  an upstream fault or a free-tier throttle, and a `null` content on a cut-off
  answer; both crashed the whole run. Both now raise `LLMCallError` with the
  provider's words, per firm, never the key.
- **Measured:** prices in config/llm.yml corrected to OpenRouter's list of the
  day; 7 new keyless tests; the engine suite passes; ja8's output cap raised
  to 1,800 for the review lines D-062 adds to its record.


## D-064 · A paid step proves itself on a handful of firms before it may spend; a provider's error is never a verdict

**Asked for (28 Sep 2026):** the user handed over the Serper and NeverBounce
keys with ten credits on the address checker and said: test first, "if
nothing is working I don't want to burn my credits". The readiness audit of
the same day (brain/plan/readiness-audit-2026-09-28.md) had found the faults
below by reading; the live run confirmed them.

**Rulings:**
- **Read the balance before the run, cap the run, read the rows after.**
  NeverBounce's account-info call is free and is the first call of any live
  check; every paid run carries `--opt max_usd`; the attempt rows are read by
  hand before the cap is raised. The same discipline applies to the first run
  of any paid step from now on.
- **A NeverBounce non-success envelope is a failed call, not a verdict.**
  The provider answers HTTP 200 with `status` of `auth_failure`,
  `throttle_triggered`, `temp_unavail` or `general_failure` and no `result`.
  That now raises, writes no attempt row and leaves the address `unverified`,
  so a later run asks again. Before, the empty result became `risky` for good
  and the idempotency guard sealed it. A keyless test pins the envelope.
- **`UNCLASSIFIED` firms are never paid for.** The verifier's and the guesser's
  selections exclude them alongside `DQ_*`: the readiness check rejects the
  tier, so a check there could never make a lead ready. Seven of the nine
  firms in the store are `UNCLASSIFIED` today because the AI reader has no
  credit; that is the AI reader's problem to fix, not money for the checker.
- **One catch-all answer settles the domain.** The verifier marks every other
  candidate on that domain `catch_all` without a call, in the same run and in
  later runs (read back from `verify_attempt`). Live: fuchsberg.com answered
  catch-all on the second address; the run had paid a third time before this
  rule; the re-run settled the remaining eight for nothing.
- **A suffix is not a surname.** The first/last split every address scheme is
  rendered from now drops Jr., Sr., II–V, Esq., J.D. and the like, and reads
  "Smith, John A." surname-first. "John A. Smith Jr." produced `john.jr@` before.
- **The seams are forced in `.env`, not left on `auto`:** `LGE_SEARCH_ENGINE=serper`,
  `LGE_LISTINGS=serper`, `LGE_EMAIL_VERIFIER=neverbounce`. A Google Places key
  arriving later must not switch listings to the provider that costs twenty
  times as much (audit finding 8), and a Hunter key must never become the
  verifier.
- **Measured live, on the real store:** listings 3 of 3 found through Serper
  (one with a 4.9 rating and 36 reviews, ten kept word for word); 10 LinkedIn
  profiles on two firms in 11 queries; 3 NeverBounce checks for $0.024 — one
  `valid`, the domain catch-all; 7 credits remain. Home's four lights are on
  after the engine restart (settings are read once; a new key needs a restart).
  Still owed from the audit before any bulk run: chunked persistence in the AI
  readers, default spend caps, the queue.


## D-065 · Every Serper call runs under one set of rules; a paid search step cannot walk the store, leak a key, or record a refusal as an answer

**Asked for (28 Sep 2026):** "one more security check and one more detail
check for the places where the SERP API will be used ... I don't want to
waste even a single credit", with the Google Business Profile named as the
thing that must work. A security review of every Serper surface found no
critical or high issue with the key itself (header only, never a URL) and
six things worth fixing; a read of every call site found the rest. Billing
was measured from Serper's own `credits` field: **every call is one credit**
-- a 10-, 20- or 30-result search, page two, a places lookup, a reviews
page (which returns twenty reviews).

**Where Serper is asked, and why (the whole list):**
1. `website_check` -- one search per firm whose sheet website is missing,
   malformed, dead or names another business; the best result is adopted
   only after its own homepage names the firm.
2. `r_listing` -- the Google Business Profile: one `/places` call on the
   firm's name and place, the listing chosen by name overlap and a law
   category, then one `/reviews` call on its id. Two credits a firm. The
   only owner of the listing.
3. `r_search_links` -- one `site:linkedin.com` sweep per firm, a second
   page only when the first was full, then one query per decision-maker
   still unmatched (at most four); the company page rides along.
4. `r_search_emails` -- one query on the firm's domain and one per
   decision-maker without an address (at most four), read off snippets.
Nothing ever fetches a Google page; the Maps link is stored and shown only.

**Rulings:**
- **One call path.** `lge.search.serper.serper_post` is the one function
  every Serper request goes through, for search and listings alike: 429 is
  a moment's block (wait once, cool off); 401/403 and a 400/402 that names
  credit are a **refusal** (`SearchRefused`) that cools the engine off at
  once, so a run stops on the first bad answer and not the fifth; 5xx and
  timeouts get two bounded retries; a body that is not JSON is one failed
  query. Serper's `credits` go to a per-thread meter and every step ends
  with "provider charged: serper: N call(s), N credit(s)" -- the number to
  hold against the dashboard after every run.
- **The listing has one owner.** When a listings provider is configured,
  `r_search_links` makes no places call and no snippet query of its own;
  its fallback exists for a machine with no listings provider at all.
- **A sheet's value is a phrase, never an operator.** `clean_term` strips
  quotes, control characters, leading signs and `word:` operators and caps
  a term at 120 characters before it enters any query.
- **A paid step never walks the store by accident.** Over 250 firms it
  refuses unless given `limit`, `firm_ids_file` or `all=1`; a persisted
  daily ceiling (`daily_credit_cap` in config/search.yml, 5,000, counted
  from search_log so threads and restarts cannot reset it) stops every
  paid search step; `r_search_emails` has the 600-query run ceiling the
  LinkedIn step already had; disqualified (`DQ_*`) firms are never
  searched for. Unclassified firms still are, because the AI reading that
  classifies them runs later in the same flow.
- **A refusal is not an answer.** `website_check` writes no row for a firm
  whose search failed (a row would have kept it from being searched again
  for thirty days), and stops searching after five failures in a row.
- **The verifier keys leave the URL and the logs.** NeverBounce is called
  with the key in a POST body; the httpx logger is set to warnings in the
  CLI and the API, so no request line with a key or a person's address
  reaches a terminal or a log file; a transport error's message has its
  query string cut before it is recorded.
- **Only our own hosts are answered.** The engine carries a trusted-host
  check (`127.0.0.1`, `localhost`) and the screens a Host check on every
  request, so a page elsewhere that re-points its own name at 127.0.0.1
  cannot read contacts or start paid research from the LAN.
- **A Maps link is judged by its host,** never by a substring anywhere in
  the URL; the pacer is thread-safe, so the screen's parallel jobs cannot
  burst past the rate gap.
- **Measured live after the change, on the real store:** listing 1/1 found
  with ten reviews and a reported charge of 2 credits; the link step 4
  queries, 4 credits, no second listing call; one NeverBounce check by POST
  answered `valid`; the engine answers 400 to a foreign Host and 200 to its
  own. 1,403 backend tests and 73 frontend tests pass.


## D-066 · A malformed id is "not found", a strange cursor is refused, an "unknown" is asked again

**Asked for (28 Sep 2026):** "sab broken fix karo jaldi se" -- everything the
readiness audit called broken or degraded, fixed at once.

**Rulings:**
- **A path id that cannot be a uuid is 404 on every route**, checked by
  `lge.api.errors.is_uuid` before any query; a pasted or truncated link
  never reaches Postgres and never becomes a 500.
- **A cursor the list did not give out is 400 `bad_cursor`**
  (`lge.api.cursor.cursor_parts`), on the leads views, the stage queue and
  the firms list; before, it was ignored and the client restarted at page
  one without knowing.
- **A hand-check decision needs a real firm and an attribute it has a claim
  for** (404 / 400); a junk row no longer counts toward gate G2.
- **A batch action keeps each lead in its own savepoint** and reports a
  refusal by its message alone, never a Python repr; one lead's failure
  neither aborts the rest nor rolls back the ones already reported ok.
- **An import left `loading` by a restart is swept to `failed`** at the
  engine's start with a note, exactly as jobs are, so it can be loaded
  again (finished batches are kept and skipped); the start is conditional
  on the status the request read, so two clicks start one load.
- **A failed AI call with no usage costs nothing** in `llm_call`; the
  estimate is booked only for a call that ran.
- **A verifier's "unknown" is not a verdict.** It is recorded as an attempt
  with result `unknown` at no cost, the address stays `unverified`, and it
  is asked again after seven days, twice at most; a real verdict settles
  the address as before. The guesser records an unknown at no cost and
  moves to the next scheme.
- **Measured:** every fix has a test (malformed ids on 16 routes, four bad
  cursors, hand-check, batch, import sweep, the unknown retry cycle); the
  suite passes; the live engine answers 404, 400 and 400 to a bad id, a bad
  cursor and a foreign host.


## D-067 · Google sign-in, one admin by settings, an onboarding form, and a Users screen that sets each person's access

**Asked for (28 Sep 2026):** Google authentication and account management.
vishal.tiwari@legalsoft.com is the primary admin, "the one who will be
initiating everything"; anyone else from the team who signs in for the
first time goes through an onboarding form; the admin has a Users tab and
decides, per person, what access to give. Plan: brain/plan/auth-plan.md.

**Rulings:**
- **The engine owns sign-in, not the screens.** The OAuth code flow runs
  through `/api/auth/google/start` and `/callback`; identity comes from
  Google's own userinfo endpoint over TLS (no token is decoded here, no
  new dependency); the session is a row keyed on the hash of a random
  token, the browser holds the token in an HttpOnly, SameSite=Lax cookie,
  thirty days sliding. The screens' proxy makes the cookie same-origin.
- **Only legalsoft.com accounts may sign in** (`LGE_ALLOWED_EMAIL_DOMAINS`);
  an unverified address, another domain or a disabled person is sent back
  to Home with a plain reason in the address bar, never a stack trace.
- **The admin is named in settings, not in the table.** `LGE_ADMIN_EMAILS`
  makes those addresses admins the moment they sign in, onboarded without
  the form, and the Users screen cannot demote or disable them; nor can an
  admin take away their own access. The owner never waits for approval.
- **Everyone else lands `pending` and fills the form once** -- name, role,
  team, what they will use the engine for, phone -- kept whole and shown to
  the admin; then they wait until the admin sets viewer, operator, admin or
  disabled. Every change of standing is a row in `app_user_event` with who
  made it.
- **Three levels are the whole of "what kind of access":** viewer reads,
  operator works the leads (every write), admin also sees Users. The door
  is one dependency on every ordinary router: 401 signed out; 403 with the
  standing as the code; 403 read_only on a viewer's write; 403 admin_only.
  Sign-in, health and the docs stand outside it.
- **The door is open until the OAuth client is configured.** With no
  `GOOGLE_OAUTH_CLIENT_ID`/`_SECRET` the engine answers its one local
  operator as before, so nothing locks the owner out before the client is
  made; Home's capabilities say sign-in is off. The one-time setup is a
  Google Cloud OAuth client (Web application) with
  `http://127.0.0.1:5000/api/auth/google/callback` as its redirect URI.
- **Records name the person.** Decisions, notes, outcomes, journey edits
  and hand-check decisions carry the signed-in address as their actor
  where they used to say "ui".
- **Measured:** migration 104; 9 sign-in tests walking start → callback →
  onboarding → the admin's decision → a viewer's refused write, with Google
  faked; the API suite passes; the contract is exported and the screens'
  types regenerated.


## D-068 · Two doors: Legal Soft walks in, an email vendor's team only by the allow list

**Asked for (29 Sep 2026):** "sign-in pages mein pucho ki user Legal Soft se
hai ya email vendor ki team se ... jo Legal Soft se hai usko seedha login do;
email vendors ko check karna hai ki wo allow list mein hai ya nahi, jo ki
hum baad mein banayenge."

**Rulings:**
- **The sign-in screen asks first.** "I'm from Legal Soft" is the staff
  door: a legalsoft.com Google account, Google shown only that domain,
  straight in. "I'm from an email vendor's team" is the vendor door: any
  Google account, but the callback admits it only when `vendor_allow`
  names the address or its whole domain (`@sendco.com`); otherwise the
  person is sent back with `signin=not_invited` and told to ask the admin.
  Which door was chosen rides inside the signed state, so nobody can
  switch doors between start and callback.
- **A Legal Soft account is staff by either door.** The domain decides,
  not the button.
- **A vendor's person is a person like any other after the door**: kind
  `vendor`, the vendor's name from the allow list on their row, the same
  onboarding form, the same wait for the admin, the same three levels.
- **The allow list is the admin's, and its API exists now** (`GET/POST
  /api/users/vendors`, `DELETE /api/users/vendors/{id}`; an entry is a
  whole address or a whole domain, with the vendor's name, a note and who
  added it). The screen for it comes with the handover work; until then the
  admin adds an entry through the API.
- **Measured:** migration 108; one test walks the vendor door refused,
  the staff door refused for the same account, the admin listing the
  domain, the vendor admitted as `vendor` with the vendor's name, a Legal
  Soft account through the vendor door still staff, and the entry removed
  closing the door again; 137 API tests pass; the screens' contract and
  types regenerated.


## D-069 · Twenty reviews a firm, the poor ones first

**Asked for (29 Sep 2026):** "max reviews rakho 20 jisme hume low star review
ko main preference dena hai, cause yeh hi humara pain point pakadne mein
help karega." Found on the way: on a 54-review listing the "most relevant"
page Google serves first held one 1-star review; the same listing sorted
lowest-first held eight.

**Rulings:**
- **`max_reviews` is 20** (config/listings.yml). Serper returns twenty a
  page, so the old cap of ten threw half of one paid page away.
- **The poor reviews come first.** Serper is asked for the lowest-rated
  page; every review at or below `low_star_max` (3) stars is kept; the rest
  of the cap is filled from the most relevant page, never a repeat. Two
  credits a firm for reviews instead of one, only when the poor ones do not
  fill the cap on their own. Google's own Places API cannot sort and stays
  at its five.
- **Measured on The Duron Law Firm:** ten reviews (one 1-star) became
  seventeen (six 1-star, all in Spanish); the pain analysis went from one
  pain ("site not updated since 2013") to three, the new two quoting the
  reviews themselves — the attorney does not return calls; staff spoke ill
  of a client on a line that was still open — at 90% confidence, nothing
  dropped. Cost of the re-read: 3 Serper credits and half a cent of Haiku.


## D-070 · Every email carries Legal Soft's offer in its own numbers, and one call to action

**Asked for (30 Sep 2026):** the team read the Duron report. The subject
was right; the bodies were not: "our USPs were not mentioned", they want
"numbers related to the revenue growth that can be achieved", the offer
must be inserted "intelligently ... addressing the pain point", and "the
CTA was actually lacking ... a button, a link". Two emails that had worked
before were given as the pattern (pre-vetted, trained by U.S. attorneys,
start in under 3 days, full-time and exclusive, about 60% less than local
hires, no long-term contract).

**Rulings:**
- **The numbers are the company's own, never the engine's.** config/usp.yml
  holds each fact with where it was read: legalsoft.com on 30 Sep 2026
  ("under 3 days", "60% savings compared to hiring locally", "40% increase
  in profits reported by law firms", "2,500 staff across 1,000+ law firms",
  "trained by U.S. attorneys", a legal assistant "from $2,227/mo") and the
  team's sent emails ("full-time exclusively for your firm", "no long-term
  contract"). A figure changes there when the company's claim changes.
- **The offer is chosen by the pain and rotated by the email.** Under the
  copy, every drafted email gets one paragraph: who we offer (by the pain
  that armed the lead; a tier can name its own, so an immigration firm with
  unreturned calls is offered "bilingual intake specialists"), up to three
  facts in the order the touch prefers (the arithmetic email leads with the
  60% and the 40%), and, in the first two emails, the sentence that answers
  the pain. A fact the copy already states is not said twice. Every email
  carries at least one number.
- **The pain is why we write, never what we say.** No offer sentence names
  a review, a rating or a complaint.
- **One call to action, as a link.** config/sender.yml `cta`: "Book a
  15-minute call with our team" and Legal Soft's own contact page, with a
  line for the reader who would rather reply. In plain text it is a line; a
  sending tool that writes HTML gets the same label and link as a button
  (`lge.journey.usp.cta_html`). No link configured, no call to action drafted.
- **Cost is now said, in the company's words.** D-060's copy kept price out
  of the emails; the team's word is that the 60% and the 40% belong in
  them. The banned phrases stay banned ("replace", "cut costs", "reduce
  headcount", "offshore", "virtual assistant", "cheaper than hiring"): the
  saving is stated as the company states it, not as a reason to let anyone go.
- **Measured:** 119 journey tests pass; six new ones pin the offer, the
  number in every email, the link, the rotation, the no-repeat rule and the
  banned phrases. The Duron report was rebuilt with the new emails.


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
