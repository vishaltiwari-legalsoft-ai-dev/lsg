"""r1_enrich: inert without a vendor, tier-gated gap-only selection (no
decision-maker, or one without an address), and the Hunter adapter against
recorded answers -- an address for a known person, people for a firm with
nobody, only decision-makers taken, Hunter's verdicts mapped onto OUR
status vocabulary. respx mocks every call; nothing here reaches Hunter."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from lge.planes.r import r1_enrich
from lge.registry import RunContext
from lge.settings import Settings, get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn, settings: Settings | None = None) -> RunContext:
    return RunContext(conn, settings or get_settings())


def _hunter_settings() -> Settings:
    return Settings(dsn="", admin_dsn="", object_store=".", user_agent="", anthropic_api_key="",
                    openrouter_api_key="", live=False, email_finder="hunter", hunter_api_key="k")


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
    return cols["id"]


def _emails(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.full_name, c.role, c.source, e.email, e.status, e.vendor_status "
            "FROM contact c JOIN contact_email e ON e.contact_id = c.id "
            "WHERE c.firm_id = %s ORDER BY c.full_name, e.email",
            (firm_id,),
        )
        return cur.fetchall()


def test_inert_by_default(db):
    make_firm(db, tier="1A")

    result = r1_enrich.run(_ctx(db))  # conftest pins LGE_EMAIL_FINDER=none
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


def test_selection_excludes_firms_whose_owner_has_an_address(db):
    firm_id = make_firm(db, tier="1B")
    cid = _insert_contact(db, firm_id, role="owner")
    with db.cursor() as cur:
        cur.execute("INSERT INTO contact_email (contact_id, email, status) VALUES (%s, %s, %s)",
                    (cid, "owner@firm.example", "unverified"))
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 0


def test_selection_includes_an_owner_without_an_address(db):
    firm_id = make_firm(db, tier="1B")
    _insert_contact(db, firm_id, role="owner")  # known by name, no email: a gap
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 1


def test_selection_includes_tiered_firm_with_only_attorney_contact(db):
    firm_id = make_firm(db, tier="1B")
    _insert_contact(db, firm_id, role="attorney")  # attorney alone is still a gap
    result = r1_enrich.run(_ctx(db))
    assert result.skipped == 1


def test_provider_follows_the_settings_then_config_then_the_option():
    cfg_auto = {"provider": "auto"}
    assert r1_enrich.provider_for(cfg_auto, _hunter_settings()) == "hunter"
    assert r1_enrich.provider_for(cfg_auto, get_settings()) == "none"
    assert r1_enrich.provider_for({"provider": "none"}, _hunter_settings()) == "hunter"
    assert r1_enrich.provider_for({"provider": "other"}, _hunter_settings()) == "other"
    assert r1_enrich.provider_for(cfg_auto, get_settings(), "hunter") == "hunter"
    assert r1_enrich.api_key_for("hunter", _hunter_settings()) == "k"
    assert r1_enrich.api_key_for("none", _hunter_settings()) == ""


def test_fake_adapter_respects_budget_and_idempotency(db, monkeypatch):
    firm_a = make_firm(db, tier="2")
    firm_b = make_firm(db, tier="2")

    calls: list[str] = []

    def _fake_enrich(conn, firm_id, *, cfg, api_key, client):
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


@respx.mock
def test_hunter_finds_the_address_of_a_known_decision_maker(db):
    firm_id = make_firm(db, tier="1A", domain="hartleylaw.com")
    owner = _insert_contact(db, firm_id, full_name="Margaret Hartley", role="owner",
                            confidence=0.9)
    _insert_contact(db, firm_id, full_name="Dana Whitfield", role="attorney")
    finder = respx.get(r1_enrich.HUNTER_FINDER_URL).mock(return_value=httpx.Response(200, json={
        "data": {"first_name": "Margaret", "last_name": "Hartley",
                 "email": "Margaret.Hartley@hartleylaw.com", "score": 92,
                 "verification": {"date": "2026-09-01", "status": "valid"}},
    }))
    domain = respx.get(r1_enrich.HUNTER_DOMAIN_URL)

    result = r1_enrich.run(_ctx(db, _hunter_settings()))
    assert result.processed == 1 and result.failed == 0, result.notes
    assert finder.calls.last.request.url.params["domain"] == "hartleylaw.com"
    assert finder.calls.last.request.url.params["last_name"] == "Hartley"
    assert domain.call_count == 0  # the firm has a decision-maker: no domain search
    rows = _emails(db, firm_id)
    assert rows == [{"full_name": "Margaret Hartley", "role": "owner", "source": None,
                     "email": "margaret.hartley@hartleylaw.com", "status": "valid",
                     "vendor_status": "hunter:92"}]
    assert "addresses attached 1" in result.notes[0]

    # the same person again is a no-op; a re-run does not pay twice
    again = r1_enrich.run(_ctx(db, _hunter_settings()))
    assert again.processed == 0 and finder.call_count == 1
    assert owner  # the contact row itself was never touched


@respx.mock
def test_hunter_domain_search_adds_only_decision_makers(db):
    firm_id = make_firm(db, tier="1A", domain="doelaw.com")
    _insert_contact(db, firm_id, full_name="Some Attorney", role="attorney")
    respx.get(r1_enrich.HUNTER_DOMAIN_URL).mock(return_value=httpx.Response(200, json={
        "data": {"domain": "doelaw.com", "organization": "Doe Law", "emails": [
            {"value": "jane@doelaw.com", "type": "personal", "confidence": 94,
             "first_name": "Jane", "last_name": "Doe", "position": "Managing Partner",
             "seniority": "executive", "linkedin": "https://www.linkedin.com/in/jane-doe",
             "verification": {"status": "accept_all"}},
            {"value": "pat@doelaw.com", "type": "personal", "confidence": 80,
             "first_name": "Pat", "last_name": "Lee", "position": "Paralegal",
             "seniority": "junior", "verification": None},
            {"value": "sam@doelaw.com", "type": "personal", "confidence": 70,
             "first_name": "Sam", "last_name": "Roe", "position": "Office Manager",
             "seniority": "senior", "verification": None},
        ]},
    }))

    result = r1_enrich.run(_ctx(db, _hunter_settings()))
    assert result.processed == 1 and result.failed == 0, result.notes
    rows = _emails(db, firm_id)
    assert [(r["full_name"], r["role"], r["source"], r["status"]) for r in rows] == [
        ("Jane Doe", "owner", "hunter", "catch_all"),  # accept_all is a failure, not a pass
        ("Sam Roe", "admin", "hunter", "unverified"),  # office manager, unverified for R4
    ]
    with db.cursor() as cur:
        cur.execute("SELECT full_name FROM contact WHERE firm_id = %s ORDER BY full_name",
                    (firm_id,))
        assert [r["full_name"] for r in cur.fetchall()] == ["Jane Doe", "Sam Roe", "Some Attorney"]


@respx.mock
def test_hunter_refusing_the_key_is_a_failure_that_costs_nothing(db):
    firm_id = make_firm(db, tier="1A", domain="doelaw.com")
    respx.get(r1_enrich.HUNTER_DOMAIN_URL).mock(return_value=httpx.Response(401, json={}))
    result = r1_enrich.run(_ctx(db, _hunter_settings()))
    assert result.failed == 1 and result.processed == 0
    assert any("refused the key" in n for n in result.notes)
    assert _emails(db, firm_id) == []
