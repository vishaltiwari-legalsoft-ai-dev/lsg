# Readiness audit — before the 100k sheet (28 Sep 2026)

**Why this exists.** NeverBounce and Serper credit has been bought, and a raw sheet of more than 100,000 leads is coming. Before a single credit is spent, the whole engine was checked for what is broken, what is degraded, and what will not survive that volume. Nothing was changed in the code during the audit; this document is the work order that follows from it.

**Status, later on 28 Sep 2026.** The Serper and NeverBounce keys are in `.env` (Serper forced for search and listings, NeverBounce forced as verifier); findings 2 (error envelope), 9's `UNCLASSIFIED` gate, 23's catch-all re-spend and the name-suffix split are fixed and tested (D-064). Live on the real store: listings 3/3 found via Serper, 10 LinkedIn profiles on 2 firms, 3 NeverBounce checks (1 valid, 1 catch-all domain), 7 checker credits left. A second pass the same evening (D-065) closed 10, 11, 12 (the search-step half of 20: a 600-query ceiling, a 250-firm refusal and a persisted daily cap of 5,000 logged searches), 25's search half (the listing has one owner) and 30 (billing measured: every Serper call is one credit; `has_listings` no longer decides spend); it also added a trusted-host check on both servers. A third pass (D-066) closed the "degraded" list: 12 (malformed id → 404 everywhere), 13 (import orphan sweep at startup; conditional start), 15 (`unknown` kept retryable, 7 days, twice), 18 (hand-check validates firm and attribute), 19 (batch: plain message, savepoint per lead), 20's bad-cursor half (400), 22 (failed AI call costs zero). Still open: 14 (upload in memory, request-held transaction), 16, 17, 20's filter half, 21 (not a defect: an unknown query parameter is ignored by design), and everything under Blockers and Scale. **29 Sep 2026:** blocker 3 closed (the AI readers persist and checkpoint every 50 firms; `chunk_size` in config/llm.yml). Everything else below stands.

**How it was done.** The full backend suite (1,373 tests) and the frontend suite (73 tests, typecheck clean) were run. Postgres and the engine were started and all 40 routes were called live, on the real store (9 firms) and then on a throw-away copy of the database into which a synthetic sheet of 100,000 rows was loaded through the normal upload path. Three focused reviews ran in parallel: every endpoint against its contract and the screens; the vendor seams (NeverBounce, Serper, Google Places, OpenRouter) against the real APIs; and the pipeline from upload to Actual Leads for what breaks at 100k, with crawl rates taken from the September probe logs (242 firms). The scratch database, the scratch page store and the synthetic sheets were removed afterwards.

## The verdict in one paragraph

The **intake** can take the sheet: 100,000 rows uploaded in under a second, loaded, deduplicated into 96,729 firms and turned into claims in 85 seconds, with the store at 531 MB and every read endpoint still answering in well under a third of a second while the leads are unscored. The **screens** cannot show the result once those leads are scored: every Leads view and the Home page then take about six seconds a click, because the list classifies the whole universe on every request, and the screens' proxy gives up at thirty. The **enrichment engine** cannot run at that volume as built: there is no queue, research is one thread per firm started from a button, the command-line flow holds every fetched page in memory until a step ends, one step rewrites every job posting in the store inside every single-firm job, and the tier gate would stop every flow the moment the sheet lands. At measured crawl rates the crawl alone is eleven days; the whole recipe run one firm after another is six to seven weeks. And the **vendor seams have never run live** — two of them have defects that would spend credit on nothing or poison the store on the first bad answer. The two keys the plan waits on are still not in `.env`. So: the sheet can be loaded today, but nothing should be enriched or verified until the blockers below are fixed and a ten-firm live run has been read by hand.

## What was measured

