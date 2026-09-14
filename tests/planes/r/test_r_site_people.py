"""r_site_contacts over px_site_facts' `site_people` claim: printed titles
classify the role, a person named without a title is still a contact (so a
printed email can attach to them), and a vendor row is upgraded, not
duplicated."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lge.planes.r import r_site_contacts
from tests.conftest import make_firm
from tests.planes.r.test_r_site_contacts import _contacts, _ctx, _insert_contact, _write_claim

pytestmark = pytest.mark.db

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_site_people_become_contacts_with_roles_from_their_titles(db):
    firm_id = make_firm(db)
    _write_claim(
        db, firm_id, "site_people",
        [
            {"name": "Margaret Hartley", "title": "Founding Partner & Trial Attorney",
             "url": "https://x/our-team/margaret-hartley/", "confidence": 0.8},
            {"name": "Priya Raman", "title": "Office Manager", "url": None, "confidence": 0.8},
            {"name": "Tom Becker", "title": None, "url": "https://x/our-team/tom-becker/",
             "confidence": 0.6},
            # a firm name slips through the extractor: person_name() still rejects it here
            {"name": "Hartley Injury Law Group", "title": None, "url": None, "confidence": 0.6},
        ],
        "site:page", 0.8, _NOW,
    )

    result = r_site_contacts.run(_ctx(db))
    assert result.processed == 1, result.notes

    by_name = {c["full_name"]: c for c in _contacts(db, firm_id)}
    assert set(by_name) == {"Margaret Hartley", "Priya Raman", "Tom Becker"}
    assert by_name["Margaret Hartley"]["role"] == "owner"
    assert by_name["Priya Raman"]["role"] == "admin"
    assert by_name["Tom Becker"]["role"] == "unknown"
    assert float(by_name["Tom Becker"]["confidence"]) == pytest.approx(0.6)
    assert all(c["source"] == "site:page" for c in by_name.values())


def test_vendor_contact_is_upgraded_by_the_site_not_duplicated(db):
    firm_id = make_firm(db)
    _insert_contact(db, firm_id, full_name="Priya Raman", role="unknown", confidence=0.3,
                    source="internal_firms")
    _write_claim(
        db, firm_id, "site_people",
        [{"name": "Priya Raman", "title": "Office Manager", "url": None, "confidence": 0.8}],
        "site:page", 0.8, _NOW,
    )
    r_site_contacts.run(_ctx(db))
    rows = _contacts(db, firm_id)
    assert len(rows) == 1
    assert rows[0]["title"] == "Office Manager"
    assert rows[0]["role"] == "admin"
