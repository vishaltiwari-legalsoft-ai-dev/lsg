# API contract — backend ↔ frontend

The contract the two repos share, for UI milestones 0–3. The backend generates `openapi.json`
from its pydantic models; the frontend generates TypeScript types from that file. **This document
is the spec both are built to; if they disagree, fix the code, not the doc.**

Conventions:
- JSON, `snake_case`, ISO 8601 UTC timestamps, cursor pagination (`cursor`, `limit` ≤ 200).
- The API binds to `127.0.0.1:8100`. The screens run on `127.0.0.1:5000` (also opened as
  `localhost:5000`) and reach the API through their own `/api` proxy, so the browser is
  same-origin; CORS allows `http://localhost:5000` and `http://127.0.0.1:5000` only, for a page
  calling the API directly. Port 3000 belongs to another project on this machine and is refused
  (D-056).
- Errors: `{"error": {"code": "not_found", "message": "Lead not found.", "fix": "Check the id."}}`
  with the matching HTTP status.
- **Display strings come from the backend** (`display`, `label`, `headline`, `source_label`). The
  frontend never humanises a slug, recomputes a tier, filters a list or renders a draft. One
  source of truth.

---

## Shared types

```ts
type Band      = "STRIKE" | "SEQUENCE" | "NURTURE" | "HOLD"
type Contest   = "NONE" | "LOW" | "MED" | "HIGH"
type EmailStatus = "valid" | "catch_all" | "risky" | "invalid" | "unverified"
type Role      = "owner" | "admin" | "attorney" | "unknown"

interface FirmRef {
  id: string; name: string; domain: string | null; city: string | null; state: string | null
  tier: string | null; tier_display: string          // "Tier 1A", "Unclassified", "Disqualified — government"
  practice_display: string | null                     // "Personal injury"
  fee_display: string | null                          // "Contingency", "Unknown — not guessed"
  cms_display: string | null                          // "Filevine"
}

interface Proof {                // the evidence the engine read on the firm's own site
  signal_id: number
  kind: string                   // job_posting_open | multi_opening | mass_tort_campaign | review_unreturned_call | cms_implemented | …
  headline: string               // "Paralegal role open 26 days"
  quote: string | null           // the verbatim sentence — rendered as the highlighted quotation
  source_label: string           // "Careers page"
  source_url: string | null
  first_seen: string             // OURS — never the board's date
  board_posted_date: string | null
  days_open: number
  repost_count: number
  sources: string[]
  closed_at: string | null
  weight: number; decay: number; contest: Contest
}

interface ContactSummary {
  id: string; full_name: string; title: string | null; role: Role
  source_label: string                        // "Firm website (read by AI)", "Purchased firm list"
  email: string | null
  email_status: EmailStatus | null
  email_status_display: string | null         // "Verified" | "Unverified — vendor says verified" | "Catch-all — failure"
  phone: string | null
}

interface LeadRow {
  id: string; firm: FirmRef
  state: string; state_display: string        // "Resolved — waiting on email verification"
  band: Band | null; fit: number | null; intent: number | null; contest: Contest | null
  grade: "A" | "B" | null
  proof: Proof | null                         // the arming signal
  contact: ContactSummary | null              // primary: owner, else admin
  scored_at: string | null
}
```

---

## Endpoints

### `GET /api/health` → `{db: "ok" | "down", version: string}`

### `GET /api/today`
```ts
{
  top_proof: LeadRow | null            // the single strongest piece of proof — Today opens on it
  first_draft: {subject: string, body: string} | null   // its touch 1, ready to copy
  strike: LeadRow[]                    // the other STRIKE leads
  attention: {
    alerts: {name: string, label: string, state: "ok" | "firing" | "no_data", detail: string}[]
    queues: {handcheck: number, conflicts: number, identity: number, agency: number, discovery: number}
    bench: {skus_available: number, stale: boolean, message: string}   // "Bench is empty — leads can't be armed"
    providers_inert: string[]          // ["AI extraction", "Email verification"]
  }
}
```