| Measurement | Result |
|---|---|
| Backend tests | 1,373 passed, 1 skipped (3 min 14 s) |
| Frontend | typecheck clean; 73 tests passed, 8 skipped |
| Live routes on the real store | 67 calls; 65 as the contract says, 2 wrong (findings 12, 21) |
| Upload of a 100,000-row CSV (10 MB) | registered in 0.6 s, columns read by rules (the AI key is out of credit) |
| Load + identity + claims for 100,000 rows | 85 s end to end; 200 batches of 500 at ~8 batches/s; 96,729 firms, 620 aliases, 372,576 claims |
| Rows with no firm name | 3,894 became "Unknown Firm" records with an open lead each — triage is still unbuilt (plan-v3 phase 1) |
| Database size at 100k firms, no crawl | 531 MB (observation 307 MB, firm_attribute 107 MB); 15–30 GB estimated after enrichment |
| Read endpoints at 100k unscored leads | everything ≤ 310 ms; leads pages 59 ms/page; firms search ~100 ms |
| Read endpoints at 96k **scored** leads | `/api/leads` (every view, including UNSCORED and stage views) 6.0 s; Home (`/api/today`) 6.1 s; EXCLUDED view 7.9 s; leads CSV export 5.5 s; engine process 211 MB |
| Crawl rate, September probe (12 hosts, 2 s per host) | P1 map 665 s / 242 firms; P2 fetch 1,360 s / 202 firms (28% of fetches were 404s from blind probes); careers 74 s / 242 firms; ~41 min per 250-firm batch |
| Stored page size | 36.7 KB average over 6,021 files; 12 pages a firm ≈ 44 GB and 1.2M files at 100k firms (free disk: 81 GB) |

## Findings, ranked

Severity: **blocker** stops the 100k run or spends credit wrongly; **degraded** gives a wrong or misleading answer today; **scale** is fine at nine firms and fails at 100k; **minor** is hygiene.

### Blockers — fix before any key goes in or any bulk run starts

1. **The keys are not there.** `.env` holds only the OpenRouter key, and it answers HTTP 402 (out of credit) on every paid model. NeverBounce, Serper and Google Places keys are absent, so the verifier, the search engine, the listing step and the address predictor are all inert and Home says so. Adding a key needs an engine restart to be seen: settings are read once and cached. Without a Serper key the search steps fall back to DuckDuckGo, which at this volume is 2,300 hours and a bot-check stop.

2. **NeverBounce error envelopes are recorded as real results.** NeverBounce answers HTTP 200 with `status: auth_failure | throttle_triggered | temp_unavail | general_failure` on any problem. The adapter never reads `status`, takes the missing `result` as empty, maps it to `risky`, writes a paid `verify_attempt` row and sets the address to `risky` — and the idempotency guard then forbids ever asking again. A mistyped key or one throttle burst would mark every candidate in the run unusable at full speed, and the address predictor would walk all six candidate patterns per person to nothing. (`lge/planes/r/r4_verify.py:183-188`, reused by `r_email_guess.py:216-225`.) Fix: raise on any non-`success` status; sleep-and-retry on throttle and temp_unavail; abort the run on auth_failure; a circuit breaker after five straight failures (the guesser has one, the verifier does not). Add a keyless test for the envelope.

3. **The AI readers persist nothing until the whole batch is done.** P8 and P9 build every selected firm's message, gather all the calls at once, and only then write `llm_call`, the claims and the ok marker. A crash or stop after 60,000 paid calls keeps none of them and the next run buys them again; memory holds every message at once. (`lge/llm/run.py:343-503`.) Fix: chunk (100 firms), persist and checkpoint per chunk, and give the run a default `limit`.

4. **No enrichment queue; research is one daemon thread per firm inside the API process.** A batch request of up to 100 leads starts 100 threads, each with its own database connection outside the pool of ten, plus a fresh connection for every progress update; nothing bounds how many batches run together; past ~105 jobs at once Postgres's 120-connection limit is hit and the progress write fails outside the step's error handling, killing the job. A restart fails every running job and nothing re-runs it. The parsing work shares the GIL with the screens. There is no sub-batch of 250, no Batch 1 before Batch 2, no start-by-itself, no pause or resume — plan-v3 phase 2 in full. (`lge/api/routes/actions.py:79, 147, 160, 240-263`; `deps.py:43`.) Fix: a persistent `enrich_batch` table (250 ids, class, status, current step, heartbeat, attempts) and one worker process outside the API claiming batches with `SKIP LOCKED`; the id-list seam every step already takes is the hook.

