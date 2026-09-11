-- 020_identity.sql
--
-- identity_review: the queue for pairs resolve_identity refuses to
-- auto-merge -- R4 candidates (same zip5, name_stem similarity above
-- threshold, no stronger R1-R3 evidence already connecting them) and
-- components that span >=2 EXISTING firms under R1-R3 evidence
-- ("cross_firm_component", rule='cross_firm').
--
-- See context/30-data-model/03-identity-resolution.md:
--   "R4 never auto-merges. A false merge is invisible and unrecoverable;
--    a false split is visible and costs one duplicate. The asymmetry is
--    the whole design."
--
-- Owned by lge/resolve/identity.py. Reserved migration number per the task
-- brief -- written in one complete pass.

CREATE TABLE identity_review (
  id                   bigserial PRIMARY KEY,
  rule                 text NOT NULL,
  reason               text,
  left_observation_id  bigint REFERENCES observation,
  right_observation_id bigint REFERENCES observation,
  left_firm_id         uuid REFERENCES firm,
  right_firm_id        uuid REFERENCES firm,
  similarity           real,
  status               text NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'merged', 'rejected')),
  created_at           timestamptz NOT NULL DEFAULT now()
);

-- Queue-size query in the gate, and the operator's worklist, both filter on
-- status.
CREATE INDEX identity_review_status_idx ON identity_review (status);

-- Idempotency guards in resolve_identity: before writing a new review row,
-- it checks whether one already exists (open) for the same observation pair
-- (rule='R4') or the same firm pair (rule='cross_firm'), so a re-run over
-- unchanged data never grows the queue.
CREATE INDEX identity_review_obs_idx
  ON identity_review (left_observation_id, right_observation_id);
CREATE INDEX identity_review_firm_idx
  ON identity_review (left_firm_id, right_firm_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON identity_review TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
