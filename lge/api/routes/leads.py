"""GET /api/leads, GET/POST /api/leads/{id}[...], GET /api/leads/export.csv.

Every business rule here is a call into the engine's own code:
`lge.export.list.classify_open_scored_leads` (list hygiene -- the same
selector `build_list` uses), `lge.journey.build.build_journey` (drafts),
`lge.db.writer`/`lge.db.lifecycle` (the same write contexts the pipeline
uses), and `sql/002_functions.sql`'s `signal_weight`/`decay`/`contest_level`
(score numbers). Nothing here recomputes a tier, a band, or a draft.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import psycopg
from fastapi import APIRouter, Query
from fastapi.responses import Response

from lge import db as lge_db
from lge.api.cursor import decode_cursor, encode_cursor
from lge.api.deps import ConnDep
from lge.api.errors import api_error, not_found
from lge.api.labels import reason_display, state_display
from lge.api.models import (
    DraftsResponse,
    LeadDetail,
    LeadNote,
    LeadOutcome,
    LeadRow,
    LeadsResponse,
    LeadViewCounts,
    OutcomeRequest,
    OutcomeResponse,
    ScoreBreakdown,
    ScoreFitTerm,
    ScoreIntentTerm,
    TimelineEvent,
    Touch,
)
from lge.api.rendering import (
    build_contact_summary,
    build_lead_row,
    build_proof,
    fetch_pain_analysis,
    fetch_signal_scores,
)
from lge.api.scoring import compute_fit_terms, signal_term_label
from lge.api.stage import STAGE_ORDER, stage_sql
from lge.export.list import (
    ClassifiedLead,
    LeadClassification,
    build_list,
    classify_open_scored_leads,
    fetch_contacts,
    fetch_emails,
    fetch_journey_edits,
    fetch_repost_first_seen,
    fetch_signals,
    select_contacts,
)
from lge.journey.build import build_journey
from lge.journey.catalogue import BY_PATH
from lge.journey.model import Contact as JourneyContact
from lge.journey.model import Firm as JourneyFirm
from lge.journey.model import JourneyEdits, JourneyLead, JourneyResult
from lge.journey.model import Signal as JourneySignal
from lge.journey.select import load_config as load_journey_config
from lge.registry import RunContext
from lge.settings import get_settings

router = APIRouter(prefix="/api", tags=["leads"])

_LIMIT_DEFAULT = 50
_LIMIT_MAX = 200
_CONTEST_RANK = {"NONE": 0, "LOW": 1, "MED": 2, "HIGH": 3, None: 4}
_VIEWS = ("STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED", "UNSCORED")

# ---------------------------------------------------------------------------
# Shared row/lead-detail plumbing
# ---------------------------------------------------------------------------


def _sort_key(row: LeadRow) -> tuple[int, int, int, str]:
    intent = row.intent if row.intent is not None else -1
    fit = row.fit if row.fit is not None else -1
    return (-intent, _CONTEST_RANK.get(row.contest, 4), -fit, row.id)


def _matches_filters(
    row: LeadRow,
    tier: str | None,
    city: str | None,
    signal: str | None,
    contest: str | None,
    verified: bool | None,
    q: str | None,
) -> bool:
    if tier and row.firm.tier != tier:
        return False
    if city and (row.firm.city or "").lower() != city.lower():
        return False
    if signal and (row.proof is None or row.proof.kind != signal):
        return False
    if contest and row.contest != contest:
        return False
    if verified is not None:
        is_verified = bool(row.contact and row.contact.email_status == "valid")
        if is_verified != verified:
            return False
    if q:
        ql = q.lower()
        name_hit = ql in row.firm.name.lower()
        domain_hit = bool(row.firm.domain) and ql in row.firm.domain.lower()
        if not (name_hit or domain_hit):
            return False
    return True


def _build_row_for(cl: ClassifiedLead, signal_scores: dict, emails_by_contact: dict, at) -> LeadRow:
    proof = build_proof(cl.signal, cl.repost_first_seen, signal_scores, at)
    contact = build_contact_summary(cl.primary_contact, emails_by_contact)
    return build_lead_row(cl.row, proof, contact, cl.blockers)


def _in_view(cl: ClassifiedLead, view: str) -> bool:
    """The band tabs show every lead in play at that band -- the email list's
    verdict (`category`) is shown on the row as blockers, not used to hide it.
    PHONE is grade B; EXCLUDED is only what is actually out."""
    if view in ("STRIKE", "SEQUENCE", "NURTURE"):
        return cl.pipeline_band == view
    if view == "PHONE":
        return cl.category == "PHONE"
    if view == "EXCLUDED":
        return cl.category == "EXCLUDED" and cl.pipeline_band is None
    return False


def _fetch_unscored_page(
    conn: psycopg.Connection,
    tier: str | None,
    city: str | None,
    contest: str | None,
    q: str | None,
    cursor_id: str | None,
    limit: int,
) -> list[dict]:
    # Never crawled counts as unscored even once the nightly scan has banded it
    # HOLD on vendor fit alone -- see list.py's _fetch_open_scored_leads.
    where = ["l.closed_at IS NULL", "(l.band IS NULL OR l.state = 'DISCOVERED')"]
    params: dict[str, Any] = {"limit": limit + 1}
    if tier:
        where.append("f.tier = %(tier)s")
        params["tier"] = tier
    if city:
        where.append("lower(f.city) = lower(%(city)s)")
        params["city"] = city
    if contest:
        where.append("l.contest = %(contest)s")
        params["contest"] = contest
    if q:
        where.append("(f.canonical_name ILIKE %(q)s OR f.domain ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if cursor_id:
        where.append("l.id > %(cursor_id)s::uuid")
        params["cursor_id"] = cursor_id

    sql = f"""
        SELECT l.id AS lead_id, l.grade, l.band, l.contest, l.fit_score, l.intent_score,
               l.arming_signal, l.state AS lead_state, l.scored_at, l.cooldown_until, l.owner,
               f.id AS firm_id, f.canonical_name, f.domain, f.city, f.state,
               f.tier, f.fee_model, f.primary_practice, f.cms_detected
        FROM lead l JOIN firm f ON f.id = l.firm_id
        WHERE {" AND ".join(where)}
        ORDER BY l.id ASC
        LIMIT %(limit)s
    """  # noqa: S608 -- every fragment above is a fixed literal; values are bound params
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def stage_counts(conn: psycopg.Connection) -> dict[str, int]:
    """Open leads per stage, every stage present (zero when empty)."""
    counts = dict.fromkeys(STAGE_ORDER, 0)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {stage_sql('l')} AS stage, count(*) AS n FROM lead l "  # noqa: S608 -- fixed SQL
            "WHERE l.closed_at IS NULL GROUP BY 1"
        )
        for r in cur.fetchall():
            counts[r["stage"]] = r["n"]
    return counts


def _fetch_stage_page(
    conn: psycopg.Connection,
    stage: str,
    band: str | None,
    tier: str | None,
    city: str | None,
    q: str | None,
    owner: str | None,
    cursor_id: str | None,
    limit: int,
) -> list[dict]:
    """One page of open leads at `stage`, the most urgent first (intent, then
    fit), keyed for the cursor by id."""
    where = ["l.closed_at IS NULL", f"({stage_sql('l')}) = %(stage)s"]
    params: dict[str, Any] = {"stage": stage, "limit": limit + 1}
    if band:
        where.append("l.band = %(band)s")
        params["band"] = band
    if tier:
        where.append("f.tier = %(tier)s")
        params["tier"] = tier
    if city:
        where.append("lower(f.city) = lower(%(city)s)")
        params["city"] = city
    if owner:
        where.append("lower(l.owner) = lower(%(owner)s)")
        params["owner"] = owner
    if q:
        where.append("(f.canonical_name ILIKE %(q)s OR f.domain ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if cursor_id:
        where.append("l.id > %(cursor_id)s::uuid")
        params["cursor_id"] = cursor_id
    sql = f"""
        SELECT l.id AS lead_id, l.grade, l.band, l.contest, l.fit_score, l.intent_score,
               l.arming_signal, l.state AS lead_state, l.scored_at, l.cooldown_until, l.owner,
               f.id AS firm_id, f.canonical_name, f.domain, f.city, f.state,
               f.tier, f.fee_model, f.primary_practice, f.cms_detected
        FROM lead l JOIN firm f ON f.id = l.firm_id
        WHERE {" AND ".join(where)}
        ORDER BY l.id ASC
        LIMIT %(limit)s
    """  # noqa: S608 -- every fragment above is a fixed literal; values are bound params
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _build_stage_rows(conn: psycopg.Connection, rows: list[dict], at: datetime) -> list[LeadRow]:
    """Rows for a stage page, each with its primary contact and its arming
    signal read once."""
    firm_ids = [r["firm_id"] for r in rows]
    contacts_by_firm = fetch_contacts(conn, firm_ids)
    contact_ids = [c["id"] for cs in contacts_by_firm.values() for c in cs]
    emails_by_contact = fetch_emails(conn, contact_ids)
    signal_ids = [r["arming_signal"] for r in rows if r["arming_signal"] is not None]
    signals_by_id = fetch_signals(conn, signal_ids)
    signal_scores = fetch_signal_scores(conn, list(signals_by_id), at)
    repost = fetch_repost_first_seen(conn, list(signals_by_id.values()))
    out: list[LeadRow] = []
    for r in rows:
        primary, _secondary = select_contacts(contacts_by_firm.get(r["firm_id"], []),
                                              emails_by_contact)
        signal_row = signals_by_id.get(r["arming_signal"]) if r["arming_signal"] else None
        signal = JourneySignal(**signal_row) if signal_row else None
        proof = build_proof(signal, repost.get(signal.id) if signal else None, signal_scores, at)
        out.append(build_lead_row(r, proof, build_contact_summary(primary, emails_by_contact)))
    return out


def _view_counts(conn: psycopg.Connection, classification: LeadClassification) -> LeadViewCounts:
    counts = dict.fromkeys(_VIEWS, 0)
    for cl in classification.leads:
        for view in ("STRIKE", "SEQUENCE", "NURTURE", "PHONE", "EXCLUDED"):
            if _in_view(cl, view):
                counts[view] += 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM lead WHERE closed_at IS NULL "
            "AND (band IS NULL OR state = 'DISCOVERED')"
        )
        counts["UNSCORED"] = cur.fetchone()["n"]
    return LeadViewCounts(**counts)


@router.get("/leads", response_model=LeadsResponse)
def list_leads(
    conn: ConnDep,
    view: str = Query("STRIKE", pattern="^(STRIKE|SEQUENCE|NURTURE|PHONE|EXCLUDED|UNSCORED)$"),
    stage: str | None = Query(None, pattern="^[a-z_]+$"),
    band: str | None = Query(None, pattern="^(STRIKE|SEQUENCE|NURTURE|HOLD)$"),
    owner: str | None = None,
    tier: str | None = None,
    city: str | None = None,
    signal: str | None = None,
    contest: str | None = None,
    verified: bool | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = Query(_LIMIT_DEFAULT, ge=1, le=_LIMIT_MAX),
) -> LeadsResponse:
    at = datetime.now(UTC)
    classification = classify_open_scored_leads(conn, at)
    counts = _view_counts(conn, classification)
    stages = stage_counts(conn)

    if stage is not None:
        # The work queue: every open lead at one stage, whatever its band.
        if stage not in STAGE_ORDER:
            raise api_error(400, "bad_request", f"There is no stage {stage!r}.")
        cursor_id = None
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded and len(decoded) == 1:
                cursor_id = str(decoded[0])
        rows = _fetch_stage_page(conn, stage, band, tier, city, q, owner, cursor_id, limit)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = _build_stage_rows(conn, page_rows, at)
        items = [
            r for r in items
            if _matches_filters(r, None, None, signal, contest, verified, None)
        ]
        next_cursor = (
            encode_cursor([str(page_rows[-1]["lead_id"])]) if has_more and page_rows else None
        )
        return LeadsResponse(items=items, next_cursor=next_cursor, counts=counts,
                             stage_counts=stages)

    if view == "UNSCORED":
        cursor_id: str | None = None
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded and len(decoded) == 1:
                cursor_id = str(decoded[0])
        rows = _fetch_unscored_page(conn, tier, city, contest, q, cursor_id, limit)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        # UNSCORED leads are pre-crawl by construction (band is set together
        # with fit/intent by the nightly scorer) -- no signal, no resolved
        # contact yet, so proof/contact are always null on this view.
        items = [build_lead_row(r, None, None) for r in page_rows]
        next_cursor = (
            encode_cursor([str(page_rows[-1]["lead_id"])]) if has_more and page_rows else None
        )
        return LeadsResponse(items=items, next_cursor=next_cursor, counts=counts,
                             stage_counts=stages)

    signal_ids = [cl.signal.id for cl in classification.leads if cl.signal is not None]
    signal_scores = fetch_signal_scores(conn, signal_ids, at)

    built = [
        _build_row_for(cl, signal_scores, classification.emails_by_contact, at)
        for cl in classification.leads
        if _in_view(cl, view)
    ]
    built = [r for r in built if _matches_filters(r, tier, city, signal, contest, verified, q)]
    built.sort(key=_sort_key)

    cursor_tuple = None
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded and len(decoded) == 4:
            cursor_tuple = tuple(decoded)
    if cursor_tuple is not None:
        built = [r for r in built if _sort_key(r) > cursor_tuple]

    page = built[:limit]
    has_more = len(built) > limit
    next_cursor = encode_cursor(list(_sort_key(page[-1]))) if has_more and page else None

    return LeadsResponse(items=page, next_cursor=next_cursor, counts=counts, stage_counts=stages)


# ---------------------------------------------------------------------------
# CSV export -- runs build_list, so list hygiene applies at export time.
# Registered before the /{lead_id} routes below: Starlette matches routes in
# registration order, and "export.csv" would otherwise be captured as a
# lead_id by the dynamic path.
# ---------------------------------------------------------------------------


@router.get("/leads/export.csv")
def export_csv(
    conn: ConnDep,
    view: str = Query("STRIKE", pattern="^(STRIKE|SEQUENCE|NURTURE|PHONE)$"),
) -> Response:
    with TemporaryDirectory() as tmp:
        ctx = RunContext(conn, get_settings())
        build_list(ctx, out_dir=tmp)
        if view == "STRIKE":
            text = (Path(tmp) / "strike.csv").read_text(encoding="utf-8")
        elif view == "PHONE":
            text = (Path(tmp) / "phone_list.csv").read_text(encoding="utf-8")
        else:
            with (Path(tmp) / "leads_ranked.csv").open(encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys() if rows else [])
            writer.writeheader()
            for r in rows:
                if r.get("band") == view:
                    writer.writerow(r)
            text = buf.getvalue()

    return Response(content=text, media_type="text/csv")


# ---------------------------------------------------------------------------
# Lead detail
# ---------------------------------------------------------------------------


def _fetch_lead_row(conn: psycopg.Connection, lead_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.id AS lead_id, l.grade, l.band, l.contest, l.wedge_sku,
                   l.fit_score, l.intent_score, l.arming_signal, l.contact_id,
                   l.state AS lead_state, l.scored_at, l.cooldown_until,
                   l.closed_at, l.close_reason, l.owner,
                   f.id AS firm_id, f.canonical_name, f.domain, f.city, f.state,
                   f.tier, f.fee_model, f.primary_practice, f.cms_detected,
                   f.entity_kind, f.country, f.attorney_count, f.staff_ratio,
                   f.review_count, f.paid_ads_active, f.spanish_intake,
                   f.has_hired_support_roles, f.repeat_role_count
            FROM lead l JOIN firm f ON f.id = l.firm_id
            WHERE l.id = %s
            """,
            (lead_id,),
        )
        return cur.fetchone()