5. **The command-line flow cannot work in batches either.** Without an id list P1 and P2 take every firm and keep every page body in memory until the step ends (~1.2M bodies at 100k: out of memory hours in, nothing committed); `limit` is `ORDER BY id LIMIT n`, not a cursor, so P8, P9 and ja8 re-pick the same first 100 firms forever; any failed firm stops the flow; and the G3 tier gate counts `UNCLASSIFIED` in its "share moved" check, so after the load it sees UNCLASSIFIED go from ~0% to ~99% and stops every flow. (`lge/fetch/selection.py:29-42`; `p1_site_map.py:481-504`; `p2_fetch.py:112-193, 372-395`; `flowrunner.py:135-146`; `ops/gates.py:67-82`.) Fix: the worker always passes an id list; batch mode records failed firms and carries on; G3 compares classified tiers only.

6. **Every single-firm job rewrites every job posting in the store.** `ja6_normalise` and `ja6_closure` take no firm list: each research job runs three to six unconditional writes per posting over the whole table, locks those rows until its step commits (so concurrent jobs queue behind each other), and the resolution ladder runs `similarity()` as a full scan of `firm` with no index on `addr_hash` or `lower(city)`. Each job gets slower as the store grows. (`config/flows.yml:113-118`; `ja6_normalise.py:29-36, 106-183`; `ja6_resolve.py:133-166`.) Fix: an id list for both steps, write only when a value changes, the two indexes.

