"""RunContext.once(): a database error inside the body is recorded as the
failure -- not masked by the failure mark itself failing inside an aborted
transaction -- and the connection stays usable for the next entity."""

from __future__ import annotations

import psycopg
import pytest

from lge.registry import RunContext
from lge.settings import get_settings

pytestmark = pytest.mark.db


def _task_run(conn, component: str, entity_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, error FROM task_run WHERE component = %s AND entity_id = %s",
            (component, entity_id),
        )
        return cur.fetchone()


def test_a_db_error_in_the_body_is_recorded_and_the_connection_survives(db):
    ctx = RunContext(db, get_settings())

    with pytest.raises(psycopg.errors.UndefinedTable):  # noqa: PT012 -- the body is the test
        with ctx.once("t_once", "firm-1", "h1") as should_run:
            assert should_run
            with db.cursor() as cur:
                cur.execute("SELECT 1 FROM table_that_does_not_exist")

    row = _task_run(db, "t_once", "firm-1")
    assert row["status"] == "failed"
    assert "table_that_does_not_exist" in row["error"]

    # the transaction is not aborted: the next entity proceeds normally
    with ctx.once("t_once", "firm-2", "h2") as should_run:
        assert should_run
        with db.cursor() as cur:
            cur.execute("SELECT 1 AS one")
            assert cur.fetchone()["one"] == 1
    assert _task_run(db, "t_once", "firm-2")["status"] == "ok"


def test_work_of_a_failed_body_is_rolled_back(db):
    ctx = RunContext(db, get_settings())
    with pytest.raises(RuntimeError):  # noqa: PT012
        with ctx.once("t_once", "firm-3", "h3"):
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO task_run (component, entity_id, input_hash, status, started_at) "
                    "VALUES ('t_side_effect', 'x', 'x', 'ok', now())"
                )
            raise RuntimeError("half way through")
    assert _task_run(db, "t_side_effect", "x") is None
    assert _task_run(db, "t_once", "firm-3")["status"] == "failed"
