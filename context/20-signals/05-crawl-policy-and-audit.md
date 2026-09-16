---
id: signals.crawl-policy
title: Crawl policy, source states and the audit findings
answers: "What may we actually crawl, at what rate, and how do we keep that answer current?"
source: 04 (whole document), 03 §9
authority: verification
stability: dated
depends_on: [signals.sources]
feeds: [pipeline.component-register, pipeline.orchestration, execution.open-questions]
---

# Crawl policy, source states and the audit findings

**Checked 10 September 2026.** Sixteen sources, by live fetch of each robots.txt plus direct
unauthenticated calls to two ATS endpoints.

> This records **stated policy and observed response**. It is not legal advice. A permissive
> robots.txt is **not a licence** — terms of use are a separate document and govern
> independently. Read them for any source that becomes load-bearing.

Result: **7 open · 5 conditional · 3 prohibited · 1 unreachable.** The tier structure in
[signals.sources](02-job-source-register.md) held. Three details did not, and one of them
promoted a source that had been written off.

---

## Source state is not a boolean

Three sources failed for reasons that **look identical from the client side and are
completely different in meaning**. The distinction has to live in the source registry, or
the crawler will treat a temporary network condition as a permanent prohibition.

| Observation | Means | Correct response |
|---|---|---|
| robots.txt read, job paths disallowed<br>*Indeed, ZipRecruiter, LinkedIn* | A **published rule**. Stable, deliberate, the site's stated position | Do not crawl. Mark `policy_closed`. Route to a licensed provider or drop the source |
| **HTTP 403 on robots.txt itself**<br>*NFPA, ABA* | A WAF or bot-management layer refusing *this* request — commonly a datacentre IP range. **No policy was published or read** | Mark `edge_blocked`, **not closed**. Re-attempt from the crawler's real egress with an honest identifying UA. If it still fails, deprioritise — **do not attempt to defeat it** |
| **Connection refused**<br>*Texas Bar* | Network-layer failure. Could be geography, routing, an outage, or IP reputation | Mark `unreachable`, retry on a schedule. **Draw no conclusion about policy** |

> A single `blocked` boolean loses the distinction that matters: one is a decision to
> respect permanently, the others are conditions to retry. Conflated, the crawler either
> abandons reachable sources or keeps hammering ones that have said no.

---

## Open — no policy obstacle to the job paths

| Source | What the file says | Platform |
|---|---|---|
| **State Bar of California** | No job/career restrictions. Selective Disallow on admin paths only. No crawl-delay | Drupal |
| **New York State Bar** | Only `/wp-admin/`. Two sitemaps published. No crawl-delay | WordPress |
| **NALA** (paralegal association) | Only `/wp-admin/`. Sitemap published. No crawl-delay | WordPress |
| **Chicago Bar Association** | No job path restrictions. Blocks only commercial SEO crawlers (Ahrefs, Semrush, MJ12, Yandex) | iMIS |
| **LA County Bar** | No job path restrictions. Sitemap published. **`Crawl-delay: 5`.** Large explicit bad-bot blocklist | — |
| **Craigslist** | **No blanket disallow.** No restriction on `/search/` or job-category paths. Only interaction endpoints blocked (`/reply`, `/flag`, `/suggest`). **30 sitemaps published** | — |
| **Greenhouse boards API** | **Verified live.** Returns JSON without auth: `id, title, location, absolute_url, requisition_id, first_published, updated_at, application_deadline` | Public ATS API |

---

## Conditional

| Source | Finding |
|---|---|
| **The Florida Bar** | `Allow: /` for `*` and no job-path restrictions — **but** explicit `Disallow: /` for ClaudeBot, GPTBot, CCBot, Google-Extended, Amazonbot, Bytespider, Applebot-Extended, meta-externalagent, plus header `Content-Signal: search=yes, ai-train=no, use=reference`. **They have drawn a line at AI training, not at crawling.** A conventional, honestly-identified crawler is not in the blocked set — but the posture is deliberate and should be respected as stated |
| **Lever postings API** | Responded without auth, but the test slug returned an empty array, so **field structure could not be confirmed**. Re-test against a slug with live postings before relying on specific fields |
| **NFPA** | HTTP 403 on robots.txt itself. `edge_blocked` |
| **American Bar Association** | HTTP 403 on robots.txt. `edge_blocked` |
| **State Bar of Texas** | Connection refused at the network layer from this egress. `unreachable` — **no conclusion either way** |

---

## Closed — in their own words

