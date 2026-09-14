-- 093: ingest -- any sheet, in batches, with a website check (D-029).
--
-- The purchased list was loaded by a loader that knew its column names. Real
-- inputs are whatever the team has; each one is an import_file with the column
-- map a person confirmed, split into import_batch rows processed one at a
-- time. observation rows remember which import and batch they came from.
-- website_check records, per firm, whether the site the sheet gave is real,
-- and what the search found when it was not.

CREATE TABLE import_file (
  id          uuid PRIMARY KEY,
  file_name   text NOT NULL,
  stored_path text NOT NULL,
  sha256      text NOT NULL UNIQUE,
  format      text NOT NULL CHECK (format IN ('csv', 'xlsx')),
  row_count   int  NOT NULL,
  source_tag  text NOT NULL DEFAULT 'internal_firms',
  column_map  jsonb NOT NULL,
  missing     text[] NOT NULL DEFAULT '{}',   -- mandatory groups the sheet lacks
  batch_size  int  NOT NULL,
  status      text NOT NULL CHECK (status IN ('mapped', 'loading', 'loaded', 'failed')),
  health      jsonb,                          -- whole-file assessment at mapping time
  notes       jsonb NOT NULL DEFAULT '[]',
  created_at  timestamptz NOT NULL DEFAULT now(),
  loaded_at   timestamptz
);

CREATE TABLE import_batch (
  id           bigserial PRIMARY KEY,
  import_id    uuid NOT NULL REFERENCES import_file,
  batch_no     int  NOT NULL,
  row_start    int  NOT NULL,   -- 1-based, inclusive
  row_end      int  NOT NULL,
  status       text NOT NULL CHECK (status IN ('pending', 'loading', 'loaded', 'failed')),
  rows_loaded  int  NOT NULL DEFAULT 0,
  rows_skipped int  NOT NULL DEFAULT 0,
  health       jsonb,
  error        text,
  started_at   timestamptz,
  finished_at  timestamptz,
  UNIQUE (import_id, batch_no)
);

ALTER TABLE observation ADD COLUMN import_id uuid REFERENCES import_file;
ALTER TABLE observation ADD COLUMN batch_no  int;
CREATE INDEX observation_import_idx ON observation (import_id, batch_no);

CREATE TABLE website_check (
  id               bigserial PRIMARY KEY,
  firm_id          uuid NOT NULL REFERENCES firm,
  checked_at       timestamptz NOT NULL DEFAULT now(),
  given            text,            -- the website as the sheet gave it
  domain           text,            -- the domain on the firm when checked
  outcome          text NOT NULL CHECK (outcome IN (
                     'ok',           -- answers, and the page is this firm
                     'missing',      -- the sheet gave no website
                     'malformed',    -- gave something, no usable domain in it
                     'dead',         -- does not resolve or does not answer
                     'blocked',      -- answers 403 at the edge
                     'mismatch',     -- answers, but the page is not this firm
                     'corrected',    -- a search found the real site
                     'unresolved'    -- searched, nothing convincing
                   )),
  http_status      int,
  title            text,
  name_match       numeric,         -- 0..1, firm-name tokens found on the page
  corrected_domain text,
  search_query     text,
  evidence         jsonb,
  note             text
);

CREATE INDEX website_check_firm_idx ON website_check (firm_id, checked_at DESC);
