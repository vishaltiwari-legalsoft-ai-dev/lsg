-- 095: the record of every web search made on a firm's behalf (D-032).
--
-- r_search_links asks DuckDuckGo two things: where a named person's LinkedIn
-- profile is ("<firm>" "<person>" linkedin) and what Google says about the
-- firm ("<firm>" <city> <state> google business reviews). Each query is
-- logged once with what came back, so a person or firm is not searched again
-- for `recheck_days`, and the URL adopted onto contact.linkedin_url or the
-- review claims can always be traced to the result that produced it.
-- LinkedIn is never fetched -- only the URL of the profile is kept.

CREATE TABLE search_log (
  id            bigserial PRIMARY KEY,
  firm_id       uuid NOT NULL REFERENCES firm,
  kind          text NOT NULL CHECK (kind IN ('linkedin', 'reviews')),
  contact_id    uuid REFERENCES contact,      -- the person, for kind = 'linkedin'
  query         text NOT NULL,
  outcome       text NOT NULL CHECK (outcome IN ('found', 'not_found', 'failed')),
  url           text,                         -- the profile or listing adopted
  rating        numeric,                      -- kind = 'reviews': what the snippets said
  review_count  int,
  results       jsonb,                        -- the results considered (title, href, body)
  searched_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX search_log_firm_idx ON search_log (firm_id, kind, searched_at DESC);
CREATE INDEX search_log_contact_idx ON search_log (contact_id, searched_at DESC)
  WHERE contact_id IS NOT NULL;
