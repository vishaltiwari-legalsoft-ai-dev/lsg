"""GET /api/qualified -- the leads on which every step has been done, ready
to reach; and the ones one or two steps away, with what is missing (D-047).

Seven checks, each with the evidence it read:

  site_read       the firm's site was read (a page of a kind the engine reads)
  fit             the firm fits the profile (tiered, not disqualified)
  person          a decision-maker is named (owner or office manager)
  email           that person has an address on file
  email_verified  the address passed OUR verification ('valid' -- nothing less)
  linkedin        that person has a LinkedIn profile
  journey         the nine-touch journey renders for the lead

`ready` is all seven. `almost` is four or more of the first six (the journey
is only asked of leads that pass the rest). The pain signal is shown, not
required: the journey renders without one for a nurture lead. Nothing here
recomputes a tier, a band or a draft -- the checks read what the engine
already wrote.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Query
from fastapi.responses import Response

from lge.api.deps import ConnDep
from lge.api.labels import email_status_display, reason_display
from lge.api.models import (
    QualifiedCheck,
    QualifiedCounts,
    QualifiedResponse,
    QualifiedRow,
)
from lge.api.routes.leads import _build_stage_rows, drafts_for_row
from lge.fetch.config import wanted_kinds

router = APIRouter(prefix="/api", tags=["qualified"])

CHECKS: tuple[tuple[str, str], ...] = (
    ("site_read", "Website read"),
    ("fit", "Fits the profile"),
    ("person", "Decision-maker named"),
    ("email", "Address on file"),
    ("email_verified", "Address verified"),
    ("linkedin", "LinkedIn profile"),
    ("journey", "Journey drafted"),
)
_SQL_CHECKS = ("site_read", "fit", "person", "email", "email_verified", "linkedin")
ALMOST_MIN_PASSES = 4  # of the six checks the database answers
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200

_BAND_WORD = {"STRIKE": "Strike", "SEQUENCE": "Sequence", "NURTURE": "Nurture", "HOLD": "Hold"}


def _fetch_candidates(conn: psycopg.Connection, q: str | None) -> list[dict]:
    """Every open lead at a firm that is not disqualified, with the six checks
    the database can answer, most complete first."""
    where = [
        "l.closed_at IS NULL",
        "l.state NOT IN ('SUPPRESSED', 'DISQUALIFIED', 'WON', 'LOST')",
        "(f.tier IS NULL OR f.tier NOT LIKE 'DQ%%')",
    ]
    params: dict[str, Any] = {"kinds": list(wanted_kinds())}
    if q:
        where.append("(f.canonical_name ILIKE %(q)s OR f.domain ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    sql = f"""
        WITH dm AS (
            SELECT DISTINCT ON (c.firm_id)
                   c.firm_id, c.id AS contact_id, c.full_name, c.title, c.linkedin_url
            FROM contact c
            WHERE c.removed_at IS NULL AND c.role IN ('owner', 'admin')
            ORDER BY c.firm_id, (c.role = 'owner') DESC, c.confidence DESC NULLS LAST, c.id
        )
        SELECT l.id AS lead_id, l.grade, l.band, l.contest, l.fit_score, l.intent_score,
               l.arming_signal, l.state AS lead_state, l.scored_at, l.cooldown_until, l.owner,
               f.id AS firm_id, f.canonical_name, f.domain, f.city, f.state,
               f.tier, f.fee_model, f.primary_practice, f.cms_detected,
               dm.contact_id AS dm_id, dm.full_name AS dm_name, dm.title AS dm_title,
               dm.linkedin_url AS dm_linkedin,
               EXISTS (SELECT 1 FROM document d WHERE d.firm_id = f.id AND d.fetch_ok
                       AND d.status_code = 200 AND NOT d.soft_404
                       AND d.page_kind = ANY(%(kinds)s)) AS site_read,
               (f.tier IS NOT NULL AND f.tier <> 'UNCLASSIFIED'
                AND f.tier NOT LIKE 'DQ%%') AS fit,
               (dm.contact_id IS NOT NULL) AS person,
               (SELECT e.email FROM contact_email e WHERE e.contact_id = dm.contact_id
                ORDER BY (e.status = 'valid') DESC, e.email LIMIT 1) AS dm_email,
               (SELECT e.status FROM contact_email e WHERE e.contact_id = dm.contact_id
                ORDER BY (e.status = 'valid') DESC, e.email LIMIT 1) AS dm_email_status,
               (SELECT e.vendor_status FROM contact_email e WHERE e.contact_id = dm.contact_id
                ORDER BY (e.status = 'valid') DESC, e.email LIMIT 1) AS dm_vendor_status,
               EXISTS (SELECT 1 FROM signal s WHERE s.firm_id = f.id AND s.closed_at IS NULL)
                   AS why_now
        FROM lead l
        JOIN firm f ON f.id = l.firm_id
        LEFT JOIN dm ON dm.firm_id = f.id
        WHERE {" AND ".join(where)}
        ORDER BY l.intent_score DESC NULLS LAST, l.fit_score DESC NULLS LAST, l.id
    """  # noqa: S608 -- every fragment above is a fixed literal; values are bound params
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _sql_results(r: dict) -> dict[str, bool]:
    return {
        "site_read": bool(r["site_read"]),
        "fit": bool(r["fit"]),
        "person": bool(r["person"]),
        "email": r["dm_email"] is not None,
        "email_verified": r["dm_email_status"] == "valid",
        "linkedin": bool(r["dm_linkedin"]),
    }


def _details(r: dict) -> dict[str, str | None]:
    email_status = email_status_display(r["dm_email_status"], r["dm_vendor_status"])
    return {
        "site_read": "The site was read" if r["site_read"] else "No page of the site read yet",
        "fit": r["tier"] if r["fit"] else (
            "Not tiered yet" if r["tier"] in (None, "UNCLASSIFIED") else r["tier"]
        ),
        "person": (
            f"{r['dm_name']}{', ' + r['dm_title'] if r['dm_title'] else ''}"
            if r["person"] else "No owner or office manager named"
        ),
        "email": r["dm_email"] or "No address for this person",
        "email_verified": (
            email_status if r["dm_email"] else "No address to verify"
        ),
        "linkedin": r["dm_linkedin"] or "No profile found",
    }


def _journey_check(conn: psycopg.Connection, r: dict) -> tuple[bool, str]:
    band = r["band"]
    if band not in ("SEQUENCE", "NURTURE"):
        return False, f"Not on the email list yet ({_BAND_WORD.get(band, 'not scored')})"
    drafts = drafts_for_row(conn, r, str(r["lead_id"]))
    if drafts.excluded_reason:
        return False, reason_display(drafts.excluded_reason)
    written = [t for t in drafts.touches if not t.skipped_reason]
    if not written:
        return False, "No touch could be drafted"
    return True, f"{len(written)} touches drafted"


def _classify(conn: psycopg.Connection, rows: list[dict]) -> list[tuple[dict, dict, dict, bool]]:
    """(row, results, details, ready) for every candidate that is at least
    almost ready; the journey is rendered only for the rows that pass the
    rest, so the list never pays for drafts it will not show."""
    out = []
    for r in rows:
        results = _sql_results(r)
        passes = sum(results.values())
        if passes < ALMOST_MIN_PASSES:
            continue
        details = _details(r)
        if passes == len(_SQL_CHECKS):
            ok, detail = _journey_check(conn, r)
        else:
            ok, detail = False, "Asked once the rest is done"
        results["journey"] = ok
        details["journey"] = detail
        out.append((r, results, details, all(results.values())))
    return out


def _rows(conn: psycopg.Connection, classified: list[tuple], at: datetime) -> list[QualifiedRow]:
    base = _build_stage_rows(conn, [c[0] for c in classified], at)
    out: list[QualifiedRow] = []
    for lead_row, (r, results, details, ready) in zip(base, classified, strict=True):
        checks = [
            QualifiedCheck(key=key, label=label, ok=results[key], detail=details.get(key))
            for key, label in CHECKS
        ]
        out.append(QualifiedRow(
            **lead_row.model_dump(),
            checks=checks,
            ready=ready,
            missing=[c.label for c in checks if not c.ok],
            why_now=bool(r["why_now"]),
        ))
    return out


@router.get("/qualified", response_model=QualifiedResponse)
def list_qualified(
    conn: ConnDep,
    only: str = Query("ready", pattern="^(ready|almost|all)$"),
    q: str | None = Query(None, max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX),
) -> QualifiedResponse:
    at = datetime.now(UTC)
    candidates = _fetch_candidates(conn, q)
    classified = _classify(conn, candidates)
    ready = [c for c in classified if c[3]]
    almost = [c for c in classified if not c[3]]
    missing_by_check: dict[str, int] = {key: 0 for key, _ in CHECKS}
    for _r, results, _d, _ready in almost:
        for key, ok in results.items():
            if not ok:
                missing_by_check[key] += 1
    chosen = ready if only == "ready" else almost if only == "almost" else ready + almost
    page = chosen[offset: offset + limit]
    next_offset = offset + limit if offset + limit < len(chosen) else None
    return QualifiedResponse(
        items=_rows(conn, page, at),
        next_offset=next_offset,
        counts=QualifiedCounts(
            ready=len(ready), almost=len(almost), checked=len(candidates),
            missing_by_check=missing_by_check,
        ),
    )


_CSV_COLUMNS = (
    "firm", "website", "city", "state", "tier", "decision_maker", "title", "email",
    "email_status", "linkedin", "why_now", "fit", "urgency", "lead",
)


@router.get("/qualified/export.csv")
def export_qualified_csv(conn: ConnDep) -> Response:
    """The ready leads as a sheet for the sending vendor -- never the almost-ready."""
    at = datetime.now(UTC)
    classified = [c for c in _classify(conn, _fetch_candidates(conn, None)) if c[3]]
    rows = _rows(conn, classified, at)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row, (r, _results, _details, _ready) in zip(rows, classified, strict=True):
        writer.writerow({
            "firm": row.firm.name, "website": row.firm.domain or "",
            "city": row.firm.city or "", "state": row.firm.state or "",
            "tier": row.firm.tier_display,
            "decision_maker": r["dm_name"] or "", "title": r["dm_title"] or "",
            "email": r["dm_email"] or "",
            "email_status": email_status_display(r["dm_email_status"], r["dm_vendor_status"]) or "",
            "linkedin": r["dm_linkedin"] or "",
            "why_now": row.proof.headline if row.proof else "",
            "fit": row.fit if row.fit is not None else "",
            "urgency": row.intent if row.intent is not None else "",
            "lead": f"/leads/{row.id}",
        })
    return Response(content=buf.getvalue(), media_type="text/csv")
