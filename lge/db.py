"""Connection, migrations, and the two transaction-local session markers
(`lge.writer`, `lge.trigger`/`lge.actor`) that the invariant triggers in
sql/001_schema.sql read via `current_setting(..., true)`.

Windows note: psycopg runs in pure-Python mode here and needs libpq.dll off
`.local/pgsql/bin`. That setup MUST happen before `import psycopg` — hence it
runs at module import time, above every other import in this file.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# libpq.dll / PSYCOPG_IMPL setup lives in lge/_bootstrap.py, which runs when the
# `lge` package is imported — always before this module.
import psycopg
from psycopg.rows import dict_row

from lge.settings import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

SQL_DIR = _PROJECT_ROOT / "sql"


def connect(dsn: str | None = None, *, autocommit: bool = False) -> psycopg.Connection:
    """Open a connection with dict-row results. Defaults to `Settings.dsn`."""
    resolved = dsn or get_settings().dsn
    conn = psycopg.connect(resolved, row_factory=dict_row, autocommit=autocommit)
    return conn


@contextmanager
def writer(conn: psycopg.Connection, name: str) -> Iterator[None]:
    """Mark the writer for `firm` column-provenance checks (I7).

    Transaction-local (`set_config(..., true)`) — it does not leak past the
    current transaction, so every write must be wrapped explicitly.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lge.writer', %s, true)", (name,))
    yield


@contextmanager
def lifecycle(conn: psycopg.Connection, trigger: str, actor: str = "system") -> Iterator[None]:
    """Mark the trigger/actor recorded on `lead_state_event` rows (I5).

    Transaction-local, same as `writer`.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lge.trigger', %s, true)", (trigger,))
        cur.execute("SELECT set_config('lge.actor', %s, true)", (actor,))
    yield


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def migrate(dsn: str, only: list[str] | None = None) -> list[str]:
    """Apply every `sql/*.sql` file in lexical order, one transaction each.

    `only` restricts the run to files whose name starts with one of the given
    prefixes (e.g. ["001", "002", "020"]). Tests use it through the
    LGE_TEST_MIGRATIONS env var so a builder's test session is not broken by
    another builder's half-written migration. Production runs never pass it.

    Tracked in `schema_migrations(filename, checksum, applied_at)`. An
    already-applied file whose content has since changed raises — a migration
    is never silently re-applied. Returns the filenames newly applied (an
    empty list if everything was already applied).
    """
    files = sorted(SQL_DIR.glob("*.sql"))
    if only:
        files = [f for f in files if f.name.startswith(tuple(only))]
    applied: list[str] = []

    with connect(dsn, autocommit=True) as bootstrap:
        with bootstrap.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename   text PRIMARY KEY,
                    checksum   text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )

    with connect(dsn) as conn:
        for path in files:
            content = path.read_text(encoding="utf-8")
            checksum = _checksum(content)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT checksum FROM schema_migrations WHERE filename = %s",
                    (path.name,),
                )
                row = cur.fetchone()

            if row is not None:
                if row["checksum"] != checksum:
                    raise RuntimeError(
                        f"migration {path.name!r} was already applied with a different "
                        f"checksum (stored {row['checksum']}, now {checksum}). "
                        "A migration is never silently re-applied — add a new numbered "
                        "file instead of editing an applied one."
                    )
                continue

            try:
                with conn.cursor() as cur:
                    cur.execute(content)
                    cur.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                        (path.name, checksum),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            applied.append(path.name)

    return applied
