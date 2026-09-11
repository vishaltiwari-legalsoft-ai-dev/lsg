"""Migrations apply cleanly and are re-run-safe; a changed applied file is
refused rather than silently re-applied."""

from __future__ import annotations

import pytest

from lge import db as lge_db

pytestmark = pytest.mark.db


def test_migrate_twice_is_noop(test_dsn: str) -> None:
    # test_dsn's session fixture already ran migrate() once during setup.
    applied = lge_db.migrate(test_dsn)
    assert applied == []


def test_checksum_drift_raises(test_dsn: str) -> None:
    conn = lge_db.connect(test_dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT checksum FROM schema_migrations WHERE filename = '001_schema.sql'"
            )
            original = cur.fetchone()
            assert original is not None

            cur.execute(
                "UPDATE schema_migrations SET checksum = 'deadbeef' "
                "WHERE filename = '001_schema.sql'"
            )

        with pytest.raises(RuntimeError, match="checksum"):
            lge_db.migrate(test_dsn)
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE schema_migrations SET checksum = %s WHERE filename = '001_schema.sql'",
                (original["checksum"],),
            )
        conn.close()
