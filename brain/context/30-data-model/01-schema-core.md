---
id: datamodel.schema
title: The schema — 13 core tables
answers: "What are the tables, and what are the two distinctions that carry the whole model?"
source: 01 §3, 02 §5, 02 §7
authority: canonical
stability: decided
depends_on: [orientation.project-brief, icp.tiers]
feeds: [datamodel.invariants, datamodel.reconciliation, pipeline.lifecycle]
---

# The schema — 13 core tables

Target file: `sql/001_schema.sql`. **Not yet written** — this is step 1 of the build.

**Postgres 16**, extensions `pg_trgm` + `postgis`.

---

## Two distinctions carry the whole model

**1. A firm is a durable entity; a lead is a time-bounded candidacy.** One firm produces
many leads over its life.

**2. Every attribute *claim* is stored separately from the resolved value** — because four
sources will disagree about a firm's phone number and the pipeline needs to be able to
explain which one won.

---

## Entity

```sql
CREATE TABLE firm (
  id             uuid PRIMARY KEY,
  -- resolved values, materialized from firm_attribute by reconcile()
  canonical_name text NOT NULL,
  name_stem      text NOT NULL,      -- see §4 normalization
  domain         text,               -- eTLD+1, null if no site
  phone_e164     text,
  addr_hash      text,               -- sha1(street_norm || zip5)
  state char(2), city text, lat numeric, lng numeric,

  entity_kind    text,   -- private_firm | inhouse | gov | directory_stub
  attorney_count int,
  staff_ratio    numeric,            -- support headcount / attorney count
  primary_practice text,
  practice_areas text[],
  fee_model      text,   -- contingency|fee_shifting|flat|hourly|mixed|unknown
  spanish_intake bool,
  cms_detected   text,
  review_count   int,                -- case-volume proxy
  paid_ads_active bool,
  has_inhouse_recruiter bool,

  tier           text,               -- output of icp_tier()
  fit_score      int,
  first_seen     timestamptz NOT NULL,
  last_crawled   timestamptz,
  content_hash   text                -- last homepage hash; drives re-extract
);
CREATE INDEX ON firm USING gin (name_stem gin_trgm_ops);
CREATE UNIQUE INDEX ON firm (domain) WHERE domain IS NOT NULL;
CREATE INDEX ON firm (tier, state) WHERE tier NOT LIKE 'DQ%';
```

The unique index on `domain` is not just an index — it is the constraint that makes the
dedupe verification query in [datamodel.identity](03-identity-resolution.md) meaningful.

---

## Provenance — the audit floor

```sql
-- raw, per-source, never mutated
CREATE TABLE observation (
  id         bigserial PRIMARY KEY,
  source     text NOT NULL,      -- 'places' | 'bar_ca' | 'site' | 'justia'
  source_key text NOT NULL,      -- place_id, bar number, url
  firm_id    uuid REFERENCES firm,   -- null until resolved
  payload    jsonb NOT NULL,
  fetched_at timestamptz NOT NULL,
  UNIQUE (source, source_key, fetched_at)
);

-- every claim any source made about any field. resolution reads this.
CREATE TABLE firm_attribute (
  firm_id     uuid NOT NULL REFERENCES firm,
  attr        text NOT NULL,     -- 'phone_e164' | 'fee_model' | ...
  value       jsonb NOT NULL,
  source      text NOT NULL,
  confidence  numeric NOT NULL,  -- 0..1
  evidence    text,              -- the span the value was read from
  observed_at timestamptz NOT NULL,
  PRIMARY KEY (firm_id, attr, source, observed_at)
);

-- merge audit. lets a bad dedupe be unpicked instead of re-run.
CREATE TABLE firm_alias (
  firm_id uuid NOT NULL REFERENCES firm,
  alias_name text, alias_domain text, alias_phone text,
  source text, merge_rule text, merged_at timestamptz
);
```

**Every source enters through `observation`** — internal ones too, with exactly one
exception. See [firstparty.one-door](../50-first-party/02-one-door-rule.md).

`firm_alias` is what makes a bad merge **unpickable rather than only re-runnable**.

---

## People

```sql
CREATE TABLE contact (
  id uuid PRIMARY KEY,
  firm_id uuid NOT NULL REFERENCES firm,
  full_name text NOT NULL,
  title text,
  role text,          -- owner | admin | attorney | unknown
  bar_number text,    -- the join key generic B2B data does not have
  linkedin_url text,
  phone_direct text,
  source text, confidence numeric, enriched_at timestamptz
);

-- one contact may carry several addresses at different verification states
CREATE TABLE contact_email (
  contact_id uuid NOT NULL REFERENCES contact,
  email text NOT NULL,
  status text NOT NULL,   -- valid|catch_all|risky|invalid|unverified
  pattern text,           -- 'first.last' | 'flast' — feeds R3
  verified_at timestamptz,
  PRIMARY KEY (contact_id, email)
);
```

`catch_all` and `risky` are **failures, not passes**. Treating them as valid is how a
sending domain dies in week one.

