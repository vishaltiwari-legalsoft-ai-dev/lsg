-- 005 — entity_kind gains 'nonprofit'.
--
-- The disqualifier table (context/10-icp/06) names "non-profit legal aid" as not a
-- private firm, but the spec's entity_kind vocabulary (private_firm | inhouse | gov |
-- directory_stub) had no value for it. The purchased vendor file contains legal-aid
-- organisations tagged as law practices (lanwt.org, arlegalaid.org). icp_tier() is
-- unchanged: anything <> 'private_firm' is DQ_ENTITY, so nonprofit disqualifies.
ALTER TABLE firm DROP CONSTRAINT firm_entity_kind_check;
ALTER TABLE firm ADD CONSTRAINT firm_entity_kind_check CHECK (
  entity_kind IS NULL OR entity_kind IN
    ('private_firm', 'inhouse', 'gov', 'nonprofit', 'directory_stub')
);
