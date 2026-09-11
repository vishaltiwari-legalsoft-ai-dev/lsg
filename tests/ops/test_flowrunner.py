"""The flow runner: config/flows.yml step execution, gate stopping, failed
component stopping, unknown-name errors, and option filtering.

Most of these tests intentionally never touch a real connection (`conn`)
because `run_flow` raises before the connection is ever used for a bad flow
/ component / gate name -- `conn=None` proves that. The one test that needs
a gate to actually see persisted `firm` rows across steps
(`test_flow_stops_at_a_failing_gate_and_skips_later_steps`) uses its own
throwaway database rather than the shared, per-test-rollback `db` fixture
from tests/conftest.py: `run_flow` calls `conn.commit()` per step by
design (mirroring `lge run`), which a rollback-based fixture cannot safely
absorb without leaking committed rows into every other test sharing that
session's database.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest
import yaml

from lge import db as lge_db
from lge.ops import flowrunner
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _write_flows(tmp_path: Path, flows: dict) -> Path:
    path = tmp_path / "flows.yml"
    path.write_text(yaml.safe_dump({"flows": flows}), encoding="utf-8")
    return path


# =============================================================================
# _filtered_opts -- pure function, no DB.
# =============================================================================


def test_filtered_opts_passes_everything_through_a_var_keyword_function():
    def fn(ctx, **opts):
        return opts

    got = flowrunner._filtered_opts(fn, {"limit": "10", "live": "1"})
    assert got == {"limit": "10", "live": "1"}


def test_filtered_opts_drops_options_the_function_does_not_accept():
    def fn(ctx, *, path=None, limit=None):
        return (path, limit)

    got = flowrunner._filtered_opts(fn, {"path": "x.csv", "limit": "5", "bogus": "y"})
    assert got == {"path": "x.csv", "limit": "5"}
    assert "bogus" not in got
    assert "ctx" not in got  # the leading positional param is never an opt


# =============================================================================
# Unknown names -- loud errors, no connection ever touched.
# =============================================================================


def test_unknown_flow_name_raises_loudly(tmp_path):
    path = _write_flows(tmp_path, {"real_flow": {"steps": [{"component": "coverage_report"}]}})
    with pytest.raises(flowrunner.FlowError, match="unknown flow 'nope'"):
        flowrunner.run_flow(None, get_settings(), "nope", flows_path=path)


def test_unknown_component_in_a_flow_raises_loudly_naming_it(tmp_path):
    path = _write_flows(
        tmp_path, {"bad": {"steps": [{"component": "totally_made_up_component_xyz"}]}}
    )
    with pytest.raises(flowrunner.FlowError, match="totally_made_up_component_xyz"):
        flowrunner.run_flow(None, get_settings(), "bad", flows_path=path)


def test_unknown_gate_in_a_flow_raises_loudly_naming_it(tmp_path):
    path = _write_flows(tmp_path, {"bad": {"steps": [{"gate": "totally_made_up_gate_xyz"}]}})
    with pytest.raises(flowrunner.FlowError, match="totally_made_up_gate_xyz"):
        flowrunner.run_flow(None, get_settings(), "bad", flows_path=path)


def test_malformed_step_raises_loudly(tmp_path):
    path = _write_flows(tmp_path, {"bad": {"steps": [{"neither_component_nor_gate": "x"}]}})
    with pytest.raises(flowrunner.FlowError, match="neither"):
        flowrunner.run_flow(None, get_settings(), "bad", flows_path=path)


# =============================================================================
# Component failure stopping -- coverage_report and a bad-path
# i2_job_history_load never touch the DB, so the shared `db` fixture is safe
# here (no real commit ever persists a row).
# =============================================================================


def test_a_failed_component_stops_the_flow(db, tmp_path):
    path = _write_flows(
        tmp_path,
        {
            "bad": {
                "steps": [
                    {"component": "i2_job_history_load", "opts": {"path": "does-not-exist.csv"}},
                    {"component": "coverage_report"},
                ]
            }
        },
    )
    outcome = flowrunner.run_flow(db, get_settings(), "bad", flows_path=path, dry_run=True)
    assert outcome.ok is False
    assert outcome.stopped_at == 1
    assert len(outcome.steps) == 1  # step 2 never ran


def test_continue_on_fail_lets_the_flow_proceed(db, tmp_path):
    path = _write_flows(
        tmp_path,
        {
            "ok": {
                "steps": [
                    {
                        "component": "i2_job_history_load",
                        "opts": {"path": "does-not-exist.csv"},
                        "continue_on_fail": True,
                    },
                    {"component": "coverage_report"},
                ]
            }
        },
    )
    outcome = flowrunner.run_flow(db, get_settings(), "ok", flows_path=path, dry_run=True)
    assert outcome.ok is True
    assert len(outcome.steps) == 2


def test_from_step_skips_earlier_steps(db, tmp_path):
    path = _write_flows(
        tmp_path,
        {
            "two_step": {
                "steps": [
                    {"component": "i2_job_history_load", "opts": {"path": "does-not-exist.csv"}},
                    {"component": "coverage_report"},
                ]
            }
        },
    )
    # from_step=2 skips the failing step entirely -- only coverage_report runs.
    outcome = flowrunner.run_flow(
        db, get_settings(), "two_step", flows_path=path, from_step=2, dry_run=True
    )
    assert outcome.ok is True
    assert len(outcome.steps) == 1
    assert outcome.steps[0].name == "coverage_report"


# =============================================================================
# Gate stopping -- needs real, persisted `firm` rows visible to the gate's
# own query after a real per-step commit, so this one uses an isolated
# throwaway database rather than the shared `db` fixture.
# =============================================================================


@pytest.fixture
def flow_conn(test_dsn):
    """An isolated, disposable database, migrated the same way test_dsn is.
    Depending on test_dsn (unused beyond its reachability skip / migration
    settings) reuses conftest.py's "Postgres unreachable -> skip" logic
    without duplicating it."""
    settings = get_settings()
    admin_dsn = settings.admin_dsn
    db_name = f"lge_flowtest_{secrets.token_hex(4)}"
    with lge_db.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')

    base = admin_dsn.rsplit("/", 1)[0]
    dsn = f"{base}/{db_name}"
    only = [p.strip() for p in os.environ.get("LGE_TEST_MIGRATIONS", "").split(",") if p.strip()]
    lge_db.migrate(dsn, only=only or None)

    conn = lge_db.connect(dsn)
    try:
        yield conn
    finally:
        conn.close()
        with lge_db.connect(admin_dsn, autocommit=True) as admin_conn, admin_conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


def test_flow_stops_at_a_failing_gate_and_skips_later_steps(flow_conn, tmp_path):
    for _ in range(3):
        make_firm(flow_conn, tier="1A")
    flow_conn.commit()

    path = _write_flows(
        tmp_path,
        {
            "profile_like": {
                "steps": [
                    {"component": "coverage_report"},  # harmless, real commit
                    {"gate": "g3_tier_distribution"},   # fails: all classified firms are 1A
                    {"component": "coverage_report"},   # must NOT run
                ]
            }
        },
    )
    outcome = flowrunner.run_flow(flow_conn, get_settings(), "profile_like", flows_path=path)
    assert outcome.ok is False
    assert outcome.stopped_at == 2
    assert len(outcome.steps) == 2
    assert outcome.steps[0].kind == "component" and outcome.steps[0].ok is True
    assert outcome.steps[1].kind == "gate" and outcome.steps[1].ok is False
