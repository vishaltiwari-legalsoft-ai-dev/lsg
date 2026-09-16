---
id: orientation.glossary
title: Glossary
answers: "What does this term mean in this system specifically?"
source: all
authority: canonical
stability: decided
depends_on: []
feeds: []
---

# Glossary

Terms that carry a specific meaning here, different from or narrower than their general use.

## Entities

**Firm** — a durable entity. Built once, maintained forever. One row in `firm`.

**Lead** — a *time-bounded candidacy for outreach*, not an entity. One firm produces many
leads over its life. At most one open lead per firm at a time (invariant I1).

**Contact** — a named person at a firm. Owner, admin, attorney or unknown. A generic
inbox is not a contact.

**Observation** — a raw, per-source, never-mutated record of what one source said at one
time. The audit floor. Every external and internal record enters here.

**Attribute claim** — one source's assertion about one field, with a confidence and the
evidence span it was read from. Stored in `firm_attribute`. Distinct from the resolved
value on `firm`, which `reconcile()` materialises.

## Axes

**Universe** — which firms could buy. Stable, breadth problem.

**In-market** — which firms need staff right now. Transient, freshness problem.

**Fit** — a pure function of firm attributes. 0–50. Deterministic, recomputed on
attribute change.

**Intent** — a windowed, decaying aggregation over signals. 0–50. Recomputed nightly.

**Contest level** — how many competing vendors can observe the same signal. A *routing
input*, not a score component. High-intent + low-contest is where human time goes.

**Tier** — output of `icp_tier()`. `1A | 1B | 2 | 3 | 4_NONBILLABLE | DQ_* | UNCLASSIFIED`.

**Wedge SKU** — the role that opens the conversation for a tier. A lookup table, not
logic, so it can be tuned from outcome data without a deploy.

**Track** — `cold | displacement | partner_intro | holdout | portal`. Which motion a firm
belongs to. Distinct from suppression: a track routes, suppression silences.

**Holdout** — a deliberate slice worked in order to *test a targeting assumption*, not to
convert. Tier 4 hourly firms and non-concentration geographies.

## Signals

**Signal** — an append-only, fingerprinted, dated observation that a firm is in market.
Weight is **not stored on the row** — it is derived at score time from kind + age, so an
ageing job posting gains weight without a second event being emitted.

**Fingerprint** — the dedupe key that makes "the same posting seen on six boards" one
signal rather than six.

**`first_seen`** — when *we* first saw it. The operative date. This is what makes
"open more than 21 days" computable at all.

**`board_posted_date`** — what a board claims. Stored, untrusted. Employers refresh
listings to stay near the top, which resets it while the vacancy is unchanged.

**Repost** — same fingerprint, `board_posted_date` moved forward while our `first_seen`
stayed put. A dated, affirmative admission of hiring failure. The strongest variant of
signal 01.

## Grades and states

**Grade A** — verified personal email. Emailable.

**Grade B** — named person, working phone, live signal, but no verifiable email. **A
product, not a reject pile** — a phone-and-research motion. Never emailed (invariant I3).

**Re-pooling** — a lead that did not convert returns to the pool with its verified contact
intact and waits for the next signal. Most firms are not in market today; the point of
holding a current record is being ready on the day they are.

**Suppression** — a hard stop on sending, checked before every send. Scoped to
`domain | email | firm_id`. Domain scope is the important one: one partner opting out
silences the whole firm. Sticky — only a human clears it.

## Source states

Four outcomes that look identical from the client side and mean completely different
things. Never collapse them into one `blocked` boolean.

| State | Means | Response |
|---|---|---|
| `open` | No policy obstacle | Crawl |
| `rate_limited` | A declared `Crawl-delay` | Crawl at the declared rate |
| `policy_closed` | A published rule disallowing the paths we need | Do not crawl. Buy or drop. |
| `edge_blocked` | HTTP 403 on robots.txt itself — a WAF refusing us. No policy was read. | Retry from real egress with an honest UA |
| `unreachable` | Connection refused at the network layer | Draw no conclusion. Retry on a schedule. |
| `auth_required` | Behind a member login | Out of scope. Not a target. |

## Planes

| Plane | Contains | Terminates? |
|---|---|---|
| **D** | Discovery — creates firm candidates | Yes, once per firm |
| **P** | Profile — fills firm attributes | Yes, once per firm |
| **W** | Watchers — emit signals | **Never** |
| **R** | Resolvers — people and verification | Yes |
| **I** | First-party — internal assets | Mixed (I1/I2 one-shot, I3/I4 hourly) |
| **JA** | Job acquisition sub-plane, replaces W1/W2 | Never |
