-- 103: the Google Business Profile lookup is its own kind of search (D-062).
--
-- r_listing asks the listings provider (Google's Places API, or Serper's
-- /places + /reviews) for the firm's listing and its reviews, and logs the
-- lookup here once per firm like every other search: `engine` names the
-- provider, `url` the Maps listing adopted, `rating` / `review_count` what
-- it said, and `results` the listing and the reviews as they came back --
-- so a later rule re-derives from the stored answer, never from a new call.
-- r_search_links skips its snippet query for reviews while a listing row
-- is fresh.

ALTER TABLE search_log DROP CONSTRAINT search_log_kind_check;
ALTER TABLE search_log ADD CONSTRAINT search_log_kind_check
  CHECK (kind IN ('linkedin', 'reviews', 'emails', 'person_email', 'company', 'sweep',
                  'listing'));
