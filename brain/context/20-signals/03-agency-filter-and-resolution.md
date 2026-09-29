---
id: signals.filter-resolve
title: The agency filter and posting-to-firm resolution
answers: "How do we stop targeting recruiters, and how do we attach a posting to a real firm?"
source: 03 §4, 03 §6
authority: canonical
stability: decided
depends_on: [signals.sources, datamodel.identity]
feeds: [signals.dedupe, pipeline.component-register]
---

# The agency filter and posting-to-firm resolution

Both stages live inside **JA6**, which is a pure function over stored `raw_posting` rows.
Everything here will be tuned repeatedly in the first months — keeping it pure means every
change is a **re-run over what is already on disk, not a re-crawl of the internet**.

Order is fixed: **agency filter → deduplicate → resolve → write signal.** Nothing writes a
signal until it has resolved to a real firm.

---

## The agency filter

A large share of legal support-staff postings are placed by **staffing and recruiting
agencies, not by law firms**. These are not leads — they are a different industry, and the
firm that actually needs the person is hidden behind "our client".

Without this filter the pipeline targets recruiters as if they were prospects, inflates
every volume estimate, and writes signals onto companies that will never buy.

> **It is the single highest-value transform in this whole lane.**

Reject a posting when **any** of these fire:

### 1. Known agency
Company matches the maintained legal-staffing blocklist — Robert Half Legal, Beacon Hill
Legal, Adams & Martin, Special Counsel / Adecco, Vaco, Lateral Link, Kforce Legal, Marina
Sirras, Latitude, Hire Counsel. **Maintained, not static.**

### 2. Client language
Body matches:
```
/\bour client\b|\bconfidential client\b/i
/\b(?:a|our)\s+(?:growing|established|boutique)\s+(?:law\s+firm|firm)\b/i
```
The second pattern catches postings that **describe rather than name** the employer.

### 3. Geographic spread — the strongest behavioural tell
Same company posting legal support roles in **≥ 5 distinct metros within 90 days**.

> A real 2–25 attorney firm does not hire paralegals in five cities at once. An agency does
> it every week.

### 4. Volume
Same company with **≥ 20 open legal support roles**. Inconsistent with the entire target
size band.

### 5. Blind posting
Employer name absent, generic, or "confidential". Unresolvable — **drop rather than guess**.

---

### Rule 3 catches what a blocklist cannot

Agency names change, new ones appear constantly, and **no maintained list stays complete**.
Geographic spread is a *behavioural signature* rather than an identity, so it catches
agencies nobody has heard of yet — and it costs one grouped query.

### Rejects are kept, not discarded

Written to `job_posting_rejected` **with the rule that fired**. The reject stream is how the
blocklist gets extended, and **a sudden spike in rule 3 usually means a new agency has
appeared, not that the market changed**.

---

## Resolving a posting to a firm

Lane 1 mostly solves this for free — a posting on a firm's own careers page is **already
attached to a domain**. Lanes 2 and 3 give a company name and a city, which is the weakest
matching position in the system.

### Keep the full posting body

The practical unlock. Application emails, "visit our website at", and apply-links back to
the firm's own site appear constantly in the text, **and each one carries a domain** —
which turns a probabilistic name match into a decisive one.

Structured fields alone lose this. Store the body.

### The resolution ladder

| # | Extract | Match rule | Confidence |
|---|---|---|---|
| 1 | **Apply-email domain in the body** — `careers@smithlaw.com` | eTLD+1 exact against `firm.domain` | **Decisive** |
| 2 | Outbound link to a non-board domain | eTLD+1 exact, board and ATS hosts excluded | **Decisive** |
| 3 | Phone number in the body | E.164 exact | **Decisive** |
| 4 | **ATS slug** — `boards.greenhouse.io/smithlaw` | Slug→firm map, built once and reused | **Decisive** |
| 5 | Company name + street address | Address hash plus name similarity (rule R3) | Strong |
| 6 | Company name + metro | Trigram within CBSA. **Accept only if exactly one candidate clears the threshold** | Review queue |
| 7 | Company name alone | — | **Reject** |

Rung 7 is a hard stop. A name-only match **writes a false hiring signal onto a real firm**,
permanently, and nothing downstream will ever question it. **Never guess.**

This ladder mirrors the identity-resolution rules R1–R4 in
[datamodel.identity](../30-data-model/03-identity-resolution.md) and the match ladder for
internal job data in [firstparty.job-history](../50-first-party/05-job-history.md). Same
principle in three places: a decisive key or nothing.

### An unmatched posting is still worth keeping

If a posting cannot be resolved, it may name a **firm that is not yet in the universe at
all** — a discovery lead rather than a failure.

Route it to the discovery queue with its company name and metro so the normal harvest can
try to find that firm properly, then **re-attempt the match**. Do not merge it into an
existing record on a hunch.
