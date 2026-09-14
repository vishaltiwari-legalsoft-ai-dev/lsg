-- 096: intent from pain the site and the search results reveal (D-033).
--
-- ja7_pain_signals writes three new signal kinds off px_site_facts' gap
-- list -- a firm with no way to capture a lead after hours, a firm whose
-- attorneys are listed with no support staff, a site nobody maintains --
-- and reuses review_unreturned_call (search snippets) and
-- new_office_or_lateral (the firm's own growth headlines).
--
-- A closed signal of ANY kind now weighs nothing: a gap the next crawl finds
-- filled is closed and must stop counting, the same way a filled job
-- posting does. (Only job_posting_open zeroed on closure before; a closed
-- multi_opening kept its 10.)

CREATE OR REPLACE FUNCTION signal_weight(
  kind text, first_seen timestamptz, closed_at timestamptz, repost_count int, at timestamptz
) RETURNS int AS $$
  SELECT CASE
    WHEN closed_at IS NOT NULL THEN 0
    WHEN kind = 'job_posting_open' THEN
      CASE
        WHEN repost_count >= 2                THEN 48
        WHEN repost_count >= 1                THEN 44
        WHEN at - first_seen > interval '21 days' THEN 40   -- hiring has failed
        WHEN at - first_seen > interval '7 days'  THEN 34
        ELSE                                       30
      END
    WHEN kind = 'partner_intro'            THEN 35
    WHEN kind = 'pricing_page_visit'       THEN 25
    WHEN kind = 'review_unreturned_call'   THEN 15
    WHEN kind = 'multi_opening'            THEN 10
    WHEN kind = 'paid_ads_spike'           THEN 10
    WHEN kind = 'mass_tort_campaign'       THEN 10
    WHEN kind = 'new_office_or_lateral'    THEN 8
    WHEN kind = 'cms_implemented'          THEN 8
    WHEN kind = 'no_support_staff_listed'  THEN 8
    WHEN kind = 'no_intake_channel'        THEN 6
    WHEN kind = 'stale_site'               THEN 4
    ELSE 0
  END
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION contest_level(kind text) RETURNS text AS $$
  SELECT CASE kind
    WHEN 'job_posting_open'        THEN 'HIGH'
    WHEN 'paid_ads_spike'          THEN 'HIGH'
    WHEN 'mass_tort_campaign'      THEN 'MED'
    WHEN 'multi_opening'           THEN 'MED'
    WHEN 'new_office_or_lateral'   THEN 'MED'
    WHEN 'review_unreturned_call'  THEN 'LOW'
    WHEN 'cms_implemented'         THEN 'LOW'
    WHEN 'no_support_staff_listed' THEN 'LOW'
    WHEN 'partner_intro'           THEN 'NONE'
    WHEN 'pricing_page_visit'      THEN 'NONE'
    WHEN 'no_intake_channel'       THEN 'NONE'
    WHEN 'stale_site'              THEN 'NONE'
    ELSE 'HIGH'
  END
$$ LANGUAGE sql IMMUTABLE;
