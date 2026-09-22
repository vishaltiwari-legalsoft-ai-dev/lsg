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

`ready` is all seven. `almost` is four or more of the first six. The
database answers the first six and returns only the leads that are at least
almost ready, most complete first; the journey is rendered in Python only
for leads that pass the other six, and at most JOURNEY_EVAL_CAP of them per
request -- beyond that a lead is shown as "not checked in this view" rather
than making every page load render thousands of drafts. The pain signal is
shown, not required. Nothing here recomputes a tier, a band or a draft.

The list rules every list and sheet applies hold a lead back from here too
(D-054): parked, a portal or competitor's customer, the firm or its domain on
the do-not-contact list (lge.export.list.HYGIENE_EXCLUSION_SQL, the same text
build_list reads). Such a lead is neither ready nor almost; the counts say
how many of the leads that would otherwise be here were held back, and why.
An address on the do-not-contact list is not an address on file. The vendor
sheet is built from the same query, so it can carry nothing the panel holds
back -- it once applied none of these rules.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import APIRouter, Query
from fastapi.responses import Response

from lge.api.deps import ConnDep
from lge.api.labels import email_status_display, reason_display, withheld_display
from lge.api.models import (
    QualifiedCheck,
    QualifiedCounts,
    QualifiedResponse,
    QualifiedRow,
    QualifiedWithheld,
)
from lge.api.routes.leads import _build_stage_rows, drafts_for_row
from lge.export.list import EMAIL_NOT_SUPPRESSED_SQL, HYGIENE_EXCLUSION_SQL, fetch_journey_edits
from lge.fetch.config import wanted_kinds
from lge.journey.model import JourneyEdits

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
JOURNEY_EVAL_CAP = 500  # drafts rendered per request, for the leads that pass the other six
_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200

_BAND_WORD = {"STRIKE": "Strike", "SEQUENCE": "Sequence", "NURTURE": "Nurture", "HOLD": "Hold"}

_BASE_WHERE = (
    "l.closed_at IS NULL "
    "AND l.state NOT IN ('SUPPRESSED', 'DISQUALIFIED', 'WON', 'LOST') "
    "AND (f.tier IS NULL OR f.tier NOT LIKE 'DQ%%')"
)
_SEARCH_WHERE = "AND (f.canonical_name ILIKE %(q)s OR f.domain ILIKE %(q)s)"


def _count_checked(conn: psycopg.Connection, q: str | None) -> int:
    """Every open lead at a firm that is not disqualified -- the denominator."""
    sql = f"SELECT count(*) AS n FROM lead l JOIN firm f ON f.id = l.firm_id WHERE {_BASE_WHERE}"
    params: dict[str, Any] = {}
    if q:
        sql += f" {_SEARCH_WHERE}"
        params["q"] = f"%{q}%"
    with conn.cursor() as cur:
        cur.execute(sql, params)  # noqa: S608 -- fixed fragments; values are bound params
        return int(cur.fetchone()["n"])


def _fetch_candidates(
    conn: psycopg.Connection, q: str | None, min_passes: int, at: datetime
) -> tuple[list[dict], list[dict]]:
    """(workable, withheld): the leads at least `min_passes` of the six
    database checks along, with the checks answered, most complete first --
    split by the list rules, so no caller can forget them. `withheld` rows
    carry the rule that holds them back. The database filters, so a universe
    of a hundred thousand leads costs one indexed pass, not a round-trip per
    lead."""
    params: dict[str, Any] = {
        "kinds": list(wanted_kinds()), "min_passes": min_passes, "at": at,
    }
    search = ""
    if q:
        search = _SEARCH_WHERE
        params["q"] = f"%{q}%"
    usable = EMAIL_NOT_SUPPRESSED_SQL.format(e="e")
    sql = f"""
        WITH dm AS (
            SELECT DISTINCT ON (c.firm_id)
                   c.firm_id, c.id AS contact_id, c.full_name, c.title, c.linkedin_url
            FROM contact c
            WHERE c.removed_at IS NULL AND c.role IN ('owner', 'admin')
            ORDER BY c.firm_id, (c.role = 'owner') DESC, c.confidence DESC NULLS LAST, c.id
        ),
        best_email AS (
            SELECT DISTINCT ON (e.contact_id) e.contact_id, e.email, e.status, e.vendor_status
            FROM contact_email e JOIN dm ON dm.contact_id = e.contact_id
            WHERE {usable}
            ORDER BY e.contact_id, (e.status = 'valid') DESC, e.email
        ),
        cand AS (
            SELECT l.id AS lead_id, l.grade, l.band, l.contest, l.fit_score, l.intent_score,
                   l.arming_signal, l.state AS lead_state, l.scored_at, l.cooldown_until,
                   l.owner,
                   f.id AS firm_id, f.canonical_name, f.domain, f.city, f.state,
                   f.tier, f.fee_model, f.primary_practice, f.cms_detected,
                   dm.contact_id AS dm_id, dm.full_name AS dm_name, dm.title AS dm_title,
                   dm.linkedin_url AS dm_linkedin,
                   be.email AS dm_email, be.status AS dm_email_status,
                   be.vendor_status AS dm_vendor_status,
                   EXISTS (SELECT 1 FROM document d WHERE d.firm_id = f.id AND d.fetch_ok
                           AND d.status_code = 200 AND NOT d.soft_404
                           AND d.page_kind = ANY(%(kinds)s)) AS site_read,
                   (f.tier IS NOT NULL AND f.tier <> 'UNCLASSIFIED'
                    AND f.tier NOT LIKE 'DQ%%') AS fit,
                   (dm.contact_id IS NOT NULL) AS person,
                   (be.email IS NOT NULL) AS email,
                   -- IS TRUE: with no address at all be.status is NULL, and a
                   -- NULL check made the passes sum NULL -- the lead vanished
                   -- instead of showing as almost
                   ((be.status = 'valid') IS TRUE) AS email_verified,
                   (dm.linkedin_url IS NOT NULL) AS linkedin,
                   EXISTS (SELECT 1 FROM signal s WHERE s.firm_id = f.id
                           AND s.closed_at IS NULL) AS why_now,
                   {HYGIENE_EXCLUSION_SQL} AS withheld
            FROM lead l
            JOIN firm f ON f.id = l.firm_id
            LEFT JOIN firm_track ft ON ft.firm_id = f.id
            LEFT JOIN dm ON dm.firm_id = f.id
            LEFT JOIN best_email be ON be.contact_id = dm.contact_id
            WHERE {_BASE_WHERE} {search}
        )
        SELECT *, (site_read::int + fit::int + person::int + email::int
                   + email_verified::int + linkedin::int) AS passes
        FROM cand
        WHERE (site_read::int + fit::int + person::int + email::int
               + email_verified::int + linkedin::int) >= %(min_passes)s
        ORDER BY passes DESC, intent_score DESC NULLS LAST, fit_score DESC NULLS LAST, lead_id
    """  # noqa: S608 -- every fragment above is a fixed literal; values are bound params
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [r for r in rows if r["withheld"] is None], [r for r in rows if r["withheld"]]


