-- 099: what the search result says about a LinkedIn profile (D-038).
--
-- The profile page is never fetched. The search engine's own snippet for a
-- linkedin.com/in/ result carries the headline ("Partner at Freehill Hogan &
-- Mahar"), the location and the company; that is kept on the contact. The
-- firm's LinkedIn company page is found the same way.

ALTER TABLE contact ADD COLUMN linkedin_headline text;
ALTER TABLE contact ADD COLUMN linkedin_location text;

ALTER TABLE search_log DROP CONSTRAINT search_log_kind_check;
ALTER TABLE search_log ADD CONSTRAINT search_log_kind_check
  CHECK (kind IN ('linkedin', 'reviews', 'emails', 'person_email', 'company'));
