from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import psycopg
import pytest

# Tests never reach a paid provider: the seams are pinned to their keyless
# implementations before lge.settings is first read (brain/plan/plan-v2.md).
os.environ.setdefault("LGE_COLUMN_READER", "rules")
os.environ.setdefault("LGE_SEARCH_ENGINE", "ddg")
os.environ.setdefault("LGE_EMAIL_FINDER", "none")
os.environ.setdefault("LGE_EMAIL_VERIFIER", "none")


from lge import db as lge_db
from lge.settings import get_settings


def _server_reachable(dsn: str) -> bool:
    try:
        conn = lge_db.connect(dsn, autocommit=True)
    except Exception:
        return False
    conn.close()
    return True


@pytest.fixture(scope="session")
def test_dsn() -> Iterator[str]:
    """A fresh, isolated database for this test session: created, migrated,
    yielded, then dropped. Multiple agents run pytest concurrently against
    this Postgres server, so a random database name per session is what
    keeps them from colliding.
    """
    settings = get_settings()
    admin_dsn = settings.admin_dsn

    if not _server_reachable(admin_dsn):
        pytest.skip(f"Postgres unreachable at {admin_dsn!r} -- db tests skipped")

    db_name = f"lge_test_{secrets.token_hex(4)}"

    with lge_db.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')

    base = admin_dsn.rsplit("/", 1)[0]
    dsn = f"{base}/{db_name}"

    # LGE_TEST_MIGRATIONS="001,002,003,004,020" limits the session to the foundation
    # plus one builder's own migration, isolating it from other in-progress files.
    only = [p.strip() for p in os.environ.get("LGE_TEST_MIGRATIONS", "").split(",") if p.strip()]
    lge_db.migrate(dsn, only=only or None)

    yield dsn

    with lge_db.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (db_name,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


@pytest.fixture
def db(test_dsn: str) -> Iterator[psycopg.Connection]:
    """A connection to the test database, wrapped in a transaction that is
    rolled back after the test -- every test starts from a clean schema with
    no rows."""
    conn = lge_db.connect(test_dsn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def expect_db_error(conn: psycopg.Connection, match: str) -> Iterator[None]:
    """Assert the wrapped block raises a psycopg error matching `match`,
    without poisoning the caller's outer transaction: runs inside a nested
    `conn.transaction()` (a savepoint), which rolls back to before the
    block on error."""
    with pytest.raises(psycopg.Error, match=match), conn.transaction():
        yield


def make_firm(conn: psycopg.Connection, **cols: object) -> str:
    """Insert a firm row under writer('reconcile') and return its id.
    Later agents reuse this factory -- keep its defaults broad enough to
    satisfy the NOT NULL columns without callers needing to know every one.
    """
    cols.setdefault("id", str(uuid.uuid4()))
    cols.setdefault("canonical_name", "Test Firm")
    cols.setdefault("name_stem", "test firm")
    cols.setdefault("first_seen", datetime.now(UTC))
    cols.setdefault("entity_kind", "private_firm")
    cols.setdefault("country", "US")
    cols.setdefault("attorney_count", 5)
    cols.setdefault("has_inhouse_recruiter", False)

    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]

    with lge_db.writer(conn, "reconcile"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO firm ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        row = cur.fetchone()
    return row["id"]
