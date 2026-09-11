-- 090_ui.sql -- UI-facing tables owned by lge/api/*.py (plan/api-contract.md).
-- One complete write. Every write path the API uses (POST /api/leads/{id}/outcome,
-- POST /api/handcheck/{firm_id}/{attr}, POST /api/review/{queue}/{item}/decision)
-- lands here; reads come from the existing schema plus the indexes below.

-- =============================================================================
-- lead_outcome -- append-only. "Outcomes are recorded ... every time" (contract):
-- this table is what lge/ops/report.py's attribution report reads, independent
-- of whether the lifecycle transition itself was allowed to apply (most leads
-- cannot legally reach ENGAGED today -- the bench is empty). Same append-only
-- contract shape as `signal`/`signal_sighting` (I6): a BEFORE UPDATE/DELETE
-- trigger raises, and UPDATE/DELETE are revoked from lge_app as belt-and-braces.
-- =============================================================================

CREATE TABLE lead_outcome (
  id                 bigserial PRIMARY KEY,
  lead_id            uuid NOT NULL REFERENCES lead,
  action             text NOT NULL CHECK (action IN (
                        'sent', 'replied', 'meeting', 'won', 'lost', 'not_now', 'opt_out'
                      )),
  until              date,
  note               text,
  actor              text NOT NULL DEFAULT 'ui',
  transition_applied bool NOT NULL,
  at                 timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX lead_outcome_lead_idx ON lead_outcome (lead_id, at DESC);
-- lge/ops/report.py's attribution query looks up each lead's most recent
-- won/lost outcome -- narrow the index to exactly the rows that query scans.
CREATE INDEX lead_outcome_won_lost_idx ON lead_outcome (lead_id, at DESC)
  WHERE action IN ('won', 'lost');

CREATE OR REPLACE FUNCTION trg_fn_lead_outcome_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION
    'lead_outcome.id=% -- append-only, never updated or deleted (attribution history)', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_lead_outcome_no_update
  BEFORE UPDATE ON lead_outcome
  FOR EACH ROW EXECUTE FUNCTION trg_fn_lead_outcome_append_only();

CREATE TRIGGER trg_lead_outcome_no_delete
  BEFORE DELETE ON lead_outcome
  FOR EACH ROW EXECUTE FUNCTION trg_fn_lead_outcome_append_only();

-- =============================================================================
-- handcheck_result -- gate G2. One row per (firm, attribute) reviewed; a
-- later review overwrites (ON CONFLICT / upsert semantics via PK), since a
-- reviewer correcting their own prior verdict is a re-review, not a new fact
-- -- unlike lead_outcome/signal, there is no "history of what we once
-- believed" value here worth keeping.
-- =============================================================================

CREATE TABLE handcheck_result (
  firm_id         uuid REFERENCES firm,
  attr            text,
  correct         bool NOT NULL,
  corrected_value text,
  reviewer        text NOT NULL DEFAULT 'ui',
  at              timestamptz DEFAULT now(),
  PRIMARY KEY (firm_id, attr)
);

-- =============================================================================
-- review_decision -- the audit of every review-queue decision (conflicts,
-- identity, agency, discovery -- plan/ui-plan.md's Review screens). `queue` +
-- `item_id` identify what was decided; `item_id` is text because the four
-- queues key on different underlying types (reconcile_conflict.id,
-- identity_review.id, raw_posting_id, discovery_lead.id).
-- =============================================================================

CREATE TABLE review_decision (
  id       bigserial PRIMARY KEY,
  queue    text,
  item_id  text,
  decision text,
  reviewer text,
  note     text,
  at       timestamptz DEFAULT now()
);

CREATE INDEX review_decision_queue_item_idx ON review_decision (queue, item_id);

-- =============================================================================
-- Read-path indexes -- GET /api/leads (STRIKE/SEQUENCE/NURTURE/PHONE/EXCLUDED/
-- UNSCORED views), each filtered on `lead.closed_at IS NULL` first. 22,182
-- firms today, one open lead each -- these keep every view's query an index
-- scan instead of a sequential scan of the whole open-lead set, and give the
-- "intent desc, contest asc, fit desc" ordering contract/api-contract.md
-- specifies a narrow set of rows to sort in memory rather than the whole table.
-- =============================================================================

CREATE INDEX lead_open_band_idx
  ON lead (band, intent_score DESC NULLS LAST, fit_score DESC NULLS LAST, id)
  WHERE closed_at IS NULL;

CREATE INDEX lead_open_grade_idx
  ON lead (grade, intent_score DESC NULLS LAST, fit_score DESC NULLS LAST, id)
  WHERE closed_at IS NULL;

-- lead has no non-unique index on firm_id at all (only the I1 partial unique
-- index keyed on firm_id WHERE closed_at IS NULL) -- GET /api/firms/{id} needs
-- to find a firm's lead (open OR closed) without a sequential scan.
CREATE INDEX lead_firm_id_idx ON lead (firm_id);

-- GET /api/firms?q= -- name/domain substring search over the full universe.
CREATE INDEX firm_canonical_name_trgm_idx ON firm USING gin (canonical_name gin_trgm_ops);
CREATE INDEX firm_domain_trgm_idx ON firm USING gin (domain gin_trgm_ops);

GRANT SELECT, INSERT ON lead_outcome TO lge_app;
REVOKE UPDATE, DELETE ON lead_outcome FROM lge_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON handcheck_result, review_decision TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
