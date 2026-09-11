# Build Plan

Lead Gen Engine · planned 11 Sep 2026
Builder: solo + Claude · Assets in hand: firm dataset export only

Knowledge base: [context/](context/) — 39 chunks. This plan references it rather than
repeating it. Start with [context/INDEX.md](context/INDEX.md).

---

## Scope

Four things. Nothing else.

| # | | Output |
|---|---|---|
| **1** | **Lead acquisition** | Find the firms. Discovery, deduplication, one clean record per firm |
| **2** | **Qualification** | Decide who is worth contacting. Fee model, practice, size → tier + wedge SKU |
| **3** | **Pain identification** | Find who is hurting *right now*, and capture the sentence that proves it |
| **4** | **Outreach journey + drafts** | The 9-touch sequence and the actual emails, written and ready |

**Delivery is out of scope.** Sending infrastructure, domains, deliverability, sequencing
tools — not modelled here, not planned for, not our problem. The deliverable ends at a
qualified lead with its pain identified and its emails drafted.

---

## Where we are

| | Status |
|---|---|
| Specification | **Complete.** 5 documents, contradictions resolved, ~34 components specified |
| Code | **None.** Greenfield. Not a git repo yet |
| Firm dataset | **In hand** — the accelerator. Coverage analysis is a day-1 win |
| Portal (talent pool + role requests) | **No access.** Affects the bench gate and one suppression source |
| Job history file | **Not in hand.** I2 deferred; it was last in the order anyway |

---

## Pain is the product

The three stages before the email exist to answer one question: **what is this specific firm
struggling with today, in their own words?**

That sentence — `signal.evidence` — is the whole point.

> Without it the outreach is generic and the whole targeting effort is wasted.

| Stage | Answers | Without it |
|---|---|---|
| Acquisition | Does this firm exist, and is it one record or four? | You email the same partner four times |
| Qualification | Would this firm ever buy? | You pitch a paralegal to an hourly firm — asking them to convert revenue into cost |
| **Pain** | **Is it hurting now, and how do I prove I noticed?** | **"We place paralegals" — indistinguishable from every other vendor** |

Every email draft in this plan is built backwards from a pain signal. No signal, no email.

---

## The pain signals, ranked

Full catalog: [context/20-signals/01-signal-catalog.md](context/20-signals/01-signal-catalog.md)

| Pain | What it proves | Who else sees it |
|---|---|---|
| **Role open >21 days** | They decided, budgeted, published — **and failed to fill it** | Everyone |
| **Role reposted** | A dated, affirmative admission that hiring failed | Almost nobody *(needs our own `first_seen`)* |
| **Reviews: nobody called back** | Signed cases walking away, in the words of the people they lost | **Almost nobody** |
| **Mass tort campaign** | About to sign claimants in bulk, each needing 4–6 provider requests | Rarely |
| **Two+ roles open** | Expansion, not backfill | Some |
| **Heavy ad spend** | Buying case volume faster than staff can absorb | Everyone |
| **New CMS implemented** | The moment they discover the workflow needed a *person*, not a feature | **Almost nobody** |

**Strategy:** run the job signal at volume, but win it on the opening line — not on speed,
which is trivially matched. Put disproportionate effort into reviews, mass tort and CMS
change: weaker evidence, **effectively uncontested**.

---

## The 48-hour target

**Ships:**

1. A Postgres database of real law firms — discovered, deduplicated, crawled, **classified
   into tiers by fee model**
2. **Live pain signals** read from firms' own careers pages, each carrying the sentence it was
   read from
3. A **ranked lead list** — highest pain, lowest competition first
4. **The outreach journey** — 9 touches, and the actual emails drafted

Hour-by-hour: [plan/48h-sprint.md](plan/48h-sprint.md)
Journey logic: [plan/outreach-journey.md](plan/outreach-journey.md)
The emails: [plan/email-drafts.md](plan/email-drafts.md)