def _pick_owner_and_admin(contacts: list[dict]) -> tuple[dict | None, dict | None]:
    owner = next((c for c in contacts if c.get("role") == "owner"), None)
    admin = next((c for c in contacts if c.get("role") == "admin"), None)
    return owner, admin


def _classified(classification: LeadClassification | None, lead_id: str) -> ClassifiedLead | None:
    if classification is None:
        return None
    return next((cl for cl in classification.leads if cl.lead_id == lead_id), None)


def _build_score_breakdown(
    conn: psycopg.Connection, row: dict, at: datetime
) -> ScoreBreakdown:
    fit_terms = [ScoreFitTerm(**t) for t in compute_fit_terms(row)]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.kind, s.closed_at,
                   signal_weight(s.kind, s.first_seen, s.closed_at, s.repost_count, %(at)s)
                     AS weight,
                   decay(EXTRACT(EPOCH FROM (%(at)s - s.last_seen)) / 86400.0) AS decay
            FROM signal s WHERE s.firm_id = %(firm_id)s
            ORDER BY s.first_seen DESC
            """,
            {"at": at, "firm_id": row["firm_id"]},
        )
        signal_rows = cur.fetchall()

    intent_terms = [
        ScoreIntentTerm(
            label=signal_term_label(s["kind"], s["closed_at"]),
            weight=int(s["weight"]),
            decay=float(s["decay"]),
            points=round(float(s["weight"]) * float(s["decay"]), 1),
        )
        for s in signal_rows
    ]

    return ScoreBreakdown(
        fit_terms=fit_terms,
        intent_terms=intent_terms,
        note="Scores use seeded weights until outcomes are recorded.",
    )


def _build_lead_detail(conn: psycopg.Connection, lead_id: str) -> LeadDetail | None:
    row = _fetch_lead_row(conn, lead_id)
    if row is None:
        return None
    at = datetime.now(UTC)

    contacts_by_firm = fetch_contacts(conn, [row["firm_id"]])
    firm_contacts = contacts_by_firm.get(row["firm_id"], [])
    contact_ids = [c["id"] for c in firm_contacts]
    emails_by_contact = fetch_emails(conn, contact_ids)

    owner, admin = _pick_owner_and_admin(firm_contacts)
    contacts = [
        c
        for c in (
            build_contact_summary(owner, emails_by_contact),
            build_contact_summary(admin, emails_by_contact),
        )
        if c is not None
    ]
    missing_roles = [r for r, c in (("owner", owner), ("admin", admin)) if c is None]
    primary_contact = owner or admin

    signal = None
    if row["arming_signal"] is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, first_seen, last_seen, closed_at, repost_count, evidence "
                "FROM signal WHERE id = %s",
                (row["arming_signal"],),
            )
            signal_row = cur.fetchone()
        if signal_row is not None:
            signal = JourneySignal(
                id=signal_row["id"], kind=signal_row["kind"],
                first_seen=signal_row["first_seen"], last_seen=signal_row["last_seen"],
                closed_at=signal_row["closed_at"], repost_count=signal_row["repost_count"] or 0,
                evidence=signal_row["evidence"] or {},
            )
    signal_scores = fetch_signal_scores(conn, [signal.id] if signal else [], at)
    repost_first_seen = (
        fetch_repost_first_seen(conn, [signal_row]).get(signal.id) if signal else None
    )
    proof = build_proof(signal, repost_first_seen, signal_scores, at)

    classification = classify_open_scored_leads(conn, at) if row["band"] is not None else None
    classified = _classified(classification, lead_id)
    exclusion_reasons = [reason_display(r) for r in classified.reasons] if classified else []
    blockers = classified.blockers if classified else ()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, action, until, note, actor, transition_applied, at "
            "FROM lead_outcome WHERE lead_id = %s ORDER BY at DESC, id DESC",
            (lead_id,),
        )
        outcomes = [LeadOutcome(**r) for r in cur.fetchall()]

        cur.execute(
            "SELECT from_state, to_state, trigger, actor, at "
            "FROM lead_state_event WHERE lead_id = %s ORDER BY at ASC, id ASC",
            (lead_id,),
        )
        timeline = [
            TimelineEvent(
                from_state=r["from_state"], to_state=r["to_state"],
                label=state_display(r["to_state"]), trigger=r["trigger"],
                actor=r["actor"] or "system", at=r["at"],
            )
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT id, text, actor, at FROM lead_note WHERE lead_id = %s "
            "ORDER BY at DESC, id DESC",
            (lead_id,),
        )
        notes = [LeadNote(**r) for r in cur.fetchall()]

    from lge.api.routes.actions import latest_job  # local: actions imports this module's helpers

    lead_row = build_lead_row(
        row, proof, build_contact_summary(primary_contact, emails_by_contact), blockers
    )
    return LeadDetail(
        **lead_row.model_dump(),
        contacts=contacts,
        missing_roles=missing_roles,
        score=_build_score_breakdown(conn, row, at),
        exclusion_reasons=exclusion_reasons,
        outcomes=outcomes,
        timeline=timeline,
        notes=notes,
        job=latest_job(conn, row["firm_id"]),
        pain=fetch_pain_analysis(conn, row["firm_id"]),
    )


@router.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: str, conn: ConnDep) -> LeadDetail:
    detail = _build_lead_detail(conn, lead_id)
    if detail is None:
        raise not_found("Lead not found.", "Check the id.")
    return detail


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

_SKIP_REASON: dict[int, str] = {
    2: "no job-posting role to reference",
    8: "the posting closed, or there is no role to reference",
}


@router.get("/leads/{lead_id}/drafts", response_model=DraftsResponse)
def get_drafts(lead_id: str, conn: ConnDep) -> DraftsResponse:
    row = _fetch_lead_row(conn, lead_id)
    if row is None:
        raise not_found("Lead not found.", "Check the id.")
    return drafts_for_row(conn, row, lead_id)


def drafts_for_row(
    conn: psycopg.Connection, row: dict, lead_id: str, edits: JourneyEdits | None = None
) -> DraftsResponse:
    """The journey for one lead row (band, firm columns, arming_signal) as the
    drafts endpoint renders it -- shared with /api/qualified (D-047). A caller
    rendering many rows reads the Email journey screen's edits once and
    passes them in."""
    band = row["band"]
    if band not in ("SEQUENCE", "NURTURE"):
        return _no_drafts(band, None)

    at = datetime.now(UTC)
    contacts_by_firm = fetch_contacts(conn, [row["firm_id"]])
    firm_contacts = contacts_by_firm.get(row["firm_id"], [])
    owner, admin = _pick_owner_and_admin(firm_contacts)
    primary = owner or admin
    if primary is None:
        return _no_drafts(band, "no_usable_contact")

    signal = None
    has_signal_evidence = False
    if row["arming_signal"] is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, first_seen, last_seen, closed_at, repost_count, evidence "
                "FROM signal WHERE id = %s",
                (row["arming_signal"],),
            )
            signal_row = cur.fetchone()
        if signal_row is not None:
            signal = JourneySignal(
                id=signal_row["id"], kind=signal_row["kind"],
                first_seen=signal_row["first_seen"], last_seen=signal_row["last_seen"],
                closed_at=signal_row["closed_at"], repost_count=signal_row["repost_count"] or 0,
                evidence=signal_row["evidence"] or {},
            )
            has_signal_evidence = bool(signal.evidence)

    firm = JourneyFirm(
        id=str(row["firm_id"]), canonical_name=row["canonical_name"], city=row["city"],
        state=row["state"], tier=row["tier"], fee_model=row["fee_model"],
        primary_practice=row["primary_practice"], cms_detected=row["cms_detected"],
    )
    contact = JourneyContact(
        id=str(primary["id"]), full_name=primary["full_name"],
        title=primary.get("title"), role=primary.get("role"),
    )
    journey_lead = JourneyLead(
        lead_id=lead_id, band=band, firm=firm, contact=contact, signal=signal,
        repost_first_seen=None, at=at,
    )
    result = build_journey(journey_lead, edits if edits is not None else fetch_journey_edits(conn))
    return drafts_from_result(band, result, has_signal_evidence)


def drafts_from_result(
    band: str, result: JourneyResult, has_signal_evidence: bool
) -> DraftsResponse:
    """A rendered journey as the API sends it: every email the band expects,
    in order, the ones this lead does not get saying why. Shared by a lead's
    drafts and the Email journey screen's example firm."""
    if result.excluded_reason is not None:
        return _no_drafts(band, result.excluded_reason)

    band_rules = load_journey_config()["band_rules"]
    if band == "SEQUENCE":
        expected_steps = list(band_rules["SEQUENCE"]["touches"])
    else:
        rules = band_rules["NURTURE"]
        expected_steps = list(
            rules["touches_with_signal"] if has_signal_evidence else rules["touches_without_signal"]
        )
    present = {t.step for t in result.touches}

    touches = [
        Touch(
            step=t.step, day=t.day, subject=t.subject, body=t.body, skipped_reason=None,
            templates=[BY_PATH[path].id for path in t.templates],
        )
        for t in result.touches
    ]
    for step in expected_steps:
        if step in present:
            continue
        touches.append(
            Touch(
                step=step, day=0, subject="", body="",
                skipped_reason=_SKIP_REASON.get(step, "not applicable for this lead"),
                templates=[],
            )
        )
    touches.sort(key=lambda t: t.step)

    return DraftsResponse(band=band, excluded_reason=None, excluded_display=None, touches=touches)


