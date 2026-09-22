"""Attribute-row rendering for `GET /api/firms/{id}` AND `GET /api/handcheck`
(the hand-check sample shows the exact same attribute/claim/winner view for
its 50 firms) -- one function, reused, per plan/api-contract.md's "one
source of truth" rule. Every claim's `won` flag is computed by
`lge.score.reconcile.resolve_claims`, the engine's own precedence
algorithm; the displayed value for a reconciled attribute always comes off
the `firm` row itself (the only thing `reconcile()` may write, per I7).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from lge.api.labels import UNKNOWN_DISPLAY, attr_label, format_attr_value, source_label
from lge.api.models import AttributeClaim, AttributeRow
from lge.score.reconcile import Claim, PrecedenceConfig, resolve_claims

# `address` composes several firm columns; every other reconciled attr's
# claim value IS the firm column of the same name (score/reconcile.py's
# _SCALAR_COLUMNS convention).
_ADDRESS_PARTS = ("street_norm", "addr_unit", "city", "state", "zip5")


def firm_value_for_attr(firm: dict[str, Any], attr: str) -> Any:
    if attr == "address":
        parts = [str(firm.get(p)) for p in _ADDRESS_PARTS if firm.get(p)]
        return ", ".join(parts) if parts else None
    return firm.get(attr)


def build_attribute_row(
    attr: str,
    firm: dict[str, Any],
    all_claim_rows: list[dict],
    open_conflict_attrs: set[str],
    stale_by_attr: dict[str, bool],
    cfg: PrecedenceConfig,
    at: datetime,
) -> AttributeRow:
    freshness_cutoff = at - timedelta(days=cfg.freshness_for(attr))
    fresh = [
        Claim(r["source"], r["value"], float(r["confidence"]), r["observed_at"], r["evidence"])
        for r in all_claim_rows
        if r["observed_at"] > freshness_cutoff
    ]
    outcome = resolve_claims(attr, fresh, cfg=cfg) if fresh else None

    winner_source = outcome.source if outcome and not outcome.conflict else None
    winner_observed_at = None
    if winner_source is not None:
        winner_observed_at = next(
            (c.observed_at for c in outcome.considered if c.source == winner_source), None
        )

    claims = [
        AttributeClaim(
            source_label=source_label(r["source"]),
            display=format_attr_value(attr, r["value"]) or UNKNOWN_DISPLAY,
            confidence=float(r["confidence"]),
            evidence=r["evidence"],
            observed_at=r["observed_at"],
            won=(
                winner_source is not None
                and r["source"] == winner_source
                and r["observed_at"] == winner_observed_at
            ),
        )
        for r in all_claim_rows
    ]
    winner_claim = next((c for c in claims if c.won), None)

    if attr in open_conflict_attrs:
        state = "conflict"
    elif stale_by_attr.get(attr):
        state = "stale"
    else:
        value = firm_value_for_attr(firm, attr)
        state = "unknown" if (value is None or value == "unknown") else "resolved"

    return AttributeRow(
        attr=attr,
        label=attr_label(attr),
        display=format_attr_value(attr, firm_value_for_attr(firm, attr)) or UNKNOWN_DISPLAY,
        state=state,
        source_label=winner_claim.source_label if winner_claim else None,
        confidence=winner_claim.confidence if winner_claim else None,
        evidence=winner_claim.evidence if winner_claim else None,
        evidence_url=None,
        observed_at=winner_claim.observed_at if winner_claim else None,
        claims=claims,
    )


def build_informational_row(attr: str, all_claim_rows: list[dict]) -> AttributeRow:
    """An attr score/reconcile.py never resolves onto a firm column
    (vendor_practice_hint, email_pattern, ...) -- shown for provenance,
    "not used for tier". The most-recently-observed claim is what's on
    display; there is no real precedence winner to compute."""
    newest = max(all_claim_rows, key=lambda r: r["observed_at"])
    claims = [
        AttributeClaim(
            source_label=source_label(r["source"]),
            display=format_attr_value(attr, r["value"]) or UNKNOWN_DISPLAY,
            confidence=float(r["confidence"]),
            evidence=r["evidence"],
            observed_at=r["observed_at"],
            won=(r is newest),
        )
        for r in all_claim_rows
    ]
    return AttributeRow(
        attr=attr,
        label=attr_label(attr),
        display=format_attr_value(attr, newest["value"]) or UNKNOWN_DISPLAY,
        state="resolved",
        source_label=source_label(newest["source"]),
        confidence=float(newest["confidence"]),
        evidence=newest["evidence"],
        evidence_url=None,
        observed_at=newest["observed_at"],
        claims=claims,
    )


def build_attributes_for_firm(
    conn: Any, firm: dict[str, Any], cfg: PrecedenceConfig, at: datetime
) -> list[AttributeRow]:
    """Every attribute `firm['id']` has at least one claim for -- reconciled
    attrs first (in `RECONCILED_ATTRS` order), then informational-only ones.
    One round trip for the claims, one each for open conflicts and
    staleness."""
    from lge.score.reconcile import RECONCILED_ATTRS

    firm_id = firm["id"]
    with conn.cursor() as cur:
        cur.execute(
            # pain_analysis is shown as its own section (D-058), not as a
            # row of raw JSON in the claims table.
            "SELECT source, attr, value, confidence, evidence, observed_at "
            "FROM firm_attribute WHERE firm_id = %s AND attr <> 'pain_analysis' "
            "ORDER BY observed_at DESC",
            (firm_id,),
        )
        all_attr_rows = cur.fetchall()

        cur.execute(
            "SELECT attr FROM reconcile_conflict WHERE firm_id = %s AND resolved_at IS NULL",
            (firm_id,),
        )
        open_conflict_attrs = {r["attr"] for r in cur.fetchall()}

        cur.execute("SELECT attr, stale FROM firm_attr_state WHERE firm_id = %s", (firm_id,))
        stale_by_attr = {r["attr"]: r["stale"] for r in cur.fetchall()}

    by_attr: dict[str, list[dict]] = {}
    for r in all_attr_rows:
        by_attr.setdefault(r["attr"], []).append(r)

    attributes: list[AttributeRow] = []
    for attr in RECONCILED_ATTRS:
        if attr in by_attr:
            attributes.append(
                build_attribute_row(
                    attr, firm, by_attr[attr], open_conflict_attrs, stale_by_attr, cfg, at
                )
            )
    for attr, rows in by_attr.items():
        if attr not in RECONCILED_ATTRS:
            attributes.append(build_informational_row(attr, rows))
    return attributes
