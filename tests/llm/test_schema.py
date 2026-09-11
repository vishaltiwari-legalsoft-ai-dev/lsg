"""Strict structured-output schema shape: additionalProperties:false and
every property required, at every nesting level -- what OpenRouter's
strict json_schema mode requires (context/40-pipeline/03-extraction-
contract.md)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lge.llm.schema import FirmExtraction, practice_area_slugs, response_format_for


def _schema() -> dict:
    return response_format_for(FirmExtraction, "firm_extraction")


def test_response_format_wrapper_shape():
    rf = _schema()
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "firm_extraction"
    assert rf["json_schema"]["strict"] is True
    assert "schema" in rf["json_schema"]


def test_top_level_additional_properties_false_and_all_required():
    schema = _schema()["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())


def test_every_nested_def_is_strict():
    schema = _schema()["json_schema"]["schema"]
    defs = schema["$defs"]
    object_defs = {name: d for name, d in defs.items() if d.get("type") == "object"}
    assert object_defs, "expected at least one nested object definition"
    for name, d in object_defs.items():
        assert d["additionalProperties"] is False, f"{name} allows additional properties"
        assert set(d["required"]) == set(d["properties"].keys()), f"{name} has optional fields"


def test_practice_area_enum_matches_closed_vocabulary_config():
    schema = _schema()["json_schema"]["schema"]
    practice_area_def = schema["$defs"]["PracticeArea"]
    assert set(practice_area_def["enum"]) == set(practice_area_slugs())
    assert len(practice_area_slugs()) == 15


def _valid_payload() -> dict:
    return {
        "primary_practice": {
            "value": "personal_injury",
            "confidence": 0.9,
            "evidence": "We handle personal injury cases.",
        },
        "practice_areas": [{"area": "personal_injury", "weight": 1.0}],
        "fee_model": {
            "value": "contingency",
            "confidence": 0.9,
            "evidence": "No fee unless we win.",
        },
        "attorney_count": {
            "value": 3,
            "confidence": 0.8,
            "method": "team_page_count",
            "excluded": 1,
            "evidence": None,
            "attorney_names": ["Jane Doe", "Richard Roe", "Alice Lee"],
        },
        "staff_ratio": {"value": 0.33, "confidence": 0.5},
        "decision_makers": [
            {"name": "Jane Doe", "title": "Owner", "role": "owner", "evidence": "Jane Doe, owner."}
        ],
        "languages": ["en"],
        "spanish_intake": {"value": False, "evidence": None},
        "entity_kind": {"value": "private_firm"},
        "has_inhouse_recruiter": {"value": False, "evidence": None},
    }


def test_valid_payload_round_trips():
    extraction = FirmExtraction.model_validate(_valid_payload())
    assert extraction.primary_practice.value == "personal_injury"
    assert extraction.fee_model.value == "contingency"
    assert extraction.attorney_count.excluded == 1


def test_unknown_values_validate_cleanly():
    payload = _valid_payload()
    payload["primary_practice"] = {"value": None, "confidence": 0.0, "evidence": None}
    payload["fee_model"] = {"value": "unknown", "confidence": 0.0, "evidence": None}
    payload["attorney_count"] = {
        "value": None,
        "confidence": 0.0,
        "method": "team_page_count",
        "excluded": 0,
        "evidence": None,
        "attorney_names": [],
    }
    extraction = FirmExtraction.model_validate(payload)
    assert extraction.primary_practice.value is None
    assert extraction.fee_model.value == "unknown"
    assert extraction.attorney_count.value is None


def test_extra_field_rejected():
    payload = _valid_payload()
    payload["unexpected_field"] = "surprise"
    with pytest.raises(ValidationError):
        FirmExtraction.model_validate(payload)


def test_invalid_enum_value_rejected():
    payload = _valid_payload()
    payload["fee_model"]["value"] = "not_a_real_fee_model"
    with pytest.raises(ValidationError):
        FirmExtraction.model_validate(payload)


def test_missing_required_field_rejected():
    payload = _valid_payload()
    del payload["fee_model"]["confidence"]
    with pytest.raises(ValidationError):
        FirmExtraction.model_validate(payload)


def test_attorney_names_over_80_rejected():
    payload = _valid_payload()
    payload["attorney_count"]["attorney_names"] = [f"Attorney {i}" for i in range(81)]
    with pytest.raises(ValidationError):
        FirmExtraction.model_validate(payload)


def test_entity_kind_nonprofit_is_valid():
    payload = _valid_payload()
    payload["entity_kind"] = {"value": "nonprofit"}
    extraction = FirmExtraction.model_validate(payload)
    assert extraction.entity_kind.value == "nonprofit"


def test_attorney_count_missing_evidence_or_names_rejected():
    payload = _valid_payload()
    del payload["attorney_count"]["attorney_names"]
    with pytest.raises(ValidationError):
        FirmExtraction.model_validate(payload)
