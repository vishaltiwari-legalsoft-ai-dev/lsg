"""bench_sync -- upsert into bench_inventory. context/50-first-party/
02-one-door-rule.md's one exception (no observation/firm_attribute involved)."""

from __future__ import annotations

import pytest

from lge.registry import RunContext
from lge.score import bench
from lge.settings import get_settings

pytestmark = pytest.mark.db


def _ctx(db):
    return RunContext(db, get_settings())


def rows(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT sku, language, practice_exp, available, replenish_rate_30d, as_of "
            "FROM bench_inventory ORDER BY sku, language, practice_exp"
        )
        return cur.fetchall()


def test_shipped_template_has_no_invented_inventory(db, tmp_path):
    # The real config/bench_inventory.csv, exercised exactly as `lge run
    # bench_sync` would use it by default.
    ctx = _ctx(db)
    result = bench.bench_sync(ctx, path="config/bench_inventory.csv")
    assert result.failed == 0
    assert result.processed == 0
    assert rows(db) == []


def test_bench_sync_upserts_rows(db, tmp_path):
    csv_path = tmp_path / "bench.csv"
    csv_path.write_text(
        "# comment line, ignored\n"
        "sku,language,practice_exp,available,replenish_rate_30d,as_of\n"
        "demand_writer,en,personal_injury,6,2,2026-01-01T00:00:00Z\n"
        "legal_assistant_es,es,immigration,14,4,2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    ctx = _ctx(db)
    result = bench.bench_sync(ctx, path=str(csv_path))
    assert result.failed == 0
    assert result.processed == 2
    got = rows(db)
    assert len(got) == 2
    demand = next(r for r in got if r["sku"] == "demand_writer")
    assert demand["available"] == 6
    assert demand["replenish_rate_30d"] == 2
    assert demand["practice_exp"] == "personal_injury"


def test_bench_sync_is_idempotent_and_updates_on_rerun(db, tmp_path):
    csv_path = tmp_path / "bench.csv"
    csv_path.write_text(
        "sku,language,practice_exp,available,replenish_rate_30d,as_of\n"
        "demand_writer,en,personal_injury,6,2,2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    ctx = _ctx(db)
    bench.bench_sync(ctx, path=str(csv_path))

    csv_path.write_text(
        "sku,language,practice_exp,available,replenish_rate_30d,as_of\n"
        "demand_writer,en,personal_injury,9,1,2026-01-02T00:00:00Z\n",
        encoding="utf-8",
    )
    result = bench.bench_sync(ctx, path=str(csv_path))
    assert result.processed == 1

    got = rows(db)
    assert len(got) == 1  # updated in place, not a duplicate row
    assert got[0]["available"] == 9
    assert got[0]["replenish_rate_30d"] == 1


def test_bench_sync_missing_file_fails_loudly(db, tmp_path):
    ctx = _ctx(db)
    result = bench.bench_sync(ctx, path=str(tmp_path / "does-not-exist.csv"))
    assert result.failed == 1
    assert rows(db) == []


def test_bench_sync_bad_row_is_skipped_not_fatal(db, tmp_path):
    csv_path = tmp_path / "bench.csv"
    csv_path.write_text(
        "sku,language,practice_exp,available,replenish_rate_30d,as_of\n"
        "demand_writer,en,personal_injury,not-a-number,2,2026-01-01T00:00:00Z\n"
        "legal_assistant_es,es,immigration,14,4,2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    ctx = _ctx(db)
    result = bench.bench_sync(ctx, path=str(csv_path))
    assert result.processed == 1
    assert result.failed == 1
    got = rows(db)
    assert len(got) == 1
    assert got[0]["sku"] == "legal_assistant_es"
