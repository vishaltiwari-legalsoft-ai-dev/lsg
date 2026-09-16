---
id: execution.risks
title: Risk register
answers: "What goes wrong, how would we notice, and what guards it?"
source: 02 §8, 01 §5, 01 §12, 03 §4, 03 §8, 04 §4
authority: canonical
stability: decided
depends_on: [execution.gates, pipeline.observability]
feeds: []
---

# Risk register

Consolidated across all five documents. **Ordered by severity.**

The dominant pattern: **almost every serious risk here is silent.** It produces plausible
data, no error, and a consequence weeks later. That is why so many guards are database
constraints and absence-alerts rather than code review.

---

## Severe — damages a customer or the sending capability

| Risk | How it shows up | Guard |
|---|---|---|
| **Cold-emailing a portal firm** | A customer receives a prospecting email from the company they already buy from. **Contradicts the product, in writing, to the person paying** | **I3 before any outbound.** Suppression at domain scope, checked at send |
| **Duplicate outreach from a broken dedupe** | One managing partner receives four emails from four of your sending domains, and reports all of them. **Ends the programme faster than any technical failure** | G1 verification queries **as a hard gate**, before profiling |
| **Sending-domain death** | Bounce rate climbs, deliverability collapses across all domains | `catch_all` and `risky` are **failures, not passes**. Grade B **never emailed** (I3). Alert at **>2% bounce** — pause the domain, do not push through |
| **Guessed email addresses** | Same as above, arriving faster | Every inferred address from R3 **still goes through R4** |

---

## High — corrupts the data permanently or wastes the largest cost

| Risk | How it shows up | Guard |
|---|---|---|
| **Name-only merges from job data** | **Silent.** A false hiring history lands on a real firm and **is never questioned again** | Match ladder. **Reject at name-only confidence rather than guessing.** Tag every attribute and keep it withdrawable |
| **Shared-host domain merge** | Every firm on wixsite/squarespace/justia merges into one entity. **Silent and catastrophic** | `SHARED_HOST_BLOCKLIST` in `norm_domain` |
| **Shared-phone merge** | Every firm using one answering service merges | `norm_phone` marks a number `shared` at **≥4 distinct firm candidates** and excludes it from matching |
| **Suite numbers in `addr_hash`** | One firm's two floors become two firms | Secondary unit **split into its own field, never in the hash** |
| **Over-trusting the firm dataset** | Discovery is narrowed on the assumption the dataset is complete, and **a segment quietly never gets collected** | **Coverage analysis before any scope reduction. Numbers, not assumption** (G7) |
| **Enriching the whole universe** | The largest avoidable cost in the system | R1 runs **only on firms that passed the tier gate** |
| **Historical postings treated as live** | Outbound opens with a role the firm filled eight months ago. **Reads as careless and kills the reply** | Job history writes **fit attributes only.** Intent requires a verifiable live source |

---

## High — silently degrades quality

| Risk | How it shows up | Guard |
|---|---|---|
| **Confident wrong `fee_model`** | A firm is routed into the wrong segment with the wrong wedge SKU and **no error anywhere** | **`unknown` is a first-class value.** Escalate to P9 at confidence <0.60 or `mixed`/`unknown`. `reconcile()` never silently resolves a tier-determining field |
| **Prompt regression** | Median `fee_model.confidence` drifts down; tier assignment degrades silently | **Alert on >0.1 week-over-week drop.** Prompt rev on every attribute row makes it attributable |
| **Classifier drift** | Tier shares move without the harvest changing | **Alert on >15% week-over-week** shift in any tier's share (G3) |
| **Boilerplate footers** | `primary_practice` reflects every area the firm ever mentioned | P4 boilerplate stripper — **an accuracy fix, not just a size one** |
| **Normalizer change without versioning** | No way to know which rows were computed under the old rule → **a full re-harvest** | **Ship `norm_version` in the first commit** |
| **Vendor size fields misread** | Total headcount taken as attorney count. Firms land in the wrong band and **the 26–50 penalty misfires** | Cross-check against team page **on a sample before trusting the field** |

---

## High — the pipeline silently stops working

| Risk | How it shows up | Guard |
|---|---|---|
| **Watcher silence** | A parser breaks or a fetch is blocked. **Zero results is not an error** | Alert when JA1 finds **0 new postings across all qualified firms** — statistically impossible across thousands of firms |
| **Closing signals on fetch failure** | A timeout, a rate-limit and a broken parser all produce **the same observable as a removed posting: nothing found.** One bad night closes thousands of live signals | **Two-sweep grace.** Distinguish *fetched and absent* from *fetch failed*; only the first counts |
| **Stale bench data** | Leads arm against inventory that is already placed. **The three-day promise breaks on exactly the leads the system worked hardest to find** | **Hourly sync, alert when `as_of` falls behind, treat a stale bench as empty** |
| **Bench starvation** | Leads for a tier silently stop arming. **Looks like a demand problem; is a supply problem** | Alert on a wedge SKU at 0 availability **>7 days** |
| **Pool decay** | The list degrades toward unusable | Alert at **>20% of pool past 90d freshness.** W7 rolling at 1/90th per day |
| **A source adds a `Disallow`** | Yield goes to zero. **A newly added `Disallow` and a site redesign present identically** | **Check robots.txt before assuming the parser broke.** Monthly re-fetch and diff |

---

## Medium — noise and cost

| Risk | How it shows up | Guard |
|---|---|---|
| **Agency postings treated as leads** | Pipeline targets recruiters, **inflates every volume estimate**, writes signals onto companies that will never buy | Five-rule agency filter. **Rule 3 (≥5 metros in 90 days) catches agencies no blocklist knows about** |
| **A new agency appears** | Rule-3 rejects spike | **Rejects are kept with the rule that fired.** The reject stream is how the blocklist gets extended |
| **One posting counted six times** | A firm's intent score tops the queue for no reason | Cross-board fingerprint dedupe |
| **Buying a feed that adds nothing** | Money spent before the gap is known | **Buy lane 2 last, against a measured number** (G9) |
| **Crawl-delay discovered late** | 60 metro bars at 5s is real scheduler time | **Read declared `Crawl-delay` per host**, do not assume 2s |

---

## Compliance posture

| Risk | Guard |
|---|---|
| Scraping a source that prohibits it | Three sources are `policy_closed` **in their own published files**. Route to a licensed provider or drop |
| Treating an edge block as a policy | **`edge_blocked` ≠ `policy_closed` ≠ `unreachable`.** Never collapse into one boolean |
| Defeating a bot-management layer | **Do not.** Deprioritise the source instead |
| Evasive crawling | **Honest, contactable User-Agent. Never rotated to evade, never impersonating a browser or a named search bot** |
| Relying on robots.txt as permission | **A permissive robots.txt is not a licence.** Read terms of use before a source becomes load-bearing (G10) |
| Repeated 403/429 | **Stop, do not retry harder.** Re-read the policy, lower the rate, mark closed if it persists |
