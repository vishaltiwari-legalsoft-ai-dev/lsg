-- 002_functions.sql
-- Deterministic scoring/classification functions. Every function that reads
-- wall-clock time takes an explicit `at timestamptz` so tests are
-- reproducible, plus a convenience overload defaulting to now().

-- =============================================================================
-- icp_tier -- context/10-icp/05-tiers-and-wedge-skus.md, verbatim CASE.
--
-- Deviation: declared STABLE, not IMMUTABLE. The spec's own listing marks it
-- IMMUTABLE, but the two-argument form below evaluates `now()` through its
-- single-argument wrapper, and a function that reads the clock cannot be
-- IMMUTABLE (Postgres would be entitled to constant-fold it). STABLE is the
-- correct, honest label: same result within one statement, changes only as
-- wall-clock time passes. Evaluation order matters and is preserved exactly:
-- hard disqualifiers first, then fee_model gates before practice_area.
-- =============================================================================

CREATE OR REPLACE FUNCTION icp_tier(f firm, at timestamptz) RETURNS text AS $$
  SELECT CASE
    -- hard disqualifiers, evaluated first
    WHEN f.entity_kind <> 'private_firm'                    THEN 'DQ_ENTITY'
    WHEN f.country <> 'US'                                  THEN 'DQ_GEO'
    WHEN f.attorney_count > 50                              THEN 'DQ_SIZE'
    WHEN f.has_inhouse_recruiter                            THEN 'DQ_SELFSERVE'
    -- no delegable procedural volume -- fails need condition 1
    WHEN f.primary_practice IN ('appellate', 'patent_prosecution',
                                 'complex_commercial')       THEN 'DQ_NOVOLUME'
    WHEN f.first_seen_bar_admission > at - interval '24 months'
         AND f.attorney_count = 1
         AND NOT f.paid_ads_active                          THEN 'DQ_NOBUDGET'

    -- tiers. fee_model gates before practice_area is consulted.
    WHEN f.fee_model IN ('contingency', 'fee_shifting')
         AND f.primary_practice IN ('personal_injury', 'mass_tort')       THEN '1A'

    WHEN f.fee_model = 'flat'
         AND f.primary_practice = 'immigration'                          THEN '1B'

    WHEN f.fee_model IN ('contingency', 'fee_shifting')
         AND f.primary_practice IN ('employment', 'lemon_law',
                                     'workers_comp', 'ssdi', 'consumer')   THEN '2'

    WHEN f.fee_model = 'flat'
         AND f.primary_practice IN ('bankruptcy', 'criminal',
                                     'estate', 'family')                  THEN '3'

    -- hourly firms: only non-billable SKUs are sellable. narrow, not excluded.
    WHEN f.fee_model = 'hourly'                                          THEN '4_NONBILLABLE'

    ELSE 'UNCLASSIFIED'  -- routes to P9 escalation, never to outreach
  END
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION icp_tier(f firm) RETURNS text AS $$
  SELECT icp_tier(f, now());
$$ LANGUAGE sql STABLE;

-- =============================================================================
-- decay -- context/40-pipeline/04-scoring-engine.md
-- =============================================================================

CREATE OR REPLACE FUNCTION decay(days numeric) RETURNS numeric AS $$
  SELECT CASE
    WHEN days <= 7  THEN 1.00
    WHEN days <= 30 THEN 0.70
    WHEN days <= 90 THEN 0.35
    ELSE 0
  END
$$ LANGUAGE sql IMMUTABLE;

-- =============================================================================
-- signal_weight -- weight is derived at score time, never stored on the row.
-- =============================================================================

CREATE OR REPLACE FUNCTION signal_weight(
  kind text, first_seen timestamptz, closed_at timestamptz, repost_count int, at timestamptz
) RETURNS int AS $$
  SELECT CASE
    WHEN kind = 'job_posting_open' THEN
      CASE
        WHEN closed_at IS NOT NULL           THEN 0
        WHEN repost_count >= 2                THEN 48
        WHEN repost_count >= 1                THEN 44
        WHEN at - first_seen > interval '21 days' THEN 40   -- hiring has failed
        WHEN at - first_seen > interval '7 days'  THEN 34
        ELSE                                       30
      END
    WHEN kind = 'partner_intro'          THEN 35
    WHEN kind = 'pricing_page_visit'     THEN 25
    WHEN kind = 'review_unreturned_call' THEN 15
    WHEN kind = 'multi_opening'          THEN 10
    WHEN kind = 'paid_ads_spike'         THEN 10
    WHEN kind = 'mass_tort_campaign'     THEN 10
    WHEN kind = 'new_office_or_lateral'  THEN 8
    WHEN kind = 'cms_implemented'        THEN 8
    ELSE 0
  END
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION signal_weight(
  kind text, first_seen timestamptz, closed_at timestamptz, repost_count int
) RETURNS int AS $$
  SELECT signal_weight(kind, first_seen, closed_at, repost_count, now());
$$ LANGUAGE sql STABLE;

-- =============================================================================
-- contest_level / contest_rank -- a routing input, never folded into a score.
-- Unknown kinds are treated as contested (HIGH) -- conservative default.
-- =============================================================================

