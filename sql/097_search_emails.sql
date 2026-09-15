-- 097: two more kinds of web search (D-035).
--
-- r_search_emails asks DuckDuckGo where a firm's addresses are printed
-- ("@<domain>": directories, bar listings, filings) and, for each
-- decision-maker without an address, "<person>" "<firm>" email. Both are
-- logged in search_log like the LinkedIn and reviews queries.

ALTER TABLE search_log DROP CONSTRAINT search_log_kind_check;
ALTER TABLE search_log ADD CONSTRAINT search_log_kind_check
  CHECK (kind IN ('linkedin', 'reviews', 'emails', 'person_email'));