def _withheld_counts(rows: list[dict]) -> list[QualifiedWithheld]:
    """How many were held back, by rule in plain words, most first."""
    by_label = Counter(withheld_display(r["withheld"]) for r in rows)
    return [QualifiedWithheld(label=label, count=n) for label, n in by_label.most_common()]


def _sql_results(r: dict) -> dict[str, bool]:
    return {key: bool(r[key]) for key in _SQL_CHECKS}


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
        "email_verified": email_status if r["dm_email"] else "No address to verify",
        "linkedin": r["dm_linkedin"] or "No profile found",
    }


def _journey_check(
    conn: psycopg.Connection, r: dict, edits: JourneyEdits
) -> tuple[bool, str]:
    band = r["band"]
    if band not in ("SEQUENCE", "NURTURE"):
        return False, f"Not on the email list yet ({_BAND_WORD.get(band, 'not scored')})"
    drafts = drafts_for_row(conn, r, str(r["lead_id"]), edits)
    if drafts.excluded_reason:
        return False, reason_display(drafts.excluded_reason)
    written = [t for t in drafts.touches if not t.skipped_reason]
    if not written:
        return False, "No touch could be drafted"
    return True, f"{len(written)} touches drafted"


def _classify(conn: psycopg.Connection, rows: list[dict]) -> list[tuple[dict, dict, dict, bool]]:
    """(row, results, details, ready) for every candidate. The journey is
    rendered only for the rows that pass the other six, and for at most
    JOURNEY_EVAL_CAP of them; the rest say so and count as almost."""
    out = []
    rendered = 0
    edits = fetch_journey_edits(conn)
    for r in rows:
        results = _sql_results(r)
        details = _details(r)
        if all(results.values()):
            if rendered < JOURNEY_EVAL_CAP:
                rendered += 1
                ok, detail = _journey_check(conn, r, edits)
            else:
                ok, detail = False, (
                    f"Not checked in this view -- more than {JOURNEY_EVAL_CAP:,} leads pass "
                    "the other six; narrow with a search"
                )
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
    checked = _count_checked(conn, q)
    workable, withheld = _fetch_candidates(conn, q, ALMOST_MIN_PASSES, at)
    classified = _classify(conn, workable)
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
            ready=len(ready), almost=len(almost), checked=checked,
            missing_by_check=missing_by_check, withheld=_withheld_counts(withheld),
        ),
    )


_CSV_COLUMNS = (
    "firm", "website", "city", "state", "tier", "decision_maker", "title", "email",
    "email_status", "linkedin", "why_now", "fit", "urgency", "lead",
)


@router.get("/qualified/export.csv")
def export_qualified_csv(conn: ConnDep) -> Response:
    """The ready leads as a sheet for the sending vendor -- never the
    almost-ready, never one the list rules hold back."""
    at = datetime.now(UTC)
    six, _withheld = _fetch_candidates(conn, None, len(_SQL_CHECKS), at)  # all six pass
    classified = [c for c in _classify(conn, six) if c[3]]
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
