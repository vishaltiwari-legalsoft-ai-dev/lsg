"""The `score` component (plane "score") -- context/40-pipeline/
04-scoring-engine.md's nightly full scan. For every OPEN lead: fit, intent,
the arming signal, contest, routing band and wedge_sku -- written to
`lead.fit_score/intent_score/band/contest/arming_signal/wedge_sku/scored_at`.

Fit is a pure function of firm attributes (`fit_score(firm)`), intent a
windowed aggregation over signal (`intent_score(firm_id, at)`) -- both SQL
functions in sql/002_functions.sql, never reimplemented here. This component
only decides which signal arms (highest `signal_weight * decay`) and
assembles the routing_band()/wedge_sku() call.

Set-based per chunk, one UPDATE ... FROM (a CTE picking the best open signal
per firm via DISTINCT ON) rather than a per-lead round trip -- "a nightly
full scan, not a stream," specifically so a re-weight is a re-run.

No `writer(conn, ...)` needed: unlike `reconcile`, this component never
touches `firm.tier`/`firm.fit_score` -- only `lead` columns, which invariant
I7 does not govern."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lge.registry import RunContext, RunResult, component

_CHUNK_SIZE = 1000

_SCORE_CHUNK_SQL = """
WITH candidates AS (
  SELECT l.id AS lead_id, l.firm_id, f.tier,
         fit_score(f) AS fit,
         intent_score(f.id, %(at)s) AS intent
  FROM lead l
  JOIN firm f ON f.id = l.firm_id
  WHERE l.closed_at IS NULL AND l.id = ANY(%(ids)s)
),
best_signal AS (
  SELECT DISTINCT ON (s.firm_id) s.firm_id, s.id AS signal_id, s.kind
  FROM signal s
  JOIN candidates c ON c.firm_id = s.firm_id
  WHERE s.closed_at IS NULL
  ORDER BY s.firm_id,
    (signal_weight(s.kind, s.first_seen, s.closed_at, s.repost_count, %(at)s)
     * decay(EXTRACT(EPOCH FROM (%(at)s - s.last_seen)) / 86400.0)) DESC,
    s.id
),
scored AS (
  SELECT c.lead_id, c.fit, c.intent, c.tier,
         bs.signal_id AS arming_signal,
         -- contest_level() has no NULL branch of its own (an unrecognized
         -- kind conservatively resolves to 'HIGH', context/40-pipeline/
         -- 04-scoring-engine.md) -- a MISSING signal is the one case that
         -- must resolve to 'NONE', so it is handled before the function is
         -- ever called, not via COALESCE around it.
         CASE WHEN bs.kind IS NULL THEN 'NONE' ELSE contest_level(bs.kind) END AS contest
  FROM candidates c
  LEFT JOIN best_signal bs ON bs.firm_id = c.firm_id
)
UPDATE lead l SET
  fit_score = s.fit,
  intent_score = s.intent,
  band = routing_band(s.fit, s.intent, s.contest),
  contest = s.contest,
  arming_signal = s.arming_signal,
  wedge_sku = wedge_sku(s.tier),
  scored_at = %(at)s
FROM scored s
WHERE l.id = s.lead_id
RETURNING l.id
"""


def _select_lead_ids(conn, opts: dict[str, Any]) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    clauses = ["closed_at IS NULL"]
    params: dict[str, Any] = {}
    if firm_ids_file:
        path = Path(str(firm_ids_file))
        ids = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        clauses.append("firm_id = ANY(%(firm_ids)s)")
        params["firm_ids"] = ids

    query = f"SELECT id FROM lead WHERE {' AND '.join(clauses)} ORDER BY id"  # noqa: S608
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %(limit)s"
        params["limit"] = int(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["id"] for r in cur.fetchall()]


def _score_chunk(conn, lead_ids: list[Any], at: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(_SCORE_CHUNK_SQL, {"ids": lead_ids, "at": at})
        return cur.rowcount


@component(
    "score", "score",
    "Nightly full scan: fit, intent, contest, routing band, arming signal and "
    "wedge_sku for every open lead.",
)
def score(ctx: RunContext, **opts: Any) -> RunResult:
    at = datetime.now(UTC)
    lead_ids = _select_lead_ids(ctx.conn, opts)
    result = RunResult()

    for i in range(0, len(lead_ids), _CHUNK_SIZE):
        chunk = lead_ids[i : i + _CHUNK_SIZE]
        result.processed += _score_chunk(ctx.conn, chunk, at)
        ctx.checkpoint()

    result.notes.append(f"leads scored: {result.processed}")
    return result
