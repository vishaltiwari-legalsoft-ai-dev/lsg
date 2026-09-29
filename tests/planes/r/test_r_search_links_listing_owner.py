"""The Google Business Profile has one owner. When a listings provider is
configured, r_listing reads it and r_search_links never spends a second
places call or a snippet query on the same firm; without one, the
search step's fallback still runs (28 Sep 2026)."""

from __future__ import annotations

import pytest

from lge.planes.r import r_search_links
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx
from tests.planes.r.test_r_search_links import Recorder, _search_log

pytestmark = pytest.mark.db


class Places:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, query: str):
        self.queries.append(query)
        return [{"name": "Doe Law", "rating": 4.8, "review_count": 12,
                 "url": "https://www.google.com/maps?cid=1", "category": "Law firm"}]


def test_no_second_listing_lookup_when_the_listings_seam_owns_it(db, monkeypatch):
    firm_id = make_firm(db, canonical_name="Doe Law", city="Atlanta", state="GA")
    places = Places()
    monkeypatch.setattr(r_search_links.listing_seam, "has_provider", lambda settings: True)
    result = r_search_links.run(ctx(db, live=True), search=Recorder(), places=places)
    assert places.queries == []
    assert [r["kind"] for r in _search_log(db, firm_id)] == []
    assert result.skipped == 1  # nothing to do for this firm here

    monkeypatch.setattr(r_search_links.listing_seam, "has_provider", lambda settings: False)
    result = r_search_links.run(ctx(db, live=True), search=Recorder(), places=places)
    assert places.queries == ["Doe Law Atlanta GA"]
    assert [r["kind"] for r in _search_log(db, firm_id)] == ["reviews"]
    assert result.processed == 1


def test_a_sheet_value_cannot_change_the_query():
    assert r_search_links.sweep_query('Doe "Law" site:x.com', "Atlanta") == (
        'site:linkedin.com "Doe Law" Atlanta'
    )
    assert r_search_links.linkedin_query("Doe Law", '-Jane "Doe"', None) == (
        '"Doe Law" "Jane Doe" linkedin'
    )
