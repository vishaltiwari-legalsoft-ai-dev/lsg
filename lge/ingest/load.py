"""ingest_load -- an import_file, batch by batch, into `observation`.

Every row enters through `observation` like a scraped source (the one-door
rule); nothing here writes `firm`. Identity resolution attaches rows to firms
afterwards; i1_claims / i1_contacts read the canonical payload keys
(lge/ingest/normalize.py), never the sheet's own column names.

    register_import  -- read + sniff + record the file and its batches (no load)
    update_mapping   -- a person's corrections to the column map
    ingest_load      -- the component: load every pending batch, one at a time,
                        each committed on its own, each with a health report
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lge.ingest.batches import DEFAULT_BATCH_SIZE, Batch, plan_batches
from lge.ingest.columns import read_columns
from lge.ingest.health import assess
from lge.ingest.normalize import NORMALIZE_VERSION, normalize_row
from lge.ingest.reader import count_rows, iter_batches, read_head
from lge.ingest.sniff import ColumnMap
from lge.norm import NORM_VERSION, norm_addr
from lge.registry import RunContext, RunResult, component

# How much of the sheet the health report and the column reader look at
# before loading. The reader's model call sees far fewer (config/llm.yml).
HEAD_ROWS = 2000

# The email-as-identity-key rule (D-017) lives in normalize.resolve_domain; this
# version travels with every observation so a rule change can be re-keyed.
DOMAIN_RULE_VERSION = "2"

_OBSERVATION_COLUMNS: tuple[str, ...] = (
    "source", "source_key", "firm_id", "payload", "fetched_at", "name_raw", "name_stem",
    "domain", "phone_e164", "addr_hash", "zip5", "city", "state", "norm_versions",
    "import_id", "batch_no",
)


def batched_insert(
    cur: psycopg.Cursor,
    table: str,
    columns: Sequence[str],
    conflict_cols: Sequence[str],
    rows: Sequence[tuple],
    batch_size: int = 2000,
    update_cols: Sequence[str] = (),
) -> int:
    """Multi-row INSERT ... ON CONFLICT (conflict_cols) DO NOTHING (or DO UPDATE
    of `update_cols` when they differ), in chunks. Returns rows actually
    inserted or changed -- conflicts skipped are not counted, which is how
    callers report duplicates without a second query."""
    if not rows:
        return 0
    col_list = ", ".join(columns)
    conflict_list = ", ".join(conflict_cols)
    n_cols = len(columns)
    inserted = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        placeholders = ", ".join("(" + ", ".join(["%s"] * n_cols) + ")" for _ in chunk)
        if update_cols:
            sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            old = ", ".join(f"{table}.{c}" for c in update_cols)
            new = ", ".join(f"EXCLUDED.{c}" for c in update_cols)
            action = f"DO UPDATE SET {sets} WHERE ({old}) IS DISTINCT FROM ({new})"
        else:
            action = "DO NOTHING"
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES {placeholders} "  # noqa: S608
            f"ON CONFLICT ({conflict_list}) {action}"
        )
        cur.execute(sql, [v for row in chunk for v in row])
        inserted += cur.rowcount
    return inserted


def source_key(norm: dict[str, Any], raw: dict[str, str], headers: Sequence[str]) -> str:
    """Stable per row: the email when there is one, else the whole raw row in
    header order (a separator no cell can contain)."""
    if norm.get("email"):
        return hashlib.sha1(norm["email"].encode("utf-8")).hexdigest()  # noqa: S324
    joined = "\x1f".join((raw.get(h) or "") for h in headers)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()  # noqa: S324


def observation_tuple(
    norm: dict[str, Any],
    raw: dict[str, str],
    headers: Sequence[str],
    *,
    source_tag: str,
    fetched_at: datetime,
    import_id: str,
    batch_no: int,
) -> tuple:
    addr = norm_addr(norm.get("address"), norm.get("city"), norm.get("state"), norm.get("zip"))
    payload = dict(norm)
    payload["_raw"] = raw
    payload["_import_id"] = import_id
    payload["_batch_no"] = batch_no
    norm_versions = {
        "norm_domain": NORM_VERSION["norm_domain"],
        "norm_name": NORM_VERSION["norm_name"],
        "i1_domain_rule": DOMAIN_RULE_VERSION,
        "normalize": NORMALIZE_VERSION,
    }
    return (
        source_tag,
        source_key(norm, raw, headers),
        None,
        Jsonb(payload),
        fetched_at,
        norm.get("firm_name"),
        norm.get("name_stem"),
        norm.get("domain"),
        norm.get("phone_e164"),
        addr.addr_hash,
        addr.zip5 or norm.get("zip"),
        norm.get("city"),
        norm.get("state"),
        Jsonb(norm_versions),
        import_id,
        batch_no,
    )


# ---------------------------------------------------------------------------
# import_file / import_batch
# ---------------------------------------------------------------------------


def _row(cur: psycopg.Cursor, import_id: str) -> dict[str, Any] | None:
    cur.execute("SELECT * FROM import_file WHERE id = %s", (import_id,))
    return cur.fetchone()


def get_import(conn: psycopg.Connection, import_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        return _row(cur, import_id)


def list_batches(conn: psycopg.Connection, import_id: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM import_batch WHERE import_id = %s ORDER BY batch_no", (import_id,)
        )
        return cur.fetchall()


def register_import(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    file_name: str | None = None,
    source_tag: str = "internal_firms",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Read the sheet's head, have the column reader map it, count its rows,
    record it and its batches. Loads nothing. The same bytes registered twice
    return the first record. The whole sheet is never held in memory."""
    p = Path(path)
    data = p.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    del data
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM import_file WHERE sha256 = %s", (sha,))
        existing = cur.fetchone()
        if existing:
            return existing

    table = read_head(p, HEAD_ROWS)
    colmap = read_columns(table.headers, table.rows)
    health = assess([normalize_row(r, colmap) for r in table.rows])
    row_count = count_rows(p) if table.row_count >= HEAD_ROWS else table.row_count
    import_id = str(uuid.uuid4())
    batches = plan_batches(row_count, batch_size)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO import_file (id, file_name, stored_path, sha256, format, row_count,
                                     source_tag, column_map, missing, batch_size, status,
                                     health, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'mapped', %s, %s)
            """,
            (
                import_id, file_name or p.name, str(p.resolve()), sha, table.format,
                row_count, source_tag, Jsonb(colmap.to_dict()), colmap.missing,
                batches[0].size if batches else batch_size, Jsonb(health.to_dict()),
                Jsonb(table.notes + colmap.notes),
            ),
        )
        if batches:
            batched_insert(
                cur, "import_batch",
                ("import_id", "batch_no", "row_start", "row_end", "status"),
                ("import_id", "batch_no"),
                [(import_id, b.number, b.row_start, b.row_end, "pending") for b in batches],
            )
        return _row(cur, import_id)


def update_mapping(
    conn: psycopg.Connection, import_id: str, overrides: dict[str, str | None]
) -> dict[str, Any]:
    """Apply a person's column corrections. Only before loading."""
    with conn.cursor() as cur:
        imp = _row(cur, import_id)
        if imp is None:
            raise KeyError(import_id)
        if imp["status"] != "mapped":
            raise ValueError(f"import {import_id} is {imp['status']}; the map is fixed")
        colmap = ColumnMap.from_dict(imp["column_map"]).with_overrides(overrides)
        table = read_head(imp["stored_path"], HEAD_ROWS)
        health = assess([normalize_row(r, colmap) for r in table.rows])
        cur.execute(
            "UPDATE import_file SET column_map = %s, missing = %s, health = %s WHERE id = %s",
            (Jsonb(colmap.to_dict()), colmap.missing, Jsonb(health.to_dict()), import_id),
        )
        return _row(cur, import_id)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_batch(
    conn: psycopg.Connection,
    imp: dict[str, Any],
    headers: Sequence[str],
    colmap: ColumnMap,
    batch: Batch,
    raw_rows: list[dict[str, str]],
) -> tuple[int, int, dict[str, Any]]:
    """One batch's rows -> observation rows. Returns (loaded, skipped_as_duplicate, health)."""
    fetched_at = imp["created_at"]
    normalized = [normalize_row(r, colmap) for r in raw_rows]
    health = assess(normalized)
    tuples = [
        observation_tuple(
            n, r, headers, source_tag=imp["source_tag"], fetched_at=fetched_at,
            import_id=str(imp["id"]), batch_no=batch.number,
        )
        for n, r in zip(normalized, raw_rows, strict=True)
    ]
    # A row already on file under this source (the same contact in last
    # quarter's sheet) is "already known", not a second copy of the observation.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_key FROM observation WHERE source = %s AND source_key = ANY(%s)",
            (imp["source_tag"], [t[1] for t in tuples]),
        )
        known = {r["source_key"] for r in cur.fetchall()}
        fresh = [t for t in tuples if t[1] not in known]
        inserted = batched_insert(
            cur, "observation", _OBSERVATION_COLUMNS, ("source", "source_key", "fetched_at"),
            fresh,
        )
    return inserted, len(tuples) - inserted, health.to_dict()


