---
id: execution.open-questions
title: Open questions and unmeasured values
answers: "What is genuinely undecided, and what is decided but unverified?"
source: all
authority: canonical
stability: decided
depends_on: [orientation.document-map]
feeds: []
---

# Open questions and unmeasured values

Three categories, and the difference matters.

- **Open** — genuinely undecided. Someone must choose or find out.
- **Unverified** — decided, but resting on an inspection nobody has done yet.
- **Seeded** — decided, working, and known to be a guess awaiting measurement.

---

## Open — needs a decision or an inspection

| # | Question | Blocks | Cost to answer |
|---|---|---|---|
| **O1** | **Which reading of portal Feed B is correct?** Are the daily role requests (a) law firms posting roles they want filled, or (b) externally aggregated postings collected for internal use? | Whether it is a suppression source, a live signal source, or both. **The suppression path is required under either reading**, so this does not block I3 | One conversation |
| ~~O2~~ | ~~What fields does the internal job-data file carry?~~ **Answered 11 Sep 2026:** name + city + date, no links. Partly usable — accepted only where exactly one firm in the city clears the threshold. See D-013 | — | — |
| ~~O3~~ | ~~Where did the firm dataset come from?~~ **Answered 11 Sep 2026:** purchased from a data vendor → directory tier, below Places. See D-013 | — | — |
| **O4** | **What is the overlap between the firm dataset and the external harvest?** | **May materially shrink the discovery plane**, the largest and most expensive stage | One query, after I1 loads |
| **O5** | **Does Lever's postings API carry the fields we need?** The audit's test slug returned an empty array | Whether JA3 covers Lever | One re-test against a slug with live postings |
| **O6** | **Are Texas Bar, NFPA and ABA reachable from the crawler's real egress?** All three failed from the audit's egress, none stated a policy | Three sources, one of them a large state bar | Re-run from production egress |
| **O7** | **What do the remaining ~94 sources permit?** The registry needs ~110; sixteen are checked | Full lane-1 coverage | An afternoon, **as a script** — see below |

**O7's answer should be infrastructure, not a document.** Checking 110 sites by hand is a week
that produces a snapshot which starts decaying immediately. The same work as a script — fetch
robots.txt, parse the directives, fingerprint the platform, write to the source registry —
runs in an afternoon and can be re-run on a schedule.

---

## Unverified — decided, resting on something unchecked

| Assumption | Rests on | How it would fail |
|---|---|---|
| Bar boards give ~3:1 parser reuse | 3 platforms observed across 5 sites | The long tail is more fragmented than the head |
| Craigslist is worth lane-1 treatment | robots.txt permissiveness, not measured yield | **High agency noise** could swamp the signal |
| ~5–8% of sites need Playwright rendering | An estimate | Higher share → P3 cost rises materially |
| Collapse ratio will land in 2.0–3.3× | An estimate | Outside the band, the gate stops the pipeline until normalizers or thresholds are fixed |
| Small firms largely avoid paid boards | Reasoning about recruiting budgets | If wrong, lane 2 matters more and should be bought earlier |
| Vendor size fields need cross-checking | Known vendor behaviour | Confirm on a sample before trusting |

---

## Seeded — working values known to be guesses

**Every number in the scoring engine.** Weights, decay curve, routing bands, arming threshold,
`bench_bonus` coefficients.

**Every ranking.** Tier order, signal order, contest levels, need-proxy choices.

**Every precedence order.** Source precedence by field in `reconcile()`.

**The tier → wedge-SKU table.** Explicitly "a set of reasoned guesses" with a named source of
truth waiting: portal role-request data.

**Every yield estimate.** Replaced by phase 0 measurement.

### The single mechanism that converts seeded → measured

```
Every WON and LOST lead carries its arming_signal.
After ninety days, the join

    outcome × signal kind × tier

re-weights the scoring table.
```

> The rankings in this document are **reasoned, not measured.** They are a starting
> hypothesis, and the only thing that makes them correct is replacing them with what the
> outcomes say.

**Building that attribution join is not a reporting nicety.** It is the mechanism by which
every seeded value in this system stops being a guess. Without it the scoring layer stays a
hypothesis indefinitely, and phase 4's holdout — the only slice that can disprove the
fee-model axis — produces a number nobody reads.

---

## What is NOT open

Three contradictions between documents 00 and 01 were **found and resolved**. They are settled
— do not re-litigate them, and do not treat a rediscovery of one as a new finding.

See [decisions.log](../70-decisions/01-decision-log.md).
