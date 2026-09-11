-- 080_observe.sql -- M10 observability storage. Owned by lge/ops/*.py
-- (context/40-pipeline/07-observability.md, context/40-pipeline/
-- 06-orchestration.md). One complete write.
--
-- observe_snapshot: one row per (day, metric, dim), written daily by the
-- observe_snapshot component. This is what makes every week-over-week alert
-- possible (extraction confidence drop, tier distribution shift, bench
-- starvation) -- without a stored history, "moved > 15% w/w" has nothing to
-- compare against. PK (taken_at, metric, dim) makes a same-day re-run an
-- UPSERT, not a duplicate: idempotent per day by construction, matching the
-- "re-run with unchanged input is a no-op" idempotency rule (context/
-- 40-pipeline/06-orchestration.md) at day granularity rather than
-- input_hash granularity -- a metric snapshot has no natural "input" to
-- hash, only a day it was taken.
CREATE TABLE observe_snapshot (
  taken_at timestamptz NOT NULL,
  metric   text NOT NULL,
  dim      text NOT NULL,
  value    numeric NOT NULL,
  PRIMARY KEY (taken_at, metric, dim)
);

CREATE INDEX observe_snapshot_metric_idx ON observe_snapshot (metric, taken_at DESC);

-- robots_snapshot: dated copies of robots.txt per host, for the monthly
-- robots-diff alert. source_registry.robots_txt (sql/001_schema.sql) is the
-- CURRENT copy only -- this table is what lets "did it change" be answered
-- without re-fetching, and what lets the diff be attributed to a date.
CREATE TABLE robots_snapshot (
  host      text NOT NULL,
  taken_at  timestamptz NOT NULL,
  robots_txt text,
  PRIMARY KEY (host, taken_at)
);

CREATE INDEX robots_snapshot_host_idx ON robots_snapshot (host, taken_at DESC);

-- alert_event: one row per (alert, evaluation). Every alert in
-- context/40-pipeline/07-observability.md is a defect, not a metric to
-- watch, so 'ok' is recorded alongside 'firing' and 'no_data' -- the point
-- is a queryable history of every evaluation, not just the bad ones.
-- 'no_data' is its own state (never coerced into 'ok') because the absence
-- of the data needed to evaluate an alert is itself information -- exactly
-- the organising idea of this whole chunk.
CREATE TABLE alert_event (
  id     bigserial PRIMARY KEY,
  alert  text NOT NULL,
  state  text NOT NULL CHECK (state IN ('ok', 'firing', 'no_data')),
  detail text,
  value  numeric,
  at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX alert_event_alert_idx ON alert_event (alert, at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON observe_snapshot, robots_snapshot, alert_event TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
