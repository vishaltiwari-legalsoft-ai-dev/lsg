"""detect_fee_model — P6, the fee-model detector.

Bump the caller's stored fee_model norm/version whenever this output can change for
any input; fee_model feeds icp_tier() directly and is never allowed to be guessed.

Rules (context/10-icp/03-fee-model.md, "Ambiguity is resolved, never guessed"):

  * Exactly one distinct family (contingency/fee_shifting/flat/hourly) matched
    anywhere on the site -> that value. Confidence 0.9, or 0.95 if two or more
    distinct sentences matched it.
  * No match anywhere -> "unknown", confidence 0.0, evidence None.
  * Several cost-centre families (contingency / fee_shifting / flat) and no hourly
    -> spec precedence, first match wins (contingency > fee_shifting > flat),
    confidence 0.8. No economic conflict: all three make support staff overhead.
  * Any cost-centre family AND hourly -> resolve by page real estate: the side
    whose sections carry strictly more weight wins (confidence 0.6); a tie ->
    "mixed", which routes to UNCLASSIFIED and P9. Never guessed.

  The spec states the mixed rule for contingency-vs-hourly because those two have
  opposite arithmetic (overhead vs billable inventory). flat-vs-hourly has the same
  opposite arithmetic, so it gets the same treatment. contingency-vs-flat does not,
  so precedence decides it — otherwise a PI firm mentioning one flat-fee service
  would drop out of tier 1A.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "fee_patterns.yml"

_PRECEDENCE: tuple[str, ...] = ("contingency", "fee_shifting", "flat", "hourly")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True, slots=True)
class FeeResult:
    value: str  # contingency | fee_shifting | flat | hourly | mixed | unknown
    confidence: float
    evidence: str | None
    matches: tuple[tuple[str, str], ...]  # (family, sentence)


@functools.lru_cache(maxsize=1)
def _load_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _compiled_patterns() -> dict[str, tuple[re.Pattern[str], ...]]:
    cfg = _load_config()
    return {
        family: tuple(re.compile(p, re.IGNORECASE) for p in cfg[family])
        for family in _PRECEDENCE
    }


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _section_weight(text: str | None, weight: float) -> float:
    if weight and weight > 0:
        return float(weight)
    return float(len((text or "").split()))


# A match inside a negated clause is not the firm's fee model: "We never charge
# hourly rates", "we do not work on a contingency basis". The clause is the text
# before the match back to the last clause break, so the "never" in "We never
# charge hourly rates -- you pay nothing unless we win" does not reach the
# contingency promise after the dash.
_CLAUSE_BREAK_RE = re.compile(r"[,;:—–]|\s-\s|\b(?:but|and|so|while|whereas)\b", re.IGNORECASE)
_NEGATION_RE = re.compile(
    r"\b(?:no|never|not|without|instead\s+of|rather\s+than|unlike|zero"
    r"|don[''’]?t|doesn[''’]?t|won[''’]?t|isn[''’]?t|aren[''’]?t)\b",
    re.IGNORECASE,
)


def _negated(sentence: str, match_start: int) -> bool:
    clause = _CLAUSE_BREAK_RE.split(sentence[:match_start])[-1]
    return bool(_NEGATION_RE.search(clause[-60:]))


def _first_unnegated_match(sentence: str, family_patterns: tuple[re.Pattern[str], ...]) -> bool:
    for pattern in family_patterns:
        m = pattern.search(sentence)
        if m is not None and not _negated(sentence, m.start()):
            return True
    return False


def _detect_fee_model_raw(sections: Sequence[tuple[str, float]]) -> FeeResult:
    patterns = _compiled_patterns()

    # (family, sentence, section_weight) for every sentence that matched, in the
    # first-family-wins-per-sentence sense.
    all_matches: list[tuple[str, str, float]] = []
    weight_by_family: dict[str, float] = {}

    for text, weight in sections:
        w = _section_weight(text, weight)
        if not text:
            continue
        families_in_section: set[str] = set()
        for sentence in _split_sentences(text):
            for family in _PRECEDENCE:
                if _first_unnegated_match(sentence, patterns[family]):
                    all_matches.append((family, sentence, w))
                    families_in_section.add(family)
                    break  # first matching family wins this sentence
        for family in families_in_section:
            weight_by_family[family] = weight_by_family.get(family, 0.0) + w

    if not all_matches:
        return FeeResult("unknown", 0.0, None, ())

    matches_tuple = tuple((f, s) for f, s, _w in all_matches)
    families_matched = {f for f, _s, _w in all_matches}

    if len(families_matched) == 1:
        family = next(iter(families_matched))
        distinct_sentences = {s for f, s, _w in all_matches if f == family}
        confidence = 0.95 if len(distinct_sentences) >= 2 else 0.9
        evidence = next(s for f, s, _w in all_matches if f == family)
        return FeeResult(family, confidence, evidence, matches_tuple)

    # Multiple families matched. Only a cost-centre vs profit-centre conflict is
    # ambiguous: contingency / fee_shifting / flat all make support staff overhead
    # (sellable), hourly makes it billable inventory (not sellable) — opposite
    # arithmetic, which is why the spec singles out "contingency AND hourly".
    # Within the cost-centre side there is no economic conflict, so the spec's
    # own rule applies: precedence top to bottom, first match wins. A PI firm that
    # mentions a flat-fee side service stays contingency (tier 1A), not mixed.
    cost_centre = [f for f in _PRECEDENCE if f in families_matched and f != "hourly"]
    if "hourly" not in families_matched:
        winner = cost_centre[0]
        evidence = next(s for f, s, _w in all_matches if f == winner)
        return FeeResult(winner, 0.8, evidence, matches_tuple)

    # Cost-centre vs hourly: resolve by page real estate; tie -> mixed. Never guess.
    cost_weight = sum(weight_by_family[f] for f in cost_centre)
    hourly_weight = weight_by_family["hourly"]
    if cost_weight != hourly_weight:
        winner = cost_centre[0] if cost_weight > hourly_weight else "hourly"
        evidence = next(s for f, s, _w in all_matches if f == winner)
        return FeeResult(winner, 0.6, evidence, matches_tuple)

    evidence = all_matches[0][1]
    return FeeResult("mixed", 0.5, evidence, matches_tuple)


# A sentence ABOUT lawyers in general is not the firm's own promise. Found in the live
# probe: "most personal injury lawyers in New York typically work on a contingency fee
# basis" (an FAQ) was taken as a firm's fee model at 0.95. Generic = a generic subject or
# hedge, with no first/second person. A slogan ("No recovery, no fee.") is the firm's own
# voice and is not generic.
_FIRM_VOICE = re.compile(r"\b(?:we|we're|we've|our|ours|us|you|your|you'll)\b", re.IGNORECASE)
_GENERIC = re.compile(
    r"\b(?:most|many|typically|generally|usually|often)\b"
    r"|\b(?:lawyers|attorneys|law\s+firms)\s+(?:typically|usually|generally|often|handle|work"
    r"|charge|take|operate|accept)\b",
    re.IGNORECASE,
)
GENERIC_CONFIDENCE_CAP = 0.6


def _is_generic(sentence: str) -> bool:
    return bool(_GENERIC.search(sentence)) and not _FIRM_VOICE.search(sentence)


def detect_fee_model(sections: Sequence[tuple[str, float]]) -> FeeResult:
    """P6. Prefers the firm's own voice as evidence; when every matching sentence for
    the winning family is a generic statement about lawyers, the value stands but its
    confidence is capped (GENERIC_CONFIDENCE_CAP) — classified, never "decisive"."""
    result = _detect_fee_model_raw(sections)
    if result.value in ("unknown", "mixed"):
        return result
    same = [s for f, s in result.matches if f == result.value]
    firm_voice = [s for s in same if not _is_generic(s)]
    if firm_voice:
        return replace(result, evidence=firm_voice[0])
    return replace(result, confidence=min(result.confidence, GENERIC_CONFIDENCE_CAP))
