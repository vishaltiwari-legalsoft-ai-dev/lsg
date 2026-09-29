"""P9 escalation-trigger tests. Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,050 \
        uv run pytest tests/llm tests/planes/p/test_p8_llm.py tests/planes/p/test_p9_escalate.py -q

Covers every trigger in context/40-pipeline/03-extraction-contract.md:
fee_model/attorney_count/primary_practice confidence thresholds,
fee_model in (mixed, unknown), tier '1A' unconditionally, and the
reconcile_conflict guard when that table (migration 060, another agent's)
does not exist yet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from lge.llm.client import OPENROUTER_URL
from lge.planes.p.p9_escalate import _select_firm_ids, p9_escalate
from lge.registry import RunContext
from lge.settings import Settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _settings(api_key: str = "sk-or-test-key") -> Settings:
    return Settings(
        dsn="unused",
        admin_dsn="unused",
        object_store=Path("."),
        user_agent="test-agent",
        anthropic_api_key="",
        openrouter_api_key=api_key,
        live=False,
    )


def _ctx(conn, api_key: str = "sk-or-test-key") -> RunContext:
    return RunContext(conn, _settings(api_key))


def _insert_page(conn, firm_id: str, page_kind: str, url: str, text: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, page_kind, fetch_ok) "
            "VALUES (%s, %s, %s, true) RETURNING id",
            (firm_id, url, page_kind),
        )
        doc_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO document_text (document_id, main_text, word_count, extractor) "
            "VALUES (%s, %s, %s, 'test:1')",
            (doc_id, text, len(text.split())),
        )


def _write_p8_claim(conn, firm_id: str, attr: str, value, confidence: float) -> None:
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO firm_attribute
                (firm_id, attr, value, source, confidence, evidence, observed_at)
            VALUES (%s, %s, %s, 'llm:p8:v1', %s, NULL, %s)
            """,
            (firm_id, attr, Jsonb(value), confidence, datetime.now(UTC)),
        )


def _seed_firm(conn, **firm_cols) -> str:
    firm_id = make_firm(conn, **firm_cols)
    _insert_page(conn, firm_id, "home", "http://example.com/", "Welcome to our firm.")
    return firm_id


# =============================================================================
# Selection query -- every trigger
# =============================================================================


def test_fee_model_confidence_below_threshold_triggers_escalation(db):
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.59)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    assert _select_firm_ids(_ctx(db), {}) == [str(firm_id)]


def test_fee_model_confidence_at_threshold_does_not_trigger(db):
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.60)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    assert _select_firm_ids(_ctx(db), {}) == []


def test_attorney_count_confidence_below_threshold_triggers_escalation(db):
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.9)
    _write_p8_claim(db, firm_id, "attorney_count", None, 0.59)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    assert _select_firm_ids(_ctx(db), {}) == [str(firm_id)]


def test_primary_practice_confidence_below_threshold_triggers_escalation(db):
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.9)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.69)
    assert _select_firm_ids(_ctx(db), {}) == [str(firm_id)]


def test_primary_practice_confidence_at_its_own_threshold_does_not_trigger(db):
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.9)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.70)
    assert _select_firm_ids(_ctx(db), {}) == []


@pytest.mark.parametrize("value", ["mixed", "unknown"])
def test_fee_model_mixed_or_unknown_triggers_escalation_regardless_of_confidence(db, value):
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", value, 0.95)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    assert _select_firm_ids(_ctx(db), {}) == [str(firm_id)]


def test_tier_1a_escalates_even_with_high_confidence_everywhere(db):
    firm_id = _seed_firm(db, tier="1A")
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.99)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.99)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.99)
    assert _select_firm_ids(_ctx(db), {}) == [str(firm_id)]


def test_no_trigger_firm_is_not_selected(db):
    _seed_firm(db)  # never gets a P8 claim at all -- no NULL-confidence trigger either
    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.9)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    assert _select_firm_ids(_ctx(db), {}) == []


def test_latest_p8_claim_wins_over_an_earlier_low_confidence_one(db):
    firm_id = _seed_firm(db)
    with db.cursor() as cur:
        from psycopg.types.json import Jsonb

        cur.execute(
            "INSERT INTO firm_attribute "
            "(firm_id, attr, value, source, confidence, evidence, observed_at) "
            "VALUES (%s, 'fee_model', %s, 'llm:p8:v1', 0.3, NULL, %s)",
            (firm_id, Jsonb("unknown"), datetime(2020, 1, 1, tzinfo=UTC)),
        )
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.95)  # observed_at = now()
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    assert _select_firm_ids(_ctx(db), {}) == []


# =============================================================================
# reconcile_conflict guard -- table does not exist under this migration set
# =============================================================================