CREATE OR REPLACE FUNCTION contest_level(kind text) RETURNS text AS $$
  SELECT CASE kind
    WHEN 'job_posting_open'       THEN 'HIGH'
    WHEN 'paid_ads_spike'         THEN 'HIGH'
    WHEN 'mass_tort_campaign'     THEN 'MED'
    WHEN 'multi_opening'          THEN 'MED'
    WHEN 'new_office_or_lateral'  THEN 'MED'
    WHEN 'review_unreturned_call' THEN 'LOW'
    WHEN 'cms_implemented'        THEN 'LOW'
    WHEN 'partner_intro'          THEN 'NONE'
    WHEN 'pricing_page_visit'     THEN 'NONE'
    ELSE 'HIGH'
  END
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION contest_rank(level text) RETURNS int AS $$
  SELECT CASE level
    WHEN 'NONE' THEN 0
    WHEN 'LOW'  THEN 1
    WHEN 'MED'  THEN 2
    WHEN 'HIGH' THEN 3
  END
$$ LANGUAGE sql IMMUTABLE;

-- =============================================================================
-- fit_score -- pure function of firm attributes, 0..50, recomputed on
-- attribute change. Clamped: the spec defines fit as 0..50 but the raw sum
-- of every term can exceed 50 (or, with only the 26-50 attorney penalty and
-- nothing else, go negative). NULL inputs contribute nothing -- each term's
-- CASE falls through to its ELSE 0 when the underlying column is NULL.
-- =============================================================================

CREATE OR REPLACE FUNCTION fit_score(f firm) RETURNS int AS $$
  SELECT GREATEST(0, LEAST(50,
      CASE WHEN f.fee_model IN ('contingency', 'fee_shifting', 'flat') THEN 15 ELSE 0 END
    + CASE f.tier
        WHEN '1A' THEN 10
        WHEN '1B' THEN 8
        WHEN '2'  THEN 8
        WHEN '3'  THEN 5
        ELSE 0
      END
    + CASE
        WHEN f.attorney_count BETWEEN 2 AND 12  THEN 12
        WHEN f.attorney_count BETWEEN 13 AND 25 THEN 8
        WHEN f.attorney_count = 1               THEN 5
        WHEN f.attorney_count BETWEEN 26 AND 50 THEN -10   -- penalise, not disqualify
        ELSE 0
      END
    + CASE WHEN f.country = 'US'        THEN 6 ELSE 0 END
    + CASE WHEN f.review_count > 40     THEN 4 ELSE 0 END   -- case-volume proxy
    + CASE WHEN f.staff_ratio < 1.0     THEN 4 ELSE 0 END   -- understaffed
    + CASE WHEN f.paid_ads_active       THEN 3 ELSE 0 END   -- cash stability
    + CASE WHEN f.spanish_intake        THEN 5 ELSE 0 END
    + CASE WHEN f.has_hired_support_roles  THEN 5 ELSE 0 END
    + CASE WHEN f.repeat_role_count >= 2   THEN 8 ELSE 0 END  -- chronic need, strongest of the four
  ))::int
$$ LANGUAGE sql IMMUTABLE;

-- =============================================================================
-- intent_score -- windowed aggregation over signal, 0..50, nightly full scan.
-- =============================================================================

CREATE OR REPLACE FUNCTION intent_score(firm_id uuid, at timestamptz) RETURNS int AS $$
  SELECT LEAST(50, COALESCE(ROUND(SUM(
    signal_weight(s.kind, s.first_seen, s.closed_at, s.repost_count, $2)
    * decay(EXTRACT(EPOCH FROM ($2 - s.last_seen)) / 86400.0)
  )), 0))::int
  FROM signal s
  WHERE s.firm_id = $1
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION intent_score(firm_id uuid) RETURNS int AS $$
  SELECT intent_score($1, now());
$$ LANGUAGE sql STABLE;

-- =============================================================================
-- routing_band -- STRIKE is the only band that consumes a person.
-- =============================================================================

CREATE OR REPLACE FUNCTION routing_band(fit int, intent int, contest text) RETURNS text AS $$
  SELECT CASE
    WHEN fit + intent >= 80 AND contest_rank(contest) <= contest_rank('MED') THEN 'STRIKE'
    WHEN fit + intent >= 80 THEN 'SEQUENCE'
    WHEN fit + intent >= 60 THEN 'SEQUENCE'
    WHEN fit + intent >= 40 THEN 'NURTURE'
    ELSE 'HOLD'
  END
$$ LANGUAGE sql IMMUTABLE;

-- =============================================================================
-- arming_threshold -- supply-derived, not fixed. A deep bench lowers the
-- bar; an empty bench with no replenishment pipeline puts it out of reach.
-- =============================================================================

CREATE OR REPLACE FUNCTION arming_threshold(available int, replenish_30d int) RETURNS numeric AS $$
  SELECT 60 - LEAST(15, available * 1.5)
       + CASE WHEN available = 0 AND replenish_30d = 0 THEN 999 ELSE 0 END
$$ LANGUAGE sql IMMUTABLE;

-- =============================================================================
-- wedge_sku -- lookup, not logic. context/10-icp/05-tiers-and-wedge-skus.md
-- =============================================================================

CREATE OR REPLACE FUNCTION wedge_sku(tier text) RETURNS text AS $$
  SELECT wedge_sku FROM tier_wedge_sku WHERE tier = $1
$$ LANGUAGE sql STABLE;