def _no_drafts(band: str | None, code: str | None) -> DraftsResponse:
    """No emails for this lead: the engine's code, and the same reason in words."""
    return DraftsResponse(
        band=band, excluded_reason=code,
        excluded_display=reason_display(code) if code else None, touches=[],
    )


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------

_ACTION_TARGET_STATE: dict[str, str] = {
    "sent": "ENGAGED",
    "replied": "RESPONDED",
    "meeting": "HANDOFF",
    "won": "WON",
    "lost": "LOST",
    "opt_out": "SUPPRESSED",
}
_SUCCESS_MESSAGE: dict[str, str] = {
    "sent": "Marked as sent.",
    "replied": "Marked as replied.",
    "meeting": "Marked as a meeting booked.",
    "won": "Marked as won.",
    "lost": "Marked as lost.",
}
_ACTION_NOUN: dict[str, str] = {
    "sent": "sent",
    "replied": "replied",
    "meeting": "a meeting",
    "won": "won",
    "lost": "lost",
}


def _target_state(action: str, lead_row: dict) -> str:
    if action == "not_now":
        return "QUALIFIED_A" if lead_row.get("grade") == "A" else "QUALIFIED_B"
    return _ACTION_TARGET_STATE[action]


def _whitelisted(conn: psycopg.Connection, from_state: str, to_state: str) -> bool:
    if from_state == to_state:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM lead_transition WHERE from_state = %s AND to_state = %s",
            (from_state, to_state),
        )
        return cur.fetchone() is not None


