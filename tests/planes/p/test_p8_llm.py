"""P8 component tests. Run isolated:

    LGE_TEST_MIGRATIONS=001,002,003,004,005,050 \
        uv run pytest tests/llm tests/planes/p/test_p8_llm.py tests/planes/p/test_p9_escalate.py -q

respx mocks every OpenRouter call -- these tests never touch the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from lge.llm.client import OPENROUTER_URL
from lge.planes.p.p8_llm import p8_llm
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


def _ctx(conn, api_key: str = "sk-or-test-key", dry_run: bool = False) -> RunContext:
    return RunContext(conn, _settings(api_key), dry_run=dry_run)


def _insert_page(conn, firm_id: str, page_kind: str, url: str, text: str) -> int:
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
    return doc_id


TEAM_TEXT = (
    "Our attorneys: Jane Doe, Esq. and Richard Roe, Esq. handle every case personally. "
    "Jane Doe is the founder and owner of the firm."
)
HOME_TEXT = (
    "We handle personal injury cases across the state. "
    "There is no fee unless we win your case."
)


def _seed_firm_with_pages(conn) -> str:
    firm_id = make_firm(conn)
    _insert_page(conn, firm_id, "home", "http://example.com/", HOME_TEXT)
    _insert_page(conn, firm_id, "team", "http://example.com/team", TEAM_TEXT)
    return firm_id


def _valid_extraction_json(**overrides: object) -> str:
    payload = {
        "primary_practice": {
            "value": "personal_injury",
            "confidence": 0.9,
            "evidence": "We handle personal injury cases across the state.",
        },
        "practice_areas": [{"area": "personal_injury", "weight": 1.0}],
        "fee_model": {
            "value": "contingency",
            "confidence": 0.9,
            "evidence": "There is no fee unless we win your case.",
        },
        "attorney_count": {
            "value": 2,
            "confidence": 0.85,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": ["Jane Doe", "Richard Roe"],
        },
        "staff_ratio": {"value": None, "confidence": 0.0},
        "decision_makers": [
            {
                "name": "Jane Doe",
                "title": "Owner",
                "role": "owner",
                "evidence": "Jane Doe is the founder and owner of the firm.",
            }
        ],
        "languages": ["en"],
        "spanish_intake": {"value": False, "evidence": None},
        "entity_kind": {"value": "private_firm"},
        "has_inhouse_recruiter": {"value": False, "evidence": None},
    }
    payload.update(overrides)
    return json.dumps(payload)


def _chat_response(content: str, usage: dict | None = None) -> dict:
    return {
        "id": "gen-1",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": usage if usage is not None else {"prompt_tokens": 200, "completion_tokens": 80},
    }


def _claims(conn, firm_id: str) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT attr, value, confidence, evidence, source FROM firm_attribute "
            "WHERE firm_id = %s",
            (firm_id,),
        )
        return {row["attr"]: row for row in cur.fetchall()}


def _llm_calls(conn, firm_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM llm_call WHERE firm_id = %s ORDER BY id", (firm_id,))
        return cur.fetchall()


# =============================================================================
# Missing key -> inert
# =============================================================================


def test_missing_api_key_is_inert_and_makes_zero_requests(db):
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db, api_key="")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(OPENROUTER_URL).mock(return_value=httpx.Response(200, json={}))
        result = p8_llm(ctx, limit=10)
        assert route.call_count == 0
    assert result.skipped >= 1
    assert any("inert" in note and "OPENROUTER_API_KEY" in note for note in result.notes)
    assert _claims(db, firm_id) == {}


# =============================================================================
# dry_run
# =============================================================================


def test_dry_run_prints_sizes_and_cost_and_makes_zero_requests(db):
    _seed_firm_with_pages(db)
    ctx = _ctx(db)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(OPENROUTER_URL).mock(return_value=httpx.Response(200, json={}))
        result = p8_llm(ctx, limit=10, dry_run="1")
        assert route.call_count == 0
    assert result.skipped >= 1
    assert any("chars" in note for note in result.notes)
    assert any("dry_run" in note for note in result.notes)


# =============================================================================
# Successful call
# =============================================================================


def test_successful_call_writes_claims_and_ok_llm_call(db):
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(_valid_extraction_json()))
        )
        result = p8_llm(ctx, limit=10)

    assert result.processed == 1
    assert result.failed == 0

    claims = _claims(db, firm_id)
    assert claims["fee_model"]["value"] == "contingency"
    assert claims["fee_model"]["source"] == "llm:p8:v2"
    assert claims["primary_practice"]["value"] == "personal_injury"
    assert claims["attorney_count"]["value"] == 2
    assert "method" not in claims  # lives on the sibling attr, not attorney_count
    assert claims["attorney_count_detail"]["value"] == {
        "method": "team_page_count",
        "excluded": 0,
        "attorney_names": ["Jane Doe", "Richard Roe"],
    }
    assert claims["decision_makers"]["value"] == [
        {
            "name": "Jane Doe",
            "title": "Owner",
            "role": "owner",
            "evidence": "Jane Doe is the founder and owner of the firm.",
        }
    ]
    # unscored fields are written at config default_field_confidence (0.7),
    # never at 1.0 -- and false/ungrounded presence flags write no claim.
    assert float(claims["practice_areas"]["confidence"]) == 0.7
    assert float(claims["languages"]["confidence"]) == 0.7
    assert float(claims["entity_kind"]["confidence"]) == 0.7
    assert "spanish_intake" not in claims
    assert "has_inhouse_recruiter" not in claims

    calls = _llm_calls(db, firm_id)
    assert len(calls) == 1
    assert calls[0]["status"] == "ok"
    assert calls[0]["model"] == "anthropic/claude-haiku-4.5"
    assert calls[0]["prompt_rev"] == "v2"
    assert calls[0]["input_tokens"] == 200
    assert calls[0]["output_tokens"] == 80
    assert calls[0]["ungrounded_fields"] is None


def test_unknown_is_written_as_a_first_class_claim(db):
    firm_id = make_firm(db)
    _insert_page(db, firm_id, "home", "http://example.com/", "Welcome to our firm's website.")
    ctx = _ctx(db)
    unknown_json = _valid_extraction_json(
        fee_model={"value": "unknown", "confidence": 0.0, "evidence": None},
        primary_practice={"value": None, "confidence": 0.0, "evidence": None},
        attorney_count={
            "value": None,
            "confidence": 0.0,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": [],
        },
        decision_makers=[],
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(unknown_json))
        )
        result = p8_llm(ctx, limit=10)

    assert result.processed == 1
    claims = _claims(db, firm_id)
    assert claims["fee_model"]["value"] == "unknown"
    assert float(claims["fee_model"]["confidence"]) == 0.0
    assert claims["primary_practice"]["value"] is None
    assert claims["attorney_count"]["value"] is None
    calls = _llm_calls(db, firm_id)
    assert calls[0]["status"] == "ok"  # no evidence was invented -- nothing to null via grounding


# =============================================================================
# Grounding
# =============================================================================


def test_invented_fee_model_evidence_is_nulled_and_marks_ungrounded(db):
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    invented_json = _valid_extraction_json(
        fee_model={
            "value": "hourly",
            "confidence": 0.85,
            "evidence": "We bill a flat monthly retainer for every client relationship.",
        }
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(invented_json))
        )
        result = p8_llm(ctx, limit=10)

    assert result.processed == 1
    claims = _claims(db, firm_id)
    assert claims["fee_model"]["value"] == "unknown"
    assert float(claims["fee_model"]["confidence"]) == 0.0
    assert claims["fee_model"]["evidence"] is None

    calls = _llm_calls(db, firm_id)
    assert calls[0]["status"] == "ungrounded"
    assert calls[0]["ungrounded_fields"] == ["fee_model"]


def test_hallucinated_attorney_count_is_recounted_capped_and_marks_ungrounded(db):
    # TEAM_TEXT only grounds "Jane Doe" and "Richard Roe" -- a reported 60
    # must never silently reach DQ_SIZE.
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    hallucinated_json = _valid_extraction_json(
        attorney_count={
            "value": 60,
            "confidence": 0.9,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": ["Jane Doe", "Richard Roe"] + [f"Attorney {i}" for i in range(58)],
        }
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(hallucinated_json))
        )
        result = p8_llm(ctx, limit=10)

    assert result.processed == 1
    claims = _claims(db, firm_id)
    assert claims["attorney_count"]["value"] == 2  # the grounded recount, not 60
    assert float(claims["attorney_count"]["confidence"]) <= 0.5
    assert claims["attorney_count_detail"]["value"]["attorney_names"] == ["Jane Doe", "Richard Roe"]

    calls = _llm_calls(db, firm_id)
    assert calls[0]["status"] == "ungrounded"
    assert calls[0]["ungrounded_fields"] == ["attorney_count"]


def test_spanish_intake_written_only_when_true_and_grounded(db):
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "home", "http://example.com/", "Se habla espanol. Hablamos con usted."
    )
    ctx = _ctx(db)
    grounded_json = _valid_extraction_json(
        spanish_intake={"value": True, "evidence": "Se habla espanol."},
        attorney_count={
            "value": None,
            "confidence": 0.0,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": [],
        },
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(grounded_json))
        )
        p8_llm(ctx, limit=10)

    claims = _claims(db, firm_id)
    assert claims["spanish_intake"]["value"] is True
    assert float(claims["spanish_intake"]["confidence"]) == 0.7
    assert "has_inhouse_recruiter" not in claims  # False in the payload -- no claim written


def test_entity_kind_nonprofit_round_trips_as_a_claim(db):
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    nonprofit_json = _valid_extraction_json(entity_kind={"value": "nonprofit"})
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(nonprofit_json))
        )
        p8_llm(ctx, limit=10)

    claims = _claims(db, firm_id)
    assert claims["entity_kind"]["value"] == "nonprofit"
    assert float(claims["entity_kind"]["confidence"]) == 0.7


# =============================================================================
# Validation failure -> retry once -> invalid -> no claims
# =============================================================================


def test_validation_failure_retries_once_then_invalid_writes_nothing(db):
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL)
        route.side_effect = [
            httpx.Response(200, json=_chat_response('{"not": "a valid extraction"}')),
            httpx.Response(200, json=_chat_response('{"still": "not valid"}')),
        ]
        result = p8_llm(ctx, limit=10)

    assert route.call_count == 2  # one initial attempt + one retry, never more
    assert result.failed == 1
    assert _claims(db, firm_id) == {}
    calls = _llm_calls(db, firm_id)
    assert len(calls) == 1
    assert calls[0]["status"] == "invalid"


# =============================================================================
# Budget stop
# =============================================================================


def test_budget_stop_skips_remaining_firms_without_calling_them(db):
    firm_a = _seed_firm_with_pages(db)
    firm_b = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(_valid_extraction_json()))
        )
        # A near-zero budget means even the first firm's estimated cost
        # exceeds it -- zero calls, both firms skipped with a note.
        result = p8_llm(ctx, limit=10, max_usd="0.0000001")
        assert route.call_count == 0
    assert result.skipped >= 2
    assert any("budget stop" in note for note in result.notes)
    assert _claims(db, firm_a) == {}
    assert _claims(db, firm_b) == {}


# =============================================================================
# Idempotency
# =============================================================================


def test_idempotent_rerun_makes_zero_requests(db):
    firm_id = _seed_firm_with_pages(db)
    ctx = _ctx(db)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_chat_response(_valid_extraction_json()))
        )
        first = p8_llm(ctx, limit=10)
        assert route.call_count == 1
        assert first.processed == 1

        second = p8_llm(ctx, limit=10)
        assert route.call_count == 1  # unchanged -- no new request on the re-run

    assert second.processed == 0
    assert second.skipped >= 1
    # still exactly one llm_call / one set of claims from the first run
    assert len(_llm_calls(db, firm_id)) == 1
