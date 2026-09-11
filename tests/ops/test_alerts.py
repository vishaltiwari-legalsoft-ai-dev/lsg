"""Every alert in lge/ops/alerts.py: an ok, a firing, and (where the alert
distinguishes it) a no_data path -- context/40-pipeline/07-observability.md
"every alert is a defect, not a metric to watch"."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.ops import alerts as ops_alerts
from lge.ops import snapshot
from lge.ops.config import load_alerts_config
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)


def _ctx(db):
    return RunContext(db, get_settings())


def _cfg():
    return load_alerts_config()


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "QUALIFIED_A")
    cols.setdefault("created_at", NOW)
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_signal(conn, firm_id, **cols):
    cols.setdefault("kind", "job_posting_open")
    cols.setdefault("fingerprint", "fp-" + uuid.uuid4().hex[:8])
    cols.setdefault("first_seen", NOW)
    cols.setdefault("last_seen", NOW)
    cols.setdefault("evidence", Jsonb({}))
    columns = ["firm_id", *cols.keys()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [firm_id, *cols.values()]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO signal ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_raw_posting(conn, **cols):
    cols.setdefault("source", "careers")
    cols.setdefault("source_key", "k-" + uuid.uuid4().hex[:8])
    cols.setdefault("title", "Paralegal")
    cols.setdefault("fetched_at", NOW)
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO raw_posting ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            list(cols.values()),
        )
        return cur.fetchone()["id"]


def outreach_event(conn, lead_id, **cols):
    cols.setdefault("channel", "email")
    cols.setdefault("step", 1)
    columns = ["lead_id", *cols.keys()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO outreach_touch ({col_list}) VALUES ({placeholders})",  # noqa: S608
            [lead_id, *cols.values()],
        )


# =============================================================================
# watcher_silence
# =============================================================================


def test_watcher_silence_no_data_when_ja1_never_ran(db):
    outcome = ops_alerts._watcher_silence(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_watcher_silence_firing_on_zero_postings_across_the_sweep(db):
    firm_id = make_firm(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO careers_sweep (firm_id, url, swept_at, fetch_ok, postings_found) "
            "VALUES (%s, 'https://x.test/careers', %s, true, 0)",
            (firm_id, NOW),
        )
    outcome = ops_alerts._watcher_silence(_ctx(db), _cfg())
    assert outcome.state == "firing"
    assert outcome.value == 0


def test_watcher_silence_ok_when_postings_found(db):
    firm_id = make_firm(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO careers_sweep (firm_id, url, swept_at, fetch_ok, postings_found) "
            "VALUES (%s, 'https://x.test/careers', %s, true, 3)",
            (firm_id, NOW),
        )
    outcome = ops_alerts._watcher_silence(_ctx(db), _cfg())
    assert outcome.state == "ok"
    assert outcome.value == 3


# =============================================================================
# platform_parser_silence
# =============================================================================


def test_platform_parser_silence_no_data_without_registered_platforms(db):
    outcome = ops_alerts._platform_parser_silence(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_platform_parser_silence_firing_when_a_platform_yields_nothing(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO source_registry (host, platform) VALUES ('bar.example.test', 'mybarhub')"
        )
    outcome = ops_alerts._platform_parser_silence(_ctx(db), _cfg())
    assert outcome.state == "firing"
    assert "mybarhub" in outcome.detail


def test_platform_parser_silence_ok_when_platform_yields(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO source_registry (host, platform) VALUES ('bar.example.test', 'mybarhub')"
        )
    make_raw_posting(db, source="bar_board:bar.example.test", fetched_at=NOW)
    outcome = ops_alerts._platform_parser_silence(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# dedupe_drift
# =============================================================================


def test_dedupe_drift_no_data_with_no_firms(db):
    outcome = ops_alerts._dedupe_drift(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_dedupe_drift_firing_on_shared_phone(db):
    # NOT shared domain -- firm.domain carries a hard UNIQUE index
    # (sql/001_schema.sql), so a duplicate domain can never reach this
    # query in the first place. phone_e164 has no such constraint (a
    # shared answering-service number is a real, if rare, possibility),
    # which is exactly the gap R2 exists to close -- and exactly what this
    # alert is watching for.
    make_firm(db, phone_e164="+12125551234")
    make_firm(db, phone_e164="+12125551234")
    outcome = ops_alerts._dedupe_drift(_ctx(db), _cfg())
    assert outcome.state == "firing"
    assert outcome.value == 1


def test_dedupe_drift_ok_with_no_duplicates(db):
    make_firm(db, domain="a.test")
    make_firm(db, domain="b.test")
    outcome = ops_alerts._dedupe_drift(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# extraction_confidence_drop
# =============================================================================


def test_extraction_confidence_drop_no_data_without_prior_week(db):
    snapshot.observe_snapshot(_ctx(db), at=NOW.isoformat())
    outcome = ops_alerts._extraction_confidence_drop(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_extraction_confidence_drop_firing_on_a_big_drop(db):
    ctx = _ctx(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW - timedelta(days=7), snapshot.METRIC_FEE_CONF, "regex:p6", 0.9),
        )
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW, snapshot.METRIC_FEE_CONF, "regex:p6", 0.5),
        )
    outcome = ops_alerts._extraction_confidence_drop(ctx, _cfg())
    assert outcome.state == "firing"
    assert outcome.value == pytest.approx(0.4)


def test_extraction_confidence_drop_ok_on_a_small_move(db):
    ctx = _ctx(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW - timedelta(days=7), snapshot.METRIC_FEE_CONF, "regex:p6", 0.85),
        )
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW, snapshot.METRIC_FEE_CONF, "regex:p6", 0.83),
        )
    outcome = ops_alerts._extraction_confidence_drop(ctx, _cfg())
    assert outcome.state == "ok"


# =============================================================================
# tier_distribution_shift
# =============================================================================


def test_tier_distribution_shift_no_data_without_prior_week(db):
    snapshot.observe_snapshot(_ctx(db), at=NOW.isoformat())
    outcome = ops_alerts._tier_distribution_shift(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_tier_distribution_shift_firing_on_a_big_move(db):
    ctx = _ctx(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW - timedelta(days=7), snapshot.METRIC_TIER_SHARE, "1A", 0.10),
        )
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW, snapshot.METRIC_TIER_SHARE, "1A", 0.40),
        )
    outcome = ops_alerts._tier_distribution_shift(ctx, _cfg())
    assert outcome.state == "firing"


def test_tier_distribution_shift_ok_on_a_small_move(db):
    ctx = _ctx(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW - timedelta(days=7), snapshot.METRIC_TIER_SHARE, "1A", 0.30),
        )
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) VALUES (%s, %s, %s, %s)",
            (NOW, snapshot.METRIC_TIER_SHARE, "1A", 0.33),
        )
    outcome = ops_alerts._tier_distribution_shift(ctx, _cfg())
    assert outcome.state == "ok"


# =============================================================================
# bounce_rate
# =============================================================================


def test_bounce_rate_no_data_before_any_delivery_outcome(db):
    firm_id = make_firm(db, domain="bounce-test-none.test")
    lead_id = make_lead(db, firm_id, grade="A")
    outreach_event(db, lead_id, mailbox="a@sends.test", sent_at=NOW)  # bounced left NULL
    outcome = ops_alerts._bounce_rate(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_bounce_rate_firing_above_threshold(db):
    firm_id = make_firm(db, domain="bounce-test-fire.test")
    lead_id = make_lead(db, firm_id, grade="A")
    for _ in range(3):
        outreach_event(db, lead_id, mailbox="a@sends.test", sent_at=NOW, bounced=True)
    for _ in range(97):
        outreach_event(db, lead_id, mailbox="a@sends.test", sent_at=NOW, bounced=False)
    outcome = ops_alerts._bounce_rate(_ctx(db), _cfg())
    assert outcome.state == "firing"


def test_bounce_rate_ok_under_threshold(db):
    firm_id = make_firm(db, domain="bounce-test-ok.test")
    lead_id = make_lead(db, firm_id, grade="A")
    for _ in range(100):
        outreach_event(db, lead_id, mailbox="a@sends.test", sent_at=NOW, bounced=False)
    outcome = ops_alerts._bounce_rate(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# signal_to_contact_latency
# =============================================================================


def test_signal_to_contact_latency_no_data_without_strike_pairs(db):
    outcome = ops_alerts._signal_to_contact_latency(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_signal_to_contact_latency_firing_when_slow(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id, band="STRIKE")  # default state=QUALIFIED_A -- keeps the
    # trigger-auto-logged creation event (I5) out of the ARMED/ENGAGED pairs this alert reads
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO lead_state_event (lead_id, from_state, to_state, trigger, at) "
            "VALUES (%s, 'QUALIFIED_A', 'ARMED', 'score', %s)",
            (lead_id, NOW - timedelta(hours=72)),
        )
        cur.execute(
            "INSERT INTO lead_state_event (lead_id, from_state, to_state, trigger, at) "
            "VALUES (%s, 'ARMED', 'ENGAGED', 'sequence', %s)",
            (lead_id, NOW),
        )
    outcome = ops_alerts._signal_to_contact_latency(_ctx(db), _cfg())
    assert outcome.state == "firing"
    assert outcome.value == pytest.approx(72.0, abs=0.1)


def test_signal_to_contact_latency_ok_when_fast(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id, band="STRIKE")  # default state=QUALIFIED_A -- keeps the
    # trigger-auto-logged creation event (I5) out of the ARMED/ENGAGED pairs this alert reads
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO lead_state_event (lead_id, from_state, to_state, trigger, at) "
            "VALUES (%s, 'QUALIFIED_A', 'ARMED', 'score', %s)",
            (lead_id, NOW - timedelta(hours=2)),
        )
        cur.execute(
            "INSERT INTO lead_state_event (lead_id, from_state, to_state, trigger, at) "
            "VALUES (%s, 'ARMED', 'ENGAGED', 'sequence', %s)",
            (lead_id, NOW),
        )
    outcome = ops_alerts._signal_to_contact_latency(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# bench_starvation
# =============================================================================


def test_bench_starvation_no_data_without_history(db):
    outcome = ops_alerts._bench_starvation(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_bench_starvation_firing_after_eight_zero_days(db):
    with db.cursor() as cur:
        for d in range(9):  # day0..day8: an 8-day span, strictly > the 7-day threshold
            cur.execute(
                "INSERT INTO observe_snapshot (taken_at, metric, dim, value) "
                "VALUES (%s, %s, 'demand_writer', 0)",
                (NOW - timedelta(days=d), snapshot.METRIC_BENCH_AVAILABLE),
            )
    outcome = ops_alerts._bench_starvation(_ctx(db), _cfg())
    assert outcome.state == "firing"


def test_bench_starvation_ok_when_recently_replenished(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) "
            "VALUES (%s, %s, 'demand_writer', 0)",
            (NOW - timedelta(days=1), snapshot.METRIC_BENCH_AVAILABLE),
        )
        cur.execute(
            "INSERT INTO observe_snapshot (taken_at, metric, dim, value) "
            "VALUES (%s, %s, 'demand_writer', 5)",
            (NOW, snapshot.METRIC_BENCH_AVAILABLE),
        )
    outcome = ops_alerts._bench_starvation(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# bench_staleness
# =============================================================================


def test_bench_staleness_no_data_when_empty(db):
    outcome = ops_alerts._bench_staleness(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_bench_staleness_firing_when_old(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO bench_inventory (sku, language, practice_exp, available, as_of) "
            "VALUES ('demand_writer', 'en', 'any', 3, %s)",
            (NOW - timedelta(hours=72),),
        )
    outcome = ops_alerts._bench_staleness(_ctx(db), _cfg())
    assert outcome.state == "firing"


def test_bench_staleness_ok_when_fresh(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO bench_inventory (sku, language, practice_exp, available, as_of) "
            "VALUES ('demand_writer', 'en', 'any', 3, %s)",
            (NOW,),
        )
    outcome = ops_alerts._bench_staleness(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# stale_share
# =============================================================================


def test_stale_share_no_data_without_a_qualified_pool(db):
    make_firm(db, tier="UNCLASSIFIED")
    outcome = ops_alerts._stale_share(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_stale_share_firing_above_20pct(db):
    old = NOW - timedelta(days=200)
    for _ in range(3):
        make_firm(db, tier="1A", last_crawled=old)
    for _ in range(2):
        make_firm(db, tier="1A", last_crawled=NOW)
    outcome = ops_alerts._stale_share(_ctx(db), _cfg())
    assert outcome.state == "firing"


def test_stale_share_ok_below_20pct(db):
    old = NOW - timedelta(days=200)
    make_firm(db, tier="1A", last_crawled=old)
    for _ in range(9):
        make_firm(db, tier="1A", last_crawled=NOW)
    outcome = ops_alerts._stale_share(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# source_yield_zero
# =============================================================================


def test_source_yield_zero_no_data_without_checked_sources(db):
    outcome = ops_alerts._source_yield_zero(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_source_yield_zero_firing_on_a_checked_but_silent_host(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO source_registry (host, robots_checked) VALUES ('silent.test', %s)",
            (NOW,),
        )
    outcome = ops_alerts._source_yield_zero(_ctx(db), _cfg())
    assert outcome.state == "firing"
    assert "silent.test" in outcome.detail


def test_source_yield_zero_ok_when_host_yields(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO source_registry (host, robots_checked) VALUES ('active.test', %s)",
            (NOW,),
        )
    make_raw_posting(
        db, source="careers", source_url="https://active.test/careers/1", fetched_at=NOW
    )
    outcome = ops_alerts._source_yield_zero(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# robots_diff
# =============================================================================


def test_robots_diff_no_data_with_fewer_than_two_snapshots(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO robots_snapshot (host, taken_at, robots_txt) "
            "VALUES ('x.test', %s, 'User-agent: *')",
            (NOW,),
        )
    outcome = ops_alerts._robots_diff(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_robots_diff_firing_on_a_job_path_change(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO robots_snapshot (host, taken_at, robots_txt) VALUES ('x.test', %s, %s)",
            (NOW - timedelta(days=30), "User-agent: *\nAllow: /careers/"),
        )
        cur.execute(
            "INSERT INTO robots_snapshot (host, taken_at, robots_txt) VALUES ('x.test', %s, %s)",
            (NOW, "User-agent: *\nDisallow: /careers/"),
        )
    outcome = ops_alerts._robots_diff(_ctx(db), _cfg())
    assert outcome.state == "firing"
    assert "x.test" in outcome.detail


def test_robots_diff_ok_on_an_irrelevant_change(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO robots_snapshot (host, taken_at, robots_txt) VALUES ('y.test', %s, %s)",
            (NOW - timedelta(days=30), "User-agent: *\nSitemap: /a.xml"),
        )
        cur.execute(
            "INSERT INTO robots_snapshot (host, taken_at, robots_txt) VALUES ('y.test', %s, %s)",
            (NOW, "User-agent: *\nSitemap: /b.xml"),
        )
    outcome = ops_alerts._robots_diff(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# agency_rule3_spike
# =============================================================================


def test_agency_rule3_spike_no_data_without_any_history(db):
    outcome = ops_alerts._agency_rule3_spike(_ctx(db), _cfg())
    assert outcome.state == "no_data"


def test_agency_rule3_spike_firing_on_a_spike(db):
    with db.cursor() as cur:
        for w in range(1, 5):  # trailing 4 weeks: 1/week baseline
            rp_id = make_raw_posting(db, fetched_at=NOW - timedelta(days=7 * w + 1))
            cur.execute(
                "INSERT INTO job_posting_rejected (raw_posting_id, rule, rejected_at) "
                "VALUES (%s, 'geographic_spread', %s)",
                (rp_id, NOW - timedelta(days=7 * w + 1)),
            )
        for _ in range(5):  # this week: 5, well above 3x a baseline of 1
            rp_id = make_raw_posting(db, fetched_at=NOW)
            cur.execute(
                "INSERT INTO job_posting_rejected (raw_posting_id, rule, rejected_at) "
                "VALUES (%s, 'geographic_spread', %s)",
                (rp_id, NOW),
            )
    outcome = ops_alerts._agency_rule3_spike(_ctx(db), _cfg())
    assert outcome.state == "firing"


def test_agency_rule3_spike_ok_at_baseline(db):
    with db.cursor() as cur:
        for w in range(0, 5):
            rp_id = make_raw_posting(db, fetched_at=NOW - timedelta(days=7 * w + 1))
            cur.execute(
                "INSERT INTO job_posting_rejected (raw_posting_id, rule, rejected_at) "
                "VALUES (%s, 'geographic_spread', %s)",
                (rp_id, NOW - timedelta(days=7 * w + 1)),
            )
    outcome = ops_alerts._agency_rule3_spike(_ctx(db), _cfg())
    assert outcome.state == "ok"


# =============================================================================
# evaluate_all / write_alert_events / the alerts component
# =============================================================================


def test_evaluate_all_returns_every_registered_alert(db):
    outcomes = ops_alerts.evaluate_all(_ctx(db))
    names = {o.name for o in outcomes}
    assert names == {n for n, _fn in ops_alerts._ALERTS}


def test_write_alert_events_persists_every_state(db):
    ctx = _ctx(db)
    outcomes = ops_alerts.evaluate_all(ctx)
    ops_alerts.write_alert_events(ctx, outcomes)
    with db.cursor() as cur:
        cur.execute("SELECT alert, state FROM alert_event")
        rows = cur.fetchall()
    assert len(rows) == len(outcomes)
    assert {r["state"] for r in rows} <= {"ok", "firing", "no_data"}


def test_alerts_component_result_counts_map_to_states(db):
    ctx = _ctx(db)
    result = ops_alerts.alerts_component(ctx)
    outcomes = ops_alerts.evaluate_all(ctx)
    assert result.processed == sum(1 for o in outcomes if o.state == "ok")
    assert result.skipped == sum(1 for o in outcomes if o.state == "no_data")
    assert result.failed == sum(1 for o in outcomes if o.state == "firing")