def _set_batch(cur: psycopg.Cursor, batch_id: int, **cols: Any) -> None:
    sets = ", ".join(f"{k} = %s" for k in cols)
    cur.execute(f"UPDATE import_batch SET {sets} WHERE id = %s", [*cols.values(), batch_id])  # noqa: S608


def load_import(ctx: RunContext, import_id: str, *, only_batch: int | None = None) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    imp = get_import(conn, import_id)
    if imp is None:
        raise KeyError(f"no import {import_id}")
    if imp["status"] == "loaded":
        return RunResult(skipped=1, notes=[f"import {import_id} already loaded"])

    colmap = ColumnMap.from_dict(imp["column_map"])
    headers = read_head(imp["stored_path"], 0).headers
    with conn.cursor() as cur:
        cur.execute("UPDATE import_file SET status = 'loading' WHERE id = %s", (import_id,))
    ctx.checkpoint()

    # Only the batches still to do are read off the sheet, in one pass.
    pending: dict[int, dict[str, Any]] = {}
    for b in list_batches(conn, import_id):
        if only_batch is not None and b["batch_no"] != only_batch:
            continue
        if b["status"] == "loaded":
            result.skipped += 1
            continue
        pending[b["batch_no"]] = b
    plan = [Batch(b["batch_no"], b["row_start"], b["row_end"]) for b in pending.values()]

    for batch, raw_rows in iter_batches(imp["stored_path"], plan):
        b = pending[batch.number]
        with conn.cursor() as cur:
            _set_batch(cur, b["id"], status="loading", started_at=datetime.now(UTC), error=None)
        try:
            loaded, skipped, health = load_batch(conn, imp, headers, colmap, batch, raw_rows)
        except Exception as exc:  # noqa: BLE001 -- one batch must not sink the import
            conn.rollback()
            with conn.cursor() as cur:
                _set_batch(
                    cur, b["id"], status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
                    finished_at=datetime.now(UTC),
                )
            result.failed += 1
            result.notes.append(f"batch {batch.number}: {type(exc).__name__}: {exc}")
            ctx.checkpoint()
            continue
        with conn.cursor() as cur:
            _set_batch(
                cur, b["id"], status="loaded", rows_loaded=loaded, rows_skipped=skipped,
                health=Jsonb(health), finished_at=datetime.now(UTC),
            )
        result.processed += 1
        result.notes.append(
            f"batch {batch.number} rows {batch.row_start}-{batch.row_end}: loaded {loaded}, "
            f"duplicates {skipped}, health {health['score']}/100"
        )
        ctx.checkpoint()

    remaining = [b for b in list_batches(conn, import_id) if b["status"] != "loaded"]
    with conn.cursor() as cur:
        if remaining:
            cur.execute("UPDATE import_file SET status = 'failed' WHERE id = %s", (import_id,))
        else:
            cur.execute(
                "UPDATE import_file SET status = 'loaded', loaded_at = now() WHERE id = %s",
                (import_id,),
            )
    ctx.checkpoint()
    return result


@component("ingest_load", "I", "Load a registered sheet into observation, one batch at a time.")
def ingest_load(ctx: RunContext, **opts: Any) -> RunResult:
    import_id = opts.get("import_id")
    path = opts.get("path")
    if not import_id and not path:
        raise ValueError("ingest_load needs --opt import_id=<id> or --opt path=<sheet>")
    if not import_id:
        imp = register_import(
            ctx.conn, str(path),
            source_tag=str(opts.get("source_tag", "internal_firms")),
            batch_size=int(opts.get("batch_size", DEFAULT_BATCH_SIZE)),
        )
        import_id = str(imp["id"])
    only = opts.get("batch_no")
    return load_import(ctx, str(import_id), only_batch=int(only) if only else None)
