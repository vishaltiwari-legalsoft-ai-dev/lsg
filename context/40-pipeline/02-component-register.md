---
id: pipeline.component-register
title: The component register — all 34 components
answers: "What is every component, what does it read and write, and what happens when it fails?"
source: 01 §6, 02 §7, 03 §10
authority: canonical
stability: decided
depends_on: [pipeline.architecture]
feeds: [pipeline.orchestration, execution.build-order]
---

# The component register

Every component declares an **idempotency key** so a re-run is free, and a **failure policy**
so a dead source degrades the pipeline rather than stopping it.

**Isolation is the recurring theme.** Failure is per-cell, per-state, per-firm, per-board —
never global. One broken source must never stall the sweep.

---

## Plane D — Discovery · creates firm candidates

| ID | Component | Input → Output | Idempotency key | On failure |
|---|---|---|---|---|
| **D1** | **Places grid harvester**<br>15 practice keywords × ~1,200 towns | `grid_cell → observation`<br>Text Search then Details for each new `place_id` | `(cell_id, keyword, page)` | Cell marked failed, retried next run. **Never blocks other cells** |
| **D2** | **Bar directory harvester**<br>Three archetypes, not fifty scrapers | `state → observation + contact`<br>A: bulk export · B: paginated search · C: per-record lookup | `(state, bar_number)` | **Per-state isolation.** A blocked state does not stall the other 49 |
| **D3** | **Legal directory crawler**<br>Justia, Avvo, Martindale — gap fill only | `practice+geo → observation`<br>Runs only where D1 coverage is thin | `(source, profile_url)` | **Optional plane.** Failure logs a coverage warning, nothing more |

*Three archetypes rather than fifty scrapers* is the same economy as *parsers per platform,
not per board* in JA2. Both reduce a long tail to a small set of shapes.

---

## Plane P — Profile · fills firm attributes, once per firm

| ID | Component | Input → Output | Notes |
|---|---|---|---|
| **P1** | Site mapper | `firm.domain → url set` | robots.txt, then sitemap.xml, then path probe for `/about`, `/attorneys`, `/our-team`, `/practice-areas`, `/contact`, `/careers`, `/fees` |
| **P2** | Page fetcher | `url set → document (GCS)` | Content-hash keyed. **Store raw HTML always** — a schema change later becomes a re-parse, not a re-crawl |
| **P3** | Render fallback | `document → document` | Playwright, **gated**: fires only when static text is under 500 words. Expect 5–8% of sites |
| **P4** | Boilerplate stripper | `html → main text` | trafilatura. Removes the footer that lists **every practice area the firm ever mentioned** — an accuracy fix, not just a size one |
| **P5** | JSON-LD extractor | `html → firm_attribute` | Deterministic. schema.org `LegalService`, `Attorney`, `JobPosting`. **Highest confidence of any source** |
| **P6** | Fee-model detector | `text → fee_model` | Regex, precedence-ordered. See [icp.fee-model](../10-icp/03-fee-model.md) |
| **P7** | Tech fingerprinter | `html → cms_detected` | Script hosts, chat widgets, form endpoints. Filevine, Clio, CASEpeer, MyCase, Litify, SmartAdvocate. **No vendor API needed** |
| **P8** | LLM extractor | `text → firm_attribute` | `claude-haiku-4-5`, Batch API, structured outputs |
| **P9** | LLM escalator | `low-conf rows → firm_attribute` | `claude-opus-5`. Fires on low confidence, `UNCLASSIFIED` tier, **or tier 1A regardless of confidence** |

**P2 storing raw HTML is the single most consequential line in this table.** It is the reason
a prompt revision or a normalizer bump is a re-parse rather than a re-crawl.

**P4 is an accuracy fix.** A law firm footer listing every practice area the firm ever
touched will wreck `primary_practice` if it reaches the extractor.

---

## Plane W — Watchers · emit signals, never terminate

| ID | Watcher | Cadence | Scope | Fingerprint |
|---|---|---|---|---|
| ~~W1~~ | ~~Careers JobPosting watcher~~ | — | — | **Replaced by JA1–JA3** |
| ~~W2~~ | ~~Job aggregator poller~~ | — | — | **Replaced by JA4** |
| **W3** | Review poller | Weekly | Tier 1A + 1B | `sha1(review_id)` · phrase-matched for intake failure, **stores the sentence** |
| **W4** | Ad library poller | Monthly | Tier 1A | `sha1(page_id + month)` |
| **W5** | Mass tort detector | Monthly | Tier 1A | `sha1(firm + tort_slug)` · tort keyword set against ad copy and landing pages |
| **W6** | Tech delta watcher | Quarterly | All qualified | `sha1(cms_from + cms_to)` · **only a change is a signal; steady state is not** |
| **W7** | Liveness prober | Rolling 90d | All | Content hash change → re-queue P2. Dead site → `STALE` |

