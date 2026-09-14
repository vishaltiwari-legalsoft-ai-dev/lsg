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
