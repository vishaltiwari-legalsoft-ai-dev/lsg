"""GET /api/meta/capabilities -- what is built, and what it waits on (D-059).

The page a visitor is shown and the engine's own behaviour must not drift, so
the states come from config/capabilities.yml and the on/off of each outside
service is asked of the seams.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def _keys(monkeypatch, **values):
    for name in ("OPENROUTER_API_KEY", "ZEROBOUNCE_API_KEY", "NEVERBOUNCE_API_KEY",
                 "HUNTER_API_KEY", "SERPER_API_KEY", "BRAVE_API_KEY"):
        monkeypatch.setenv(name, values.get(name, ""))
    monkeypatch.setenv("LGE_EMAIL_VERIFIER", "auto")
    monkeypatch.setenv("LGE_SEARCH_ENGINE", "auto")


def _body(client, monkeypatch, **keys):
    _keys(monkeypatch, **keys)
    from lge.settings import get_settings

    get_settings.cache_clear()
    try:
        resp = client.get("/api/meta/capabilities")
        assert resp.status_code == 200
        return resp.json()
    finally:
        get_settings.cache_clear()


def test_the_three_steps_of_the_brief_with_their_parts(client, monkeypatch):
    body = _body(client, monkeypatch, OPENROUTER_API_KEY="sk-x")
    assert [s["step"] for s in body["steps"]] == [1, 2, 3]
    assert [s["label"] for s in body["steps"]] == ["Raw leads", "Enrichment", "Handover"]
    assert all(s["parts"] for s in body["steps"])
    counted = sum(len(s["parts"]) for s in body["steps"])
    assert body["built"] + body["partial"] + body["planned"] == counted
    assert str(body["built"]) in body["summary"]


def test_a_part_waits_on_the_key_it_needs_and_stops_waiting_when_it_is_set(client, monkeypatch):
    off = _body(client, monkeypatch, OPENROUTER_API_KEY="sk-x")
    checked = next(
        p for s in off["steps"] for p in s["parts"]
        if p["label"] == "Every address checked before it is used"
    )
    assert checked["state"] == "built"
    assert checked["waiting_on"] == "Address checking"
    assert off["waiting"] >= 1
    assert "idle until a key is set" in off["summary"]

    on = _body(client, monkeypatch, OPENROUTER_API_KEY="sk-x", NEVERBOUNCE_API_KEY="nb-x")
    checked = next(
        p for s in on["steps"] for p in s["parts"]
        if p["label"] == "Every address checked before it is used"
    )
    assert checked["waiting_on"] is None
    assert on["waiting"] < off["waiting"]


def test_a_part_nobody_has_built_never_waits_on_a_key(client, monkeypatch):
    body = _body(client, monkeypatch)
    for step in body["steps"]:
        for part in step["parts"]:
            if part["state"] == "planned":
                assert part["waiting_on"] is None, part["label"]


def test_the_outside_services_say_what_they_unlock_and_never_a_key_value(client, monkeypatch):
    body = _body(client, monkeypatch, OPENROUTER_API_KEY="sk-secret-value",
                 SERPER_API_KEY="serper-secret")
    assert "sk-secret-value" not in resp_text(body)
    assert "serper-secret" not in resp_text(body)
    services = {s["id"]: s for s in body["outside"]}
    assert set(services) == {"ai", "verification", "search"}
    assert services["ai"]["on"] is True
    assert services["ai"]["key"] == "OPENROUTER_API_KEY"
    assert services["verification"]["on"] is False
    assert services["search"]["on"] is True
    assert all(s["what"] and s["cost"] for s in services.values())


def test_what_the_ai_has_cost_is_read_from_its_own_log(client, db, monkeypatch):
    from tests.conftest import make_firm

    firm_id = make_firm(db, canonical_name="Cost Law")
    with db.cursor() as cur:
        for cost in (0.01, 0.02):
            cur.execute(
                "INSERT INTO llm_call (firm_id, component, model, prompt_rev, input_chars, "
                "cost_usd, status) VALUES (%s, 'p8_llm', 'm', 'v1', 10, %s, 'ok')",
                (firm_id, cost),
            )
    body = _body(client, monkeypatch, OPENROUTER_API_KEY="sk-x")
    ai = next(s for s in body["outside"] if s["id"] == "ai")
    assert ai["spent_display"] == "$0.03 so far, over 2 readings"


def resp_text(body) -> str:
    import json

    return json.dumps(body)
