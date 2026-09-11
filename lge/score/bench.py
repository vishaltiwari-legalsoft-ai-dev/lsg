"""`bench_sync` (plane "score") -- upsert the hand-maintained bench CSV into
`bench_inventory`.

context/50-first-party/02-one-door-rule.md's one exception: bench_inventory
does NOT go through observation/firm_attribute -- it is a live mirror of
internal state with its own freshness contract (hourly sync, a stale bench
treated as empty by invariant I4), so this component writes the table
directly rather than through `reconcile()`.

The CSV never carries invented numbers (config/bench_inventory.csv ships as
header + comments only until portal access lands) -- an empty or missing
file is a legitimate "no inventory" result, not a failure this component
manufactures data to avoid.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dateutil import parser as dateutil_parser

from lge.registry import RunContext, RunResult, component
from lge.settings import PROJECT_ROOT

DEFAULT_PATH = "config/bench_inventory.csv"

_REQUIRED_COLUMNS = ("sku", "language", "practice_exp", "available", "replenish_rate_30d", "as_of")


def _resolve_path(raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _strip_comment_lines(text: str) -> str:
    """`#`-prefixed lines (the template's documentation header) are not part
    of the CSV -- everything else, including the real header row, is."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _parse_as_of(raw: str) -> datetime:
    dt = dateutil_parser.parse(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _upsert_row(conn, sku: str, language: str, practice_exp: str, available: int,
                 replenish: int, as_of: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bench_inventory
                (sku, language, practice_exp, available, replenish_rate_30d, as_of)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sku, language, practice_exp) DO UPDATE
              SET available = EXCLUDED.available,
                  replenish_rate_30d = EXCLUDED.replenish_rate_30d,
                  as_of = EXCLUDED.as_of
            """,
            (sku, language, practice_exp, available, replenish, as_of),
        )


@component(
    "bench_sync", "score",
    "Upsert the hand-maintained bench CSV into bench_inventory (I4's supply gate).",
)
def bench_sync(ctx: RunContext, **opts: Any) -> RunResult:
    raw_path = opts.get("path", DEFAULT_PATH)
    path = _resolve_path(str(raw_path))
    if not path.is_file():
        return RunResult(failed=1, notes=[f"bench_sync: no such file: {path}"])

    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(_strip_comment_lines(text)))
    fieldnames = reader.fieldnames or []
    missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        return RunResult(
            failed=1,
            notes=[f"bench_sync: CSV missing required column(s): {', '.join(missing)}"],
        )

    result = RunResult()
    for i, row in enumerate(reader):
        sku = (row.get("sku") or "").strip()
        if not sku:
            continue  # blank/trailing line
        try:
            language = (row.get("language") or "").strip() or "en"
            practice_exp = (row.get("practice_exp") or "").strip() or "any"
            available = int(row["available"])
            replenish = int(row["replenish_rate_30d"] or 0)
            as_of = _parse_as_of(row["as_of"])
        except (ValueError, KeyError) as exc:
            result.failed += 1
            ctx.log.warning("bench_sync: row %d skipped (%s): %r", i, exc, row)
            continue

        _upsert_row(ctx.conn, sku, language, practice_exp, available, replenish, as_of)
        result.processed += 1

    result.notes.append(f"rows upserted: {result.processed}")
    if result.processed == 0:
        result.notes.append(
            "no inventory rows in the CSV -- bench is empty; I4 treats that as no "
            "capacity for any SKU, not an error"
        )
    return result
