-- 094: what a fetch was, on the document row itself (D-030).
--
-- fetch_error -- why a fetch produced no page (the fetcher's own words: a
--   timeout, a robots rule, a host stopped this run, a slow-host budget).
--   Until now a failed fetch was a row with fetch_ok=false and no reason.
-- soft_404 -- a 200 whose content is an error page. Every reader skips
--   these; before, only the careers watcher knew.
-- discovered_via on site_map already says where a URL came from; 'crawl' is
--   the new value for links the fetcher found on pages it read.

ALTER TABLE document ADD COLUMN fetch_error text;
ALTER TABLE document ADD COLUMN soft_404 bool NOT NULL DEFAULT false;

-- Three more kinds of page worth reading, and a fourth way to have found one.
ALTER TABLE document DROP CONSTRAINT document_page_kind_check;
ALTER TABLE document ADD CONSTRAINT document_page_kind_check
  CHECK (page_kind IN ('home','about','attorneys','team','practice','contact',
                       'careers','fees','locations','testimonials','news','other'));

ALTER TABLE site_map DROP CONSTRAINT site_map_page_kind_check;
ALTER TABLE site_map ADD CONSTRAINT site_map_page_kind_check
  CHECK (page_kind IN ('home','about','attorneys','team','practice','contact',
                       'careers','fees','locations','testimonials','news','other'));

ALTER TABLE site_map DROP CONSTRAINT site_map_discovered_via_check;
ALTER TABLE site_map ADD CONSTRAINT site_map_discovered_via_check
  CHECK (discovered_via IN ('sitemap','probe','link','crawl'));
