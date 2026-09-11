"""r5_phone tests: normalise contact.phone_direct (falling back to
firm.phone_e164) into contact.phone_e164 + an honest phone_line_type; DNC
scrub stays 'unknown' (inert -- no provider under contract). Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,060,070 \
        uv run pytest tests/planes/r -q
"""

from __future__ import annotations

import uuid

import pytest

from lge.norm import norm_phone
from lge.planes.r import r5_phone
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_contact(conn, firm_id, full_name, **cols) -> str:
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols["full_name"] = full_name
    columns = list(cols.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({', '.join(columns)}) VALUES ({placeholders}) "  # noqa: S608
            "RETURNING id",
            [cols[c] for c in columns],
        )
        return cur.fetchone()["id"]


def _contact_row(conn, contact_id) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT phone_e164, phone_line_type, dnc_status FROM contact WHERE id = %s",
            (contact_id,),
        )
        return cur.fetchone()


def test_normalises_phone_direct(db):
    firm_id = make_firm(db)
    contact_id = _insert_contact(db, firm_id, "Jane Doe", phone_direct="(212) 555-1212")

    result = r5_phone.run(_ctx(db))
    assert result.processed == 1
    assert result.failed == 0
    assert any("inert: no DNC provider configured" in n for n in result.notes)

    row = _contact_row(db, contact_id)
    assert row["phone_e164"] == norm_phone("(212) 555-1212")
    assert row["phone_line_type"] == r5_phone.line_type(row["phone_e164"])
    assert row["dnc_status"] == "unknown"


def test_falls_back_to_firm_phone_when_contact_has_none(db):
    firm_phone = norm_phone("212-555-9999")
    assert firm_phone is not None
    firm_id = make_firm(db, phone_e164=firm_phone)
    contact_id = _insert_contact(db, firm_id, "Solo Practitioner", phone_direct=None)

    result = r5_phone.run(_ctx(db))
    assert result.processed == 1

    row = _contact_row(db, contact_id)
    assert row["phone_e164"] == firm_phone


def test_no_usable_number_is_skipped(db):
    firm_id = make_firm(db)  # no phone_e164
    contact_id = _insert_contact(db, firm_id, "No Phone", phone_direct="not-a-number")

    result = r5_phone.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 1

    row = _contact_row(db, contact_id)
    assert row["phone_e164"] is None
    assert row["phone_line_type"] is None


def test_already_normalised_contacts_are_left_alone(db):
    firm_id = make_firm(db)
    e164 = norm_phone("(212) 555-1212")
    contact_id = _insert_contact(
        db, firm_id, "Already Done", phone_direct="(212) 555-1212",
        phone_e164=e164, phone_line_type="mobile",
    )

    result = r5_phone.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 0  # excluded by the WHERE clause entirely, not even considered

    row = _contact_row(db, contact_id)
    assert row["phone_line_type"] == "mobile"  # untouched
