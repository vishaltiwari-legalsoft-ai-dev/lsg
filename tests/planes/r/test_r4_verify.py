"""r4_verify tests: provider status mapping (catch_all/risky are failures,
only 'valid' is a pass), tier gate, budget stop, per-(email,provider)
idempotency, inert without a configured key. respx mocks every provider
call -- these tests never touch the network. Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,060,070 \
        uv run pytest tests/planes/r -q
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from lge.planes.r import r4_verify
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _insert_contact_with_email(
    conn, firm_id, *, role, email, status="unverified"
) -> tuple[str, str]:
    contact_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact (id, firm_id, full_name, role) VALUES (%s, %s, %s, %s)",
            (contact_id, firm_id, "Test Contact", role),
        )
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status) VALUES (%s, %s, %s)",
            (contact_id, email, status),
        )
    return contact_id, email


def _email_status(conn, contact_id, email) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM contact_email WHERE contact_id = %s AND email = %s",
            (contact_id, email),
        )
        return cur.fetchone()["status"]


def _attempt_count(conn, email, provider) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM verify_attempt WHERE email = %s AND provider = %s",
            (email, provider),
        )
        return cur.fetchone()["n"]


def test_inert_without_api_key(db, monkeypatch):
    monkeypatch.delenv("ZEROBOUNCE_API_KEY", raising=False)
    firm_id = make_firm(db, tier="1A")
    _insert_contact_with_email(db, firm_id, role="owner", email="owner@example.com")

    result = r4_verify.run(_ctx(db), provider="zerobounce")
    assert result.processed == 0
    assert result.skipped == 1
    assert any("inert: no verification provider configured" in n for n in result.notes)


def test_inert_when_provider_none(db):
    firm_id = make_firm(db, tier="1A")
    _insert_contact_with_email(db, firm_id, role="owner", email="owner@example.com")
    result = r4_verify.run(_ctx(db))  # default provider: none
    assert result.processed == 0
    assert result.skipped == 1


def test_tier_gate_excludes_dq_firms(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    dq_firm = make_firm(db, tier="DQ_SIZE")
    _insert_contact_with_email(db, dq_firm, role="owner", email="dq@example.com")

    with respx.mock:
        route = respx.get(r4_verify._ZEROBOUNCE_URL).mock(
            return_value=httpx.Response(200, json={"status": "valid"})
        )
        result = r4_verify.run(_ctx(db), provider="zerobounce")

    assert route.call_count == 0
    assert result.processed == 0
    assert result.skipped == 0  # excluded from selection entirely -- not even counted


def test_tier_gate_excludes_untiered_firms(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    untiered = make_firm(db, tier=None)
    _insert_contact_with_email(db, untiered, role="owner", email="untiered@example.com")

    with respx.mock:
        route = respx.get(r4_verify._ZEROBOUNCE_URL).mock(
            return_value=httpx.Response(200, json={"status": "valid"})
        )
        result = r4_verify.run(_ctx(db), provider="zerobounce")

    assert route.call_count == 0
    assert result.processed == 0


def test_selection_excludes_attorney_role(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    _insert_contact_with_email(db, firm_id, role="attorney", email="associate@example.com")

    with respx.mock:
        route = respx.get(r4_verify._ZEROBOUNCE_URL).mock(
            return_value=httpx.Response(200, json={"status": "valid"})
        )
        result = r4_verify.run(_ctx(db), provider="zerobounce")

    assert route.call_count == 0
    assert result.processed == 0


@respx.mock
def test_zerobounce_valid_is_a_pass(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    contact_id, email = _insert_contact_with_email(
        db, firm_id, role="owner", email="owner@acme.com"
    )
    respx.get(r4_verify._ZEROBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"address": email, "status": "valid"})
    )

    result = r4_verify.run(_ctx(db), provider="zerobounce")
    assert result.processed == 1
    assert result.failed == 0
    assert _email_status(db, contact_id, email) == "valid"
    assert _attempt_count(db, email, "zerobounce") == 1


@respx.mock
def test_zerobounce_catch_all_is_a_failure_not_a_pass(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    contact_id, email = _insert_contact_with_email(
        db, firm_id, role="admin", email="admin@acme.com"
    )
    respx.get(r4_verify._ZEROBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"address": email, "status": "catch-all"})
    )

    result = r4_verify.run(_ctx(db), provider="zerobounce")
    assert result.processed == 1
    status = _email_status(db, contact_id, email)
    assert status == "catch_all"
    assert status != "valid"


@respx.mock
def test_zerobounce_risky_is_a_failure_not_a_pass(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    contact_id, email = _insert_contact_with_email(
        db, firm_id, role="owner", email="risky@acme.com"
    )
    respx.get(r4_verify._ZEROBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"address": email, "status": "unknown"})
    )

    result = r4_verify.run(_ctx(db), provider="zerobounce")
    assert result.processed == 1
    status = _email_status(db, contact_id, email)
    assert status == "risky"
    assert status != "valid"


@respx.mock
def test_neverbounce_status_mapping(db, monkeypatch):
    monkeypatch.setenv("NEVERBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1B")
    contact_id, email = _insert_contact_with_email(
        db, firm_id, role="owner", email="owner@nb.com"
    )
    respx.get(r4_verify._NEVERBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"status": "success", "result": "catchall"})
    )

    result = r4_verify.run(_ctx(db), provider="neverbounce")
    assert result.processed == 1
    assert _email_status(db, contact_id, email) == "catch_all"


@respx.mock
def test_budget_stop(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_a = make_firm(db, tier="1A")
    firm_b = make_firm(db, tier="1A")
    _insert_contact_with_email(db, firm_a, role="owner", email="a@acme.com")
    _insert_contact_with_email(db, firm_b, role="owner", email="b@acme.com")

    route = respx.get(r4_verify._ZEROBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"status": "valid"})
    )
    # config/resolvers.yml: price_per_email_usd.zerobounce == 0.007
    result = r4_verify.run(_ctx(db), provider="zerobounce", max_usd="0.007")

    assert route.call_count == 1
    assert result.processed == 1
    assert result.skipped == 1
    assert any("budget stop" in n for n in result.notes)


@respx.mock
def test_idempotent_no_second_call_on_rerun(db, monkeypatch):
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_id = make_firm(db, tier="1A")
    _insert_contact_with_email(db, firm_id, role="owner", email="owner@acme.com")
    route = respx.get(r4_verify._ZEROBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"status": "valid"})
    )

    first = r4_verify.run(_ctx(db), provider="zerobounce")
    assert first.processed == 1
    assert route.call_count == 1

    second = r4_verify.run(_ctx(db), provider="zerobounce")
    assert second.processed == 0
    assert route.call_count == 1  # never billed twice for the same address


@respx.mock
def test_idempotent_across_different_contacts_same_email(db, monkeypatch):
    """The verify_attempt guard is a (email, provider) dedupe, not merely a
    contact_email.status filter -- two different contacts (different firms)
    claiming the same email address must still only ever be billed once."""
    monkeypatch.setenv("ZEROBOUNCE_API_KEY", "test-key")
    firm_a = make_firm(db, tier="1A")
    firm_b = make_firm(db, tier="1A")
    shared_email = "shared@sameaddr.com"
    _insert_contact_with_email(db, firm_a, role="owner", email=shared_email)
    _insert_contact_with_email(db, firm_b, role="owner", email=shared_email)

    route = respx.get(r4_verify._ZEROBOUNCE_URL).mock(
        return_value=httpx.Response(200, json={"status": "valid"})
    )
    result = r4_verify.run(_ctx(db), provider="zerobounce")

    assert route.call_count == 1
    assert result.processed == 1
    assert result.skipped == 1


@respx.mock
def test_hunter_status_mapping_and_a_pending_check_is_not_billed(db, monkeypatch):
    """Hunter's `accept_all` is a catch-all -- a failure; `valid` is the only
    pass; an answer with no data (Hunter's 222 "still checking") writes no
    attempt row, so the next run asks again (D-046)."""
    monkeypatch.setenv("HUNTER_API_KEY", "k")
    firm_id = make_firm(db, tier="1A")
    c1, e1 = _insert_contact_with_email(db, firm_id, role="owner", email="a@firm.example")
    c2, e2 = _insert_contact_with_email(db, firm_id, role="admin", email="b@firm.example")
    c3, e3 = _insert_contact_with_email(db, firm_id, role="owner", email="c@firm.example")

    def answer(request):
        email = request.url.params["email"]
        if email == e1:
            return httpx.Response(200, json={"data": {"status": "accept_all", "result": "risky"}})
        if email == e2:
            return httpx.Response(200, json={"data": {"status": "valid", "result": "deliverable"}})
        return httpx.Response(222, json={"errors": [{"id": "in_progress"}]})

    route = respx.get(r4_verify._HUNTER_URL).mock(side_effect=answer)
    result = r4_verify.run(_ctx(db), provider="hunter")
    assert route.calls.last.request.url.params["api_key"] == "k"
    assert result.processed == 2 and result.failed == 1
    assert _email_status(db, c1, e1) == "catch_all"
    assert _email_status(db, c2, e2) == "valid"
    assert _email_status(db, c3, e3) == "unverified"
    assert _attempt_count(db, e1, "hunter") == 1 and _attempt_count(db, e3, "hunter") == 0


@respx.mock
def test_the_verifier_follows_the_settings_when_config_says_auto(db):
    from lge.settings import Settings

    firm_id = make_firm(db, tier="1A")
    c1, e1 = _insert_contact_with_email(db, firm_id, role="owner", email="a@firm.example")
    respx.get(r4_verify._HUNTER_URL).mock(
        return_value=httpx.Response(200, json={"data": {"status": "valid"}})
    )
    settings = Settings(dsn="", admin_dsn="", object_store=".", user_agent="",
                        anthropic_api_key="", openrouter_api_key="", live=False,
                        email_verifier="auto", hunter_api_key="k")
    assert r4_verify.provider_for({"provider": "auto"}, settings) == "hunter"
    result = r4_verify.run(RunContext(db, settings))
    assert result.processed == 1
    assert _email_status(db, c1, e1) == "valid"
    # the test suite's own settings name no verifier: inert, as before
    assert r4_verify.provider_for({"provider": "auto"}, get_settings()) == "none"
