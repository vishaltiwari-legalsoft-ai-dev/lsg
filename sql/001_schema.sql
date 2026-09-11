-- 001_schema.sql
-- All tables for the Lead Gen Engine, plus invariants I1-I7 as constraints
-- and triggers (context/30-data-model/05-invariants.md). Applied by
-- lge.db.migrate() inside its own transaction; do not edit an applied file --
-- add a new numbered migration instead (checksum drift raises loudly).
--
-- Deviation from context/30-data-model/01-schema-core.md: that chunk names
-- extensions "pg_trgm + postgis". PostGIS is NOT available in this
-- environment and nothing here requires it -- firm.lat/lng and firm.metro_code
-- (CBSA) are plain numeric/text columns, no geography type, no spatial index.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Application role. Idempotent: re-running this file (or a future migration
-- that also touches roles) never errors on "already exists". Actual DB
-- access from this codebase runs as the `postgres` superuser per the DSNs in
-- lge/settings.py; lge_app exists so the least-privilege boundary is in
-- place before anything depends on it.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lge_app') THEN
    CREATE ROLE lge_app LOGIN;
  END IF;
END
$$;

-- =============================================================================
-- Entity: firm
-- =============================================================================

CREATE TABLE firm (
  id             uuid PRIMARY KEY,

  -- resolved values, materialized from firm_attribute by reconcile()
  canonical_name text NOT NULL,
  name_stem      text NOT NULL,
  domain         text,
  phone_e164     text,
  addr_hash      text,
  state          char(2),
  city           text,
  lat            numeric,
  lng            numeric,

  -- ext: icp_tier() (context/10-icp/05-tiers-and-wedge-skus.md) reads
  -- f.country and f.first_seen_bar_admission directly, but the spec's firm
  -- table omits both columns entirely.
  country                   text,
  first_seen_bar_admission  timestamptz,

  -- ext: normalization-contracts (context/30-data-model/02) requires a
  -- separate secondary-unit field kept OUT of addr_hash (suites differ
  -- within one firm; putting them in the hash turns one firm's two floors
  -- into two firms), plus zip5 as its own indexable column for the hash
  -- formula sha1(street_norm || zip5) and for blocking queries.
  zip5        char(5),
  street_norm text,
  addr_unit   text,

  -- ext: CBSA code. Used by posting-fingerprint dedupe and the agency
  -- geographic rule (job signal acquisition) -- those need a metro code to
  -- compare against, not lat/lng distance math, at query time.
  metro_code  text,

  -- ext: normalization-contracts requires the version of every normalizer
  -- that produced a canonical value to be stored alongside it, so a
  -- normalizer bump is a targeted recompute rather than a full re-harvest.
  norm_versions jsonb NOT NULL DEFAULT '{}',

  entity_kind    text,
  attorney_count int,
  staff_ratio    numeric,
  primary_practice text,
  practice_areas   text[],
  fee_model        text,
  spanish_intake   bool,
  cms_detected     text,
  review_count     int,
  paid_ads_active  bool,
  has_inhouse_recruiter bool,

  -- ext: doc-02 first-party fit additions, from internal job-posting history
  -- (context/30-data-model/01 "Additions from the extensions" table). Feed
  -- fit_score()'s +5 / +8 terms.
  has_hired_support_roles bool,
  support_roles_posted    text[],
  last_known_hiring_attempt date,
  repeat_role_count       int,

  tier         text,
  fit_score    int,
  first_seen   timestamptz NOT NULL,
  last_crawled timestamptz,
  content_hash text,

  CONSTRAINT firm_tier_check CHECK (tier IS NULL OR tier IN (
    '1A','1B','2','3','4_NONBILLABLE','UNCLASSIFIED',
    'DQ_ENTITY','DQ_GEO','DQ_SIZE','DQ_SELFSERVE','DQ_NOVOLUME','DQ_NOBUDGET'
  )),
  CONSTRAINT firm_fee_model_check CHECK (fee_model IS NULL OR fee_model IN (
    'contingency','fee_shifting','flat','hourly','mixed','unknown'
  )),
  CONSTRAINT firm_entity_kind_check CHECK (entity_kind IS NULL OR entity_kind IN (
    'private_firm','inhouse','gov','directory_stub'
  ))
);

