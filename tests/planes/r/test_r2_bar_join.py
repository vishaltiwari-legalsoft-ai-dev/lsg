"""r2_bar_join tests: join bar-directory attorney observations to resolved
firms on name+address, on fixtures (no bar harvester exists yet). Run
isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,060,070 \
        uv run pytest tests/planes/r -q
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from lge.planes.r import r2_bar_join
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_observation(
    conn, *, source, name_stem, payload, fetched_at, addr_hash=None, city=None
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO observation "
            "(source, source_key, payload, fetched_at, name_stem, addr_hash, city) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (source, str(uuid.uuid4()), Jsonb(payload), fetched_at, name_stem, addr_hash, city),
        )
        return cur.fetchone()["id"]


def _contacts(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT full_name, role, bar_number, source FROM contact WHERE firm_id = %s",
            (firm_id,),
        )
        return cur.fetchall()


def _claims(conn, firm_id, attr) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value, source FROM firm_attribute WHERE firm_id = %s AND attr = %s",
            (firm_id, attr),
        )
        return cur.fetchall()


def test_addr_hash_match_creates_attorney_contact(db):
    firm_id = make_firm(db, name_stem="smith law group", addr_hash="addrhash-1")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_observation(
        db, source="bar:CA", name_stem="smith law group", addr_hash="addrhash-1",
        payload={
            "name": "John Smith", "bar_number": "CA12345", "status": "Active",
            "admission_date": "2010-05-01", "firm_name": "Smith Law Group",
            "address": "123 Main St",
        },
        fetched_at=now,
    )

    result = r2_bar_join.run(_ctx(db))
    assert result.processed == 1
    assert result.failed == 0

    contacts = _contacts(db, firm_id)
    assert len(contacts) == 1
    assert contacts[0]["full_name"] == "John Smith"
    assert contacts[0]["role"] == "attorney"
    assert contacts[0]["bar_number"] == "CA12345"
    assert contacts[0]["source"] == "bar:CA"


def test_managing_status_is_role_owner(db):
    firm_id = make_firm(db, name_stem="jones legal", addr_hash="addrhash-2")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_observation(
        db, source="bar:NY", name_stem="jones legal", addr_hash="addrhash-2",
        payload={
            "name": "Pat Jones", "bar_number": "NY99999", "status": "Managing Partner",
            "admission_date": "2005-01-01", "firm_name": "Jones Legal",
            "address": "1 Broadway",
        },
        fetched_at=now,
    )

    result = r2_bar_join.run(_ctx(db))
    assert result.processed == 1
    contacts = _contacts(db, firm_id)
    assert contacts[0]["role"] == "owner"


def test_same_city_match_without_address(db):
    firm_id = make_firm(db, name_stem="acme legal partners", city="Austin")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_observation(
        db, source="bar:TX", name_stem="acme legal partners", city="Austin",
        payload={
            "name": "Terry Lee", "bar_number": "TX55555", "status": "Active",
            "admission_date": "2015-06-01", "firm_name": "Acme Legal Partners",
            "address": "999 Congress Ave",
        },
        fetched_at=now,
    )

    result = r2_bar_join.run(_ctx(db))
    assert result.processed == 1
    contacts = _contacts(db, firm_id)
    assert len(contacts) == 1
    assert contacts[0]["full_name"] == "Terry Lee"


def test_no_match_writes_no_contact(db):
    make_firm(db, name_stem="alpha firm", addr_hash="addrhash-alpha", city="Boston")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_observation(
        db, source="bar:WA", name_stem="omega practice completely different",
        addr_hash="addrhash-omega", city="Seattle",
        payload={
            "name": "No Match Person", "bar_number": "WA00000", "status": "Active",
            "admission_date": "2020-01-01", "firm_name": "Omega Practice",
            "address": "1 Nowhere Rd",
        },
        fetched_at=now,
    )

    result = r2_bar_join.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 1
    assert result.failed == 0

    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM contact")
        assert cur.fetchone()["n"] == 0


def test_solo_firm_gets_first_seen_bar_admission_claim(db):
    firm_id = make_firm(db, name_stem="solo practice pllc", addr_hash="addrhash-solo")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_observation(
        db, source="bar:CA", name_stem="solo practice pllc", addr_hash="addrhash-solo",
        payload={
            "name": "Solo Attorney", "bar_number": "CA11111", "status": "Active",
            "admission_date": "2022-03-15", "firm_name": "Solo Practice PLLC",
            "address": "42 Solo Way",
        },
        fetched_at=now,
    )

    result = r2_bar_join.run(_ctx(db))
    assert result.processed == 1

    claims = _claims(db, firm_id, "first_seen_bar_admission")
    assert len(claims) == 1
    assert claims[0]["value"] == "2022-03-15"
    assert claims[0]["source"] == "bar:CA"


def test_idempotent_rerun_creates_no_duplicate_contact(db):
    firm_id = make_firm(db, name_stem="rerun law", addr_hash="addrhash-rerun")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_observation(
        db, source="bar:CA", name_stem="rerun law", addr_hash="addrhash-rerun",
        payload={
            "name": "Rerun Attorney", "bar_number": "CA22222", "status": "Active",
            "admission_date": "2018-01-01", "firm_name": "Rerun Law",
            "address": "7 Loop St",
        },
        fetched_at=now,
    )

    first = r2_bar_join.run(_ctx(db))
    assert first.processed == 1
    assert len(_contacts(db, firm_id)) == 1

    second = r2_bar_join.run(_ctx(db))
    assert second.processed == 0
    assert second.skipped == 1
    assert len(_contacts(db, firm_id)) == 1
