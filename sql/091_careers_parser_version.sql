-- 091 — careers_sweep records which parser version read the page.
--
-- JA1 skips re-parsing a careers page whose content hash is unchanged since the last
-- successful sweep. Without the parser version in that comparison, a PARSER fix changes
-- nothing for pages already swept: the probe found Dressie Law Firm's three open roles
-- (h3 headings under "Employment Opportunities") missed by the first heuristic, and the
-- corrected parser would have skipped the page as "unchanged". Same principle as
-- norm_version: a logic change is a re-parse, never silently ignored.
ALTER TABLE careers_sweep ADD COLUMN parser_version text;