CREATE INDEX ON firm USING gin (name_stem gin_trgm_ops);
CREATE UNIQUE INDEX ON firm (domain) WHERE domain IS NOT NULL;
CREATE INDEX ON firm (tier, state) WHERE tier NOT LIKE 'DQ%';
-- ext: hot blocking-query paths for identity resolution.
CREATE INDEX ON firm (zip5);
CREATE INDEX ON firm (phone_e164);

-- =============================================================================
-- Provenance -- the audit floor
-- =============================================================================

CREATE TABLE observation (
  id         bigserial PRIMARY KEY,
  source     text NOT NULL,
  source_key text NOT NULL,
  firm_id    uuid REFERENCES firm,
  payload    jsonb NOT NULL,
  fetched_at timestamptz NOT NULL,

  -- ext: normalized match keys computed at WRITE time, never at query time
  -- (normalization-contracts) -- otherwise the blocking-query indexes below
  -- are useless, since an expression in a WHERE clause can't use them.
  name_raw      text,
  name_stem     text,
  domain        text,
  phone_e164    text,
  addr_hash     text,
  zip5          char(5),
  city          text,
  state         char(2),
  norm_versions jsonb NOT NULL DEFAULT '{}',

  UNIQUE (source, source_key, fetched_at)
);

CREATE INDEX ON observation (domain);
CREATE INDEX ON observation (phone_e164);
CREATE INDEX ON observation (zip5);
CREATE INDEX ON observation (firm_id);
CREATE INDEX ON observation USING gin (name_stem gin_trgm_ops);

CREATE TABLE firm_attribute (
  firm_id     uuid NOT NULL REFERENCES firm,
  attr        text NOT NULL,
  value       jsonb NOT NULL,
  source      text NOT NULL,
  confidence  numeric NOT NULL,
  evidence    text,
  observed_at timestamptz NOT NULL,
  PRIMARY KEY (firm_id, attr, source, observed_at)
);

CREATE INDEX ON firm_attribute (firm_id, attr);

CREATE TABLE firm_alias (
  firm_id      uuid NOT NULL REFERENCES firm,
  alias_name   text,
  alias_domain text,
  alias_phone  text,
  source       text,
  merge_rule   text,
  merged_at    timestamptz
);

-- =============================================================================
-- People
-- =============================================================================

CREATE TABLE contact (
  id         uuid PRIMARY KEY,
  firm_id    uuid NOT NULL REFERENCES firm,
  full_name  text NOT NULL,
  title      text,
  role       text,
  bar_number text,
  linkedin_url text,
  phone_direct text,
  -- ext: contact_email.status is OUR verification result; a purchased
  -- dataset's raw claimed address needs somewhere to land before that
  -- verification runs, and namesakes mean (firm_id, full_name) is not unique
  -- -- indexed on firm_id instead.
  email_raw  text,
  source     text,
  confidence numeric,
  enriched_at timestamptz
);

CREATE INDEX ON contact (firm_id);

CREATE TABLE contact_email (
  contact_id    uuid NOT NULL REFERENCES contact,
  email         text NOT NULL,
  status        text NOT NULL,
  -- ext: a purchased dataset's own claim about the address (e.g.
  -- 'verified'), kept separate from `status` which is OUR verification --
  -- catch_all/risky are failures regardless of what a vendor claimed.
  vendor_status text,
  pattern       text,
  verified_at   timestamptz,
  PRIMARY KEY (contact_id, email),
  CONSTRAINT contact_email_status_check CHECK (status IN (
    'valid','catch_all','risky','invalid','unverified'
  ))
);

-- =============================================================================
-- Signal -- append-only, weight derived
--
-- Reconciliation of a spec contradiction (see task brief section G):
-- 01-schema-core.md's I6 says "signal is append-only; correction is a new
-- row with a later last_seen -- REVOKE UPDATE, DELETE". But the table also
-- carries UNIQUE (firm_id, kind, fingerprint), so a correction row for an
-- existing (firm, kind, fingerprint) cannot be inserted -- and closure
-- detection explicitly SETS closed_at and MOVES last_seen on the existing
-- row. Resolved as: signal is insert-once for its identity columns
-- (firm_id, kind, fingerprint, first_seen, evidence), but three columns
-- remain mutable under a narrow, trigger-enforced contract --
-- last_seen (forward only), closed_at (settable, or clearable back to NULL
-- only when last_seen also advances -- a reposted listing), and
-- repost_count (increase only). Delete is refused unconditionally. Enforced
-- by trigger (binds superusers too) AND by grant revocation (belt and
-- braces) per the task brief.
-- =============================================================================

