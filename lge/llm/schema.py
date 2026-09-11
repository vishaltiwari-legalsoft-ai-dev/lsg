"""The one schema P8 and P9 share (context/40-pipeline/03-extraction-contract.md).

Every model here sets `extra="forbid"` and leaves every field required (no
defaults) — that is what makes strict structured-output mode possible:
`additionalProperties: false` plus every property in `required`. A field
that may legitimately be absent is typed `X | None`, never `Optional[X] =
None` with a default, because a default drops the field out of `required`.

`unknown` is a first-class value, not an omission: `fee_model.value` has an
explicit `"unknown"` member, `primary_practice.value` and
`attorney_count.value` are nullable rather than forced to guess. See "Why
`unknown` must be reachable" in the extraction contract.

`PracticeArea` is built from `config/practice_areas.yml` at import time so
this schema and `norm_practice`'s closed vocabulary can never drift apart —
see context/10-icp/02-practice-areas.md.
"""

from __future__ import annotations

import functools
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

_PRACTICE_AREAS_CONFIG = Path(__file__).resolve().parents[2] / "config" / "practice_areas.yml"


@functools.lru_cache(maxsize=1)
def practice_area_slugs() -> tuple[str, ...]:
    """The closed 15-slug vocabulary, loaded from config/practice_areas.yml."""
    with _PRACTICE_AREAS_CONFIG.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return tuple(cfg["practices"].keys())


PracticeArea: type[Enum] = Enum(
    "PracticeArea",
    {slug.upper(): slug for slug in practice_area_slugs()},
    type=str,
)


class FeeModelValue(StrEnum):
    CONTINGENCY = "contingency"
    FEE_SHIFTING = "fee_shifting"
    FLAT = "flat"
    HOURLY = "hourly"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AttorneyCountMethod(StrEnum):
    TEAM_PAGE_COUNT = "team_page_count"
    STATED = "stated"
    INFERRED = "inferred"


class DecisionMakerRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ATTORNEY = "attorney"


class EntityKindValue(StrEnum):
    PRIVATE_FIRM = "private_firm"
    INHOUSE = "inhouse"
    GOV = "gov"
    NONPROFIT = "nonprofit"
    DIRECTORY_STUB = "directory_stub"


class PrimaryPractice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: PracticeArea | None
    confidence: float
    evidence: str | None


class PracticeAreaWeight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: PracticeArea
    weight: float


class FeeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: FeeModelValue
    confidence: float
    evidence: str | None  # required unless value == "unknown"; enforced by grounding, not the type


class AttorneyCount(BaseModel):
    """prompt_rev v2: attorney_count is now groundable (context/40-pipeline/
    03-extraction-contract.md, "GROUND attorney_count" follow-up). `evidence`
    carries the quoted sentence for method="stated"; `attorney_names` carries
    the names counted for method="team_page_count", each checked against the
    source text the same way any other evidence is — the grounding pass then
    resets `value` to the count of names that actually ground. Capped at 80
    entries: a firm above 50 attorneys is DQ_SIZE regardless, so there is
    nothing meaningful past that to enumerate."""

    model_config = ConfigDict(extra="forbid")
    value: int | None
    confidence: float
    method: AttorneyCountMethod
    excluded: int
    evidence: str | None  # required for method="stated"; grounded like any other evidence
    attorney_names: list[str] = Field(max_length=80)


class StaffRatio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float | None
    confidence: float


class DecisionMaker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    title: str
    role: DecisionMakerRole
    evidence: str


class SpanishIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool
    evidence: str | None


class EntityKind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: EntityKindValue


class HasInhouseRecruiter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool
    evidence: str | None


class FirmExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_practice: PrimaryPractice
    practice_areas: list[PracticeAreaWeight]
    fee_model: FeeModel
    attorney_count: AttorneyCount
    staff_ratio: StaffRatio
    decision_makers: list[DecisionMaker]
    languages: list[str]
    spanish_intake: SpanishIntake
    entity_kind: EntityKind
    has_inhouse_recruiter: HasInhouseRecruiter


def response_format_for(model: type[BaseModel], name: str) -> dict[str, Any]:
    """`response_format` payload for OpenRouter's OpenAI-compatible
    structured-output mode: an enforced schema, not a prompt instruction."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": model.model_json_schema(),
        },
    }
