# API contract — backend ↔ frontend

The contract the two repos share, for UI milestones 0–3. The backend generates `openapi.json`
from its pydantic models; the frontend generates TypeScript types from that file. **This document
is the spec both are built to; if they disagree, fix the code, not the doc.**

Conventions:
- JSON, `snake_case`, ISO 8601 UTC timestamps, cursor pagination (`cursor`, `limit` ≤ 200).
- The API binds to `127.0.0.1:8000`. CORS allows `http://localhost:3000` and
  `http://127.0.0.1:3000` only.
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
- `GET /api/meta/providers` → `{ai_extraction: boolean, email_verification: boolean, places: boolean, crawler_identity: string}`. Booleans only — **never key values**.
- `GET /api/pipeline/alerts` → `{items: {name, label, state, value, detail}[]}`
- `GET /api/pipeline/gates` → `{items: {name, label, passed, report}[]}` (fast gates only: invariants, g1_identity, g3_tier_distribution, g7_coverage)

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
