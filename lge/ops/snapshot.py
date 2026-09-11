"""`observe_snapshot` (plane "ops") -- one row per (day, metric, dim) into
observe_snapshot (sql/080_observe.sql), so week-over-week alerts
(extraction confidence drop, tier distribution shift, bench starvation)
have history to compare against. Idempotent per day: every write is an
UPSERT keyed on (taken_at, metric, dim), so a re-run today just overwrites
today's numbers rather than growing duplicate rows.

Metrics recorded, per context/40-pipeline/07-observability.md and the M10
build brief:
  tier_share               dim=tier             share of firm.tier (0..1)
  fee_model_confidence_median  dim=source family   regex:p6 vs llm:p8:* -- the
                            LATEST claim per firm within each family, not
                            every historical row (a firm re-profiled twice
                            must not double-count)
  rejects_7d                dim=rule            job_posting_rejected count,
                            trailing 7 days, one row per known rule (0 for
                            a rule that fired zero times -- absence is data)
  bench_available            dim=sku             sum(available) across
                            language/practice_exp for that sku
  pool_size / stale_firms_90d  dim="qualified"/"90d"  the freshness-sweep
                            denominator and numerator (tier not DQ_*, not
                            UNCLASSIFIED -- "the pool" is the qualified list,
                            not the pre-crawl universe)
  new_open_signals_24h       dim="all"           job_posting_open signals
                            first_seen in the last 24h
  review_queue_open          dim=identity_review / reconcile_conflict
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from lge.registry import RunContext, RunResult, component

METRIC_TIER_SHARE = "tier_share"
METRIC_FEE_CONF = "fee_model_confidence_median"
METRIC_REJECTS_7D = "rejects_7d"
METRIC_BENCH_AVAILABLE = "bench_available"
METRIC_POOL_SIZE = "pool_size"
METRIC_STALE_COUNT = "stale_firms_90d"
METRIC_NEW_OPEN_SIGNALS_24H = "new_open_signals_24h"
METRIC_REVIEW_QUEUE = "review_queue_open"

# sql/003_shared_lanes.sql job_posting_rejected.rule CHECK constraint,
# repeated here so every rule gets a 0 row when it did not fire this week --
# an omitted dim is not distinguishable from "never measured" downstream.
REJECT_RULES = (
    "known_agency", "client_language", "geographic_spread", "volume",
    "blind_posting", "name_only", "not_support_role", "unresolved",
)


def _today(at: datetime) -> datetime:
    at_utc = at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)
    return at_utc.replace(hour=0, minute=0, second=0, microsecond=0)


def _upsert(conn, taken_at: datetime, metric: str, dim: str, value: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe_snapshot (taken_at, metric, dim, value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (taken_at, metric, dim) DO UPDATE SET value = EXCLUDED.value
            """,
            (taken_at, metric, dim, value),
        )


def _tier_shares(conn) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(tier, 'UNCLASSIFIED') AS tier, count(*) AS n FROM firm GROUP BY 1"
        )
        rows = cur.fetchall()
    total = sum(r["n"] for r in rows)
    if total == 0:
        return {}
    return {r["tier"]: r["n"] / total for r in rows}


