from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lge.ops import snapshot
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(db):
    return RunContext(db, get_settings())


def _rows(db, metric: str | None = None):
    with db.cursor() as cur:
        if metric:
            cur.execute(
                "SELECT taken_at, metric, dim, value FROM observe_snapshot "
                "WHERE metric = %s ORDER BY dim",
                (metric,),
            )
        else:
            cur.execute(
                "SELECT taken_at, metric, dim, value FROM observe_snapshot ORDER BY metric, dim"
            )
        return cur.fetchall()


def test_tier_share_is_computed(db):
    make_firm(db, tier="1A")
    make_firm(db, tier="1A")
    make_firm(db, tier="UNCLASSIFIED")
    make_firm(db, tier="UNCLASSIFIED")

    result = snapshot.observe_snapshot(_ctx(db))
    assert result.failed == 0

    rows = {r["dim"]: float(r["value"]) for r in _rows(db, snapshot.METRIC_TIER_SHARE)}
    assert rows["1A"] == pytest.approx(0.5)
    assert rows["UNCLASSIFIED"] == pytest.approx(0.5)


def test_fee_model_confidence_median_per_family_latest_claim_only(db):
    firm_id = make_firm(db)
    now = datetime.now(UTC)
    with db.cursor() as cur:
        # Two regex:p6 claims for the SAME firm at different times -- only
        # the later (higher confidence) one should count.
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, observed_at) "
            "VALUES (%s, 'fee_model', %s, 'regex:p6', 0.4, %s)",
            (firm_id, Jsonb("hourly"), now - timedelta(days=2)),
        )
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, observed_at) "
            "VALUES (%s, 'fee_model', %s, 'regex:p6', 0.8, %s)",
            (firm_id, Jsonb("hourly"), now),
        )
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, observed_at) "
            "VALUES (%s, 'fee_model', %s, 'llm:p8:v1', 0.6, %s)",
            (firm_id, Jsonb("hourly"), now),
        )

    result = snapshot.observe_snapshot(_ctx(db))
    assert result.failed == 0

    rows = {r["dim"]: float(r["value"]) for r in _rows(db, snapshot.METRIC_FEE_CONF)}
    assert rows["regex:p6"] == pytest.approx(0.8)
    assert rows["llm:p8"] == pytest.approx(0.6)


def test_rejects_7d_includes_every_known_rule_even_at_zero(db):
    firm_id = make_firm(db)
    now = datetime.now(UTC)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_posting (source, source_key, firm_id, title, fetched_at) "
            "VALUES ('careers', 'k1', %s, 'Paralegal', %s) RETURNING id",
            (firm_id, now),
        )
        rp_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO job_posting_rejected (raw_posting_id, rule, rejected_at) "
            "VALUES (%s, 'geographic_spread', %s)",
            (rp_id, now),
        )

    result = snapshot.observe_snapshot(_ctx(db))
    assert result.failed == 0

    rows = {r["dim"]: int(r["value"]) for r in _rows(db, snapshot.METRIC_REJECTS_7D)}
    assert rows["geographic_spread"] == 1
    assert rows["known_agency"] == 0  # present at zero -- absence is data
    assert set(rows) == set(snapshot.REJECT_RULES)


def test_bench_available_summed_by_sku(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO bench_inventory (sku, language, practice_exp, available, as_of) "
            "VALUES ('demand_writer', 'en', 'personal_injury', 3, now()), "
            "       ('demand_writer', 'es', 'personal_injury', 2, now())"
        )

    result = snapshot.observe_snapshot(_ctx(db))
    assert result.failed == 0
    rows = {r["dim"]: int(r["value"]) for r in _rows(db, snapshot.METRIC_BENCH_AVAILABLE)}
    assert rows["demand_writer"] == 5


def test_stale_share_inputs_scoped_to_qualified_pool(db):
    old = datetime.now(UTC) - timedelta(days=200)
    make_firm(db, tier="1A", last_crawled=old)          # qualified + stale
    make_firm(db, tier="1A", last_crawled=datetime.now(UTC))  # qualified + fresh
    make_firm(db, tier="UNCLASSIFIED", last_crawled=None)  # excluded from pool
    make_firm(db, tier="DQ_SIZE", last_crawled=old)        # excluded from pool

    snapshot.observe_snapshot(_ctx(db))
    pool_rows = {r["dim"]: int(r["value"]) for r in _rows(db, snapshot.METRIC_POOL_SIZE)}
    stale_rows = {r["dim"]: int(r["value"]) for r in _rows(db, snapshot.METRIC_STALE_COUNT)}
    assert pool_rows["qualified"] == 2
    assert stale_rows["90d"] == 1


