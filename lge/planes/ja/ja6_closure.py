"""JA6 closure -- ends a `job_posting_open` signal once the vacancy is
confirmed gone. context/20-signals/04-dedupe-dates-and-closure.md:

    a posting is CLOSED only when it is absent from every source in its
    sightings across TWO CONSECUTIVE sweeps
    precedence: the firm's own careers page is authoritative
    grace: 2 sweeps, not 1 -- one failed fetch must never close a live signal

`careers_sweep` (sql/004) is the only table that records "we looked and found
nothing" as distinct from "we didn't look" -- JA1 writes a row for every sweep of
a firm's careers page, found-or-not and failed-or-not. A board/ATS watcher's
raw_posting rows only ever record a HIT, so there is no equivalent "we checked
this board and it's gone" log to read for those sources. That asymmetry is
exactly why the careers page is authoritative here, not a simplification: a
signal's `last_seen` not advancing past a run of career sweeps IS the "absent
from every source" evidence (last_seen is bumped by ja6_normalise the moment ANY
source resees the fingerprint), and careers_sweep.fetch_ok is what tells apart
"confirmed absent" from "we don't actually know" for that run. A firm with no
careers_sweep history at all never closes through this path -- consistent with
the rest of this lane: no evidence, no action, never a guess.
"""

from __future__ import annotations

from lge.registry import RunContext, RunResult, component

_MIN_CONFIRMING_SWEEPS = 2


def _open_signals(conn, limit: int | None) -> list[dict]:
    sql = (
        "SELECT id, firm_id, last_seen FROM signal "
        "WHERE kind = 'job_posting_open' AND closed_at IS NULL ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _confirming_sweep_count(conn, firm_id: str, last_seen) -> int:
    """Successful careers_sweep rows for this firm strictly after last_seen. A
    failed sweep (fetch_ok=false) is simply skipped -- it neither confirms
    absence nor resets progress toward the two the grace period requires."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM careers_sweep "
            "WHERE firm_id = %s AND swept_at > %s AND fetch_ok = true",
            (firm_id, last_seen),
        )
        return cur.fetchone()["n"]


def _close(conn, signal_id: int) -> None:
    with conn.cursor() as cur:
        # closed_at IS NULL guard: belt-and-braces against double-closing inside
        # one run (the caller already only selects open signals, so this is a
        # no-op in practice, not the primary idempotency mechanism).
        cur.execute(
            "UPDATE signal SET closed_at = now() WHERE id = %s AND closed_at IS NULL",
            (signal_id,),
        )
        cur.execute(
            "INSERT INTO signal_sighting (signal_id, source, present, fetch_ok) "
            "VALUES (%s, 'careers_page', false, true)",
            (signal_id,),
        )


@component(
    "ja6_closure",
    "ja",
    "Close a job_posting_open signal once it is confirmed absent across two "
    "consecutive successful careers-page sweeps. A failed sweep never closes it.",
)
def ja6_closure(ctx: RunContext, **opts: object) -> RunResult:
    limit_opt = opts.get("limit")
    limit = int(limit_opt) if limit_opt is not None else None

    result = RunResult()
    open_signals = _open_signals(ctx.conn, limit)

    for sig in open_signals:
        result.processed += 1
        confirmations = _confirming_sweep_count(ctx.conn, sig["firm_id"], sig["last_seen"])
        if confirmations >= _MIN_CONFIRMING_SWEEPS:
            _close(ctx.conn, sig["id"])
        else:
            result.skipped += 1

    closed = result.processed - result.skipped
    result.notes.append(
        f"open_signals_examined={result.processed} closed={closed} still_open={result.skipped}"
    )
    return result