---

## Milestone arc

Gates are hard. A failed gate stops the flow — everything downstream is spent per-firm, so an
upstream error multiplies through every later stage.
Full detail: [plan/milestones.md](plan/milestones.md)

| # | Milestone | Gate at exit | Estimate |
|---|---|---|---|
| **M0** | **Procurement** — customer list, Places key, portal access | — | Day 1, ongoing |
| **M1** | **Foundation** — repo, schema, invariants I1–I7 as constraints, normalizers + tests | Normalizer suite green; I1–I7 provably enforced | **Day 1** |
| **M2** | **Firm dataset load** — I1 → observation, coverage analysis | G7 — numbers before any discovery narrowing | **Day 1** |
| **M3** | **Identity resolution** — blocking, R1–R4, union-find | **G1 — dedupe verification. Hard stop** | **Day 2 AM** |
| **M4** | **Qualification** — P1–P8, reconcile(), icp_tier() | G3 — tier distribution sane | **Day 2 PM** |
| **M5** | **Pain detection** — JA1 careers, JA6 agency filter | G8 — agency filter before a second source | **Day 2 PM** |
| **M6** | **Journey + drafts** — 9 touches, every token resolving to a column | No unresolvable token exports | **Day 2 PM** |
| — | *48h line* | | |
| **M7** | **Probe validation** — 3 metros, tier 1A, full chain | **G2 — 50 records hand-checked on every attribute** | ~2 days |
| **M8** | **Contacts** — D2 bar directories, R2, R1, R3, R4 verify | Verified-email rate measured | ~1 week |
| **M9** | **Pain breadth** — JA2 bar boards, JA3 ATS, Craigslist, W3 reviews, robots audit as a script | G9 — lane 1 measured before lane 2 is bought | ~1.5 weeks |
| **M10** | **Scoring & lifecycle** — score_nightly, arm_leads, observability | G5 bench join | ~1 week |
| **M11** | **Beachhead** — tier 1A nationally, metros first by density | Duplicate check clean, decision-maker coverage holds | ~2 weeks |
| **M12** | **Widen** — tier 1B, tier 2, then tier 3 + tier-4 holdout | Tier 2 converts within range of 1A | ongoing |

---

## UI track — two repos

Full plan: [plan/ui-plan.md](plan/ui-plan.md)

| Repo | What | Where |
|---|---|---|
| **backend** | This engine + a FastAPI layer + the knowledge base | This folder (already a git repo; the database, venv and data live here) |
| **frontend** | Next.js web app, types generated from the backend's OpenAPI contract | New sibling repo `C:\Users\ACER\Desktop\lead-gen-web` |

**Split timing:** right after the live probe completes and its results are verified. Moving the
database or venv under a running crawl would break it, and the API contract has to exist before
the first line of frontend code.

**Why the UI matters beyond convenience:** it is where outcomes (replied, won, lost) get
recorded. Sending happens outside this system, so without an outcome button the attribution join
never runs and every scoring weight stays a seeded guess.

UI milestones: UI-0 API + scaffold → UI-1 Leads → UI-2 Hand-check (gate G2) → UI-3 Outcomes +
attribution → UI-4 Review queues → UI-5 Pipeline + Settings → UI-6 Journey preview → UI-7 Auth
(before any hosting).

---

## Critical path

```
Day 1 ─── M1 foundation ──► M2 dataset ──► M3 identity ─┐
     │                                     [GATE G1]    │
     │                                                  ▼
Day 2 ────────────────────────► M4 qualify ──► M5 pain ──► M6 journey + drafts
     │                          [GATE G3]      [GATE G8]
     │
     └─── customer list request ──────► clean handoff list ──►
     └─── portal access request ──────► I3/I4 ────────────────►
```

Nothing on the code track blocks on anything external. The customer list only matters at
hour 44, when the list gets produced.

---

## The one list hygiene rule that stays

