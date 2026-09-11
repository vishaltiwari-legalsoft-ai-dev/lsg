-- 030_profile.sql — profile-plane additions owned by the P1-P4/JA1 builder.
-- Everything else P1-P4 and JA1 write to (document, document_text,
-- raw_posting, careers_sweep, source_registry) already exists from
-- 001/003/004 — this file adds only what those didn't already cover.

-- ── P1: the URL set discovered per firm before P2 fetches anything ─────────
CREATE TABLE site_map (
  firm_id        uuid NOT NULL REFERENCES firm,
  url            text NOT NULL,
  page_kind      text NOT NULL CHECK (page_kind IN (
                   'home','about','attorneys','team','practice','contact',
                   'careers','fees','other')),
  discovered_via text NOT NULL CHECK (discovered_via IN ('sitemap','probe','link')),
  discovered_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (firm_id, url)
);
CREATE INDEX site_map_firm_kind_idx ON site_map (firm_id, page_kind);

-- ── P3: which documents the render gate selected ────────────────────────────
-- The gate fires when a page's static main text is under 500 words
-- (document.word_count, written by P2). This flags what P3 decided NEEDS
-- rendering; `document.rendered` (already in 001_schema.sql) records
-- whether a render actually completed. Playwright is not installed in this
-- environment, so most rows here stay render_needed=true, rendered=false —
-- see lge/planes/p/p3_render.py for the "render unavailable" reporting path.
ALTER TABLE document ADD COLUMN render_needed bool NOT NULL DEFAULT false;

GRANT SELECT, INSERT, UPDATE, DELETE ON site_map TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
