"""r1_enrich tests: inert default + tier-gated, owner/admin-gap-only
selection. No real vendor is contracted -- these tests cover the interface,
selection query, and (via a fake adapter) the budget/idempotency machinery
built ahead of a real one. Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,060,070 \
        uv run pytest tests/planes/r -q
"""

from __future__ import annotations

import uuid

import pytest

from lge.planes.r import r1_enrich
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_contact(conn, firm_id, **cols) -> str:
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("full_name", "Existing Contact")
    columns = list(cols.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({', '.join(columns)}) VALUES ({placeholders})",  # noqa: S608
            [cols[c] for c in columns],
        )


def test_inert_by_default(db):
    make_firm(db, tier="1A")

    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 1
    assert result.processed == 0
    assert any("inert: no enrichment provider configured" in n for n in result.notes)


def test_selection_excludes_dq_tiers(db):
    make_firm(db, tier="DQ_SIZE")
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 0  # not even selected -- filtered before the inert count


def test_selection_excludes_untiered_firms(db):
    make_firm(db, tier=None)
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 0


def test_selection_excludes_firms_with_owner_or_admin_already(db):
    firm_id = make_firm(db, tier="1B")
    _insert_contact(db, firm_id, role="owner")
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 0


def test_selection_includes_tiered_firm_with_only_attorney_contact(db):
    firm_id = make_firm(db, tier="1B")
    _insert_contact(db, firm_id, role="attorney")  # attorney alone is still a gap
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 1


def test_fake_adapter_respects_budget_and_idempotency(db, monkeypatch):
    firm_a = make_firm(db, tier="2")
    firm_b = make_firm(db, tier="2")

    calls: list[str] = []

    def _fake_enrich(firm_id, *, cfg):
        calls.append(firm_id)
        return r1_enrich.EnrichResult(contacts=[], cost_usd=5.0, raw={})

    monkeypatch.setitem(r1_enrich._ADAPTERS, "fake", _fake_enrich)

    result = r1_enrich.run(_ctx(db), provider="fake", max_usd="5.0")
    assert result.processed == 1
    assert result.skipped == 1  # the second firm hits the budget stop
    assert len(calls) == 1
    assert any("budget stop" in n for n in result.notes)

    # Re-run with a much larger budget: the firm already paid for is never
    # called again (ctx.once), only the previously budget-stopped one is.
    result2 = r1_enrich.run(_ctx(db), provider="fake", max_usd="100.0")
    assert result2.processed == 1
    assert len(calls) == 2
    assert {firm_a, firm_b} == set(calls)
