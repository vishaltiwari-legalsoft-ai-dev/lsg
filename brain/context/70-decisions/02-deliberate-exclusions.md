---
id: decisions.exclusions
title: Deliberate exclusions
answers: "What is deliberately NOT in this system, and why — so nobody re-proposes it?"
source: 00 §7, 01 §6, 03 §2, 04 §3, README
authority: canonical
stability: decided
depends_on: [orientation.document-map]
feeds: []
---

# Deliberate exclusions

Things left out **on purpose**. Each is recorded so it does not get re-proposed as an
oversight.

---

## Data sources

### Direct job-board scraping — excluded

Indeed, ZipRecruiter and LinkedIn all publish rules covering exactly the paths this pipeline
would need. Verified in their own files on 10 September 2026:

```
INDEED        Disallow: /job/  /jobs/  /viewjob?
ZIPRECRUITER  Disallow: /      (Allow: /llms.txt only)
LINKEDIN      "automated means ... strictly prohibited"
```

> **The signal is not lost, only the exposure.**

JA1 reads the firm's own careers page — **the same signal, from the firm's own server, with a
real `datePosted`** — and JA4 covers the remainder through a **licensed aggregator**.

For these three, **a licensed data provider is not the compliant alternative to scraping, it
is the only route that exists.**

### Automated professional-network extraction — excluded

LinkedIn and equivalents. Account bans and real legal exposure.

> **It is not a technical obstacle to route around.**

Manual research is a different matter and is not covered by this exclusion.

### Member-login bar boards — out of scope

A minority of state bar career centres sit behind a member login.

> **Not an obstacle to route around; simply not a source.**

### Law school career portals — excluded

Symplicity and similar are authenticated and institution-scoped. **Requires credentials we
have no basis to hold.**

### Bot-management layers — never defeated

NFPA and ABA return HTTP 403 on robots.txt itself — a WAF refusing a datacentre IP, not a
published policy.

**Response:** re-attempt from real egress with an honest identifying user-agent. **If it still
fails, deprioritise — do not attempt to defeat it.**

Likewise on repeated 403 or 429: **stop, do not retry harder.** Re-read the policy, lower the
rate, and if it persists mark the source closed rather than working around it.

### Evasive crawling — never

**One identifying UA string with a contact URL. Never rotated to evade, never impersonating a
browser or a named search bot.**

> The Florida Bar blocks AI-training agents *by name* while allowing general crawling. **That
> distinction only works if crawlers identify honestly** — and it is the direction more sites
> are moving.

---

## Scope

### Commercial modelling — out of scope

Funnel projections, cost estimates, CAC.

Both current documents state this in their footers. The three archived documents contain it,
and it was **built on published marketing claims rather than measured facts.**

> `_archive/` holds three earlier documents that are superseded. **Do not build from them.**

### Demand weighting by geography — not in version one

Weighting states because the company has sold there before is **circular** — it may reflect
where the founders' network is, and it can point at a **saturated** market rather than an open
one.

Collection is prioritised by **density** instead: an **efficiency decision, not a demand
assumption.** Non-concentration geographies are carried as a `holdout` track so the
assumption stays testable, and **close-rate data names the good geographies later.**

---

## Populations deliberately kept in

The inverse of an exclusion, and equally deliberate — each of these would be easy to drop and
each is kept for a stated reason.

| Kept | Why | If dropped |
|---|---|---|
| **Hourly firms (tier 4)** | The weakest fit under the fee-model axis | **The axis becomes unfalsifiable** — they are never contacted, so contrary evidence can never arrive |
| **Disqualified firms** | A disqualification you can explain is reusable | **A firm you never collected is invisible forever** — and `DQ_*` is revisitable on attribute change |
| **Grade B leads** | Named partner, working phone, live signal, no verifiable email | **Deleting them throws away a large slice of the collection effort.** Emailing them anyway damages the ability to email anyone |
| **Competitor customers** | Category-educated with an approved budget | **The strongest population there is**, silenced by accident |
| **Non-concentration geographies** | Tests the density-not-demand assumption | The geography assumption stays unexamined |
| **Agency-filter rejects** | Written to `job_posting_rejected` with the rule that fired | **The reject stream is how the blocklist gets extended** — and a rule-3 spike means a new agency appeared |
| **Unmatched job postings** | May name a firm not yet in the universe | A discovery lead is thrown away as a failure |
| **Closed job signals** | Weight drops to 0, but the row stays | The **fit history** — "this firm hires paralegals" — is lost |

The pattern across all eight: **removing a population removes the evidence that would tell you
whether removing it was right.**