### `GET /api/leads`
Query: `view` = `STRIKE | SEQUENCE | NURTURE | PHONE | EXCLUDED | UNSCORED` (default `STRIKE`),
`tier`, `city`, `signal`, `contest`, `verified` (bool), `q`, `cursor`, `limit`.
```ts
{ items: LeadRow[], next_cursor: string | null,
  counts: {STRIKE: number, SEQUENCE: number, NURTURE: number, PHONE: number, EXCLUDED: number, UNSCORED: number} }
```
`PHONE` is grade B. `EXCLUDED` is every lead the list-hygiene filter removes, each carrying its
reasons in the detail. `UNSCORED` is leads not yet scored (most of the universe before a crawl).
Order: intent descending, then contest ascending (low contest first), then fit descending.

### `GET /api/leads/{id}` → `LeadDetail`
```ts
interface LeadDetail extends LeadRow {
  contacts: ContactSummary[]                 // owner AND admin when both exist
  missing_roles: ("owner" | "admin")[]       // "No office manager found"
  score: {
    fit_terms: {label: string, points: number}[]
    intent_terms: {label: string, weight: number, decay: number, points: number}[]
    note: string                             // "Scores use seeded weights until outcomes are recorded."
  }
  exclusion_reasons: string[]                // why it is not on the email list, in plain words
  outcomes: LeadOutcome[]
  timeline: {from_state: string | null, to_state: string, label: string, trigger: string, actor: string, at: string}[]
}
```

### `GET /api/leads/{id}/drafts`
Calls the journey renderer (`build_journey`). Never re-implemented in the frontend.
```ts
{ band: Band | null, excluded_reason: string | null,
  touches: {step: number, day: number, subject: string, body: string, skipped_reason: string | null}[] }
```

### `POST /api/leads/{id}/outcome`
```ts
// request
{ action: "sent" | "replied" | "meeting" | "won" | "lost" | "not_now" | "opt_out",
  until?: string /* date, required for not_now */, note?: string }
// response
{ lead: LeadDetail, transition_applied: boolean, message: string }
```
**Outcomes are recorded in `lead_outcome` (append-only) every time.** That table is what
attribution reads. The lifecycle transition is applied **only when the state machine allows it**:
arming needs bench inventory (invariant I4), and the bench is empty until portal access exists,
so most leads cannot legally reach `ENGAGED` today. The response says whether the transition
happened and why not. `not_now` sets `cooldown_until`. **`opt_out` always adds the firm's domain
to suppression** (sticky; only an admin clears it). Toast copy comes from `message`.

### `GET /api/leads/export.csv?view=…`
Runs `build_list`, so list hygiene applies at export time. `text/csv`. Grade B never appears in an
email export.

### `GET /api/firms`
Query: `q` (name or domain), `tier`, `city`, `lead_state`, `cursor`, `limit`.
`{items: {id, name, domain, city, state, tier_display, state_display, fit}[], next_cursor, total}`

### `GET /api/firms/{id}` — "the record"
```ts
{
  firm: FirmRef
  tier_reason: string              // "Contingency fee and a personal-injury practice, so tier 1A."
  attributes: AttributeRow[]
  documents: {url: string, page_kind: string, status_code: number | null, words: number | null, robots_decision: string | null, fetched_at: string}[]
  signals: Proof[]
  contacts: ContactSummary[]
  aliases: {name: string | null, domain: string | null, phone: string | null, merge_rule: string | null, source_label: string}[]
  lead: {id: string, state_display: string, band: Band | null} | null
}

interface AttributeRow {
  attr: string; label: string                              // "fee_model", "Fee model"
  display: string                                          // "Contingency" | "Unknown — not guessed"
  state: "resolved" | "unknown" | "conflict" | "stale"
  source_label: string | null; confidence: number | null
  evidence: string | null; evidence_url: string | null; observed_at: string | null
  claims: {source_label: string, display: string, confidence: number, evidence: string | null, observed_at: string, won: boolean}[]
}
```

### Hand-check — gate G2
`GET /api/handcheck` →
```ts
{ gate: {needed: 50, reviewed_firms: number, passed: boolean, rule: string},
  accuracy: {attr: string, label: string, checked: number, correct: number}[],
  sample: {firm_id: string, name: string, domain: string | null, attributes: AttributeRow[],
           reviews: Record<string, {correct: boolean, corrected_value: string | null}>}[] }
```
The sample is 50 firms from the probe that have documents, stable across calls.
`POST /api/handcheck/{firm_id}/{attr}` with `{correct: boolean, corrected_value?: string}` → `204`.

