-- 003 — tables shared by more than one plane. Owned by the controller so parallel
-- builders (profile, job acquisition, job normaliser, job-history loader) code
-- against one definition instead of racing to create it.

-- ─── profile plane: which page a document is ─────────────────────────────────
-- P1 decides the kind from the URL before fetching; P4-P8 select pages by it.
ALTER TABLE document ADD COLUMN page_kind text
  CHECK (page_kind IN ('home','about','attorneys','team','practice','contact',
                       'careers','fees','other'));
CREATE INDEX document_firm_kind_idx ON document (firm_id, page_kind);

-- P4 output, persisted: no component reads another component's output directly,
-- everything is mediated by the store. P5-P8 read main_text from here.
CREATE TABLE document_text (
  document_id  bigint PRIMARY KEY REFERENCES document,
  main_text    text,
  word_count   int,
  extractor    text NOT NULL,          -- e.g. 'trafilatura:2.0' — re-runnable on bump
  extracted_at timestamptz NOT NULL DEFAULT now()
);

-- ─── job acquisition lanes → one normaliser ──────────────────────────────────
-- Every acquisition component (JA1 careers, JA2 bar boards, JA3 ATS, JA4 licensed,
-- JA5 SERP) and the I2 job-history loader write here. JA6 is a pure function over
-- these rows, so blocklist / synonym / resolution changes are a re-run over what is
-- already on disk, never a re-crawl.
CREATE TABLE raw_posting (
  id                bigserial PRIMARY KEY,
  source            text NOT NULL,      -- careers | bar_board:<host> | ats:greenhouse |
                                        -- ats:lever | craigslist | licensed:<vendor> |
                                        -- serp | internal_jobs
  source_key        text NOT NULL,      -- stable per-source id (url, ATS job id, file row key)
  source_url        text,               -- null for internal_jobs (the file has no links)
  firm_id           uuid REFERENCES firm,  -- known at fetch for careers pages; else set by JA6
  company_name      text,
  title             text NOT NULL,
  location_raw      text,
  city              text,
  state             char(2),
  metro_code        text,               -- CBSA, not a raw city string
  body              text,               -- the FULL body. Apply emails, outbound links and
                                        -- phones in the text are rungs 1-3 of the resolution
                                        -- ladder; structured fields alone lose them.
  apply_email       text,
  outbound_links    text[],
  phone_raw         text,
  ats_slug          text,
  employment_type   text,
  board_posted_date date,               -- what the board claims. UNTRUSTED — stored only
  first_published   timestamptz,        -- ATS-supplied (Greenhouse): trusted for reposts
  updated_at_src    timestamptz,        -- ATS-supplied updated_at
  fetch_ok          bool NOT NULL DEFAULT true,  -- fetch failed ≠ posting absent (closure)
  content_hash      text,
  payload           jsonb NOT NULL DEFAULT '{}',
  fetched_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, source_key, fetched_at)
);
CREATE INDEX raw_posting_firm_idx    ON raw_posting (firm_id);
CREATE INDEX raw_posting_company_idx ON raw_posting (lower(company_name));
CREATE INDEX raw_posting_fetched_idx ON raw_posting (fetched_at);

-- Agency-filter and resolution rejects are KEPT with the rule that fired. The reject
-- stream is how the agency blocklist gets extended, and a spike in
-- geographic_spread usually means a new agency appeared, not that the market moved.
CREATE TABLE job_posting_rejected (
  raw_posting_id bigint PRIMARY KEY REFERENCES raw_posting,
  rule           text NOT NULL CHECK (rule IN (
                   'known_agency','client_language','geographic_spread','volume',
                   'blind_posting','name_only','not_support_role','unresolved')),
  detail         text,
  rejected_at    timestamptz NOT NULL DEFAULT now()
);

-- Which raw posting a sighting came from. Adding a column does not touch existing
-- rows, so signal_sighting stays append-only (I6).
ALTER TABLE signal_sighting ADD COLUMN raw_posting_id bigint REFERENCES raw_posting;

GRANT SELECT, INSERT, UPDATE, DELETE ON document_text, raw_posting, job_posting_rejected
  TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
