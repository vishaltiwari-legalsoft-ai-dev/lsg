"""coverage_report + the g7_coverage gate.

The report always writes to the fixed data/out/coverage_report.md path (that IS
the deliverable), so every test here redirects the module's `_REPORT_PATH`
constant into `tmp_path` via monkeypatch rather than touching the real repo file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

import lge.planes.i.coverage as coverage_mod
from lge.planes.i.coverage import coverage_report, g7_coverage
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_observation(conn, firm_id, domain, fetched_at, city=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO observation (source, source_key, firm_id, payload, fetched_at, "
            "domain, city) VALUES ('internal_firms', %s, %s, %s, %s, %s, %s)",
            (f"key-{firm_id}-{fetched_at.isoformat()}", firm_id, Jsonb({}), fetched_at,
             domain, city),
        )


@pytest.fixture(autouse=True)
def _isolated_report_path(monkeypatch, tmp_path):
    monkeypatch.setattr(coverage_mod, "_REPORT_PATH", tmp_path / "coverage_report.md")
    return tmp_path / "coverage_report.md"


def test_gate_fails_when_report_missing(db):
    passed, report = g7_coverage(_ctx(db))
    assert passed is False
    assert "does not exist" in report


def test_report_contains_required_sections(db):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    firm_id = make_firm(db, canonical_name="Bigfirm Pllc", entity_kind="gov")
    _insert_observation(db, firm_id, "smallcountyda.gov", at)

    result = coverage_report(_ctx(db))
    assert result.processed == 1

    text = coverage_mod._REPORT_PATH.read_text(encoding="utf-8")
    assert "Firms resolved from internal_firms observations: 1" in text
    assert "entity_kind = 'gov': 1" in text
    assert "Places harvest not yet run" in text
    assert "not yet classified" in text  # no firm.tier values set anywhere


def test_report_states_places_overlap_as_unknown_not_complete(db):
    coverage_report(_ctx(db))
    text = coverage_mod._REPORT_PATH.read_text(encoding="utf-8")
    assert "unknown" in text.lower()
    assert "overlap cannot be computed" in text


def test_gate_passes_after_fresh_report(db):
    at = datetime(2026, 1, 1, tzinfo=UTC)
    firm_id = make_firm(db)
    _insert_observation(db, firm_id, "example.com", at)
    coverage_report(_ctx(db))

    passed, report = g7_coverage(_ctx(db))
    assert passed is True
    assert "current" in report


def test_gate_fails_when_report_is_stale(db):
    coverage_report(_ctx(db))  # empty-dataset report, written "now"

    # A load lands AFTER the report was generated -- the report no longer
    # reflects current data.
    firm_id = make_firm(db)
    future = datetime.now(UTC) + timedelta(hours=1)
    _insert_observation(db, firm_id, "example.com", future)

    passed, report = g7_coverage(_ctx(db))
    assert passed is False
    assert "predates" in report or "older" in report


def test_gate_fails_when_report_does_not_state_overlap_unknown(db):
    coverage_mod._REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    coverage_mod._REPORT_PATH.write_text("# Coverage report\n\nEverything is fine.\n")

    passed, report = g7_coverage(_ctx(db))
    assert passed is False
    assert "unknown" in report.lower()
