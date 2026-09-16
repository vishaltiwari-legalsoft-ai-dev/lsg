---
id: signals.sources
title: Where the job signal actually comes from
answers: "Which job boards matter for 2-25 attorney firms, and how do we reach each one?"
source: 03 §1, 03 §2, 03 §3
authority: canonical
stability: decided
depends_on: [signals.catalog, icp.size]
feeds: [signals.crawl-policy, pipeline.component-register, execution.build-order]
---

# Where the job signal actually comes from

## The insight that decides the architecture

The obvious answer to "which job boards matter" is Indeed, LinkedIn, ZipRecruiter. For
general hiring that is right. **For 2–25 attorney law firms hiring support staff, it is
misleading.**

Posting on the large boards costs money per listing or per click. A 4-attorney firm filling
one paralegal seat **does not run a recruiting budget**, so it posts where posting is free
or already paid for: its own website, its bar association, and the niche legal boards it
already belongs to.

> That reverses the usual trade-off. Normally the compliant sources are the weak ones and
> the good data sits behind terms that prohibit collecting it. **Here the sources with the
> best coverage of our exact segment are also the ones that publish structured,
> machine-readable postings and invite crawling.**

**Build lane 1 first and completely.** It covers the ICP better than the big boards do, it
is free, it is stable, and nothing about it breaks when a vendor changes its terms.

The large boards are a **coverage top-up, not the foundation**. They matter for the larger
end of the range and for firms that do run a recruiting budget, and they are **bought
rather than scraped**.

---

## Three lanes, one signal table

Three acquisition modes with different economics and different failure modes, converging on
one deduplicated signal. **Each lane can fail without taking the others down.**

| Lane | Sources | Economics | Component |
|---|---|---|---|
| **1 — Crawl** | Careers pages, bar boards, paralegal associations, ATS endpoints, Craigslist | Free, stable, best ICP coverage | JA1, JA2, JA3 |
| **2 — Buy** | Indeed, LinkedIn, ZipRecruiter via a licensed provider | Costs money. Buy last, against a measured gap | JA4 |
| **3 — Query** | Google for Jobs via a SERP provider | Discovery — finds sources we have not thought to crawl | JA5 |

The **agency filter sits before deduplication** deliberately: a staffing agency posting the
same role in eleven cities would otherwise survive as eleven distinct signals against
eleven wrong firms. **Nothing writes a signal until it has resolved to a real firm.**

---

## Tier A — best ICP coverage, publicly accessible

| Source | Why it matters here | Access route | Verdict |
|---|---|---|---|
| **The firm's own careers page** | Where small firms post first and often only. Also the one place the posting is **unambiguously tied to the firm** — no name resolution needed | Crawl. `JobPosting` JSON-LD is the standard markup, so most pages parse deterministically | **Primary** |
| **State bar association boards** (50) | Free or cheap for members, so firms use them heavily. High legal purity — almost no noise from other industries | Public listings crawl. A minority sit behind member login — **out of scope, not a target** | **Primary** |
| **Metro & county bar associations** (LA County, Chicago, Houston, Dallas, Miami-Dade, Brooklyn…) | **Even closer to the target.** A county bar board is where a 6-attorney PI firm posts a paralegal role | Public listings crawl. Long tail — prioritise the metros in the collection plan | **Primary** |
| **Paralegal association boards** (NALA, NFPA, NALS, state associations) | Role-specific and precisely on target — these boards carry **almost nothing but the roles we sell** | Public listings crawl | **Primary** |
| **ATS-hosted boards** (Greenhouse, Lever, Workable, JazzHR, BambooHR, Recruitee) | Firms at the larger end run an ATS. Small share of our universe, but **perfectly clean data where present** | Public per-company JSON endpoints — `boards-api.greenhouse.io/v1/boards/{co}/jobs`, `api.lever.co/v0/postings/{co}`. Structured, free, documented | **Primary** |
| **Craigslist** — metro jobs → legal/paralegal | Genuinely still used by small firms for admin and support roles, especially in large metros. **Consistently underestimated** | Public RSS per city/category | **Promoted to lane 1** by the audit |

---

## Tier B — high volume, licensed access

| Source | Why it matters here | Access route | Verdict |
|---|---|---|---|
| **Indeed** | Largest single volume of US support-staff postings. Skews to firms that *do* pay to advertise roles | No public API — the Publisher API was retired, the remaining Apply API is partner-only. Route is a licensed provider (Coresignal, Bright Data, Techmap, TheirStack) returning normalised JSON | **Buy, don't scrape** |
| **LinkedIn Jobs** | Attorney and administrator roles more than support staff. Useful for the lateral-hire signal | Licensed provider only. Direct automated collection carries account bans and real legal exposure — **not a technical obstacle to route around** | **Buy, don't scrape** |
| **ZipRecruiter** | SMB-heavy, which fits the segment better than LinkedIn does | Has a partner API programme. Apply for it; otherwise the same licensed providers | Partner API |
| **Glassdoor · SimplyHired** | Largely mirror Indeed's index. Little independent signal | Same licensed providers if wanted | Skip initially |

---

## Tier C — legal niche aggregators

| Source | Note | Verdict |
|---|---|---|
| LawCrossing | Aggregates legal jobs including from firm sites. Subscription — and its listings are **partly re-published from sources we already cover directly** | Evaluate for overlap before paying |
| Lawjobs.com · Law.com (ALM) | Skews larger firms and attorney roles | Low priority |
| ABA Career Center | National, attorney-weighted, moderate support-staff volume | Supplementary |
| Vault · Leopard Solutions | Large-firm intelligence products — our disqualified band | Out of scope |
| Law school career portals (Symplicity) | Authenticated, institution-scoped. **Requires credentials we have no basis to hold** | Excluded |

---

## Tier D — the query lane

**Google for Jobs** is not a board — it is an index built from `JobPosting` markup across
the web. Its value is **discovery**: it finds postings on sites we have not thought to crawl.

Google retired its Jobs API, so there is no endpoint to query directly. Reach it through a
SERP data provider — DataForSEO (already in the stack) or SerpApi.

---

## Buy the feed last, not first

The instinct is to start with a licensed provider because it arrives as clean JSON. But
until lane 1 is running **there is no way to know what it adds** — and given that small
firms largely avoid the paid boards, the honest expectation is that its incremental
coverage of this ICP is smaller than it looks.

Run lane 1, measure what share of firms produce postings there, **then buy against a
number**.
