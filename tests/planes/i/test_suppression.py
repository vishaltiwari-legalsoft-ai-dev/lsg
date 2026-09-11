"""suppression_load — customer-domain CSV -> suppression (scope=domain, reason=customer)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from lge.planes.i.suppression import suppression_load
from lge.registry import RunContext
from lge.settings import get_settings

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_detects_domain_column_normalizes_and_rejects(db, tmp_path):
    path = tmp_path / "customers.csv"
    _write_csv(
        path,
        ["Customer Name", "Domain"],
        [
            {"Customer Name": "Acme Law", "Domain": "https://www.AcmeLaw.com/"},
            {"Customer Name": "Beta LLP", "Domain": "betallp.com"},
            {"Customer Name": "Blank row", "Domain": ""},
            {"Customer Name": "Blocked host", "Domain": "https://someone.wixsite.com/x"},
        ],
    )
    result = suppression_load(_ctx(db), path=str(path))

    assert result.processed == 4
    with db.cursor() as cur:
        cur.execute("SELECT value, reason, added_at FROM suppression ORDER BY value")
        rows = cur.fetchall()
    assert [r["value"] for r in rows] == ["acmelaw.com", "betallp.com"]
    assert all(r["reason"] == "customer" for r in rows)
    assert all(r["added_at"] is not None for r in rows)
    assert "column used: 'Domain'" in result.notes
    assert "rows loaded (new suppression rows): 2" in result.notes
    assert "rows rejected: 2" in result.notes


def test_falls_back_to_email_column_and_blocks_freemail(db, tmp_path):
    # "someone@gmail.com" must NEVER normalize to a bare "gmail.com" suppression
    # entry -- that would suppress every firm that happens to use Gmail.
    path = tmp_path / "customers.csv"
    _write_csv(
        path,
        ["Contact Email"],
        [
            {"Contact Email": "billing@acmecorp.com"},
            {"Contact Email": "someone@gmail.com"},
        ],
    )
    result = suppression_load(_ctx(db), path=str(path))

    with db.cursor() as cur:
        cur.execute("SELECT value FROM suppression")
        values = {r["value"] for r in cur.fetchall()}
    assert values == {"acmecorp.com"}
    assert "gmail.com" not in values
    assert "rows rejected: 1" in result.notes


def test_no_recognizable_column_raises(db, tmp_path):
    path = tmp_path / "customers.csv"
    _write_csv(path, ["Customer Name", "Notes"], [{"Customer Name": "X", "Notes": "y"}])
    with pytest.raises(ValueError, match="no domain/website/url/email"):
        suppression_load(_ctx(db), path=str(path))


def test_idempotent_reload(db, tmp_path):
    path = tmp_path / "customers.csv"
    _write_csv(path, ["Domain"], [{"Domain": "acmelaw.com"}, {"Domain": "acmelaw.com"}])
    ctx = _ctx(db)

    first = suppression_load(ctx, path=str(path))
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM suppression")
        first_count = cur.fetchone()["n"]
    assert first_count == 1
    assert first.processed == 2  # two rows read, one distinct domain after normalization

    second = suppression_load(ctx, path=str(path))
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM suppression")
        second_count = cur.fetchone()["n"]
    assert second_count == 1
    assert second.skipped == 2


def test_missing_path_raises(db):
    with pytest.raises(ValueError, match="path"):
        suppression_load(_ctx(db))