7. **The Leads screen and Home classify the whole universe on every call.** `classify_open_scored_leads` loads every open scored lead, all their contacts and emails, and renders a nine-email journey for each SEQUENCE/NURTURE lead in Python — and it is called by `GET /api/leads` for every view (only to fill the counts), by Home, by the lead detail page (to find one lead's blockers) and therefore by every action that returns a lead. Measured at 96k scored leads: six seconds a click, on every screen, before contacts exist; it grows with every finished batch and the screens' proxy times out at 30 s. (`lge/export/list.py:151-179, 362-512`; `leads.py:305, 530`; `today.py:109`.) Fix: counts in SQL; classify only the page; classify one lead by id for the detail page; store the classification per batch (the Actual Leads pool, brought forward) and page it in SQL.

8. **Google Places is preferred by `auto` and costs about twenty times Serper.** A Text Search with reviews in the field mask is the Enterprise + Atmosphere SKU, about $40 per 1,000 after the free 1,000 a month; at 100k firms that is ~$4,000 per pass and the 30-day recheck re-buys it monthly. Serper does the same job for two credits a firm. The day a Google key lands, listings silently switch to the dear provider. Likewise the `auto` verifier prefers Hunter ($0.049) over NeverBounce ($0.008) should a Hunter key ever appear. (`lge/settings.py:112-132`, `config/listings.yml`, `config/resolvers.yml`.) Fix: Serper first in `auto`, Google only when forced; `LGE_EMAIL_VERIFIER=neverbounce` and `LGE_LISTINGS=serper` in `.env`; recheck at 180 days or only for leads in play.

9. **No default budget on any paid step.** The dollar cap on verification and guessing is opt-in; `r_search_emails` has no query cap; `r_listing` looks up every firm with no lead or tier filter and no limit (one command-line `research` run is 100k listing lookups); P9 escalates to Opus on low confidence or an unknown fee model and is 45–65% of the AI bill. Verification and guessing also spend on firms that can never be ready: the gate is `tier NOT LIKE 'DQ%'`, but a firm with no fee model or practice falls through to `UNCLASSIFIED`, which passes the gate while the readiness check rejects it. Nothing calls NeverBounce's account-info endpoint before a run. (`r4_verify.py:261-266, 326`; `r_email_guess.py:85-90, 172`; `r_listing.py:99-122`; `p9_escalate.py:69-95`; `sql/002_functions.sql:50`.) Fix: a spend ledger with default per-run and per-day caps; listing and search only for open non-DQ, non-UNCLASSIFIED leads; P9 opt-in for bulk runs; a balance preflight.

10. **The search pacer is shared by up to 100 threads with no lock.** The 0.25 s Serper gap is not enforced across threads; a burst gets a 429, the 300 s cooldown fails every thread's searches, and the jobs finish "done" with the LinkedIn and email steps silently empty. (`lge/search/__init__.py:113-127`, `pace.py:50-113`.) The single worker from finding 4 removes this; otherwise a lock.

11. **The NeverBounce key and the person's email travel in the URL, and httpx logs full URLs at INFO.** The root logger is at INFO, so every command-line verification prints the key and a personal address to stdout and the log files. (`r4_verify.py:184`; `cli.py:15`.) Fix: `httpx` logger to WARNING; the key in a POST body.

### Degraded — wrong today, at any size

12. **Any id-taking route returns 500 on a malformed id** where the contract promises 404: `/api/leads/{id}` and everything under it, `/api/firms/{id}`, `/api/jobs/{id}`, `/api/imports/{id}`, `/api/firms/{id}/jobs`, hand-check. A pasted or truncated link shows "Something went wrong". Every test uses a well-formed zero UUID, so none caught it. Fix: one helper that parses the UUID or raises not-found.

13. **An import interrupted mid-load is stuck "loading" forever.** The status flips to `loading` on its own connection and the pipeline runs as a background task in the API process; a restart leaves the row at `loading` and every later load attempt gets 409. Jobs have a start-up sweep; imports do not. Two quick clicks also launch the load twice (no conditional update). Also seen live: the screen says **Loaded** while identity resolution and claims are still running — the notes arrive only at the end. (`imports.py:254-283`.)

14. **The load request holds a transaction open for the whole background chain.** Observed: a connection "idle in transaction" for the entire load, pinned out of the pool. The research runner avoided exactly this by using threads; the import path did not. And the upload itself reads the whole file into memory behind a 50 MB cap and runs the column reader (up to 60 s) plus a full count pass inside the request, behind the 30 s proxy: a 100k-row sheet carrying job-post text will likely be over 50 MB and need splitting, and a big XLSX shows an error in the browser while the server registers it anyway. Fix: stream the upload to disk; register and load off the request, the way jobs run.

15. **Unknown verification results are permanent.** NeverBounce `unknown` (transient by its definition) becomes `risky` and is never re-asked; the lead is parked at "almost" for good. Fix: keep `unverified`, store the attempt with a retry-after, at most two tries.

16. **A failed reviews call re-buys the listing.** When Serper `/reviews` fails the lookup is logged failed, the firm is re-selected next run, `/places` is bought again, the failure does not count toward the breaker, and the search-links step buys a third `/places`. Fix: count review failures in the breaker; log `found` with reviews pending, keyed on the stored place id.

17. **Verification timeouts are paid twice.** No NeverBounce `timeout` is sent and the client gives up at 10 s; NeverBounce finishes and bills, the engine writes no row, the next run pays again. Fix: send `timeout=25`, client at 35 s.

18. **The hand-check endpoint writes without checking the firm or the attribute** (an unknown firm is a 500 on the foreign key; a typo'd attribute is silently counted toward the gate). Fix: 404 and 400.

19. **Batch actions leak a Python repr and can report success for rolled-back writes** (all leads share one transaction; a mid-loop failure aborts everything after it while earlier rows already said ok). Fix: read the error's message; a savepoint per lead.

20. **A bad cursor silently restarts at page 1** (`cursor=garbage` → 200 first page). Fix: 400. **Stage-view filters apply after the page is cut**, so a page can be short or empty with a next cursor. Fix: push the filters into SQL.

21. **The journey example ignores an unknown lead id** and returns the invented firm (should be 404).

22. **A failed AI call is booked at its estimated cost** — a 402 sweep over 100k firms would show ~$1,400 "spent" that never was. Fix: cost zero when there is no usage.

23. **The address predictor learns the firm's pattern from catch-all and invalid addresses** and mints unverified addresses for everyone, which verification then pays to confirm as catch-all. Fix: learn from valid addresses only; skip domains with a prior catch-all.

### Scale — fine today, not at 100k

24. **Actual Leads (`/api/qualified`) loads every candidate with no LIMIT and then runs ~3 queries per row** for up to 500 rows — about 1,500 queries a page once contacts exist. **The leads CSV export runs the whole list build per request**, writing a temp tree and rendering every journey (5.5 s at 96k leads with no contacts; minutes with them). **Home and Overview run ~25 whole-table aggregates plus all 13 alerts per hit**, and the screens poll Overview every 5 s while any job runs — including a `count(DISTINCT firm_id)` over ~1.2M document rows and a 7-day `task_run` aggregate with no index. Fix: batch the per-row queries, paginate in SQL, materialise Home's numbers into the existing snapshot table per batch.

25. **Sequential vendor calls.** Verification is single checks one after another with no pacing (days of wall clock; NeverBounce's throttle will fire, which with finding 2 poisons rows); `ja8` makes one AI call at a time (~330 h at 100k); the search steps run one blocking query after another (~250 h). Fix: 4–8 in flight inside the worker; NeverBounce bulk jobs above ~1,000 addresses.

26. **Crawl volume.** Twelve pages a firm where the brief says five; 28% of fetches are 404s from blind path probes; robots.txt is fetched three times a firm (P1, P2, careers) — ~23 rate-limited fetches a firm. At the probe's measured rate that is ~273 h (11 days) of crawl alone; with five pages, no blind probes and 48 concurrent hosts, ~12–15 h. Both are config changes (pages re-derive from stored HTML). The nightly careers sweep, if it were registered, would re-crawl every firm (~8.5 h a night, +100k task rows) and share no rate limiter with the worker.

27. **Whole-table scans in hot paths.** P9's `latest` block is materialised and scans every P8 claim (~5M rows) even for a one-firm list; firm search has no trigram index on `domain` and no btree for its sort; `already_done` runs one query per firm; the research runner has a check-then-insert race (two clicks, two jobs, twice the spend). Fix: push the firm filter into P9's block; the indexes; one `ANY` query; a partial unique index on running jobs.

### Minor

28. Uploads and job id files go to fixed paths under the project, not to settings, so a second engine (as in this test) shares them. The test suite writes its uploads into the real `.local/imports`, which holds ~200 leftover test files and is never cleaned. The 5 MB body cap on fetches is applied after the whole body is downloaded. Failed fetches with a NULL hash are re-inserted on every re-crawl.
29. `openapi.json` and the generated frontend types are current (0 differences). `brain/plan/api-contract.md` is behind the code: it promises identity-review routes, `quotable`, `merged_into` that do not exist, and says the Google key is read by nothing. Three backend routes have no screen (`meta/providers`, `pipeline/alerts`, `pipeline/gates`). `FirmListItem.state_display`, `Proof.days_open`, `DocumentRow.page_kind` are nullable in code and non-null in the contract. The docs describe a Redis-shared limiter, Prefect workers and cloud storage; the code has an in-process limiter, the web server as job runner, and a local folder.
30. Serper `num=30` may bill double; the listings "off" switch does not stop the search step's own places query; `has_listings` reads the search seam instead of the listings seam. Home's "well under a penny a firm" for the AI is wrong once P9 is counted (5–7 cents modelled); correct `config/capabilities.yml` after measuring.
31. The 23 Sep listings work (migration 103, `lge/listings/`, `r_listing`, the Home wording) is still uncommitted across all three repos. Migration 103 was applied to the live database during this audit so the uncommitted routes stop failing against it.

## What 100k firms would cost and take under the current code

First live pass, `research` flow. Assumptions are in the vendor and pipeline reviews; the two reviews' AI estimates differ on the P9 escalation rate, so a range is given. Serper at ~$0.30–1.00 per 1,000 credits; NeverBounce at $0.003–0.008 a check; Haiku 4.5 for P8 and ja8, Opus 5 for P9.

| Item | Per firm (typical → worst) | Per 100k firms |
|---|---|---|
| Serper: website check, listing (+reviews), link sweep, per-person links, snippet emails | ~7–8 → 15 queries | ~700k–900k credits first pass (1.5M worst), +200k every 30 days on rechecks ≈ $350–1,000 |
| NeverBounce: verify found addresses, confirm guessed ones | ~2.4–3 → 11 checks | ~180k–240k checks ≈ $500–1,900; 3–10 days of wall clock on single checks |
| OpenRouter: P8 read, P9 escalation (15–70% of firms), pain analysis | ~2.2 calls; P9 is 45–65% of the money | ~$3,000–7,500; $0 today (402) |
| Google Places, only if its key is added | 1 Text Search (Enterprise + Atmosphere) | ~$4,000 per pass, monthly under the 30-day recheck |
| Crawl, as configured (12 pages, 12 hosts) | ~41 min per 250-firm batch | ≈ 273 h ≈ 11 days |
| Crawl, 5 pages, no blind probes, 48 hosts | — | ≈ 12–15 h |
| Whole recipe, one sequential worker, today's code | ≈ 2.8 h per batch | ≈ 1,100 h ≈ 6–7 weeks |
| Whole recipe, one worker, overlapped and tuned | ≈ 25–35 min per batch | ≈ 8–10 days |
| Page store / database | 12 × 36.7 KB | ≈ 44 GB, 1.2M files / 15–30 GB |

The **cost-of-mistake** numbers matter more than the totals: finding 2 can void a whole verification run in minutes; finding 3 can throw away tens of thousands of paid AI calls on a single crash; finding 8 quietly multiplies the listing bill by twenty; finding 9 lets one command-line run buy 100k listings.

## The order of work

1. **Spend and secret guards (about a day) — before any key goes in.** NeverBounce envelope and breaker (2), chunked persistence in the AI readers (3), `UNCLASSIFIED` out of the paid gates and default per-run caps with a balance preflight (9), Serper before Google and NeverBounce before Hunter in `auto` (8), `unknown` kept retryable (15), reviews failure not re-buying the listing (16), the verification timeout (17), httpx logging and the key out of the URL (11), P9 opt-in for bulk runs. Each with a keyless test against the recorded envelope.
2. **Keys in `.env`, engine restarted, ten firms run live** by the checklist below, every row read by hand. Compare the vendor dashboards' counters with the engine's own log tables; they must move together.
3. **Triage on the way in (plan-v3 phase 1).** No-name rows to a rejects table, never into the store; Batch 1/2 marked after identity; the three counts shown before loading; the import orphan sweep and conditional start (13); the load off the request (14). Check on a scratch copy of the real sheet: zero "Unknown Firm".
4. **The queue and one worker (plan-v3 phase 2).** The `enrich_batch` table, `SKIP LOCKED` claiming, Batch 1 first, resumable at the step after a kill; the whole-table steps limited to the batch with their indexes (6); the flow's batch mode and the G3 fix (5); 4–8 vendor calls in flight and NeverBounce bulk jobs inside it (25); five pages and no blind probes in config (26). Check: kill the worker during a fetch; on restart it resumes with no duplicate rows in the search or verification logs.
5. **Screens that survive the sheet.** Counts in SQL and per-page classification for Leads and Home, the stored classification per batch (7); batched Actual Leads and export, Overview from a summary table (24); the UUID helper (12); the remaining degraded items (18–23). Re-measure with the 100k synthetic sheet — the generator and timing scripts take minutes to recreate — and require every endpoint under a second.
6. **Housekeeping.** Commit the 23 Sep listings work in all three repos, update `api-contract.md` and the capabilities line, clean the imports folder, the indexes in (27).

Only after 1–4 should the real sheet be enriched — and then one sub-batch of 250 first, measured, before the rest.

Rejected on the way: a bigger thread pool inside the API (keeps the GIL, the restart loss and the connection exhaustion); Celery, Redis or Prefect (new services on a Windows machine under Application Control, when a Postgres table gives the same durability); `limit` as a batching cursor (it is not one).

## First live run — ten firms

1. Keys in `.env` only, never exported in the shell; restart the engine; check Home's lights.
2. NeverBounce by hand: account info must answer `success` with the bought balance.
3. `python -m lge run r_listing --opt live=1 --opt limit=10`; read `search_log` where `kind='listing'`: expect `found` rows with reviews and a Serper delta of at most 20 credits. A `failed` row with a listing present means reviews are being rejected (16): stop.
4. `python -m lge run r_search_links --opt live=1 --opt limit=10 --opt max_queries=40`; compare the dashboard delta with the engine's search-log count to learn whether `num=30` bills double.
5. `python -m lge run r4_verify --opt live=1 --opt limit=10 --opt max_usd=0.10`; every `verify_attempt` row must carry `status = success`; anything else is finding 2 — delete those rows and reset the addresses before continuing. Unknowns should not decrement the balance.
6. Size the candidate set before the big run, by tier; the `UNCLASSIFIED` row is money finding 9 would spend for nothing.
7. OpenRouter: dry run for the cost estimate, then `--opt max_usd=1`, and confirm `usage` is populated and the P9 escalation rate is measured (it decides half the AI bill).
8. Settle the unknowns that move the estimates: the real sheet's file size and whether the job-post column is full text (the 50 MB cap); what Serper bills for `num>10`, `/places` and `/reviews`; the Google Places tier price; the share of firms tiered non-DQ after the first batch.
