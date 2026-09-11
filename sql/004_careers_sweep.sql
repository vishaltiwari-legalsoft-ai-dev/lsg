-- 004 — careers-page sweep log. Shared: JA1 writes it, JA6 closure detection reads it.
--
-- Closure needs to tell "fetched successfully and the posting was absent" apart from
-- "the fetch failed". Both look identical as "nothing found", and conflating them lets
-- one bad night silently close thousands of live signals. raw_posting can only record
-- postings that WERE found, so every sweep of a careers page — including ones that
-- find nothing and ones that fail — gets a row here.
CREATE TABLE careers_sweep (
  id             bigserial PRIMARY KEY,
  firm_id        uuid NOT NULL REFERENCES firm,
  url            text NOT NULL,
  swept_at       timestamptz NOT NULL DEFAULT now(),
  fetch_ok       bool NOT NULL,        -- false = timeout / 403 / 429 / parser crash
  status_code    int,
  postings_found int,                  -- null when fetch_ok is false
  content_hash   text,                 -- unchanged hash → parse skipped
  parse_method   text                  -- jsonld | microdata | ats_embed | html | none
);
CREATE INDEX careers_sweep_firm_idx ON careers_sweep (firm_id, swept_at DESC);

GRANT SELECT, INSERT ON careers_sweep TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