def _outcome_message(action: str, transition_applied: bool, target_state: str) -> str:
    if action == "opt_out":
        return "Opted out. The firm's domain has been suppressed."
    if action == "not_now":
        return (
            f"Marked as not now — moved to {state_display(target_state)}."
            if transition_applied
            else "Recorded as not now. The cooldown is set; the lead's state did not change."
        )
    if transition_applied:
        return _SUCCESS_MESSAGE.get(action, f"Marked as {action}.")
    noun = _ACTION_NOUN.get(action, action)
    return (
        f"Recorded as {noun}. The lead can't move to {state_display(target_state)} "
        "until it has been armed — the bench is empty."
    )


@router.post("/leads/{lead_id}/outcome", response_model=OutcomeResponse)
def post_outcome(
    lead_id: str, body: OutcomeRequest, conn: ConnDep
) -> OutcomeResponse:
    row = _fetch_lead_row(conn, lead_id)
    if row is None:
        raise not_found("Lead not found.", "Check the id.")
    if body.action == "not_now" and body.until is None:
        raise api_error(400, "bad_request", "`until` is required for not_now.")

    target_state = _target_state(body.action, row)
    current_state = row["lead_state"]
    can_apply = _whitelisted(conn, current_state, target_state)

    with lge_db.lifecycle(conn, "ui_outcome", actor="ui"):
        if can_apply:
            with conn.cursor() as cur:
                cur.execute("UPDATE lead SET state = %s WHERE id = %s", (target_state, lead_id))

        if body.action == "not_now":
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE lead SET cooldown_until = %s WHERE id = %s",
                    (body.until, lead_id),
                )

        if body.action == "opt_out":
            with conn.cursor() as cur:
                if row["domain"]:
                    cur.execute(
                        "INSERT INTO suppression (scope, value, reason, added_at) "
                        "VALUES ('domain', %s, 'optout', now()) "
                        "ON CONFLICT (scope, value) DO NOTHING",
                        (row["domain"],),
                    )
                else:
                    cur.execute(
                        "INSERT INTO suppression (scope, value, reason, added_at) "
                        "VALUES ('firm_id', %s, 'optout', now()) "
                        "ON CONFLICT (scope, value) DO NOTHING",
                        (str(row["firm_id"]),),
                    )

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lead_outcome "
                "(lead_id, action, until, note, actor, transition_applied) "
                "VALUES (%s, %s, %s, %s, 'ui', %s)",
                (lead_id, body.action, body.until, body.note, can_apply),
            )

    detail = _build_lead_detail(conn, lead_id)
    message = _outcome_message(body.action, can_apply, target_state)
    return OutcomeResponse(lead=detail, transition_applied=can_apply, message=message)