def test_new_open_signals_24h(db):
    firm_id = make_firm(db)
    now = datetime.now(UTC)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO signal (firm_id, kind, fingerprint, first_seen, last_seen, evidence) "
            "VALUES (%s, 'job_posting_open', 'fp1', %s, %s, '{}'::jsonb)",
            (firm_id, now, now),
        )
        cur.execute(
            "INSERT INTO signal (firm_id, kind, fingerprint, first_seen, last_seen, evidence) "
            "VALUES (%s, 'job_posting_open', 'fp2', %s, %s, '{}'::jsonb)",
            (firm_id, now - timedelta(days=3), now),
        )

    snapshot.observe_snapshot(_ctx(db))
    rows = {r["dim"]: int(r["value"]) for r in _rows(db, snapshot.METRIC_NEW_OPEN_SIGNALS_24H)}
    assert rows["all"] == 1


def test_review_queue_sizes(db):
    firm_id = make_firm(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO identity_review (rule, status) VALUES ('cross_firm', 'open')"
        )
        cur.execute(
            "INSERT INTO identity_review (rule, status) VALUES ('cross_firm', 'merged')"
        )
        cur.execute(
            "INSERT INTO reconcile_conflict (firm_id, attr, claims, reason) "
            "VALUES (%s, 'fee_model', '[]'::jsonb, 'test')",
            (firm_id,),
        )

    snapshot.observe_snapshot(_ctx(db))
    rows = {r["dim"]: int(r["value"]) for r in _rows(db, snapshot.METRIC_REVIEW_QUEUE)}
    assert rows["identity_review"] == 1
    assert rows["reconcile_conflict"] == 1


def test_observe_snapshot_is_idempotent_per_day(db):
    make_firm(db, tier="1A")
    ctx = _ctx(db)

    r1 = snapshot.observe_snapshot(ctx, at="2026-06-01T02:00:00+00:00")
    n_after_first = len(_rows(db))

    make_firm(db, tier="1A")  # data changes between the two runs
    r2 = snapshot.observe_snapshot(ctx, at="2026-06-01T10:00:00+00:00")  # same day
    n_after_second = len(_rows(db))

    assert r1.failed == 0 and r2.failed == 0
    assert n_after_first == n_after_second  # UPSERT, not a new set of rows
    tier_rows = {r["dim"]: float(r["value"]) for r in _rows(db, snapshot.METRIC_TIER_SHARE)}
    assert tier_rows["1A"] == pytest.approx(1.0)  # reflects the SECOND run's data


def test_observe_snapshot_different_days_do_not_collide(db):
    make_firm(db, tier="1A")
    ctx = _ctx(db)
    snapshot.observe_snapshot(ctx, at="2026-06-01T02:00:00+00:00")
    snapshot.observe_snapshot(ctx, at="2026-06-02T02:00:00+00:00")

    with db.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT taken_at) AS n FROM observe_snapshot WHERE metric = %s",
            (snapshot.METRIC_TIER_SHARE,),
        )
        assert cur.fetchone()["n"] == 2


def test_latest_and_latest_before_helpers(db):
    ctx = _ctx(db)
    make_firm(db, tier="1A")
    snapshot.observe_snapshot(ctx, at="2026-06-01T00:00:00+00:00")
    make_firm(db, tier="1A")
    snapshot.observe_snapshot(ctx, at="2026-06-08T00:00:00+00:00")

    day, vals = snapshot.latest(ctx, snapshot.METRIC_TIER_SHARE)
    assert day.date().isoformat() == "2026-06-08"
    assert vals["1A"] == pytest.approx(1.0)

    prev = snapshot.latest_before(ctx, snapshot.METRIC_TIER_SHARE, datetime(2026, 6, 8, tzinfo=UTC))
    assert prev is not None
    prev_day, prev_vals = prev
    assert prev_day.date().isoformat() == "2026-06-01"

    none_before = snapshot.latest_before(
        ctx, snapshot.METRIC_TIER_SHARE, datetime(2026, 5, 1, tzinfo=UTC)
    )
    assert none_before is None