Even though we do not send, **the list we hand over must be clean.** Three filters, applied
when the list is produced — not once, every time:

```
suppression   domain | email | firm_id     -- customer, optout, dq, bounce
firm_track    'portal'      → never cold    -- when portal access lands
grade         'B'           → phone motion only, never on an email list
```

**Why the customer filter matters even though we are not the sender.** A list containing your
own paying customers, handed to whoever does send, produces a prospecting email arriving at a
firm that already pays you. The failure lands the same way regardless of whose SMTP server it
came from — and it is one afternoon to prevent.

**Grade B is not a reject pile.** Named partner, working phone, live pain — just no verifiable
email. That is a phone-and-research list, worked differently. Deleting them throws away a
large slice of the collection effort; putting them on an email list damages the ability to
email anyone.

---

## Stack

Every choice is either named in the source documents or forced by them.

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Forced — trafilatura, Playwright, phonenumbers, Prefect are Python |
| Packaging | **uv** | Fast, lockfile, no ceremony |
| Store | **Postgres 16** + `pg_trgm` + `postgis` | Specified. Docker Compose locally |
| DB access | **psycopg3 + plain `.sql` files** | The spec is SQL-first — `icp_tier()`, `reconcile()`, invariants as triggers. An ORM would fight it |
| HTTP | **httpx** + per-host token bucket | Rate discipline is per-domain, not global |
| Parsing | **selectolax** → **trafilatura** (P4) → **Playwright** (P3, gated <500 words) | Specified |
| Domains | **tldextract** (Public Suffix List) | eTLD+1 is the core dedupe key |
| Phones | **phonenumbers** | libphonenumber, region US → E.164 |
| LLM | **claude-haiku-4-5** (P8, Batch API) · **claude-opus-5** (P9) | Specified, structured outputs |
| Orchestration | **Deferred.** CLI first, Prefect at M10 | See below |
| Test | pytest · ruff | |

### Why Prefect is deferred, and why that is not a shortcut

The architecture's core invariant is that **no component reads another component's output
directly — everything is mediated by the store.** That makes every component independently
runnable, and the orchestrator a **late-binding choice**.

Each component gets a CLI entry point (`lge run p6 --firm-id …`). Prefect at M10 wraps those
callables; it does not restructure them.

The one thing that must be right from the start is **idempotency keying on
`(component, entity_id, input_hash)`** — build it into the CLI runner in M1, because
retrofitting it is expensive and it is what makes every re-run free.

---

## Repo layout

```
lead-gen-engine/
├── PLAN.md                    ← this file
├── context/                   ← the knowledge base, 39 chunks
├── plan/
│   ├── 48h-sprint.md
│   ├── outreach-journey.md    sequence logic, eligibility, pain → angle mapping
│   ├── email-drafts.md        the actual copy
│   └── milestones.md
├── docker-compose.yml         postgres 16 + redis
├── pyproject.toml
├── sql/
│   ├── 001_schema.sql         13 tables + indexes + invariants I1–I7
│   ├── 002_functions.sql      icp_tier() · signal_weight() · decay() · reconcile()
│   └── 003_views.sql          lead ranking, coverage analysis, gate queries
├── config/
│   ├── practice_areas.yml     the 15-slug closed vocabulary
│   ├── fee_patterns.yml       P6 regex, precedence-ordered
│   ├── sources.yml            per-source rate limits, blocklists
│   ├── agency_blocklist.yml   legal-staffing agencies — maintained, not static
│   ├── title_synonyms.yml     normalize_title() canonical role map
│   └── board_registry.yml     source_state · crawl_delay_s · platform
├── journey/
│   ├── sequences.yml          9 touches × tier × signal-kind branching
│   └── copy/                  one file per touch per tier
├── lge/
│   ├── cli.py                 lge run <component> — idempotency keyed here
│   ├── db.py                  psycopg pool, migrations
│   ├── norm/                  domain · phone · addr · name · practice (+ norm_version)
│   ├── planes/
│   │   ├── d/                 D1 places · D2 bar · D3 directories
│   │   ├── p/                 P1–P9
│   │   ├── ja/                JA1–JA6
│   │   ├── r/                 R1–R5
│   │   └── i/                 I1–I4
│   ├── resolve/               blocking · rules R1–R4 · union-find · verify
│   ├── score/                 fit · intent · decay · contest · bands
│   └── fetch/                 httpx client, per-host buckets, robots cache
└── tests/
    ├── test_norm_*.py         ← written BEFORE any harvest runs
    ├── test_list_hygiene.py   ← suppressed and grade-B rows must never appear
    ├── fixtures/
    └── test_gates.py          G1, G3 as executable assertions
```

