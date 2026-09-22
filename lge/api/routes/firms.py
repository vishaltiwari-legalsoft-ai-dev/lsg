"""GET /api/firms, GET /api/firms/{id} -- "the record". Every claim's
winner is computed by `lge.score.reconcile.resolve_claims`, the engine's
own precedence algorithm -- never re-derived here. The displayed value for
a reconciled attribute always comes straight off the `firm` row (the only
thing `reconcile()` is allowed to write, per invariant I7); this route
explains that value, it never recomputes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

from lge.api.attributes import build_attributes_for_firm
from lge.api.cursor import decode_cursor, encode_cursor
from lge.api.deps import ConnDep
from lge.api.errors import not_found
from lge.api.labels import source_label, state_display, tier_display, tier_reason
from lge.api.models import (
    AliasRow,
    DocumentRow,
    FirmDetail,
    FirmLeadRef,
    FirmListItem,
    FirmsResponse,
)
from lge.api.rendering import (
    build_contact_summary,
    build_firm_ref,
    build_proof,
    fetch_pain_analysis,
    fetch_signal_scores,
)
from lge.export.list import fetch_contacts, fetch_emails, fetch_repost_first_seen
from lge.journey.model import Signal as JourneySignal
from lge.score.reconcile import load_precedence

router = APIRouter(prefix="/api", tags=["firms"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200

@router.get("/firms", response_model=FirmsResponse)
def list_firms(
    conn: ConnDep,
    q: str | None = None,
    tier: str | None = None,
    city: str | None = None,
    lead_state: str | None = None,
    cursor: str | None = None,
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX),
) -> FirmsResponse:
    where = ["1=1"]
    params: dict[str, Any] = {}
    if q:
        where.append("(f.canonical_name ILIKE %(q)s OR f.domain ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if tier:
        where.append("f.tier = %(tier)s")
        params["tier"] = tier
    if city:
        where.append("lower(f.city) = lower(%(city)s)")
        params["city"] = city
    if lead_state:
        where.append("l.state = %(lead_state)s")
        params["lead_state"] = lead_state

    cursor_clause = ""
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded and len(decoded) == 2:
            cursor_clause = " AND (f.canonical_name, f.id) > (%(cn)s, %(cid)s::uuid)"
            params["cn"], params["cid"] = decoded[0], decoded[1]

    where_sql = " AND ".join(where) + cursor_clause
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) AS n FROM firm f "  # noqa: S608 -- fixed fragments, bound params
            f"LEFT JOIN lead l ON l.firm_id = f.id AND l.closed_at IS NULL "
            f"WHERE {' AND '.join(where)}",
            params,
        )
        total = cur.fetchone()["n"]

        cur.execute(
            f"""
            SELECT f.id, f.canonical_name AS name, f.domain, f.city, f.state,
                   f.tier, f.fit_score, l.state AS lead_state
            FROM firm f
            LEFT JOIN lead l ON l.firm_id = f.id AND l.closed_at IS NULL
            WHERE {where_sql}
            ORDER BY f.canonical_name ASC, f.id ASC
            LIMIT %(limit)s
            """,  # noqa: S608
            {**params, "limit": limit + 1},
        )
        rows = cur.fetchall()

    has_more = len(rows) > limit
    page = rows[:limit]
    items = [
        FirmListItem(
            id=str(r["id"]), name=r["name"], domain=r["domain"], city=r["city"], state=r["state"],
            tier_display=tier_display(r["tier"]),
            state_display=state_display(r["lead_state"]) if r["lead_state"] else None,
            fit=r["fit_score"],
        )
        for r in page
    ]
    next_cursor = (
        encode_cursor([page[-1]["name"], str(page[-1]["id"])]) if has_more and page else None
    )
    return FirmsResponse(items=items, next_cursor=next_cursor, total=total)


# ---------------------------------------------------------------------------
# Firm detail
# ---------------------------------------------------------------------------


@router.get("/firms/{firm_id}", response_model=FirmDetail)
def get_firm(firm_id: str, conn: ConnDep) -> FirmDetail:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM firm WHERE id = %s", (firm_id,))
        firm = cur.fetchone()
    if firm is None:
        raise not_found("Firm not found.", "Check the id.")
    firm = dict(firm)
    firm["firm_id"] = firm["id"]

    at = datetime.now(UTC)
    cfg = load_precedence()
    attributes = build_attributes_for_firm(conn, firm, cfg, at)

    with conn.cursor() as cur:
        # One row per URL, its latest fetch: a page read in two crawls is one
        # page on the record (and one React key on the screen).
        cur.execute(
            "SELECT url, page_kind, status_code, words, robots_decision, fetched_at FROM ("
            "  SELECT DISTINCT ON (url) url, page_kind, status_code, word_count AS words, "
            "         robots_decision, fetched_at"
            "  FROM document WHERE firm_id = %s ORDER BY url, fetched_at DESC"
            ") latest ORDER BY fetched_at DESC",
            (firm_id,),
        )
        documents = [DocumentRow(**r) for r in cur.fetchall()]

        cur.execute(
            "SELECT alias_name AS name, alias_domain AS domain, alias_phone AS phone, "
            "merge_rule, source FROM firm_alias WHERE firm_id = %s",
            (firm_id,),
        )
        aliases = [
            AliasRow(
                name=r["name"], domain=r["domain"], phone=r["phone"],
                merge_rule=r["merge_rule"], source_label=source_label(r["source"]),
            )
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT id, kind, first_seen, last_seen, closed_at, repost_count, evidence "
            "FROM signal WHERE firm_id = %s ORDER BY first_seen DESC",
            (firm_id,),
        )
        signal_rows = cur.fetchall()

        cur.execute(
            "SELECT id, state, band FROM lead WHERE firm_id = %s AND closed_at IS NULL",
            (firm_id,),
        )
        lead_row = cur.fetchone()

    signals_typed = [
        JourneySignal(
            id=r["id"], kind=r["kind"], first_seen=r["first_seen"], last_seen=r["last_seen"],
            closed_at=r["closed_at"], repost_count=r["repost_count"] or 0,
            evidence=r["evidence"] or {},
        )
        for r in signal_rows
    ]
    signal_scores = fetch_signal_scores(conn, [s.id for s in signals_typed], at)
    repost_by_signal_id = fetch_repost_first_seen(conn, signal_rows)
    signals = [
        build_proof(s, repost_by_signal_id.get(s.id), signal_scores, at) for s in signals_typed
    ]

    # fetch_contacts keys by the row's uuid; the path gives a str. Looking up
    # with the str hid every contact on every firm page (found 15 Sep 2026).
    contacts_by_firm = fetch_contacts(conn, [firm["id"]])
    firm_contacts = contacts_by_firm.get(firm["id"], [])
    emails_by_contact = fetch_emails(conn, [c["id"] for c in firm_contacts])
    contacts = [build_contact_summary(c, emails_by_contact) for c in firm_contacts]

    lead_ref = (
        FirmLeadRef(id=str(lead_row["id"]), state_display=state_display(lead_row["state"]),
                    band=lead_row["band"])
        if lead_row
        else None
    )

    return FirmDetail(
        firm=build_firm_ref(firm),
        tier_reason=tier_reason(firm),
        attributes=attributes,
        documents=documents,
        signals=signals,
        contacts=contacts,
        aliases=aliases,
        pain=fetch_pain_analysis(conn, firm_id),
        lead=lead_ref,
    )
