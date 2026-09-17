"""Imports: upload a sheet, see and correct how its columns were read, load it
in batches, watch it. plan/api-contract.md Revision 3.

Loading runs after the response (a background task on its own connection)
and chains the steps that make the rows visible: identity resolution, the
sheet's claims, the sheet's contacts. `?sync=1` runs the same chain on the
request's connection and returns when it is done -- the tests use it, and so
can a small file.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.api.deps import ConnDep
from lge.api.errors import api_error, not_found
from lge.api.models import (
    FieldOption,
    ImportBatch,
    ImportColumn,
    ImportDetail,
    ImportLoadResponse,
    ImportsResponse,
    ImportSummary,
    MappingRequest,
)
from lge.ingest.batches import DEFAULT_BATCH_SIZE, MAX_BATCH_SIZE, MIN_BATCH_SIZE
from lge.ingest.load import get_import, list_batches, load_import, register_import, update_mapping
from lge.ingest.sniff import ColumnMap
from lge.ingest.vocab import FIELDS, MANDATORY_LABELS, field_label_of, research_fill_label
from lge.registry import RunContext, discover, registered_components
from lge.settings import PROJECT_ROOT, get_settings

logger = logging.getLogger("lge.api.imports")
router = APIRouter(prefix="/api")

IMPORT_DIR = PROJECT_ROOT / ".local" / "imports"
_ALLOWED_SUFFIXES = (".csv", ".xlsx", ".xlsm", ".txt", ".tsv")
_MAX_BYTES = 50 * 1024 * 1024
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# What runs after the rows land, so they show up as firms, claims and people.
AFTER_LOAD = ("resolve_identity", "i1_claims", "i1_contacts")

_STATUS_DISPLAY = {
    "mapped": "Mapped — not loaded yet",
    "loading": "Loading",
    "loaded": "Loaded",
    "failed": "Failed — some batches did not load",
}


def _summary(row: dict[str, Any], batches: list[dict[str, Any]]) -> ImportSummary:
    health = row.get("health") or {}
    colmap = ColumnMap.from_dict(row["column_map"])
    return ImportSummary(
        id=str(row["id"]),
        file_name=row["file_name"],
        format=row["format"],
        row_count=row["row_count"],
        status=row["status"],
        status_display=_STATUS_DISPLAY.get(row["status"], row["status"]),
        missing=[MANDATORY_LABELS.get(m, m) for m in (row.get("missing") or [])],
        research_fills=[research_fill_label(f) for f in colmap.research_fills],
        reader=colmap.reader,
        batch_size=row["batch_size"],
        batches_total=len(batches),
        batches_loaded=sum(1 for b in batches if b["status"] == "loaded"),
        health_score=health.get("score"),
        created_at=row["created_at"],
        loaded_at=row.get("loaded_at"),
    )


def _detail(row: dict[str, Any], batches: list[dict[str, Any]]) -> ImportDetail:
    colmap = ColumnMap.from_dict(row["column_map"])
    columns = [
        ImportColumn(
            column=g.column, field=g.field, field_label=field_label_of(g.field),
            confidence=g.confidence, reason=g.reason, samples=list(g.samples),
        )
        for g in colmap.guesses
    ]
    fields = [
        FieldOption(name=f.name, label=f.label, mandatory_group=f.group, filled_by=f.filled_by)
        for f in FIELDS
    ]
    return ImportDetail(
        **_summary(row, batches).model_dump(),
        columns=columns,
        fields=fields,
        batches=[
            ImportBatch(
                batch_no=b["batch_no"], row_start=b["row_start"], row_end=b["row_end"],
                status=b["status"], rows_loaded=b["rows_loaded"], rows_skipped=b["rows_skipped"],
                health=b.get("health"), error=b.get("error"),
            )
            for b in batches
        ],
        health=row.get("health"),
        notes=[str(n) for n in (row.get("notes") or [])],
    )


def _load_detail(conn: psycopg.Connection, import_id: str) -> ImportDetail:
    row = get_import(conn, import_id)
    if row is None:
        raise not_found("Import not found.", "Check the id.")
    return _detail(row, list_batches(conn, import_id))


def _append_notes(conn: psycopg.Connection, import_id: str, notes: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE import_file SET notes = notes || %s WHERE id = %s", (Jsonb(notes), import_id)
        )


def run_import_pipeline(conn: psycopg.Connection, import_id: str, *, commit: bool) -> list[str]:
    """Load every pending batch, then the steps that make the rows visible.
    Every stage's outcome is appended to the import's notes."""
    ctx = RunContext(conn, get_settings(), commit_checkpoints=commit)
    stages: list[str] = []
    loaded = load_import(ctx, import_id)
    stages.append(
        f"load: {loaded.processed} batch(es) loaded, {loaded.failed} failed, "
        f"{loaded.skipped} already done"
    )
    discover()  # the CLI does this at start-up; the API must too
    components = registered_components()
    for name in AFTER_LOAD:
        spec = components.get(name)
        if spec is None:
            stages.append(f"{name}: not available")
            continue
        try:
            r = spec.fn(ctx)
            stages.append(f"{name}: processed={r.processed} skipped={r.skipped} failed={r.failed}")
        except Exception as exc:  # noqa: BLE001 -- a later stage must not undo the load
            logger.exception("import %s: stage %s failed", import_id, name)
            stages.append(f"{name}: failed -- {type(exc).__name__}: {exc}"[:300])
            conn.rollback()
        ctx.checkpoint()
    _append_notes(conn, import_id, [f"{datetime.now(UTC).isoformat(timespec='seconds')} {s}"
                                    for s in stages])
    if commit:
        conn.commit()
    return stages


def _pipeline_in_background(import_id: str) -> None:
    settings = get_settings()
    try:
        with lge_db.connect(settings.dsn) as conn:
            run_import_pipeline(conn, import_id, commit=True)
    except Exception:  # noqa: BLE001 -- logged; the import row records the failure
        logger.exception("import %s: pipeline failed", import_id)
        try:
            with lge_db.connect(settings.dsn) as conn, conn.cursor() as cur:
                cur.execute("UPDATE import_file SET status = 'failed' WHERE id = %s", (import_id,))
                conn.commit()
        except Exception:  # noqa: BLE001
            logger.exception("import %s: could not record the failure", import_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/imports", response_model=ImportsResponse)
def list_imports(conn: ConnDep) -> ImportsResponse:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM import_file ORDER BY created_at DESC LIMIT 200")
        rows = cur.fetchall()
        cur.execute(
            "SELECT import_id, status FROM import_batch WHERE import_id = ANY(%s::uuid[])",
            ([str(r["id"]) for r in rows],),
        )
        by_import: dict[str, list[dict[str, Any]]] = {}
        for b in cur.fetchall():
            by_import.setdefault(str(b["import_id"]), []).append(b)
    return ImportsResponse(items=[_summary(r, by_import.get(str(r["id"]), [])) for r in rows])


@router.post("/imports", response_model=ImportDetail, status_code=201)
def upload_import(
    conn: ConnDep,
    file: UploadFile = File(...),  # noqa: B008 -- FastAPI's declaration style
    source_tag: str = Form("internal_firms"),
    batch_size: int = Form(DEFAULT_BATCH_SIZE),
) -> ImportDetail:
    # A plain `def`: FastAPI runs it on the threadpool, so parsing a large
    # sheet and the column reader's model call never block the event loop.
    name = file.filename or "upload.csv"
    if not name.lower().endswith(_ALLOWED_SUFFIXES):
        raise api_error(
            422, "validation_error", f"'{name}' is not a CSV or XLSX file.",
            "Upload a .csv, .tsv or .xlsx file.",
        )
    data = file.file.read()
    if not data:
        raise api_error(422, "validation_error", "The file is empty.")
    if len(data) > _MAX_BYTES:
        raise api_error(
            413, "too_large", "The file is over 50 MB.", "Split it and upload the parts."
        )
    if not MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE:
        raise api_error(
            422, "validation_error",
            f"batch_size must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}.",
        )
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe = _SAFE_NAME_RE.sub("_", Path(name).name)[:120]
    stored = IMPORT_DIR / f"{uuid.uuid4().hex[:8]}_{safe}"
    stored.write_bytes(data)
    row = register_import(
        conn, stored, file_name=name, source_tag=source_tag, batch_size=batch_size
    )
    if row["row_count"] == 0:
        raise api_error(422, "validation_error", "No rows were found in the file.")
    return _detail(row, list_batches(conn, str(row["id"])))


@router.get("/imports/{import_id}", response_model=ImportDetail)
def get_import_detail(import_id: str, conn: ConnDep) -> ImportDetail:
    return _load_detail(conn, import_id)


@router.put("/imports/{import_id}/mapping", response_model=ImportDetail)
def put_mapping(import_id: str, body: MappingRequest, conn: ConnDep) -> ImportDetail:
    if get_import(conn, import_id) is None:
        raise not_found("Import not found.", "Check the id.")
    try:
        update_mapping(conn, import_id, body.overrides)
    except ValueError as exc:
        raise api_error(
            409, "conflict", str(exc), "The map can only change before loading."
        ) from exc
    return _load_detail(conn, import_id)


@router.post("/imports/{import_id}/load", response_model=ImportLoadResponse)
def start_load(
    import_id: str, conn: ConnDep, background: BackgroundTasks, sync: bool = False
) -> ImportLoadResponse:
    row = get_import(conn, import_id)
    if row is None:
        raise not_found("Import not found.", "Check the id.")
    if row["status"] == "loading":
        raise api_error(
            409, "conflict", "This import is already loading.", "Wait for it to finish."
        )
    if row["status"] == "loaded":
        return ImportLoadResponse(id=import_id, status="loaded", message="Already loaded.")
    if sync:
        stages = run_import_pipeline(conn, import_id, commit=False)
        final = get_import(conn, import_id)
        return ImportLoadResponse(
            id=import_id, status=final["status"] if final else "failed", message="; ".join(stages)
        )
    # The status flip must not ride the request's transaction: that transaction
    # stays open until the request tears down, which is after the background
    # task runs -- and the task's first write on this row would wait on the
    # lock forever. A short autocommit connection makes it visible at once.
    with lge_db.connect(get_settings().dsn, autocommit=True) as flip, flip.cursor() as cur:
        cur.execute("UPDATE import_file SET status = 'loading' WHERE id = %s", (import_id,))
    background.add_task(_pipeline_in_background, import_id)
    return ImportLoadResponse(
        id=import_id, status="loading",
        message=f"Loading {row['row_count']} rows in batches of {row['batch_size']}.",
    )