---

## Signal — append-only, weight derived

```sql
CREATE TABLE signal (
  id bigserial PRIMARY KEY,
  firm_id uuid NOT NULL REFERENCES firm,
  kind text NOT NULL,
  fingerprint text NOT NULL,   -- same posting ≠ new signal
  first_seen timestamptz NOT NULL,
  last_seen  timestamptz NOT NULL,
  closed_at  timestamptz,      -- posting removed → signal ends
  evidence   jsonb NOT NULL,   -- the quote the first line is built from
  UNIQUE (firm_id, kind, fingerprint)
);
```

**Weight is NOT stored.** It is derived at score time from kind + age, so an ageing job
posting gains weight without the watcher emitting a second event. That is why this table has
`first_seen`/`last_seen`/`closed_at` rather than a static weight column.

Append-only by grant, not by convention: `REVOKE UPDATE, DELETE` (invariant I6).

---

## Lead — a candidacy, not an entity

```sql
CREATE TABLE lead (
  id uuid PRIMARY KEY,
  firm_id uuid NOT NULL REFERENCES firm,
  contact_id uuid REFERENCES contact,
  grade char(1),          -- 'A' verified email | 'B' phone-first
  state text NOT NULL,
  wedge_sku text,         -- from tier → sku lookup
  intent_score int,
  arming_signal bigint REFERENCES signal,   -- what woke it
  cooldown_until timestamptz,
  created_at timestamptz NOT NULL,
  closed_at timestamptz, close_reason text
);
-- INVARIANT I1: at most one open lead per firm
CREATE UNIQUE INDEX ON lead (firm_id) WHERE closed_at IS NULL;

CREATE TABLE lead_state_event (
  lead_id uuid NOT NULL REFERENCES lead,
  from_state text, to_state text NOT NULL,
  trigger text NOT NULL, actor text,
  payload jsonb, at timestamptz NOT NULL
);

CREATE TABLE outreach_touch (
  id bigserial PRIMARY KEY,
  lead_id uuid NOT NULL REFERENCES lead,
  channel text, step int, mailbox text,
  sent_at timestamptz, delivered bool, bounced bool,
  replied_at timestamptz, reply_sentiment text
);
```

`arming_signal` is the attribution key. Every `WON` and `LOST` carries it, and the join
`outcome × signal kind` after 90 days is what re-weights the whole scoring table.

`lead_state_event` **is the audit log. Nothing else needs to be.**

---

## Control

```sql
CREATE TABLE suppression (
  scope text NOT NULL,    -- domain | email | firm_id
  value text NOT NULL,
  reason text NOT NULL,   -- customer | optout | dq | bounce
  added_at timestamptz NOT NULL,
  PRIMARY KEY (scope, value)
);
-- 'competitor' is deliberately NOT a suppression reason.

CREATE TABLE firm_track (
  firm_id uuid PRIMARY KEY REFERENCES firm,
  track text NOT NULL DEFAULT 'cold',
  -- cold | displacement | partner_intro | holdout | portal
  reason text, set_at timestamptz
);

CREATE TABLE bench_inventory (
  sku text, language text,
  practice_exp text,              -- added by 02 §5 — see below
  available int, replenish_rate_30d int, as_of timestamptz,
  PRIMARY KEY (sku, language)
);
```

### Why `bench_inventory` is in the data layer

The product promises a start in **under three days**. If a lead is armed for a wedge SKU
with an empty bench, the pipeline is **manufacturing a promise the delivery side cannot
keep** — and the failure lands on the strongest part of the pitch.

Making inventory a table the arming gate joins against turns that from an operational
accident into a **scheduling constraint** (invariant I4).

The `practice_exp` dimension is what makes it useful rather than decorative: *"12 case
managers available"* tells the arming gate almost nothing. *"12 case managers, 4 of them
Spanish-speaking with immigration experience"* tells it exactly which tier to arm. See
[firstparty.portal](../50-first-party/03-portal-bench-and-supply.md).

---

## Additions from the extensions

| Table / column | Added by | Purpose |
|---|---|---|
| `firm_track.track = 'portal'` | 02 §5 | Firms in the portal role-request feed. Suppressed from cold |
| `bench_inventory.practice_exp` | 02 §5 | Makes the arming gate tier-aware |
| `firm.has_hired_support_roles` | 02 §3 | Fit +5 |
| `firm.support_roles_posted text[]` | 02 §3 | Which roles |
| `firm.last_known_hiring_attempt` | 02 §3 | — |
| `firm.repeat_role_count` | 02 §3 | **Fit +8 at ≥2** — chronic need in a seat we can fill |
| `raw_posting` | 03 §10 | Stored postings, so JA6 is re-runnable without re-fetching |
| `job_posting_rejected` | 03 §4 | Agency-filter rejects **with the rule that fired** |
| Source registry (`source_state`, `crawl_delay_s`, `robots_checked`, `platform`) | 04 §6 | Crawl policy per host |