---

## Procurement — request today

| # | Item | Lead time | Blocks | Ask |
|---|---|---|---|---|
| 1 | **Customer list export** | Hours–days | List hygiene. **Biggest risk retired per unit of effort** | *"Domains are enough."* |
| 2 | **Google Places API key + quota** | Hours | D1 — all external discovery | Billing enabled |
| 3 | **Portal API/DB access** | Unknown | I3, I4, `firm_track='portal'`, open question O1 | |
| 4 | **Email verification** (R4) | Days | Grade A/B split | |
| 5 | Contact enrichment (R1) | Days | Deferrable — R2 bar records is free and better | Not urgent |
| 6 | DataForSEO (JA5) | Days | Deferrable to M9 | Already in the stack per docs |
| 7 | Licensed job feed (JA4) | Weeks | **Deliberately last** — G9 | Do not start |

---

## Open questions this plan carries

| # | Question | Costs | Changes |
|---|---|---|---|
| **O3** | Where did the firm dataset come from — team-built, purchased, unknown? | One conversation | Its reconciliation precedence. **Must be set before the first load, not after the first conflict** |
| **O4** | Its overlap with the external harvest? | One query, in M2 | **May materially shrink the discovery plane** — the largest stage in the build |
| **O1** | Which reading of portal Feed B is right? | One conversation | Whether it is a suppression source, a pain signal source, or both |
| **O2** | What fields does the job history file carry? | 15-min inspection | Whether that asset is usable, partly usable, or a trap |

---

## A note on where the numbers come from

Every scoring weight, tier ranking, signal ordering and routing band in the specification is a
**seeded hypothesis** — the source documents say so in their own footers.

`lead.arming_signal` records which pain signal surfaced each lead. If reply or outcome data
ever becomes available from whoever sends, this join converts the guesses into measurements:

```sql
outcome × signal kind × tier      -- joined on lead.arming_signal
```

The column costs nothing to carry and cannot be reconstructed later. **Keep it populated even
though nothing reads it yet** — it is the difference between the targeting improving over time
and staying a permanent hypothesis.

---

## Deliberately out of scope

Carried from [context/70-decisions/02-deliberate-exclusions.md](context/70-decisions/02-deliberate-exclusions.md)
so none of it gets re-proposed as an oversight:

- **No scraping of Indeed, ZipRecruiter or LinkedIn.** All three prohibit it in their own
  published files. JA1 gets the same pain signal from the firm's own server with a real
  `datePosted`
- **No automated professional-network extraction.** Bans and legal exposure
- **No defeating bot-management layers.** Repeated 403/429 → stop, re-read the policy, lower
  the rate, mark the source closed. Never retry harder
- **No evasive crawling.** One honest, contactable User-Agent
- **No commercial modelling.** `_archive/` is not to be built from
- **No sending, no delivery, no deliverability.** Out of scope entirely

---

## First actions

**Before code:**
1. Request the customer list export
2. Enable the Places API key
3. Answer **O3** — where the firm dataset came from

**Then:** [plan/48h-sprint.md](plan/48h-sprint.md), hour 0.
