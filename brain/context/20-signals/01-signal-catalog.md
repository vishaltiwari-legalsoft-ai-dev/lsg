---
id: signals.catalog
title: The signal catalog and contest levels
answers: "What signals mean a firm is in market, how strong is each, and who else can see it?"
source: 00 §9, 01 §9, 03 §7
authority: canonical
stability: seeded
depends_on: [icp.need-model]
feeds: [pipeline.scoring, pipeline.component-register, signals.sources]
---

# The signal catalog and contest levels

The universe tells us who *could* buy. Signals tell us who is trying to solve this problem
**right now** — [need condition 4](../10-icp/01-need-model.md), observable from outside.

Ranked by strength of evidence, with a second column that matters just as much:
**how many competitors can see the same thing.** A signal every rival watches is a race;
a signal nobody watches is an advantage.

| # | Signal | What it proves | Observable from | Contest | Weight |
|---|---|---|---|---|---|
| 1 | **A legal-support role posted and still open after three weeks** | The strongest possible evidence. The firm has decided it needs this person, approved the budget, published the need — **and failed to fill it**. Condition 4 confirmed, in writing, by the firm itself | Firm's own careers page. *Track first-seen ourselves — that is what makes "still open" computable* | **HIGH** | 40 |
| 1b | **Repost** — same role re-listed | Stronger than 1. A dated, affirmative admission of hiring failure, not an inference from absence | Our `first_seen` held against the board's shifting date | HIGH | 44 / 48 |
| 2 | Same role, newly posted | In market now, still optimistic about hiring locally. Earlier in the window, less urgency | Careers page | HIGH | 30–34 |
| 3 | **Reviews complaining nobody called back** | Documented capacity failure, in the firm's own public record, in the words of the people it lost. For a firm buying leads, this is **signed cases walking away** | Review text, last 90 days. Phrases: "never called back", "couldn't reach anyone", "no response" | **LOW** | 15 |
| 4 | Two or more support roles open at once | Expansion rather than backfill. Multi-role opportunity | Careers page | MED | 10 |
| 5 | Heavy active advertising | Buying case volume faster than existing staff can absorb it. Also confirms money moving predictably | Ad transparency libraries | **HIGH** | 10 |
| 6 | **Running a mass tort campaign** | About to sign claimants in bulk, each needing several provider record requests, all against a filing deadline. Pure document-collection demand at volume | Ad copy, tort-specific landing pages | MED | 10 |
| 7 | New office, or a lateral attorney hire | Capacity added at the top with no support added beneath it. Infrastructure spending already approved | Firm news, listings, professional posts | MED | 8 |
| 8 | **Case management system newly implemented** | The point at which a firm discovers the workflow needed a person, not a feature. Also a natural co-sell if the vendor is a partner | Site tech fingerprint, quarter-over-quarter change | **LOW** | 8 |
| — | `partner_intro` | A warm introduction | Partner channel | **NONE** | 35 |
| — | `pricing_page_visit` | First-party intent | Site analytics | NONE | 25 |

---

## Strategy, not just ranking

Signal 1 is the strongest evidence **and** the one every competing vendor sees the same
morning. A firm that posts a paralegal role gets pitched by several of them that week.
Treating it as the whole strategy makes **speed the only advantage, and speed is trivially
matched**.

So:

1. **Run signal 1 at volume**, but win it on the opening line — the specific role, the date
   it was posted, their actual case system, the partner's real name from the bar record.
2. **Put disproportionate effort into signals 3, 6 and 8**, which are weaker evidence but
   effectively uncontested.

Contest level is a **routing input, not a score component**. It never changes the intent
number. It decides where scarce human SDR time goes:

```
fit + intent ≥ 80 AND contest ≤ MED  → STRIKE    (human, same day)
fit + intent ≥ 80                    → SEQUENCE  (automated, 9 touches)
```

A high-intent, high-contest lead still gets worked — automatically. A high-intent,
low-contest lead gets a person. See [pipeline.scoring](../40-pipeline/04-scoring-engine.md).

---

## Weight is derived, never stored

`signal` has `first_seen`, `last_seen` and `closed_at` **instead of a weight column**.

An open job posting *gains* weight as it ages — the same event, re-weighted, not a second
event. A watcher never has to emit a second row to say "this is still open, and now it
matters more".

```
job_posting_open:
  closed_at IS NOT NULL     →  0    -- role filled, signal over
  age(first_seen) > 21 days →  40   -- hiring has failed
  age(first_seen) >  7 days →  34
  otherwise                 →  30
```

Then decayed by staleness of last sighting:

```
decay(days_since_last_seen):  ≤7d → 1.00 · ≤30d → 0.70 · ≤90d → 0.35 · >90d → 0
```

---

## The one metric this whole layer exists to minimise

**Signal-to-contact latency: p50 under 48 hours for the STRIKE band.**

A role found on day two converts far better than the same role found on day twenty. That
is the entire reason the signal sweep is nightly and the entire reason we track our own
`first_seen`. It is an alerting condition in
[pipeline.observability](../40-pipeline/07-observability.md), not a metric to watch.

---

## These rankings are a hypothesis

The ordering and the weights are **reasoned, not measured**. They are a starting position.

Every `WON` and `LOST` lead carries its `arming_signal`. After ninety days, that one join
— **outcome by signal kind, and by tier** — is what re-weights this table. Running that
query and rewriting these numbers is the only thing that makes them correct.
