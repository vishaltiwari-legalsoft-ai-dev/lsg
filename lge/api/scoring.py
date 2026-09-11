"""Score breakdown for `GET /api/leads/{id}` -- decomposes the SAME totals
`sql/002_functions.sql`'s `fit_score()`/`intent_score()` compute into the
named terms a human reads. The totals themselves are never recomputed here
-- `LeadRow.fit`/`.intent` always come straight off the `lead` row (written
by the `score` component calling those SQL functions) or, for the live
per-signal weight/decay/contest a `Proof` needs, from a direct SQL call
(`lge.api.rendering.build_proof`'s `signal_scores`). `fit_terms` below is a
display-only decomposition that mirrors `fit_score()`'s CASE expression
term-for-term (same constants, same conditions) so the two can never
silently drift without a diff showing it -- it is not itself the source of
the number shown anywhere else.
"""

from __future__ import annotations

from typing import Any

_TIER_FIT_POINTS: dict[str, int] = {"1A": 10, "1B": 8, "2": 8, "3": 5}


def compute_fit_terms(firm: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-zero terms only -- a firm with no signal on a term does not get
    a noisy zero-point row. Order matches `fit_score()`'s CASE, top to
    bottom."""
    terms: list[dict[str, Any]] = []

    if firm.get("fee_model") in ("contingency", "fee_shifting", "flat"):
        terms.append({"label": "Delegable fee model", "points": 15})

    tier_points = _TIER_FIT_POINTS.get(firm.get("tier") or "")
    if tier_points:
        terms.append({"label": f"Tier {firm.get('tier')} fit", "points": tier_points})

    attorney_count = firm.get("attorney_count")
    if attorney_count is not None:
        if 2 <= attorney_count <= 12:
            terms.append({"label": "2-12 attorneys (sweet spot)", "points": 12})
        elif 13 <= attorney_count <= 25:
            terms.append({"label": "13-25 attorneys", "points": 8})
        elif attorney_count == 1:
            terms.append({"label": "Solo practice", "points": 5})
        elif 26 <= attorney_count <= 50:
            terms.append({"label": "26-50 attorneys (longer cycle)", "points": -10})

    if firm.get("country") == "US":
        terms.append({"label": "US-based", "points": 6})
    if (firm.get("review_count") or 0) > 40:
        terms.append({"label": "High review volume (40+)", "points": 4})
    if firm.get("staff_ratio") is not None and firm["staff_ratio"] < 1.0:
        terms.append({"label": "Understaffed (ratio under 1.0)", "points": 4})
    if firm.get("paid_ads_active"):
        terms.append({"label": "Running paid ads", "points": 3})
    if firm.get("spanish_intake"):
        terms.append({"label": "Spanish intake", "points": 5})
    if firm.get("has_hired_support_roles"):
        terms.append({"label": "Has hired support roles before", "points": 5})
    if (firm.get("repeat_role_count") or 0) >= 2:
        terms.append({"label": "Repeat hiring need (2+ roles)", "points": 8})

    return terms


def signal_term_label(kind: str, closed_at: Any) -> str:
    label = kind.replace("_", " ").capitalize()
    return f"{label} (closed)" if closed_at is not None else label
