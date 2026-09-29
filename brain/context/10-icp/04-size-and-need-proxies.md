---
id: icp.size
title: Size, shape and better need-proxies
answers: "What size firm, and what predicts overload better than headcount?"
source: 00 §4, 01 §2 (size policy), 01 §9
authority: canonical
stability: decided
depends_on: [icp.need-model]
feeds: [icp.tiers, icp.disqualifiers, pipeline.scoring]
---

# Size, shape and better need-proxies

Serves **need condition 4** — whether local hiring is actually blocked — and describes how
the purchase decision gets made.

| Band | Hiring reality | How a purchase happens | Verdict |
|---|---|---|---|
| **Solo** — 1 attorney | Cannot compete for local staff at all. Often does the support work personally | One person decides in a day. No process | **Include** — real need, but only where case volume is real. Expect one role |
| **Small** — 2–12 | The sharpest version of the problem. Enough volume to genuinely need staff, no HR function, no recruiting budget, competing against bigger firms for the same local hires | Owner or managing partner signs. No procurement, no security review, no committee | **Core** |
| **Lower-mid** — 13–25 | Has an office manager or administrator who feels the pain daily and is usually the one who posted the unfilled job | Administrator champions, owner approves. Slightly longer, still weeks not quarters | **Core** |
| **Mid** — 26–50 | Often has an internal recruiter, so condition 4 is weaker — they *can* hire | More stakeholders, some IT involvement | **Deprioritise** |
| **Large** — 50+ | Has recruiting capacity and usually an incumbent outsourcing vendor already | Procurement, infosec review, MSA. A different sales motion entirely | **Exclude** |

---

## Size policy — disqualify at 50, penalise from 26

**This was a resolved contradiction.** 01 originally disqualified above 25 while also
scoring a 26–50 band at −10. Both could not be true. Resolved to match 00.

- `attorney_count > 50` → `DQ_SIZE`
- `attorney_count` 26–50 → **−10 fit penalty**, not disqualified

Those firms have a real need and a longer cycle. A strong signal should still be able to
surface one, and a whole band should not disappear on an assumption. See
[decisions.log](../70-decisions/01-decision-log.md).

**Fit contributions:** 2–12 → **+12** · 13–25 → **+8** · 1 → **+5** · 26–50 → **−10**

---

## Better need-proxies than headcount

Attorney count says how big a firm is, **not how overloaded it is**. Three cheap,
observable attributes predict need better, and all three come from sources already being
touched.

| Proxy | What it indicates | Where it comes from | Fit |
|---|---|---|---|
| **Review count** | Case volume. A firm with 300 Google reviews is processing far more matters than one with 12, regardless of attorney count | Places record — free, already collected | +4 if > 40 |
| **Staff-to-attorney ratio** | Whether the firm is understaffed. Two attorneys with one assistant is a different firm from two attorneys with six | Team page — count *roles*, not just people | +4 if < 1.0 |
| **Active paid advertising** | Two things at once: buying case volume faster than it can process, *and* has predictable money to spend | Ad transparency libraries | +3 |

`attorney_count` has **no fallback source**: precedence is `llm(team page)` only. No other
source is even approximately right. Absent team page → **null, not a guess**.

Watch for the vendor trap: commercial size fields are often *total headcount*, not
attorney count. A material difference here — it misfires the 26–50 penalty. Cross-check
against the team page on a sample before trusting any purchased size field. See
[firstparty.firm-dataset](../50-first-party/04-firm-dataset.md).

---

## Geography

**No demand weighting in version one.**

Weighting states because that is where the company has sold before is circular — it may
simply reflect where the founders' network is, and it can point at a *saturated* market
rather than an open one.

Prioritise collection by **density** instead: metropolitan areas first, because more firms
per unit of collection effort. That is an **efficiency decision, not a demand assumption**.

Let close-rate data name the good geographies later. Non-concentration geographies are
carried as a `holdout` track so the assumption stays testable.
