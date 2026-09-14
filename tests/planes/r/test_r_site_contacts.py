"""r_site_contacts tests: LLM decision_makers + P5 jsonld_people claims
become `contact` rows, deduped by normalised person name against existing
(vendor) contacts. Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,060,070 \
        uv run pytest tests/planes/r -q
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from lge.planes.r import r_site_contacts
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _write_claim(conn, firm_id, attr, value, source, confidence, observed_at) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, "
            "evidence, observed_at) VALUES (%s, %s, %s, %s, %s, NULL, %s)",
            (firm_id, attr, Jsonb(value), source, confidence, observed_at),
        )


def _insert_contact(conn, firm_id, **cols) -> str:
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("full_name", "Test Person")
    columns = list(cols.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({', '.join(columns)}) VALUES ({placeholders}) "  # noqa: S608
            "RETURNING id",
            [cols[c] for c in columns],
        )
        return cur.fetchone()["id"]


def _contacts(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, full_name, title, role, source, confidence FROM contact "
            "WHERE firm_id = %s ORDER BY full_name",
            (firm_id,),
        )
        return cur.fetchall()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Paul A. Greenberg - Personal Injury Lawyer", "Paul A. Greenberg"),  # suffix is a title
        ("Jeremy D. Raincrow, J.D., Ph.D.", "Jeremy D. Raincrow"),  # credentials after the comma
        ("C. Richard (Rick) Rayburn, Jr.", "C. Richard (Rick) Rayburn"),
        ("Rich Kovarsky, Pe, Dfe, Cfi, Cfei", "Rich Kovarsky"),
        ("Attorney Tiffany Lunn", "Tiffany Lunn"),  # honorific, not a practice word
        ("Michael Lijoi Jr.", "Michael Lijoi"),  # credentials with no comma
        ("Elena Butko Esq.", "Elena Butko"),
        ("Robert C Hahn, Iii", "Robert C Hahn"),
        ("Shana De Caro", "Shana De Caro"),
        ("Valerie Harris Adler", "Valerie Harris Adler"),
        ("Chicago Injury Attorneys Near Northwestern Memorial Hospital", None),
        ("Chicago Car Accident Center", None),
        ("Lawyers With An Edge", None),
        ("Rosenberg, Minc, Falkoff &amp; Wolff, LLP.", None),
        ("Friend, Levinson & Turner LTD", None),
        ("Arizona Litigation Support Court Reporters", None),
        ("Briskman Briskman Greenberg LLC", None),
        ("Law Office of Jane Doe", None),
        ("24/7 Intake Team", None),
        ("Madonna", None),  # one token is not a person we can address
        ("", None),
    ],
)
def test_person_name_rejects_page_titles_and_firm_names(raw, expected):
    assert r_site_contacts.person_name(raw) == expected


def test_page_titles_in_claims_never_become_contacts(db):
    firm_id = make_firm(db)
    _write_claim(
        db, firm_id, "jsonld_people",
        [{"name": "Chicago Injury Attorneys Near Northwestern Memorial Hospital",
          "title": "Attorney"},
         {"name": "Paul A. Greenberg - Personal Injury Lawyer", "title": "Partner"}],
        "site:jsonld", 0.95, datetime(2026, 9, 15, tzinfo=UTC),
    )
    r_site_contacts.run(_ctx(db))
    assert [c["full_name"] for c in _contacts(db, firm_id)] == ["Paul A. Greenberg"]


def test_llm_owner_and_jsonld_office_manager_become_contacts(db):
    firm_id = make_firm(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _write_claim(
        db, firm_id, "decision_makers",
        [{
            "name": "Jane Doe", "title": "Owner", "role": "owner",
            "evidence": "Jane Doe is the founder and owner of the firm.",
        }],
        "llm:p8:v2", 1.0, now,
    )
    _write_claim(
        db, firm_id, "jsonld_people",
        [{"name": "Bob Roe", "title": "Office Manager"}],
        "site:jsonld", 0.95, now,
    )

    result = r_site_contacts.run(_ctx(db))
    assert result.processed == 1
    assert result.failed == 0

    contacts = _contacts(db, firm_id)
    assert {c["full_name"] for c in contacts} == {"Jane Doe", "Bob Roe"}

    jane = next(c for c in contacts if c["full_name"] == "Jane Doe")
    assert jane["role"] == "owner"
    assert jane["title"] == "Owner"
    assert jane["source"] == "site:llm"

    bob = next(c for c in contacts if c["full_name"] == "Bob Roe")
    assert bob["role"] == "admin"  # classify_role("Office Manager")
    assert bob["title"] == "Office Manager"
    assert bob["source"] == "site:jsonld"


def test_dedupe_against_vendor_contact_upgrades_title(db):
    firm_id = make_firm(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    vendor_id = _insert_contact(
        db, firm_id, full_name="Jane Q. Doe", title="Attorney",
        role=None, source="internal_firms", confidence=None,
    )

    _write_claim(
        db, firm_id, "decision_makers",
        [{
            "name": "Jane Doe", "title": "Managing Partner", "role": "owner",
            "evidence": "Jane Doe, our managing partner, founded the firm.",
        }],
        "llm:p8:v2", 1.0, now,
    )

    result = r_site_contacts.run(_ctx(db))
    assert result.processed == 1

    contacts = _contacts(db, firm_id)
    assert len(contacts) == 1  # no duplicate row -- the vendor row was upgraded, not doubled
    assert contacts[0]["id"] == vendor_id
    assert contacts[0]["title"] == "Managing Partner"
    assert contacts[0]["role"] == "owner"
    assert contacts[0]["source"] == "site:llm"


def test_ungrounded_name_never_appears(db):
    """Grounding already ran upstream (lge.llm.grounding.ground) before a
    decision_makers claim is written -- this component adds no invention of
    its own. Only the names present in the claim's value list may appear;
    nothing beyond that list is ever written."""
    firm_id = make_firm(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _write_claim(
        db, firm_id, "decision_makers",
        [{
            "name": "Real Person", "title": "Owner", "role": "owner",
            "evidence": "Real Person owns the firm.",
        }],
        "llm:p8:v2", 1.0, now,
    )

    result = r_site_contacts.run(_ctx(db))
    assert result.processed == 1

    contacts = _contacts(db, firm_id)
    assert {c["full_name"] for c in contacts} == {"Real Person"}
    assert "Hallucinated Person" not in {c["full_name"] for c in contacts}


def test_idempotent_rerun_writes_nothing_new(db):
    firm_id = make_firm(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _write_claim(
        db, firm_id, "decision_makers",
        [{
            "name": "Jane Doe", "title": "Owner", "role": "owner",
            "evidence": "Jane Doe is the owner.",
        }],
        "llm:p8:v2", 1.0, now,
    )

    first = r_site_contacts.run(_ctx(db))
    assert first.processed == 1
    before = len(_contacts(db, firm_id))
    assert before == 1

    second = r_site_contacts.run(_ctx(db))
    assert second.processed == 0
    assert second.skipped == 1
    assert len(_contacts(db, firm_id)) == before


def test_no_claims_is_skipped(db):
    firm_id = make_firm(db)
    result = r_site_contacts.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 0  # no firm even selected -- nothing has a claim
    assert _contacts(db, firm_id) == []
