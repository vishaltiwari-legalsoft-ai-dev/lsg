-- 101: which engine answered each web search (D-045). The search seam has
-- interchangeable engines (serper, brave, ddg); a logged query says which
-- one produced its results, so an adopted URL or a review count can be
-- traced to the engine as well as to the result. Rows from before this
-- migration were all DuckDuckGo.

ALTER TABLE search_log ADD COLUMN engine text;
UPDATE search_log SET engine = 'ddg' WHERE engine IS NULL;
