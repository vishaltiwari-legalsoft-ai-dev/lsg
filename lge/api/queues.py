"""Review-queue counts and bench status -- shared by `GET /api/today`'s
`attention` block and (for hand-check) `GET /api/handcheck`. Plain read
queries; every queue is "items with no `review_decision` row yet" except
hand-check, which has its own gate logic in `lge.api.handcheck_logic`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

_BENCH_FRESHNESS = timedelta(hours=48)  # mirrors I4's trg_fn_lead_arming_bench


def conflicts_count(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM reconcile_conflict WHERE resolved_at IS NULL")
        return cur.fetchone()["n"]


def identity_count(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM identity_review WHERE status = 'open'")
        return cur.fetchone()["n"]


def agency_count(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM job_posting_rejected jpr "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM review_decision rd "
            "  WHERE rd.queue = 'agency' AND rd.item_id = jpr.raw_posting_id::text"
            ")"
        )
        return cur.fetchone()["n"]


def discovery_count(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM discovery_lead dl "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM review_decision rd "
            "  WHERE rd.queue = 'discovery' AND rd.item_id = dl.id::text"
            ")"
        )
        return cur.fetchone()["n"]


def bench_status(conn: Any, at: datetime | None = None) -> dict[str, Any]:
    """{skus_available, stale, message} -- I4 (sql/001_schema.sql) treats a
    bench row older than 48h as empty regardless of `available`; this
    mirrors that exactly so the UI's "can this lead be armed" story matches
    what the trigger will actually allow."""
    at = at or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute("SELECT sku, available, as_of FROM bench_inventory")
        rows = cur.fetchall()

    if not rows:
        return {
            "skus_available": 0, "stale": False,
            "message": "Bench inventory has never been synced — leads can't be armed.",
        }

    fresh_skus = {
        r["sku"] for r in rows if r["available"] > 0 and (at - r["as_of"]) < _BENCH_FRESHNESS
    }
    all_stale = all((at - r["as_of"]) >= _BENCH_FRESHNESS for r in rows)

    if fresh_skus:
        return {
            "skus_available": len(fresh_skus), "stale": False,
            "message": f"{len(fresh_skus)} SKU(s) available.",
        }
    if all_stale:
        return {
            "skus_available": 0, "stale": True,
            "message": "Bench data is stale (over 48h old) — leads can't be armed.",
        }
    return {
        "skus_available": 0, "stale": False,
        "message": "Bench is empty — leads can't be armed.",
    }