CREATE TABLE signal (
  id           bigserial PRIMARY KEY,
  firm_id      uuid NOT NULL REFERENCES firm,
  kind         text NOT NULL,
  fingerprint  text NOT NULL,
  first_seen   timestamptz NOT NULL,
  last_seen    timestamptz NOT NULL,
  closed_at    timestamptz,
  evidence     jsonb NOT NULL,
  repost_count int NOT NULL DEFAULT 0,
  UNIQUE (firm_id, kind, fingerprint)
);

-- Append-only history a signal's mutable fields are derived from.
-- sources[] and repost detection read this log, never the signal row alone.
CREATE TABLE signal_sighting (
  id                bigserial PRIMARY KEY,
  signal_id         bigint NOT NULL REFERENCES signal,
  source            text NOT NULL,
  url               text,
  board_posted_date date,
  present           bool NOT NULL,
  fetch_ok          bool NOT NULL,
  seen_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON signal_sighting (signal_id);

-- =============================================================================
-- Lead -- a candidacy, not an entity
-- =============================================================================

CREATE TABLE lead (
  id             uuid PRIMARY KEY,
  firm_id        uuid NOT NULL REFERENCES firm,
  contact_id     uuid REFERENCES contact,
  grade          char(1),
  state          text NOT NULL,
  wedge_sku      text,
  intent_score   int,
  arming_signal  bigint REFERENCES signal,
  cooldown_until timestamptz,
  created_at     timestamptz NOT NULL,
  closed_at      timestamptz,
  close_reason   text,

  -- ext: doc-04 scoring-engine columns (context/40-pipeline/04), materialized
  -- on the lead row so routing_band() output and the nightly scorer's pass
  -- are readable without a join back to firm.
  fit_score int,
  band      text,
  contest   text,
  scored_at timestamptz,

  CONSTRAINT lead_grade_check CHECK (grade IS NULL OR grade IN ('A','B')),
  CONSTRAINT lead_state_check CHECK (state IN (
    'DISCOVERED','PROFILING','NO_WEB','PROFILED','CLASSIFIED','ESCALATED',
    'DISQUALIFIED','CONTACT_PENDING','RESOLVED','QUALIFIED_A','QUALIFIED_B',
    'ARMED','ENGAGED','RESPONDED','HANDOFF','WON','LOST','STALE','SUPPRESSED'
  ))
);

-- INVARIANT I1: at most one open lead per firm.
CREATE UNIQUE INDEX lead_open_firm_id_uidx ON lead (firm_id) WHERE closed_at IS NULL;

CREATE TABLE lead_state_event (
  id         bigserial PRIMARY KEY,
  lead_id    uuid NOT NULL REFERENCES lead,
  from_state text,
  to_state   text NOT NULL,
  trigger    text NOT NULL,
  actor      text,
  payload    jsonb,
  at         timestamptz NOT NULL
);

CREATE INDEX ON lead_state_event (lead_id);

CREATE TABLE outreach_touch (
  id             bigserial PRIMARY KEY,
  lead_id        uuid NOT NULL REFERENCES lead,
  channel        text,
  step           int,
  mailbox        text,
  sent_at        timestamptz,
  delivered      bool,
  bounced        bool,
  replied_at     timestamptz,
  reply_sentiment text
);

CREATE INDEX ON outreach_touch (lead_id);

-- =============================================================================
-- Lifecycle transition whitelist
--
-- Seeded from context/40-pipeline/05-lead-lifecycle.md's transition table,
-- with three expansions per the task brief: QUALIFIED_* -> both A and B;
-- "any -> SUPPRESSED" -> every non-SUPPRESSED state; HANDOFF -> WON/LOST ->
-- two rows. The creation row ("-- -> DISCOVERED") is not represented here --
-- this whitelist governs UPDATE OF state on an existing row, not INSERT.
-- =============================================================================

CREATE TABLE lead_transition (
  from_state text NOT NULL,
  to_state   text NOT NULL,
  PRIMARY KEY (from_state, to_state)
);

INSERT INTO lead_transition (from_state, to_state) VALUES
  ('DISCOVERED', 'PROFILING'),
  ('DISCOVERED', 'NO_WEB'),
  ('PROFILING', 'PROFILED'),
  ('PROFILED', 'CLASSIFIED'),
  ('PROFILED', 'ESCALATED'),
  ('ESCALATED', 'CLASSIFIED'),
  ('CLASSIFIED', 'DISQUALIFIED'),
  ('CLASSIFIED', 'CONTACT_PENDING'),
  ('CONTACT_PENDING', 'RESOLVED'),
  ('RESOLVED', 'QUALIFIED_A'),
  ('RESOLVED', 'QUALIFIED_B'),
  ('QUALIFIED_A', 'ARMED'),
  ('QUALIFIED_B', 'ARMED'),
  ('ARMED', 'ENGAGED'),
  ('ENGAGED', 'RESPONDED'),
  ('ENGAGED', 'QUALIFIED_A'),
  ('ENGAGED', 'QUALIFIED_B'),
  ('RESPONDED', 'HANDOFF'),
  ('RESPONDED', 'QUALIFIED_A'),
  ('RESPONDED', 'QUALIFIED_B'),
  ('HANDOFF', 'WON'),
  ('HANDOFF', 'LOST'),
  ('LOST', 'QUALIFIED_A'),
  ('LOST', 'QUALIFIED_B'),
  ('QUALIFIED_A', 'STALE'),
  ('QUALIFIED_B', 'STALE'),
  -- "any -> SUPPRESSED": every state except SUPPRESSED itself.
  ('DISCOVERED', 'SUPPRESSED'),
  ('PROFILING', 'SUPPRESSED'),
  ('NO_WEB', 'SUPPRESSED'),
  ('PROFILED', 'SUPPRESSED'),
  ('CLASSIFIED', 'SUPPRESSED'),
  ('ESCALATED', 'SUPPRESSED'),
  ('DISQUALIFIED', 'SUPPRESSED'),
  ('CONTACT_PENDING', 'SUPPRESSED'),
  ('RESOLVED', 'SUPPRESSED'),
  ('QUALIFIED_A', 'SUPPRESSED'),
  ('QUALIFIED_B', 'SUPPRESSED'),
  ('ARMED', 'SUPPRESSED'),
  ('ENGAGED', 'SUPPRESSED'),
  ('RESPONDED', 'SUPPRESSED'),
  ('HANDOFF', 'SUPPRESSED'),
  ('WON', 'SUPPRESSED'),
  ('LOST', 'SUPPRESSED'),
  ('STALE', 'SUPPRESSED');

-- =============================================================================
-- Control
-- =============================================================================

CREATE TABLE suppression (
  scope    text NOT NULL,
  value    text NOT NULL,
  reason   text NOT NULL,
  added_at timestamptz NOT NULL,
  PRIMARY KEY (scope, value),
  CONSTRAINT suppression_scope_check CHECK (scope IN ('domain', 'email', 'firm_id')),
  -- NOTE: 'competitor' is deliberately NOT a suppression reason. A firm
  -- already buying from a rival is category-educated with an approved
  -- budget; it goes on the `displacement` firm_track, not into silence.
  -- See context/10-icp/06-disqualifiers-and-tracks.md.
  CONSTRAINT suppression_reason_check CHECK (reason IN ('customer', 'optout', 'dq', 'bounce'))
);

CREATE TABLE firm_track (
  firm_id uuid PRIMARY KEY REFERENCES firm,
  track   text NOT NULL DEFAULT 'cold',
  reason  text,
  set_at  timestamptz,
  CONSTRAINT firm_track_check CHECK (track IN (
    'cold', 'displacement', 'partner_intro', 'holdout', 'portal'
  ))
);

CREATE TABLE bench_inventory (
  sku                text,
  language           text,
  practice_exp       text NOT NULL DEFAULT 'any',
  available          int NOT NULL,
  replenish_rate_30d int NOT NULL DEFAULT 0,
  as_of              timestamptz NOT NULL,
  PRIMARY KEY (sku, language, practice_exp)
);

-- Lookup table, not logic -- tunable without a deploy.
-- Seeded from context/10-icp/05-tiers-and-wedge-skus.md.
CREATE TABLE tier_wedge_sku (
  tier          text PRIMARY KEY,
  segment       text,
  wedge_sku     text,
  client_facing text,
  second_sku    text
);

INSERT INTO tier_wedge_sku (tier, segment, wedge_sku, client_facing, second_sku) VALUES
  ('1A', 'PI & mass tort', 'demand_writer', 'No', 'document_collector'),
  ('1B', 'Immigration', 'legal_assistant_es', 'Partly', 'document_collector'),
  ('2', 'Fee-shifting litigation', 'case_manager', 'Yes', 'legal_assistant'),
  ('3', 'Flat-fee volume', 'legal_assistant', 'Partly', 'bookkeeper'),
  ('4_NONBILLABLE', 'Hourly practices', 'bookkeeper', 'No', 'marketing_specialist');

-- =============================================================================
-- Shared control tables
-- =============================================================================

CREATE TABLE task_run (
  component   text NOT NULL,
  entity_id   text NOT NULL,
  input_hash  text NOT NULL,
  status      text NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error       text,
  output      jsonb,
  PRIMARY KEY (component, entity_id, input_hash)
);

CREATE TABLE source_registry (
  host            text PRIMARY KEY,
  source_kind     text,
  -- a policy STATE, never a boolean.
  source_state    text NOT NULL DEFAULT 'open' CHECK (source_state IN (
    'open', 'rate_limited', 'policy_closed', 'edge_blocked', 'unreachable', 'auth_required'
  )),
  crawl_delay_s   numeric,
  robots_checked  timestamptz,
  robots_txt      text,
  platform        text,
  notes           text
);

CREATE TABLE document (
  id              bigserial PRIMARY KEY,
  firm_id         uuid REFERENCES firm,
  url             text NOT NULL,
  final_url       text,
  status_code     int,
  content_hash    text,
  object_key      text,
  bytes           int,
  word_count      int,
  rendered        bool NOT NULL DEFAULT false,
  fetch_ok        bool NOT NULL,
  robots_decision text,
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (url, content_hash)
);

CREATE INDEX ON document (firm_id);

-- =============================================================================
-- Invariant triggers
-- =============================================================================

-- ---- I2: no outreach_touch for a suppressed firm ---------------------------
-- Re-checked at send (insert) time, not at arm time -- a lead can sit ARMED
-- for hours and a suppression can land in between.

CREATE OR REPLACE FUNCTION trg_fn_outreach_touch_suppression() RETURNS trigger AS $$
DECLARE
  v_firm_id    uuid;
  v_domain     text;
  v_contact_id uuid;
BEGIN
  SELECT l.firm_id, f.domain, l.contact_id
    INTO v_firm_id, v_domain, v_contact_id
  FROM lead l
  JOIN firm f ON f.id = l.firm_id
  WHERE l.id = NEW.lead_id;

  IF v_firm_id IS NULL THEN
    RAISE EXCEPTION 'outreach_touch: lead % not found', NEW.lead_id;
  END IF;

  IF v_domain IS NOT NULL AND EXISTS (
    SELECT 1 FROM suppression WHERE scope = 'domain' AND value = v_domain
  ) THEN
    RAISE EXCEPTION 'I2 violation: firm domain % is suppressed', v_domain;
  END IF;

  IF EXISTS (
    SELECT 1 FROM suppression WHERE scope = 'firm_id' AND value = v_firm_id::text
  ) THEN
    RAISE EXCEPTION 'I2 violation: firm % is suppressed', v_firm_id;
  END IF;

  IF v_contact_id IS NOT NULL AND EXISTS (
    SELECT 1
    FROM contact_email ce
    JOIN suppression s ON s.scope = 'email' AND s.value = ce.email
    WHERE ce.contact_id = v_contact_id
  ) THEN
    RAISE EXCEPTION 'I2 violation: a contact email on lead % is suppressed', NEW.lead_id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_outreach_touch_suppression
  BEFORE INSERT ON outreach_touch
  FOR EACH ROW EXECUTE FUNCTION trg_fn_outreach_touch_suppression();

-- ---- I3: grade B leads may never be emailed --------------------------------
-- The spec's CHECK (grade='A' OR channel <> 'email') can't be a table CHECK
-- because grade lives on `lead`, not `outreach_touch` -- implemented as a
-- trigger that enforces the identical rule.

CREATE OR REPLACE FUNCTION trg_fn_outreach_touch_grade_b_email() RETURNS trigger AS $$
DECLARE
  v_grade char(1);
BEGIN
  IF NEW.channel = 'email' THEN
    SELECT grade INTO v_grade FROM lead WHERE id = NEW.lead_id;
    IF v_grade IS DISTINCT FROM 'A' THEN
      RAISE EXCEPTION
        'I3 violation: lead % has grade % -- only grade A may be emailed',
        NEW.lead_id, v_grade;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_outreach_touch_grade_b_email
  BEFORE INSERT OR UPDATE ON outreach_touch
  FOR EACH ROW EXECUTE FUNCTION trg_fn_outreach_touch_grade_b_email();

-- ---- I4: no ARMED without fresh bench --------------------------------------
-- Stale bench (as_of older than 48h) counts as empty.

CREATE OR REPLACE FUNCTION trg_fn_lead_arming_bench() RETURNS trigger AS $$
BEGIN
  IF NEW.state = 'ARMED' AND NEW.state IS DISTINCT FROM OLD.state THEN
    IF NEW.wedge_sku IS NULL THEN
      RAISE EXCEPTION 'I4 violation: lead % has no wedge_sku, cannot arm', NEW.id;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM bench_inventory
      WHERE sku = NEW.wedge_sku
        AND available > 0
        AND as_of > now() - interval '48 hours'
    ) THEN
      RAISE EXCEPTION
        'I4 violation: no fresh bench inventory (available > 0, as_of within 48h) for sku %',
        NEW.wedge_sku;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_lead_arming_bench
  BEFORE UPDATE OF state ON lead
  FOR EACH ROW EXECUTE FUNCTION trg_fn_lead_arming_bench();