```
INDEED        User-agent: *
              Disallow: /job/
              Disallow: /jobs/          (plus country variants)
              Disallow: /viewjob?
              -- no blanket disallow, but these three prefixes are precisely
              -- the listing and detail paths. nothing usable remains.

ZIPRECRUITER  User-agent: *
              Disallow: /
              Allow: /llms.txt
              -- deny by default. the single permitted file is a manifest.

LINKEDIN      "The use of robots or other automated means to access LinkedIn
               without the express permission of LinkedIn is strictly prohibited."
              -- no User-agent: * section at all. whitelist application only.
```

**This confirms the architecture rather than constraining it.** The build order already put
these last, on the reasoning that small firms mostly avoid paid boards. That reasoning is
now joined by a harder one: **for these three, a licensed data provider is not the compliant
alternative to scraping, it is the only route that exists.**

---

## What the audit changed

| Assumption | Finding | Change |
|---|---|---|
| Bar and paralegal boards are primary sources | Confirmed — 4 of 5 reachable association sites carry no job-path restriction | Holds |
| Craigslist is a light-touch supplementary feed | **Understated.** More open than most association sites | **Promote to lane 1** |
| Parsers per platform ≈ 3:1 reuse | Supported — three platforms across five sites | Holds |
| Public ATS endpoints return structured data | Confirmed for Greenhouse, **better fields than expected**. Lever partial | Holds · re-test Lever |
| The big three are "buy, don't scrape" | Confirmed explicitly by all three | Holds |
| 1 request / 2s is adequate | **Not universal.** LA County Bar declares `Crawl-delay: 5` | **Per-host, honour declared** |
| Association sites are uniformly reachable | **No** — 3 of 11 attempted failed | **Add reachability states** |

---

## Five design changes

**1. Source registry gains a policy state, not a boolean**
```
source_state ∈ { open, rate_limited, policy_closed,
                 edge_blocked, unreachable, auth_required }
crawl_delay_s   int    -- parsed from robots.txt, per host
robots_checked  date   -- staleness of our own reading
platform        text   -- wordpress | imis | drupal | naylor …
```

**2. Crawl-delay is read, not assumed.** The per-host token bucket takes its rate from the
host's declared `Crawl-delay` where one exists, falling back to 2s only where none is
declared. *LACBA at 5s: a 200-listing board takes ~17 min. Across 60 metro bars that is real
scheduler time and has to be planned, not discovered on the first slow night.*

**3. User-agent is honest and contactable.** One identifying UA string with a contact URL.
**Never rotated to evade, never impersonating a browser or a named search bot.** The Florida
Bar blocks AI-training agents *by name* while allowing general crawling — that distinction
only works if crawlers identify honestly, and it is the direction more sites are moving.

**4. Craigslist moves into lane 1.** Per-city RSS by job category, metros first. Expect
**high agency noise** — the [agency filter](03-agency-filter-and-resolution.md) matters more
here than on any association board.

**5. Greenhouse `first_published` is used directly** rather than inferring reposts.

---

## Still unchecked — the registry needs ~110 sources

| Group | Count | Priority | Note |
|---|---|---|---|
| Remaining state bars | ~46 | High | Expect a handful of platforms to cover most. **Identify the platform while checking** — it determines parser reuse |
| Metro & county bars | ~55 | High | Top 20 metros first. Closest to the ICP of any source |
| State paralegal associations | ~30 | Medium | Role-specific, low noise, small volume each |
| Remaining ATS platforms | 4 | Medium | Workable, JazzHR, BambooHR, Recruitee |
| Re-check the three that failed | 3 | High | Texas Bar, NFPA, ABA — **from the crawler's real egress** |

### Make the audit a component, not a task

Checking 110 sites by hand is a week that produces a snapshot which **starts decaying
immediately**. The same work as a script — fetch robots.txt, parse directives, fingerprint
the platform, write to the source registry — runs in an afternoon and **can be re-run on a
schedule**.

> A hand-built table is a document; a generated one is infrastructure.

---

## Re-audit triggers

| Trigger | Action |
|---|---|
| Monthly, all registered sources | Re-fetch robots.txt, **diff against the stored copy**, alert on any change touching job paths, crawl-delay, or agent-level rules |
| A source's yield drops to zero | **Check robots.txt before assuming the parser broke.** A newly added `Disallow` and a site redesign present identically |
| Repeated 403 or 429 | **Stop, do not retry harder.** Re-read the policy, lower the rate, and if it persists mark the source closed rather than working around it |
| Before a source becomes load-bearing | Read the site's **terms of use**, not only robots.txt. The two are separate documents and **the terms are the binding one** |

The Florida Bar's AI-crawler blocklist and `Content-Signal` header did not exist a few years
ago, and that pattern is spreading. **A permission checked once and never rechecked becomes
an assumption again.**
