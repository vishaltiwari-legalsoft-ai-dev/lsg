"""Grounding: every evidence string must occur in the supplied source text
(case/whitespace-normalised); ungrounded evidence nulls the field and, for
a tier-determining field, flips call status to 'ungrounded'
(context/40-pipeline/03-extraction-contract.md).

prompt_rev v2: attorney_count is groundable too (attorney_names for
method="team_page_count", evidence for method="stated", a hard cap for
method="inferred") — see the "GROUND attorney_count" follow-up."""

from __future__ import annotations

from lge.llm import grounding
from lge.llm.schema import FirmExtraction

SOURCE = (
    "We handle personal injury cases across the state. "
    "There is no fee unless we win your case. "
    "Jane Doe is the founder and owner of the firm. "
    "Se habla espanol at our office."
)


def _payload(**overrides: dict) -> dict:
    base = {
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
            "value": 1,
            "confidence": 0.8,
            "method": "team_page_count",
            "excluded": 1,
            "evidence": None,
            "attorney_names": ["Jane Doe"],
        },
        "staff_ratio": {"value": 0.5, "confidence": 0.5},
        "decision_makers": [
            {
                "name": "Jane Doe",
                "title": "Owner",
                "role": "owner",
                "evidence": "Jane Doe is the founder and owner of the firm.",
            }
        ],
        "languages": ["en", "es"],
        "spanish_intake": {"value": True, "evidence": "Se habla espanol at our office."},
        "entity_kind": {"value": "private_firm"},
        "has_inhouse_recruiter": {"value": False, "evidence": None},
    }
    base.update(overrides)
    return base


def test_is_grounded_case_and_whitespace_normalised():
    normalized = grounding.normalize(SOURCE)
    assert grounding.is_grounded("Jane Doe is the CEO", normalized) is False  # not a substring
    assert grounding.is_grounded("Jane Doe is the founder and owner", normalized)
    assert grounding.is_grounded("JANE doe IS the   FOUNDER and owner", normalized)


def test_is_grounded_rejects_missing_or_empty_evidence():
    normalized = grounding.normalize(SOURCE)
    assert grounding.is_grounded(None, normalized) is False
    assert grounding.is_grounded("", normalized) is False
    assert grounding.is_grounded("this sentence is not on the page", normalized) is False


def test_fully_grounded_response_is_ok_and_unchanged():
    extraction = FirmExtraction.model_validate(_payload())
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert ungrounded_fields == []
    assert grounding.call_status(ungrounded_fields) == "ok"
    assert grounded.fee_model.value == "contingency"
    assert grounded.primary_practice.value == "personal_injury"
    assert grounded.attorney_count.value == 1
    assert grounded.attorney_count.attorney_names == ["Jane Doe"]
    assert grounded.attorney_count.confidence == 0.8


