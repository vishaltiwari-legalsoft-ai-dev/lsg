-- 040_job_signals.sql
-- Owned by JA6 (normaliser) / I2 (job-history loader). One complete write.

-- ─── rung 4: ATS slug -> firm, built once and reused ─────────────────────────
CREATE TABLE ats_slug_map (
  ats     text NOT NULL,   -- 'greenhouse', 'lever', ... (raw_posting.source minus
                            -- the 'ats:' prefix)
  slug    text NOT NULL,    -- e.g. 'smithlaw' in boards.greenhouse.io/smithlaw
  firm_id uuid NOT NULL REFERENCES firm,
  PRIMARY KEY (ats, slug)
);

-- ─── rung 6 "otherwise" / rung 7: an unmatched posting may name a firm not yet
-- in the universe -- context/20-signals/03-agency-filter-and-resolution.md,
-- "An unmatched posting is still worth keeping". One row per raw_posting: JA6 is
-- a pure recompute over what's on disk, so a later run that DOES resolve the
-- posting (a new firm entered the universe, or a threshold moved) deletes this
-- row rather than leaving a stale lead behind -- see ja6_resolve.py.
CREATE TABLE discovery_lead (
  id             bigserial PRIMARY KEY,
  company_name   text,
  city           text,
  state          char(2),
  source         text,
  raw_posting_id bigint NOT NULL REFERENCES raw_posting,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (raw_posting_id)
);
CREATE INDEX discovery_lead_company_idx ON discovery_lead (lower(company_name));

-- ─── the resolution ladder's verdict for every posting that passed the agency +
-- support-role filter, whichever rung it landed on (or failed at). Audit trail:
-- rung 0 = firm_id already set at fetch (careers page), 1-6 = the ladder in
-- context/20-signals/03-agency-filter-and-resolution.md, 7 = no usable city.
-- Upserted every run -- a firm added to the universe between two JA6 runs can
-- turn last run's rung-6/7 miss into a rung-6 hit on this run without touching
-- raw_posting.
CREATE TABLE posting_resolution (
  raw_posting_id bigint PRIMARY KEY REFERENCES raw_posting,
  firm_id        uuid REFERENCES firm,
  rung           int NOT NULL,
  confidence     real NOT NULL,
  detail         text
);
CREATE INDEX posting_resolution_firm_idx ON posting_resolution (firm_id);

-- ─── dedupe guard for JA6's signal_sighting appends (context/20-signals/
-- 04-dedupe-dates-and-closure.md: "Append one signal_sighting per contributing
-- raw_posting ... dedupe so re-runs don't append duplicates"). Partial on
-- raw_posting_id IS NOT NULL so ja6_closure's own present=false sightings, which
-- have no single contributing raw_posting, are never constrained by it.
CREATE UNIQUE INDEX signal_sighting_signal_raw_posting_uidx
  ON signal_sighting (signal_id, raw_posting_id) WHERE raw_posting_id IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON ats_slug_map, discovery_lead, posting_resolution
  TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