-- ---- Lifecycle transition whitelist -----------------------------------------

CREATE OR REPLACE FUNCTION trg_fn_lead_transition_whitelist() RETURNS trigger AS $$
BEGIN
  IF NEW.state IS DISTINCT FROM OLD.state THEN
    IF NOT EXISTS (
      SELECT 1 FROM lead_transition WHERE from_state = OLD.state AND to_state = NEW.state
    ) THEN
      RAISE EXCEPTION
        'lead_transition violation: % -> % is not a whitelisted transition',
        OLD.state, NEW.state;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_lead_transition_whitelist
  BEFORE UPDATE OF state ON lead
  FOR EACH ROW EXECUTE FUNCTION trg_fn_lead_transition_whitelist();

-- ---- I5: every state change writes exactly one lead_state_event -----------

CREATE OR REPLACE FUNCTION trg_fn_lead_state_event_insert() RETURNS trigger AS $$
BEGIN
  INSERT INTO lead_state_event (lead_id, from_state, to_state, trigger, actor, at)
  VALUES (
    NEW.id, NULL, NEW.state,
    coalesce(current_setting('lge.trigger', true), 'unspecified'),
    coalesce(current_setting('lge.actor', true), 'system'),
    now()
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_lead_state_event_insert
  AFTER INSERT ON lead
  FOR EACH ROW EXECUTE FUNCTION trg_fn_lead_state_event_insert();

CREATE OR REPLACE FUNCTION trg_fn_lead_state_event_update() RETURNS trigger AS $$
BEGIN
  IF NEW.state IS DISTINCT FROM OLD.state THEN
    INSERT INTO lead_state_event (lead_id, from_state, to_state, trigger, actor, at)
    VALUES (
      NEW.id, OLD.state, NEW.state,
      coalesce(current_setting('lge.trigger', true), 'unspecified'),
      coalesce(current_setting('lge.actor', true), 'system'),
      now()
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_lead_state_event_update
  AFTER UPDATE OF state ON lead
  FOR EACH ROW EXECUTE FUNCTION trg_fn_lead_state_event_update();

-- ---- I6: signal immutability + signal_sighting append-only -----------------

CREATE OR REPLACE FUNCTION trg_fn_signal_immutable_update() RETURNS trigger AS $$
BEGIN
  IF NEW.firm_id     IS DISTINCT FROM OLD.firm_id
  OR NEW.kind         IS DISTINCT FROM OLD.kind
  OR NEW.fingerprint  IS DISTINCT FROM OLD.fingerprint
  OR NEW.first_seen   IS DISTINCT FROM OLD.first_seen
  OR NEW.evidence     IS DISTINCT FROM OLD.evidence THEN
    RAISE EXCEPTION
      'I6 violation: signal.id=% -- firm_id/kind/fingerprint/first_seen/evidence are immutable',
      OLD.id;
  END IF;

  IF NEW.last_seen < OLD.last_seen THEN
    RAISE EXCEPTION 'I6 violation: signal.id=% -- last_seen may only move forward', OLD.id;
  END IF;

  IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS NULL AND NEW.last_seen <= OLD.last_seen THEN
    RAISE EXCEPTION
      'I6 violation: signal.id=% -- closed_at may only be cleared when last_seen also advances (a repost)',
      OLD.id;
  END IF;

  IF NEW.repost_count < OLD.repost_count THEN
    RAISE EXCEPTION 'I6 violation: signal.id=% -- repost_count may only increase', OLD.id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_signal_immutable_update
  BEFORE UPDATE ON signal
  FOR EACH ROW EXECUTE FUNCTION trg_fn_signal_immutable_update();

CREATE OR REPLACE FUNCTION trg_fn_signal_no_delete() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'I6 violation: signal.id=% -- signal rows are never deleted', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_signal_no_delete
  BEFORE DELETE ON signal
  FOR EACH ROW EXECUTE FUNCTION trg_fn_signal_no_delete();

CREATE OR REPLACE FUNCTION trg_fn_signal_sighting_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION
    'I6 violation: signal_sighting.id=% -- append-only, never updated or deleted', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_signal_sighting_no_update
  BEFORE UPDATE ON signal_sighting
  FOR EACH ROW EXECUTE FUNCTION trg_fn_signal_sighting_immutable();

CREATE TRIGGER trg_signal_sighting_no_delete
  BEFORE DELETE ON signal_sighting
  FOR EACH ROW EXECUTE FUNCTION trg_fn_signal_sighting_immutable();

-- ---- I7: reconcile() (and named partners) are the only writers of firm ----
-- resolved columns. Writer identity comes from current_setting('lge.writer'),
-- set transaction-locally by lge.db.writer(conn, name).

CREATE OR REPLACE FUNCTION trg_fn_firm_writer_check() RETURNS trigger AS $$
DECLARE
  v_writer text := current_setting('lge.writer', true);
  qualification_changed boolean;
  tier_changed boolean;
  identity_changed boolean;
  crawl_changed boolean;
BEGIN
  IF v_writer IS NULL OR v_writer = '' THEN
    RAISE EXCEPTION
      'I7 violation: firm insert/update with no writer set (use lge.db.writer(conn, name))';
  END IF;

  IF TG_OP = 'INSERT' THEN
    qualification_changed :=
      NEW.entity_kind IS NOT NULL OR NEW.attorney_count IS NOT NULL OR
      NEW.staff_ratio IS NOT NULL OR NEW.primary_practice IS NOT NULL OR
      NEW.practice_areas IS NOT NULL OR NEW.fee_model IS NOT NULL OR
      NEW.spanish_intake IS NOT NULL OR NEW.cms_detected IS NOT NULL OR
      NEW.review_count IS NOT NULL OR NEW.paid_ads_active IS NOT NULL OR
      NEW.has_inhouse_recruiter IS NOT NULL OR NEW.country IS NOT NULL OR
      NEW.first_seen_bar_admission IS NOT NULL OR
      NEW.has_hired_support_roles IS NOT NULL OR
      NEW.support_roles_posted IS NOT NULL OR
      NEW.last_known_hiring_attempt IS NOT NULL OR
      NEW.repeat_role_count IS NOT NULL;

    tier_changed := NEW.tier IS NOT NULL OR NEW.fit_score IS NOT NULL;

    identity_changed :=
      NEW.canonical_name IS NOT NULL OR NEW.name_stem IS NOT NULL OR
      NEW.domain IS NOT NULL OR NEW.phone_e164 IS NOT NULL OR
      NEW.addr_hash IS NOT NULL OR NEW.zip5 IS NOT NULL OR
      NEW.street_norm IS NOT NULL OR NEW.addr_unit IS NOT NULL OR
      NEW.state IS NOT NULL OR NEW.city IS NOT NULL OR
      NEW.lat IS NOT NULL OR NEW.lng IS NOT NULL OR
      NEW.metro_code IS NOT NULL OR
      (NEW.norm_versions IS NOT NULL AND NEW.norm_versions <> '{}'::jsonb);

    crawl_changed := NEW.last_crawled IS NOT NULL OR NEW.content_hash IS NOT NULL;
  ELSE
    qualification_changed :=
      NEW.entity_kind IS DISTINCT FROM OLD.entity_kind OR
      NEW.attorney_count IS DISTINCT FROM OLD.attorney_count OR
      NEW.staff_ratio IS DISTINCT FROM OLD.staff_ratio OR
      NEW.primary_practice IS DISTINCT FROM OLD.primary_practice OR
      NEW.practice_areas IS DISTINCT FROM OLD.practice_areas OR
      NEW.fee_model IS DISTINCT FROM OLD.fee_model OR
      NEW.spanish_intake IS DISTINCT FROM OLD.spanish_intake OR
      NEW.cms_detected IS DISTINCT FROM OLD.cms_detected OR
      NEW.review_count IS DISTINCT FROM OLD.review_count OR
      NEW.paid_ads_active IS DISTINCT FROM OLD.paid_ads_active OR
      NEW.has_inhouse_recruiter IS DISTINCT FROM OLD.has_inhouse_recruiter OR
      NEW.country IS DISTINCT FROM OLD.country OR
      NEW.first_seen_bar_admission IS DISTINCT FROM OLD.first_seen_bar_admission OR
      NEW.has_hired_support_roles IS DISTINCT FROM OLD.has_hired_support_roles OR
      NEW.support_roles_posted IS DISTINCT FROM OLD.support_roles_posted OR
      NEW.last_known_hiring_attempt IS DISTINCT FROM OLD.last_known_hiring_attempt OR
      NEW.repeat_role_count IS DISTINCT FROM OLD.repeat_role_count;

    tier_changed :=
      NEW.tier IS DISTINCT FROM OLD.tier OR NEW.fit_score IS DISTINCT FROM OLD.fit_score;

    identity_changed :=
      NEW.canonical_name IS DISTINCT FROM OLD.canonical_name OR
      NEW.name_stem IS DISTINCT FROM OLD.name_stem OR
      NEW.domain IS DISTINCT FROM OLD.domain OR
      NEW.phone_e164 IS DISTINCT FROM OLD.phone_e164 OR
      NEW.addr_hash IS DISTINCT FROM OLD.addr_hash OR
      NEW.zip5 IS DISTINCT FROM OLD.zip5 OR
      NEW.street_norm IS DISTINCT FROM OLD.street_norm OR
      NEW.addr_unit IS DISTINCT FROM OLD.addr_unit OR
      NEW.state IS DISTINCT FROM OLD.state OR
      NEW.city IS DISTINCT FROM OLD.city OR
      NEW.lat IS DISTINCT FROM OLD.lat OR
      NEW.lng IS DISTINCT FROM OLD.lng OR
      NEW.metro_code IS DISTINCT FROM OLD.metro_code OR
      NEW.norm_versions IS DISTINCT FROM OLD.norm_versions;

    crawl_changed :=
      NEW.last_crawled IS DISTINCT FROM OLD.last_crawled OR
      NEW.content_hash IS DISTINCT FROM OLD.content_hash;
  END IF;

  IF qualification_changed AND v_writer <> 'reconcile' THEN
    RAISE EXCEPTION
      'I7 violation: firm % -- qualification columns may only be set by writer ''reconcile'' (got %)',
      NEW.id, v_writer;
  END IF;

  IF tier_changed AND v_writer NOT IN ('reconcile', 'score') THEN
    RAISE EXCEPTION
      'I7 violation: firm % -- tier/fit_score may only be set by writer ''reconcile'' or ''score'' (got %)',
      NEW.id, v_writer;
  END IF;

  IF identity_changed AND v_writer NOT IN ('resolve', 'reconcile') THEN
    RAISE EXCEPTION
      'I7 violation: firm % -- identity columns may only be set by writer ''resolve'' or ''reconcile'' (got %)',
      NEW.id, v_writer;
  END IF;

  IF crawl_changed AND v_writer NOT IN ('profile', 'reconcile') THEN
    RAISE EXCEPTION
      'I7 violation: firm % -- last_crawled/content_hash may only be set by writer ''profile'' or ''reconcile'' (got %)',
      NEW.id, v_writer;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_firm_writer_check
  BEFORE INSERT OR UPDATE ON firm
  FOR EACH ROW EXECUTE FUNCTION trg_fn_firm_writer_check();

-- =============================================================================
-- Grants
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;

-- I6 belt-and-braces: revoke at the grant level too, not just by trigger.
REVOKE UPDATE, DELETE ON signal FROM lge_app;
GRANT UPDATE (last_seen, closed_at, repost_count) ON signal TO lge_app;

REVOKE UPDATE, DELETE ON signal_sighting FROM lge_app;