W3, W5 and W6 are the **low-contest** watchers. They are weaker evidence than a job posting
and effectively uncontested, which is where disproportionate effort belongs. See
[signals.catalog](../20-signals/01-signal-catalog.md).

---

## Sub-plane JA — Job signal acquisition · replaces W1/W2

| ID | Component | Input → Output | Cadence | On failure |
|---|---|---|---|---|
| **JA1** | **Careers page watcher** | `firm.domain → raw_posting` | Nightly | Per-firm isolation; a broken site never stalls the sweep |
| **JA2** | **Bar board watcher**<br>*parsers per platform, not per board* | `board registry → raw_posting` | Nightly | Per-board isolation; **alert when a platform parser yields zero across all its boards** |
| **JA3** | ATS endpoint poller | `ats slug map → raw_posting` | Nightly | Cheap and stable; low alert priority |
| **JA4** | Licensed feed ingester | `provider delta → raw_posting` | Daily | **Vendor-agnostic adapter** — the provider will change; the schema should not |
| **JA5** | SERP discovery | `query set → raw_posting + discovery queue` | Weekly | Best-effort. Its job is finding sources we do not know about |
| **JA6** | **Normaliser**<br>agency filter → dedupe → resolve → signal | `raw_posting → signal` | After each sweep | **Pure function over stored rows** — fully re-runnable without re-fetching |

### Why JA6 is separate

The agency blocklist **will** be extended, the title synonym map **will** be corrected, and
the resolution rules **will** be tuned — repeatedly, in the first months.

Keeping normalisation a pure function over stored `raw_posting` rows means every one of
those changes is a **re-run over what is already on disk, not a re-crawl of the internet**.

Same principle as P2 storing raw HTML.

### Bar board parser economics

~50 state + ~60 metro boards, but only about **40 distinct platforms** behind them
(YourMembership, Naylor, MemberClicks, Careerwebsite, Personify…). **Write parsers per
platform, not per board** — coverage per parser is roughly **3:1**, confirmed by the audit.

### Parse order — cheapest and most reliable first

```
1. JobPosting JSON-LD in the page        -- deterministic, most sites
2. microdata / RDFa                      -- older sites
3. ATS JSON endpoint if the page embeds one
4. HTML parse with per-template selectors -- bar boards: ~40 templates
5. LLM extraction, low volume only        -- last resort, flagged
```

---

## Plane R — Resolvers · people and verification

| ID | Component | Input → Output | Notes |
|---|---|---|---|
| **R1** | Contact enricher | `firm → contact` | Multi-vendor adapter behind one interface. **Runs only on firms that passed the tier gate** — enriching the whole universe is the largest avoidable cost in the system |
| **R2** | Bar record joiner | `bar rows × firm → contact` | Matches D2 attorney records to resolved firms on name + address. **Yields real partner names free**, which generic B2B sources do not carry |
| **R3** | Email pattern inferencer | `known-good @domain → candidate` | Learn the firm's pattern from any verified address, apply to unresolved contacts at the same domain. **Every inferred address still goes through R4** |
| **R4** | Email verifier | `email → status` | SMTP verification. **`catch_all` and `risky` are failures, not passes** — treating them as valid is how a sending domain dies in week one |
| **R5** | Phone normalizer + DNC scrub | `phone → e164 + flag` | Business lines sit outside most DNC scope, but **solos routinely list a mobile as the firm number**. Scrub anyway |

Run order is **R2 → R1 → R3 → R4**. Free authoritative names from bar records first; paid
enrichment only for the remainder. R1's tier gate is the single largest cost control in the
pipeline.

---

## Plane I — First-party sources

| ID | Component | Input → Output | Cadence | Notes |
|---|---|---|---|---|
| **I1** | Firm dataset loader | `export → observation` | One-shot, re-runnable | Source tag `internal_firms`. **Runs the coverage analysis as part of the load and reports it** |
| **I2** | Job history loader | `export → observation + firm_attribute` | One-shot, re-runnable | Applies the match ladder. **Name-only confidence is rejected, not merged.** Writes fit attributes only — **never signals** |
| **I3** | **Portal demand feed** | `portal → firm_track + suppression` | Hourly | **Build first.** Suppression correctness matters more than latency anywhere else in the system |
| **I4** | Talent pool sync | `portal → bench_inventory` | Hourly | **Writes directly** — the one feed that does not pass through `observation`. **Stale bench data is worse than none** |

---

## Rate discipline

**Per-host token bucket in Redis, not global.** One firm's site sees ≤1 request / 2s
regardless of worker count.

Where a host declares a `Crawl-delay`, **that value is used instead of the 2s default** —
LA County Bar declares 5s, and across 60 metro bars that is real scheduler time that must be
planned rather than discovered on the first slow night.

Honest, contactable User-Agent. robots.txt honoured. **Never rotated to evade, never
impersonating a browser or a named search bot.** Paid APIs get a separate bucket sized to
the plan's QPS. See [signals.crawl-policy](../20-signals/05-crawl-policy-and-audit.md).