def _fee_model_confidence_medians(conn) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH tagged AS (
              SELECT firm_id, confidence, observed_at,
                     CASE WHEN source = 'regex:p6' THEN 'regex:p6' ELSE 'llm:p8' END AS family
              FROM firm_attribute
              WHERE attr = 'fee_model' AND (source = 'regex:p6' OR source LIKE 'llm:p8:%%')
            ),
            latest AS (
              SELECT DISTINCT ON (firm_id, family) family, confidence
              FROM tagged
              ORDER BY firm_id, family, observed_at DESC
            )
            SELECT family, percentile_cont(0.5) WITHIN GROUP (ORDER BY confidence) AS median_conf
            FROM latest GROUP BY family
            """
        )
        rows = cur.fetchall()
    return {r["family"]: float(r["median_conf"]) for r in rows if r["median_conf"] is not None}


def _rejects_7d(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT rule, count(*) AS n FROM job_posting_rejected "
            "WHERE rejected_at >= now() - interval '7 days' GROUP BY rule"
        )
        counts = {r["rule"]: r["n"] for r in cur.fetchall()}
    return {rule: counts.get(rule, 0) for rule in REJECT_RULES}


def _bench_available_by_sku(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT sku, sum(available) AS n FROM bench_inventory GROUP BY sku")
        rows = cur.fetchall()
    return {r["sku"]: int(r["n"] or 0) for r in rows}


def _freshness(conn) -> tuple[int, int]:
    # "The pool" = the qualified list (tier assigned, not disqualified, not
    # still pre-crawl UNCLASSIFIED) -- W7's 90-day guarantee is about
    # keeping THAT list current, not about firms never profiled at all.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM firm "
            "WHERE tier IS NOT NULL AND tier NOT LIKE 'DQ%%' AND tier <> 'UNCLASSIFIED'"
        )
        pool = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM firm "
            "WHERE tier IS NOT NULL AND tier NOT LIKE 'DQ%%' AND tier <> 'UNCLASSIFIED' "
            "AND (last_crawled IS NULL OR last_crawled < now() - interval '90 days')"
        )
        stale = cur.fetchone()["n"]
    return pool, stale


def _new_open_signals_24h(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM signal "
            "WHERE kind = 'job_posting_open' AND first_seen >= now() - interval '24 hours'"
        )
        return cur.fetchone()["n"]


def _review_queue_sizes(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM identity_review WHERE status = 'open'")
        identity = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM reconcile_conflict WHERE resolved_at IS NULL")
        reconcile = cur.fetchone()["n"]
    return {"identity_review": identity, "reconcile_conflict": reconcile}


@component("observe_snapshot", "ops", "Daily metrics snapshot for week-over-week alerting.")
def observe_snapshot(ctx: RunContext, **opts: Any) -> RunResult:
    at_opt = opts.get("at")
    at = datetime.fromisoformat(str(at_opt)) if at_opt else datetime.now(UTC)
    taken_at = _today(at)
    conn = ctx.conn
    result = RunResult()

    for tier, share in _tier_shares(conn).items():
        _upsert(conn, taken_at, METRIC_TIER_SHARE, tier, share)
        result.processed += 1

    for family, median_conf in _fee_model_confidence_medians(conn).items():
        _upsert(conn, taken_at, METRIC_FEE_CONF, family, median_conf)
        result.processed += 1

    for rule, n in _rejects_7d(conn).items():
        _upsert(conn, taken_at, METRIC_REJECTS_7D, rule, n)
        result.processed += 1

    for sku, n in _bench_available_by_sku(conn).items():
        _upsert(conn, taken_at, METRIC_BENCH_AVAILABLE, sku, n)
        result.processed += 1

    pool, stale = _freshness(conn)
    _upsert(conn, taken_at, METRIC_POOL_SIZE, "qualified", pool)
    _upsert(conn, taken_at, METRIC_STALE_COUNT, "90d", stale)
    result.processed += 2

    _upsert(conn, taken_at, METRIC_NEW_OPEN_SIGNALS_24H, "all", _new_open_signals_24h(conn))
    result.processed += 1

    for queue, n in _review_queue_sizes(conn).items():
        _upsert(conn, taken_at, METRIC_REVIEW_QUEUE, queue, n)
        result.processed += 1

    ctx.checkpoint()
    result.notes.append(f"snapshot taken_at={taken_at.isoformat()} rows={result.processed}")
    return result


def latest(ctx: RunContext, metric: str) -> tuple[datetime, dict[str, float]] | None:
    """The most recent snapshot day for one metric, as {dim: value}. None
    when the metric has never been snapshotted."""
    with ctx.conn.cursor() as cur:
        cur.execute("SELECT max(taken_at) AS d FROM observe_snapshot WHERE metric = %s", (metric,))
        row = cur.fetchone()
    day = row["d"] if row else None
    if day is None:
        return None
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT dim, value FROM observe_snapshot WHERE metric = %s AND taken_at = %s",
            (metric, day),
        )
        rows = cur.fetchall()
    return day, {r["dim"]: float(r["value"]) for r in rows}


def latest_before(
    ctx: RunContext, metric: str, before: datetime
) -> tuple[datetime, dict[str, float]] | None:
    """The most recent snapshot day strictly before `before`, as {dim:
    value}. None when no such day exists -- callers report no_data rather
    than silently treating "no history" as "no change"."""
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT max(taken_at) AS d FROM observe_snapshot WHERE metric = %s AND taken_at < %s",
            (metric, before),
        )
        row = cur.fetchone()
    day = row["d"] if row else None
    if day is None:
        return None
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT dim, value FROM observe_snapshot WHERE metric = %s AND taken_at = %s",
            (metric, day),
        )
        rows = cur.fetchall()
    return day, {r["dim"]: float(r["value"]) for r in rows}
