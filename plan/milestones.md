# Milestones — the full arc

Beyond the [48-hour sprint](48h-sprint.md). Solo + Claude estimates.
Master plan: [PLAN.md](../PLAN.md)

Ordering principle, consistent across all five source documents:
**risk retired per unit of effort, not data volume.**

---

## M0 · Procurement & access — starts day 1, never "done"

Runs alongside everything. Nothing here is code; all of it is someone else's queue.

| Item | Lead time | Blocks |
|---|---|---|
| **Customer list export** | Hours–days | The export filter. **Biggest risk retired per unit of effort** |
| Portal API/DB access | Unknown | I3, I4, `firm_track='portal'`, open question O1 |
| Places API key + quota | Hours | D1, all external discovery |
| Email verification | Days | Grade A/B split |
| Contact enrichment | Days | R1 only — deferrable, R2 is free and better |
| DataForSEO | Days | JA5, deferrable to M9 |
| Licensed job feed | Weeks | **Deliberately last** — G9 |

**Nothing about sending appears on this list.** Delivery is out of scope, which removes the
one incompressible multi-week item the project would otherwise have carried.

---

## M1–M6 · The 48-hour sprint

Foundation → firm dataset → identity → qualification → pain detection → journey + drafts.
Detail in [48h-sprint.md](48h-sprint.md). Gates cleared: G7, G1, G3, G8.

---

## M7 · Probe validation · **GATE G2** — ~2 days

**Three metros, tier 1A only. A few hundred firms, fully processed through every step.**

- [ ] Complete D1 Places grid across the three metros
- [ ] Full chain on every firm: discover → resolve → crawl → extract → classify → signal
- [ ] **Hand-check 50 records on every attribute.** Not a sampled accuracy metric — fifty
      records, every attribute, by hand
- [ ] Record the real yield of each stage

> Every number in a plan like this is an estimate until this phase replaces it.

**Exit:** 50 records accurate on every attribute. **Nothing widens until this passes.**

The attribute most likely to fail here is `fee_model`, and it is the one that matters most —
it gates the tier before practice area is consulted. If it is wrong at any material rate, fix
P6's precedence and P8's prompt before a national harvest multiplies the error.

---

## M8 · Contacts — ~1 week

Reference: [context/40-pipeline/02-component-register.md](../context/40-pipeline/02-component-register.md)

Order matters: **R2 → R1 → R3 → R4.** Free authoritative names first, paid enrichment only
for the remainder.

- [ ] **`D2` bar directory harvester** — three archetypes, not fifty scrapers
      (A bulk export · B paginated search · C per-record lookup). Per-state isolation
- [ ] **`R2` bar record joiner** — matches attorney records to resolved firms on name +
      address. **Yields real partner names free, which generic B2B sources do not carry.**
      This is the differentiated move: bar directories are public records naming every
      practising attorney, and almost nobody doing outbound into this market bothers
- [ ] `R1` contact enricher — **tier-gated.** Enriching the whole universe is the largest
      avoidable cost in the system
- [ ] `R3` pattern inference — every inferred address still goes through R4
- [ ] `R4` SMTP verify — **`catch_all` and `risky` are failures, not passes.** Treating them
      as valid is what turns a clean list into a damaging one
- [ ] `R5` phone + DNC scrub — solos routinely list a mobile as the firm number
- [ ] Emit `QUALIFIED_A` / `QUALIFIED_B`

**Capture both people, not one** — owner *and* administrator. A record with only a generic
inbox is not a lead; a record with only the owner misses the person most likely to act.

**Exit:** grade A/B split measured. Every grade-A row carries a verified address.

---

## M9 · Pain breadth · **GATE G9** — ~1.5 weeks

- [ ] **Robots audit as a script, not a task** — fetch robots.txt, parse directives,
      fingerprint the platform, write to the source registry. ~110 sources.
      *A hand-built table is a document; a generated one is infrastructure*
- [ ] `JA2` bar boards, **top 10 metros first.** Parsers per *platform*, not per board —
      ~40 platforms behind ~110 boards, roughly 3:1 reuse. **Prove it on ten before writing
      forty**