def test_reconcile_conflict_guard_works_when_table_absent(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('reconcile_conflict')")
        if cur.fetchone()["to_regclass"] is not None:
            # Under the full suite, another agent's migration 060 has already
            # landed and created this table -- the absent-table path this
            # test exercises can only be reproduced under the isolated
            # migration set this component's tests are meant to run under
            # (LGE_TEST_MIGRATIONS=001,002,003,004,005,050, per this file's
            # module docstring). Nothing to prove here in that environment.
            pytest.skip("reconcile_conflict already exists under this migration set")

    firm_id = _seed_firm(db)
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.9)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)
    # Must not raise (no "relation reconcile_conflict does not exist") and
    # must not spuriously select a firm with no trigger.
    assert _select_firm_ids(_ctx(db), {}) == []


def test_limit_option_caps_the_trigger_query(db):
    ids = []
    for _ in range(3):
        firm_id = _seed_firm(db, tier="1A")
        ids.append(firm_id)
    assert len(_select_firm_ids(_ctx(db), {"limit": 2})) == 2


def _confident_p8(db, firm_id) -> None:
    _write_p8_claim(db, firm_id, "fee_model", "contingency", 0.9)
    _write_p8_claim(db, firm_id, "attorney_count", 3, 0.9)
    _write_p8_claim(db, firm_id, "primary_practice", "personal_injury", 0.9)


def test_firm_ids_file_narrows_the_trigger_query_never_bypasses_it(tmp_path, db):
    # A research job for one firm hands p9 that firm's id. Escalating it
    # regardless would send every firm researched from the screen to the
    # expensive model (D-054): only a firm a trigger fires for is selected.
    quiet = _seed_firm(db)
    _confident_p8(db, quiet)
    unsure = _seed_firm(db)
    _write_p8_claim(db, unsure, "fee_model", "contingency", 0.4)
    unlisted = _seed_firm(db, tier="1A")  # a trigger fires, but it is not on the list
    path = tmp_path / "firms.txt"
    path.write_text(f"{quiet}\n{unsure}\n", encoding="utf-8")

    assert _select_firm_ids(_ctx(db), {"firm_ids_file": str(path)}) == [str(unsure)]
    assert str(unlisted) in _select_firm_ids(_ctx(db), {})


def test_force_escalates_every_listed_firm(tmp_path, db):
    quiet = _seed_firm(db)
    _confident_p8(db, quiet)
    path = tmp_path / "firms.txt"
    path.write_text(f"{quiet}\n", encoding="utf-8")
    assert _select_firm_ids(_ctx(db), {"firm_ids_file": str(path), "force": "1"}) == [str(quiet)]


def test_an_empty_firm_list_selects_nothing(tmp_path, db):
    _seed_firm(db, tier="1A")
    path = tmp_path / "firms.txt"
    path.write_text("\n", encoding="utf-8")
    assert _select_firm_ids(_ctx(db), {"firm_ids_file": str(path)}) == []


# =============================================================================
# End to end: the shared engine runs under p9's model/prompt_rev/source
# =============================================================================


def _valid_extraction_json() -> str:
    payload = {
        "primary_practice": {
            "value": "personal_injury",
            "confidence": 0.95,
            "evidence": "We handle personal injury cases across the state.",
        },
        "practice_areas": [{"area": "personal_injury", "weight": 1.0}],
        "fee_model": {
            "value": "contingency",
            "confidence": 0.95,
            "evidence": "There is no fee unless we win your case.",
        },
        "attorney_count": {
            "value": None,
            "confidence": 0.0,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": [],
        },
        "staff_ratio": {"value": None, "confidence": 0.0},
        "decision_makers": [],
        "languages": ["en"],
        "spanish_intake": {"value": False, "evidence": None},
        "entity_kind": {"value": "private_firm"},
        "has_inhouse_recruiter": {"value": False, "evidence": None},
    }
    return json.dumps(payload)


def _chat_response(content: str) -> dict:
    return {
        "id": "gen-1",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 90},
    }


def test_tier_1a_firm_is_escalated_with_opus_model_and_p9_source(db):
    firm_id = _seed_firm(db, tier="1A")
    _insert_page(
        db,
        firm_id,
        "home",
        "http://example.com/home",
        "We handle personal injury cases across the state. "
        "There is no fee unless we win your case.",
    )
    ctx = _ctx(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(_valid_extraction_json()))
        )
        result = p9_escalate(ctx, limit=10)
        assert route.call_count == 1
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["model"] == "anthropic/claude-opus-5"

    assert result.processed == 1
    with db.cursor() as cur:
        cur.execute(
            "SELECT source, model FROM firm_attribute fa "
            "JOIN llm_call lc ON lc.firm_id = fa.firm_id "
            "WHERE fa.firm_id = %s AND fa.attr = 'fee_model' LIMIT 1",
            (firm_id,),
        )
        row = cur.fetchone()
    assert row["source"] == "llm:p9:v3"
    assert row["model"] == "anthropic/claude-opus-5"