### Meta and pipeline (read-only)
- `GET /api/meta/providers` → `{ai_extraction: boolean, email_verification: boolean, places: boolean, crawler_identity: string}`. Booleans only — **never key values**. Each is asked of the seam that does the work (D-054): `email_verification` is true when the verification step would run (a verifier chosen and its key set); `places` is true when the Google Business Profile is looked up directly — the search engine in use has a listings endpoint (Serper) and its key is set. `GOOGLE_PLACES_API_KEY` is read by nothing.
- `GET /api/pipeline/alerts` → `{items: {name, label, state, value, detail}[]}`
- `GET /api/pipeline/gates` → `{items: {name, label, passed, report}[]}` (fast gates only: invariants, g1_identity, g3_tier_distribution, g7_coverage)

---

## Revision 2 — found by running the UI against real data (additive)

**Plain words everywhere.** No slug or code reaches the UI as display text: attribute values
(`private_firm` → "Private law firm", `personal_injury, workers_comp` → "Personal injury, Workers'
comp"), exclusion reasons (`tier_unclassified` → "Fee model unknown — not guessed, so the firm
isn't tiered yet."), `Proof.sources` (`careers` → "Careers page") and alert details.

**Non-null as documented:** `Proof.days_open`, `documents[].page_kind` (`"other"` when unknown),
`firms[].state_display` ("Not a lead" when there is no open lead). A malformed id returns `404`
with the error body, never `500`. List rows carry `proof` exactly as the detail does.

**Only real sentences are quoted.** `AttributeRow` and each of its `claims[]` gain
`quotable: boolean`. It is true only when the evidence is a sentence read from page text (fee
language, practice pages, AI extraction): at least four words, different from the displayed
value, and not markup. Structured-data echoes ("Attorney", "US", the phone number itself, an HTML
tag) are `quotable: false`, and the UI does not quote or highlight them. The highlighter marks
proof, not metadata.

```ts
interface AttributeRow { /* …as above… */ quotable: boolean
  claims: {source_label, display, confidence, evidence, observed_at, won, quotable: boolean}[] }

interface Alert { name, label, state, detail /* plain language */, technical: string | null }

interface FirmDetail { /* …as above… */ merged_into: {id: string, name: string} | null }
```

### Identity review — duplicates found after crawling (decision D-024)
Firms' own websites reveal identity keys the discovery sources did not: two vendor domains turned
out to be one firm with two sites, sharing a name and a phone. Signals are immutable and carry
`firm_id`, so firms are **merged by retirement**, never physically merged. The duplicate gets
`merged_into = survivor`, its open lead closes as a duplicate, its contacts move to the
survivor, its name, domain and phone become aliases, and its signals count toward the survivor's
intent. Merged firms disappear from lists, scoring and gate G1.

```ts
interface FirmSide { id: string; name: string; domain: string | null; phone: string | null
  city: string | null; state: string | null; tier_display: string; state_display: string
  observations: number; contacts: number; signals: number }

interface IdentityReviewItem { id: number; reason: string /* plain words */; rule: string
  similarity: number | null; created_at: string; left: FirmSide; right: FirmSide }
```
- `GET /api/review/identity` → `{items: IdentityReviewItem[]}` (open items only)
- `POST /api/review/identity/{id}/decision` with
  `{decision: "merge" | "keep_separate", survivor_id?: string, note?: string}` → `{message: string}`.
  `merge` without `survivor_id` keeps the firm with more observations (then the older one).
  Every decision is written to `review_decision`.

---

## Revision 3 — one recipe, one set of list rules (D-054, additive)

**A research job's steps are the flow's.** `POST /api/firms/{id}/research` with scope `full`
runs the components of the `research` flow in `config/flows.yml`, scope `contacts` those of
`find_contacts` — the same recipe `lge flow` runs, gates left out. Each step carries its plain
label from the engine; the screen keeps no map of its own.

```ts
interface JobStep { name: string; label: string /* "Move the lead forward" */
  status: "pending" | "running" | "done" | "failed"; note?: string | null }
```

**The list rules hold a lead back from the Qualified panel and its sheet** exactly as they do
from every list: parked, a portal or competitor's customer, the firm or its domain on the
do-not-contact list. Such a lead is neither ready nor almost, and never on
`/api/qualified/export.csv`. An address on the do-not-contact list is not an address on file.

```ts
interface QualifiedCounts { /* …ready, almost, checked, missing_by_check… */
  withheld: {label: string /* "Do not contact", "Parked" */; count: number}[] }  // most first
```

---

## Revision 4 — the email journey (D-057, additive)

**`day` is days after the first email.** The screens show it as "Day {day + 1}": the first
email goes on Day 1. A skipped touch carries `day: 0` and no meaning; it would have gone on the
schedule's day.

**Each drafted email names the templates it was built from**, its own wording first, then any
paragraph set into it. Empty for a skipped touch. **A lead with no emails says why in words**
beside the code, so no screen shows `unresolved_token:cms`.

```ts
interface Touch { step; day; subject; body; skipped_reason; templates: string[] /* ["1-open-role", "1-paragraph-pi"] */ }
interface DraftsResponse { band; excluded_reason: string | null
  excluded_display: string | null /* "An email needs the case system, and it is not known" */; touches: Touch[] }
```

### `GET /api/journey` → `JourneyResponse`
The nine emails in order, each with its day (edits applied) and original day, its plain title,
purpose and what varies it, and every template that can serve it: wording as it stands and as
written, when it is used, the fill-ins an edit may use, and the paragraph slot an email must keep.
Plus the tracks (Sequence, Nurture with its `pace`, Strike, Hold), the fill-in glossary, the
banned phrases, the latest day an email can move to, and the example firm's options.

```ts
interface JourneyTemplate { id: string; step: number; kind: "email" | "paragraph"; used_when: string
  subject: string | null; body: string; original_subject: string | null; original_body: string
  edited_at: string | null; fill_ins: string[]; keeps: string | null }
interface JourneyStep { step: number; day: number; original_day: number; title: string
  purpose: string; varies_by: string; templates: JourneyTemplate[] }
interface JourneyTrack { band: Band; label: string; description: string; steps: number[]; pace: number }
interface JourneyResponse { steps: JourneyStep[]; tracks: JourneyTrack[]
  fill_ins: {token: string; label: string; meaning: string}[]; banned_phrases: string[]
  max_day: number; tiers: {value: string; label: string}[]; pains: {value: string; label: string}[] }
```

### `PUT /api/journey/templates/{id}` `{subject?: string | null, body: string}` → `JourneyTemplate`
New wording for every lead from now on. Refused with `422 invalid_copy` (the message says every
reason) for a banned phrase, a fill-in the template cannot fill, a stray brace, a paragraph slot
not kept exactly once, or an empty subject or body. A paragraph's subject is ignored. Saving the
original back is a restore. `DELETE` restores the original.

### `PUT /api/journey/days` `{days: {step, day}[]}` → `JourneyResponse`
The whole schedule: an email left out goes back to its original day. Email 1 is always Day 1;
each later email must come after the one before, by Day 91 at the latest (`422 invalid_days`).
`DELETE` restores every original day. Nurture keeps its pace over the new days.

### `GET /api/journey/example?tier&pain&system&band` → `JourneyExample`
An invented firm's journey, rendered by `build_journey` with the saved edits, so the screen
shows real emails before any lead is ready.

```ts
interface JourneyExample { firm: string; person: string; tier; pain; system: boolean
  band: "SEQUENCE" | "NURTURE"; drafts: DraftsResponse }
```

---

## Source labels

| Tag | Shown as |
|---|---|
| `site:jsonld` | Firm website (structured data) |
| `regex:p6` | Firm website (fee language) |
| `rules:p7` | Firm website (page code) |
| `rules:practice` | Firm website (practice pages) |
| `rules:site` | Firm website |
| `llm:p8:*` | Firm website (read by AI) |
| `llm:p9:*` | Firm website (read by AI, escalated) |
| `internal_firms` | Purchased firm list |
| `internal_jobs` | Job history file |
| `careers` | Careers page |