def test_invented_fee_model_evidence_is_nulled_and_marks_ungrounded():
    payload = _payload(
        fee_model={
            "value": "contingency",
            "confidence": 0.9,
            "evidence": "This exact sentence never appeared on the page.",
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert ungrounded_fields == ["fee_model"]
    assert grounding.call_status(ungrounded_fields) == "ungrounded"
    assert grounded.fee_model.value == "unknown"
    assert grounded.fee_model.confidence == 0.0
    assert grounded.fee_model.evidence is None
    # other fields untouched
    assert grounded.primary_practice.value == "personal_injury"


def test_fee_model_value_not_unknown_with_missing_evidence_is_ungrounded():
    payload = _payload(fee_model={"value": "hourly", "confidence": 0.7, "evidence": None})
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert "fee_model" in ungrounded_fields
    assert grounded.fee_model.value == "unknown"


def test_invented_primary_practice_evidence_nulls_and_escalates():
    payload = _payload(
        primary_practice={
            "value": "immigration",
            "confidence": 0.9,
            "evidence": "We are the top immigration firm in the region.",
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert "primary_practice" in ungrounded_fields
    assert grounding.call_status(ungrounded_fields) == "ungrounded"
    assert grounded.primary_practice.value is None
    assert grounded.primary_practice.confidence == 0.0


def test_decision_maker_with_ungrounded_name_is_dropped():
    payload = _payload(
        decision_makers=[
            {
                "name": "Jane Doe",
                "title": "Owner",
                "role": "owner",
                "evidence": "Jane Doe is the founder and owner of the firm.",
            },
            {
                "name": "John Nobody",
                "title": "Administrator",
                "role": "admin",
                "evidence": "John Nobody runs the office.",
            },
        ]
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    names = {dm.name for dm in grounded.decision_makers}
    assert names == {"Jane Doe"}
    # dropping a decision maker is not a scalar-field null -- it never
    # appears in ungrounded_fields and never flips call status.
    assert "decision_makers" not in ungrounded_fields
    assert grounding.call_status(ungrounded_fields) == "ok"


def test_decision_maker_with_ungrounded_evidence_quote_is_dropped():
    payload = _payload(
        decision_makers=[
            {
                "name": "Jane Doe",
                "title": "Owner",
                "role": "owner",
                "evidence": "an invented quote about Jane Doe",
            }
        ]
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, _ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.decision_makers == []


def test_ungrounded_spanish_intake_is_nulled_but_not_tier_determining():
    payload = _payload(
        spanish_intake={"value": True, "evidence": "Hablamos espanol y frances tambien."}
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert "spanish_intake" in ungrounded_fields
    assert grounded.spanish_intake.value is False
    assert grounded.spanish_intake.evidence is None
    assert grounding.call_status(ungrounded_fields) == "ok"


# =============================================================================
# attorney_count grounding (prompt_rev v2)
# =============================================================================


def test_team_page_count_drops_ungrounded_names_and_recounts():
    payload = _payload(
        attorney_count={
            "value": 2,
            "confidence": 0.9,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": ["Jane Doe", "A Person Never Named On The Page"],
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.attorney_names == ["Jane Doe"]
    # |reported(2) - recounted(1)| == 1 -- within tolerance, not ungrounded.
    assert grounded.attorney_count.value == 1
    assert "attorney_count" not in ungrounded_fields
    assert grounded.attorney_count.confidence == 0.9


def test_team_page_count_large_mismatch_caps_confidence_and_marks_ungrounded():
    payload = _payload(
        attorney_count={
            "value": 60,  # a hallucinated count -- must not silently trip DQ_SIZE
            "confidence": 0.9,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": ["Jane Doe"],  # only one of the 60 actually grounds
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.value == 1  # the recount, not the hallucinated 60
    assert grounded.attorney_count.confidence <= 0.5
    assert "attorney_count" in ungrounded_fields
    assert grounding.call_status(ungrounded_fields) == "ungrounded"


def test_team_page_count_null_with_no_names_stays_null_not_zero():
    payload = _payload(
        attorney_count={
            "value": None,
            "confidence": 0.0,
            "method": "team_page_count",
            "excluded": 0,
            "evidence": None,
            "attorney_names": [],
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.value is None
    assert "attorney_count" not in ungrounded_fields
    assert grounding.call_status(ungrounded_fields) == "ok"


def test_stated_method_evidence_grounded_is_kept():
    payload = _payload(
        attorney_count={
            "value": 1,
            "confidence": 0.7,
            "method": "stated",
            "excluded": 0,
            "evidence": "Jane Doe is the founder and owner of the firm.",
            "attorney_names": [],
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.value == 1
    assert grounded.attorney_count.evidence is not None
    assert "attorney_count" not in ungrounded_fields


def test_stated_method_invented_evidence_nulls_and_marks_ungrounded():
    payload = _payload(
        attorney_count={
            "value": 12,
            "confidence": 0.7,
            "method": "stated",
            "excluded": 0,
            "evidence": "Our firm of 12 dedicated attorneys serves the whole state.",
            "attorney_names": [],
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.value is None
    assert grounded.attorney_count.confidence == 0.0
    assert grounded.attorney_count.evidence is None
    assert "attorney_count" in ungrounded_fields
    assert grounding.call_status(ungrounded_fields) == "ungrounded"


def test_inferred_method_never_above_point_four():
    payload = _payload(
        attorney_count={
            "value": 5,
            "confidence": 0.9,
            "method": "inferred",
            "excluded": 0,
            "evidence": None,
            "attorney_names": [],
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.confidence <= 0.4
    assert grounded.attorney_count.value == 5  # inferred is capped, not nulled
    # a confidence cap alone is not a grounding failure -- nothing to check.
    assert "attorney_count" not in ungrounded_fields


def test_inferred_method_confidence_already_below_cap_is_untouched():
    payload = _payload(
        attorney_count={
            "value": 5,
            "confidence": 0.2,
            "method": "inferred",
            "excluded": 0,
            "evidence": None,
            "attorney_names": [],
        }
    )
    extraction = FirmExtraction.model_validate(payload)
    grounded, _ungrounded_fields = grounding.ground(extraction, SOURCE)
    assert grounded.attorney_count.confidence == 0.2
