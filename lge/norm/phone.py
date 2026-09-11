"""norm_phone / shared_numbers — canonical E.164 phone identity keys.

Bump NORM_VERSION["norm_phone"] whenever output can change for any input.

Storing a phone number formatted (rather than E.164) means two spellings of the same
number never compare equal, and dedupe silently degrades to name matching only. A
number that resolves to many distinct firm candidates is an answering service or a
call-tracking pool, not an identity key — shared_numbers() flags those for exclusion.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import phonenumbers


def norm_phone(raw: str | None, region: str = "US") -> str | None:
    """Parse `raw` and return E.164 iff it is a valid number, else None.

    Extensions ("x123", "ext. 5", ...) are recognised by phonenumbers as part of
    parsing and are never included in the E.164 output — the canonical value is the
    line number alone.
    """
    if not raw or not raw.strip():
        return None
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def shared_numbers(pairs: Iterable[tuple[str, str]], threshold: int = 4) -> set[str]:
    """Return the E.164 numbers backed by >= `threshold` DISTINCT candidate ids.

    `pairs` is (e164_number, candidate_id). Repeats of the same id against the same
    number (e.g. multiple observations) do not inflate the distinct count.
    """
    candidates_by_number: dict[str, set[str]] = defaultdict(set)
    for number, candidate_id in pairs:
        candidates_by_number[number].add(candidate_id)
    return {
        number
        for number, candidates in candidates_by_number.items()
        if len(candidates) >= threshold
    }
