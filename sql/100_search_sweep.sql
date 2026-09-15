-- 100: one search per firm finds its people's LinkedIn profiles (D-041).
-- search_log.kind 'sweep' is the firm-level `site:linkedin.com "<firm>"`
-- query; each person it matches still gets a 'linkedin' row (contact_id,
-- found) so the person is not asked about again for the recheck window.

ALTER TABLE search_log DROP CONSTRAINT search_log_kind_check;
ALTER TABLE search_log ADD CONSTRAINT search_log_kind_check
  CHECK (kind IN ('linkedin', 'reviews', 'emails', 'person_email', 'company', 'sweep'));
