"""Grounding — the most important requirement in the extraction contract.

Every `evidence` string must occur in the supplied page text (case- and
whitespace-normalised compare; a quoted substring is fine). Evidence not
found -> that field becomes unknown/null with confidence 0, the field name
goes into `ungrounded_fields`, and the call status is 'ungrounded' if a
tier-determining field (fee_model, primary_practice, attorney_count) was
nulled. A decision maker whose name does not appear in the text is dropped.

prompt_rev v2: attorney_count is now fully groundable (previously the one
tier-determining field grounding could not check at all — a hallucinated
"60" could silently trip DQ_SIZE on a prime prospect):

  * method="team_page_count": every name in `attorney_names` is checked like
    any other evidence; `attorney_names` is replaced with only the names
    that ground, and `value` becomes the count of those grounded names —
    the model's own count is discarded, not merely checked. Exception: a
    reported `null` with zero grounded names stays `null` (the legitimate
    "no team page" answer), never recomputed to a fabricated zero. If the
    model's own value differed from the recount by more than 1, confidence
    is capped at 0.5 and 'attorney_count' is recorded in
    `ungrounded_fields` (status -> 'ungrounded', same as any other
    tier-determining field).
  * method="stated": `evidence` must ground exactly like fee_model's
    evidence; ungrounded evidence nulls value/confidence and records
    'attorney_count'.
  * method="inferred": never trusted above confidence 0.4, capped
    unconditionally — there is no text span an inferred count could be
    checked against.
"""

from __future__ import annotations

import re

from lge.llm.schema import AttorneyCountMethod, FeeModelValue, FirmExtraction

_WHITESPACE_RE = re.compile(r"\s+")
_INFERRED_CONFIDENCE_CAP = 0.4
_MISMATCH_CONFIDENCE_CAP = 0.5
_MISMATCH_TOLERANCE = 1

# The three fields that decide the tier (context/30-data-model/04-attribute-
# reconciliation.md, context/40-pipeline/03-extraction-contract.md). A call
# whose grounding pass nulls any of these gets status 'ungrounded' rather
# than 'ok' — the same "convert a silent misclassification into a visible
# escalation" move as everywhere else in this system.
TIER_DETERMINING_FIELDS = frozenset({"primary_practice", "fee_model", "attorney_count"})


def normalize(text: str) -> str:
    """Case- and whitespace-normalise for substring comparison."""
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def is_grounded(evidence: str | None, normalized_source: str) -> bool:
    """Whether `evidence` occurs verbatim (post-normalisation) in the
    already-normalised source text. Empty/None evidence is never grounded —
    a required-evidence field with no evidence is exactly what should fail."""
    if not evidence:
        return False
    needle = normalize(evidence)
    return bool(needle) and needle in normalized_source


def _ground_attorney_count(ac, normalized_source: str, ungrounded: list[str]) -> None:
    """Mutates `ac` (an AttorneyCount) in place."""
    if ac.method == AttorneyCountMethod.TEAM_PAGE_COUNT:
        grounded_names = [n for n in ac.attorney_names if is_grounded(n, normalized_source)]
        recounted = len(grounded_names)
        reported = ac.value
        ac.attorney_names = grounded_names
        if reported is None and recounted == 0:
            # Nothing claimed and nothing to ground -- the legitimate "no
            # team page" null (contract: null rather than a guess). Recomputing
            # this to 0 would silently turn "unknown" into "a firm confirmed
            # to have zero attorneys", a different and false claim.
            ac.value = None
        else:
            ac.value = recounted
            reported_or_zero = reported if reported is not None else 0
            if abs(reported_or_zero - recounted) > _MISMATCH_TOLERANCE:
                ungrounded.append("attorney_count")
                ac.confidence = min(ac.confidence, _MISMATCH_CONFIDENCE_CAP)

    elif ac.method == AttorneyCountMethod.STATED:
        if not is_grounded(ac.evidence, normalized_source):
            ungrounded.append("attorney_count")
            ac.value = None
            ac.confidence = 0.0
            ac.evidence = None
            ac.attorney_names = []

    elif ac.method == AttorneyCountMethod.INFERRED:
        ac.confidence = min(ac.confidence, _INFERRED_CONFIDENCE_CAP)


def ground(extraction: FirmExtraction, source_text: str) -> tuple[FirmExtraction, list[str]]:
    """Return a grounded copy of `extraction` plus the field names whose
    evidence failed the grounding check (nulled to their unknown/zero-
    confidence state). Never mutates `extraction` itself."""
    normalized_source = normalize(source_text)
    data = extraction.model_copy(deep=True)
    ungrounded: list[str] = []

    pp = data.primary_practice
    if pp.value is not None and not is_grounded(pp.evidence, normalized_source):
        ungrounded.append("primary_practice")
        pp.value = None
        pp.confidence = 0.0
        pp.evidence = None

    # fee_model: evidence is required whenever value != "unknown" (contract:
    # "required if != unknown"). Missing evidence and invented evidence are
    # both grounding failures.
    fm = data.fee_model
    if fm.value != FeeModelValue.UNKNOWN and not is_grounded(fm.evidence, normalized_source):
        ungrounded.append("fee_model")
        fm.value = FeeModelValue.UNKNOWN
        fm.confidence = 0.0
        fm.evidence = None

    _ground_attorney_count(data.attorney_count, normalized_source, ungrounded)

    # spanish_intake / has_inhouse_recruiter: bool value + evidence, but the
    # contract gives them no confidence field to zero. Ungrounded evidence
    # gets the conservative reading (False) and the evidence cleared; still
    # recorded in ungrounded_fields for observability. Neither is
    # tier-determining, so this never flips call status to 'ungrounded'.
    # write_claims() only ever writes these as an asserted-true claim, so a
    # value forced False here also means no claim is written at all.
    si = data.spanish_intake
    if si.evidence is not None and not is_grounded(si.evidence, normalized_source):
        ungrounded.append("spanish_intake")
        si.value = False
        si.evidence = None

    hr = data.has_inhouse_recruiter
    if hr.evidence is not None and not is_grounded(hr.evidence, normalized_source):
        ungrounded.append("has_inhouse_recruiter")
        hr.value = False
        hr.evidence = None

    # A decision maker whose name does not appear in the text is dropped —
    # per the contract, framed around the name specifically. Also require
    # the evidence quote itself to be grounded: an invented quote attached to
    # a real name is exactly as untrustworthy as an invented name.
    data.decision_makers = [
        dm
        for dm in data.decision_makers
        if is_grounded(dm.name, normalized_source) and is_grounded(dm.evidence, normalized_source)
    ]

    return data, ungrounded


def call_status(ungrounded_fields: list[str]) -> str:
    """'ungrounded' if grounding nulled a tier-determining field, else 'ok'.
    Never returns 'invalid' or 'failed' — those are call-level outcomes
    decided before grounding ever runs."""
    if any(field in TIER_DETERMINING_FIELDS for field in ungrounded_fields):
        return "ungrounded"
    return "ok"
