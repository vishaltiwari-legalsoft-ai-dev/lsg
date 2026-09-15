-- 098: the user can act (D-036).
--
-- Until now the interface only showed what the engine did. This migration
-- gives it hands: on-demand research jobs per firm, notes and an owner on a
-- lead, contacts a person added or struck out, and the lifecycle transitions
-- a human decision is allowed to make.

-- ---- research jobs --------------------------------------------------------
CREATE TABLE action_job (
  id           uuid PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('research', 'find_contacts')),
  firm_id      uuid NOT NULL REFERENCES firm,
  lead_id      uuid REFERENCES lead,
  requested_by text NOT NULL DEFAULT 'ui',
  status       text NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued', 'running', 'done', 'failed')),
  steps        jsonb NOT NULL DEFAULT '[]',   -- [{name, status, note}]
  error        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz
);

CREATE INDEX action_job_firm_idx ON action_job (firm_id, created_at DESC);

-- ---- notes and ownership --------------------------------------------------
CREATE TABLE lead_note (
  id       bigserial PRIMARY KEY,
  lead_id  uuid NOT NULL REFERENCES lead,
  text     text NOT NULL,
  actor    text NOT NULL DEFAULT 'ui',
  at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX lead_note_lead_idx ON lead_note (lead_id, at DESC);

ALTER TABLE lead ADD COLUMN owner text;

-- ---- contacts a person edits ---------------------------------------------
-- A wrong person is struck out, not deleted: the row keeps r_site_contacts
-- from re-adding the same name from the same page, and the history stays.
ALTER TABLE contact ADD COLUMN removed_at     timestamptz;
ALTER TABLE contact ADD COLUMN removed_reason text;
ALTER TABLE contact ADD COLUMN edited_at      timestamptz;

-- ---- transitions a human decision may make ---------------------------------
-- The engine's own transitions stay as they were (I5's whitelist trigger);
-- these are the ones a person needs from the screen: disqualify from any
-- working state, reopen a disqualification, qualify on their own judgement
-- (grade B until an email is verified), hand a warm lead to sales, and send a
-- stale record back for research.
INSERT INTO lead_transition (from_state, to_state)
SELECT f, t FROM (VALUES
  ('DISCOVERED', 'DISQUALIFIED'), ('PROFILING', 'DISQUALIFIED'), ('NO_WEB', 'DISQUALIFIED'),
  ('PROFILED', 'DISQUALIFIED'), ('ESCALATED', 'DISQUALIFIED'),
  ('CONTACT_PENDING', 'DISQUALIFIED'), ('RESOLVED', 'DISQUALIFIED'),
  ('QUALIFIED_A', 'DISQUALIFIED'), ('QUALIFIED_B', 'DISQUALIFIED'),
  ('ARMED', 'DISQUALIFIED'), ('STALE', 'DISQUALIFIED'),
  ('DISQUALIFIED', 'CLASSIFIED'),
  ('CLASSIFIED', 'QUALIFIED_A'), ('CLASSIFIED', 'QUALIFIED_B'),
  ('CONTACT_PENDING', 'QUALIFIED_A'), ('CONTACT_PENDING', 'QUALIFIED_B'),
  ('QUALIFIED_A', 'HANDOFF'), ('QUALIFIED_B', 'HANDOFF'),
  ('ARMED', 'HANDOFF'), ('ENGAGED', 'HANDOFF'),
  ('STALE', 'PROFILING')
) AS v(f, t)
WHERE NOT EXISTS (
  SELECT 1 FROM lead_transition x WHERE x.from_state = v.f AND x.to_state = v.t
);
