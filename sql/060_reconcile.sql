-- 060_reconcile.sql -- attribute-reconciliation support tables. Owned by
-- lge/score/reconcile.py (context/30-data-model/04-attribute-reconciliation.md).
--
-- reconcile_conflict: an open row (resolved_at IS NULL) is the P9 escalation
-- queue itself -- "emit reconcile_conflict, set NULL, queue P9" is exactly
-- the INSERT below, no separate queue table needed. The partial unique index
-- keeps at most one OPEN conflict per (firm_id, attr); a later run that
-- resolves it sets resolved_at rather than deleting the row, so the history
-- of what was ever ambiguous survives.
CREATE TABLE reconcile_conflict (
  id          bigserial PRIMARY KEY,
  firm_id     uuid NOT NULL REFERENCES firm,
  attr        text NOT NULL,
  claims      jsonb NOT NULL,
  reason      text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);

CREATE UNIQUE INDEX reconcile_conflict_open_uidx
  ON reconcile_conflict (firm_id, attr) WHERE resolved_at IS NULL;

CREATE INDEX reconcile_conflict_firm_idx ON reconcile_conflict (firm_id);

-- firm_attr_state: per-(firm,attr) staleness bookkeeping. Written by the
-- single-firm reconcile(conn, firm_id, attr) path (used directly by tests
-- and by anything that needs one firm's attribute reconciled on demand);
-- the bulk `reconcile` component intentionally does NOT maintain this table
-- per-attribute for 37k firms every run (it would be ~800k upserts a night
-- for no consumer yet) -- it is the hook a future freshness sweep (W7,
-- ">20% of pool past 90d freshness") reads, not a hot path today.
CREATE TABLE firm_attr_state (
  firm_id       uuid NOT NULL REFERENCES firm,
  attr          text NOT NULL,
  stale         bool NOT NULL DEFAULT false,
  reconciled_at timestamptz,
  PRIMARY KEY (firm_id, attr)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON reconcile_conflict, firm_attr_state TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