- [ ] `JA3` ATS endpoints — Greenhouse confirmed live and returning `first_published` +
      `updated_at` separately, which is exactly the pair repost detection needs.
      **Re-test Lever** — the audit's test slug returned empty
- [ ] Craigslist per-city RSS — promoted to lane 1 by the audit. **Expect high agency noise**
- [ ] Cross-board dedupe — one opening on six boards is **one signal**. Keep `sources[]`:
      a role posted to five boards is a firm trying harder than one posted to its own page
- [ ] Repost detection — same fingerprint, `board_posted_date` moved forward while our
      `first_seen` stayed put. **A dated, affirmative admission of hiring failure.** Weight 44/48
- [ ] Closure detection — absent from **every** source across **two consecutive sweeps**.
      **Distinguish *fetched and absent* from *fetch failed*** — without it, one bad night
      silently closes thousands of live signals
- [ ] `W3` review poller — the intake-failure phrase set. **Weaker evidence, almost
      uncontested.** Worth disproportionate effort
- [ ] `JA5` SERP discovery — reveals which sources are being missed, **and that answer sizes
      the lane-2 decision**

**Exit:** lane 1 measured. **Only then is JA4 (licensed feed) sized against a real number
rather than an assumption.**

---

## M10 · Scoring, lifecycle, arming · **GATE G5** — ~1 week

- [ ] `score_nightly` — fit + intent + band, **full scan, not a stream**, so a re-weight is a
      re-run
- [ ] Contest level as a **routing input, not a score component**
- [ ] `arm_leads` — supply-derived threshold, **joining `bench_inventory`** (I4). Hand-maintained
      CSV until portal access lands. **Stale bench treated as empty**
- [ ] Lifecycle: all 16 states, every transition guarded in the DB
- [ ] Re-pooling — a lead that does not convert returns to the pool **with its verified
      contact intact**
- [ ] Prefect wraps the existing CLI callables
- [ ] **Observability — every alert is a defect, and most alert on absence:**
      watcher silence · dedupe drift · extraction confidence drop · tier distribution shift ·
      signal-to-contact latency p50 >48h · bench starvation · stale share >20%
- [ ] **`arming_signal` populated on every lead** — records which pain surfaced it. Nothing
      reads it yet; it is the only thing that could ever turn the seeded weights into
      measured ones, and it cannot be reconstructed later

**Exit:** end-to-end, first STRIKE lead surfaced to a human within 48h of its signal, and
and SEQUENCE-band leads landing on a clean list with suppression re-filtered every time it is
produced.

---

## M11 · Beachhead — ~2 weeks

Tier 1A nationally — PI and mass tort, 2–25 attorneys, **metros first by density.**

Proves coverage at scale, and that identity resolution holds when the same firm appears in
three sources across fifty states.

**Exit:** duplicate check clean, decision-maker coverage holds.

---

## M12 · Widen — ongoing

| Phase | Collect | Proves |
|---|---|---|
| 3 — Adjacent | Tier 1B immigration, then tier 2 fee-shifting | That the profile generalises beyond PI — **the first real test of the fee-model axis** |
| 4 — Breadth & holdouts | Tier 3, plus **a deliberate slice of tier 4 hourly firms on a non-billable role** | **Whether the fee-model axis is a fact or a good story. The only phase that can disprove it** |

Tier 2 is worth reaching sooner than its number suggests: **identical overhead economics to
contingency, and far less crowded — almost every competitor targets PI first.**

---

## The 90-day job that is not a milestone

At ninety days of outcome data, run:

```
outcome × signal kind × tier      -- joined on lead.arming_signal
```

and **rewrite the scoring table from it** — as and when outcome data becomes available.

Every weight, ranking, precedence order and routing band in this system is a **seeded
hypothesis**. The source documents say so in their own footers. This join is the only
mechanism that converts them to measured values — and without it, phase 4's holdout produces
a number nobody reads.

> The rankings in this document are reasoned, not measured. They are a starting hypothesis,
> and the only thing that makes them correct is replacing them with what the outcomes say.
