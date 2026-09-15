"""The user can act (D-036): research a firm on demand, fix its people, decide
a lead, note it, own it, and do the same to many at once.

  POST /api/firms/{firm_id}/research        -> a background job (full or contacts-only)
  GET  /api/jobs/{job_id}                   -> its progress, step by step
  GET  /api/firms/{firm_id}/jobs            -> recent jobs for the firm
  POST /api/firms/{firm_id}/contacts        -> add a person
  PATCH /api/contacts/{contact_id}          -> correct a person (title, role, email, ...)
  POST /api/contacts/{contact_id}/remove    -> strike a wrong person out
  PUT  /api/leads/{lead_id}/contact         -> choose the primary contact
  POST /api/leads/{lead_id}/decision        -> qualify / disqualify / hold / reopen / handoff
  POST /api/leads/{lead_id}/notes           -> a note
  PUT  /api/leads/{lead_id}/owner           -> who works it
  POST /api/leads/batch                     -> the same for a list of leads

A research job runs the engine's own components for one firm, in the
order the flow runs them, under live=1, and records each step's outcome on
the job row as it goes (a short autocommit connection, so the screen sees
progress while the job's own transaction is open). A decision moves the
lead only through a transition the whitelist allows (I5) and always leaves
a note; the state event carries actor 'ui'.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, BackgroundTasks
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.api.deps import ConnDep
from lge.api.errors import api_error, not_found
from lge.api.models import (
    ActionJob,
    BatchRequest,
    BatchResponse,
    BatchResult,
    ContactCreate,
    ContactPatch,
    ContactRemove,
    ContactResponse,
    DecisionRequest,
    DecisionResponse,
    JobResponse,
    JobsResponse,
    JobStep,
    LeadDetail,
    NoteRequest,
    OwnerRequest,
    PrimaryContactRequest,
    ResearchRequest,
)
from lge.api.rendering import build_contact_summary
from lge.export.list import fetch_emails
from lge.norm import norm_phone
from lge.registry import RunContext, discover, registered_components
from lge.settings import get_settings

logger = logging.getLogger("lge.api.actions")
router = APIRouter(prefix="/api", tags=["actions"])

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
JOB_DIR = _PROJECT_ROOT / ".local" / "jobs"

FULL_STEPS = (
    "p1_site_map", "p2_fetch", "p3_render", "p4_text", "p5_jsonld", "p6_fee", "p7_tech",
    "px_site_rules", "px_site_facts", "reconcile", "r_site_contacts", "r_site_emails",
    "r_search_links", "r_search_emails", "r3_email_pattern", "ja1_careers", "ja6_normalise",
    "ja6_closure", "ja7_pain_signals", "reconcile", "score",
)
CONTACT_STEPS = (
    "px_site_facts", "r_site_contacts", "r_site_emails", "r_search_links", "r_search_emails",
    "r3_email_pattern", "reconcile", "score",
)
_MAX_BATCH = 100


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _job_from_row(row: dict) -> ActionJob:
    return ActionJob(
        id=str(row["id"]), kind=row["kind"], firm_id=str(row["firm_id"]),
        lead_id=str(row["lead_id"]) if row["lead_id"] else None, status=row["status"],
        steps=[JobStep(**s) for s in (row["steps"] or [])], error=row["error"],
        created_at=row["created_at"], started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _fetch_job(conn: psycopg.Connection, job_id: str) -> ActionJob | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM action_job WHERE id = %s", (job_id,))
        row = cur.fetchone()
    return _job_from_row(row) if row else None


def latest_job(conn: psycopg.Connection, firm_id: Any) -> ActionJob | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM action_job WHERE firm_id = %s ORDER BY created_at DESC LIMIT 1",
            (firm_id,),
        )
        row = cur.fetchone()
    return _job_from_row(row) if row else None


def _create_job(
    conn: psycopg.Connection, firm_id: Any, lead_id: Any, kind: str, steps: tuple[str, ...]
) -> ActionJob:
    job_id = str(uuid.uuid4())
    pending = [{"name": s, "status": "pending", "note": None} for s in steps]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO action_job (id, kind, firm_id, lead_id, steps) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (job_id, kind, firm_id, lead_id, Jsonb(pending)),
        )
        return _job_from_row(cur.fetchone())


def _set_job(job_id: str, fields: dict[str, Any], status_conn: psycopg.Connection | None) -> None:
    """Progress the screen can see while the job's own transaction is open:
    written on a separate autocommit connection (or the one a test hands in)."""
    assignments = ", ".join(f"{k} = %s" for k in fields)
    values = [Jsonb(v) if k == "steps" else v for k, v in fields.items()]
    sql = f"UPDATE action_job SET {assignments} WHERE id = %s"  # noqa: S608 -- fixed keys
    if status_conn is not None:
        with status_conn.cursor() as cur:
            cur.execute(sql, [*values, job_id])
        return
    with lge_db.connect(get_settings().dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql, [*values, job_id])


def run_job(
    job_id: str,
    conn: psycopg.Connection | None = None,
    status_conn: psycopg.Connection | None = None,
) -> None:
    """One firm through the engine's components, step by step. `conn` and
    `status_conn` default to fresh connections; tests pass their own."""
    settings = get_settings()
    own = conn is None
    conn = conn or lge_db.connect(settings.dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM action_job WHERE id = %s", (job_id,))
            job = cur.fetchone()
        if job is None:
            return
        steps = [dict(s) for s in job["steps"]]
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        ids_file = JOB_DIR / f"{job_id}.txt"
        ids_file.write_text(f"{job['firm_id']}\n", encoding="utf-8")
        _set_job(job_id, {"status": "running", "started_at": datetime.now(UTC)}, status_conn)
        discover()
        components = registered_components()
        # On its own connection each step commits; on a caller's (a test's)
        # each step is a savepoint, so the caller's transaction stays whole.
        ctx = RunContext(conn, settings, commit_checkpoints=own)
        failed_any = False
        for i, step in enumerate(steps):
            spec = components.get(step["name"])
            if spec is None:
                steps[i].update(status="failed", note="not available")
                failed_any = True
                continue
            steps[i]["status"] = "running"
            _set_job(job_id, {"steps": steps}, status_conn)
            if not own:
                with conn.cursor() as cur:
                    cur.execute("SAVEPOINT job_step")
            try:
                r = spec.fn(ctx, firm_ids_file=str(ids_file), live="1")
                note = f"processed={r.processed} skipped={r.skipped} failed={r.failed}"
                extra = [n for n in r.notes if not n.startswith("  -") and len(n) < 160]
                if extra:
                    note += " -- " + extra[-1]
                steps[i].update(status="done", note=note[:300])
                if own:
                    conn.commit()
                else:
                    with conn.cursor() as cur:
                        cur.execute("RELEASE SAVEPOINT job_step")
            except Exception as exc:  # noqa: BLE001 -- a failed step is recorded, the job goes on
                logger.exception("job %s: step %s failed", job_id, step["name"])
                if own:
                    conn.rollback()
                else:
                    with conn.cursor() as cur:
                        cur.execute("ROLLBACK TO SAVEPOINT job_step")
                steps[i].update(status="failed", note=f"{type(exc).__name__}: {exc}"[:300])
                failed_any = True
            _set_job(job_id, {"steps": steps}, status_conn)
        _set_job(job_id, {
            "status": "failed" if failed_any else "done", "finished_at": datetime.now(UTC),
            "error": "one or more steps failed" if failed_any else None,
        }, status_conn)
        try:
            ids_file.unlink()
        except OSError:
            pass
    finally:
        if own:
            conn.close()


def _run_job_in_background(job_id: str) -> None:
    try:
        run_job(job_id)
    except Exception as exc:  # noqa: BLE001 -- the job row records the failure
        logger.exception("job %s failed", job_id)
        try:
            _set_job(job_id, {
                "status": "failed", "finished_at": datetime.now(UTC),
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }, None)
        except Exception:  # noqa: BLE001
            logger.exception("job %s: could not record the failure", job_id)


def _firm_and_lead(conn: psycopg.Connection, firm_id: str) -> tuple[dict, dict | None]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, canonical_name, domain FROM firm WHERE id = %s", (firm_id,))
        firm = cur.fetchone()
        if firm is None:
            raise not_found("Firm not found.", "Check the id.")
        cur.execute(
            "SELECT id, state FROM lead WHERE firm_id = %s AND closed_at IS NULL", (firm_id,)
        )
        return firm, cur.fetchone()


def _start_research(
    conn: psycopg.Connection, background: BackgroundTasks, firm_id: str, scope: str
) -> ActionJob:
    firm, lead = _firm_and_lead(conn, firm_id)
    if scope == "full" and not firm["domain"]:
        raise api_error(
            409, "no_domain", "This firm has no website on record.",
            "Correct the website first; the crawl has nothing to read.",
        )
    running = latest_job(conn, firm_id)
    if running and running.status in ("queued", "running"):
        return running
    kind = "research" if scope == "full" else "find_contacts"
    steps = FULL_STEPS if scope == "full" else CONTACT_STEPS
    job = _create_job(conn, firm["id"], lead["id"] if lead else None, kind, steps)
    # No commit here: the pooled request connection commits when the response
    # is done, and FastAPI runs background tasks only after that.
    background.add_task(_run_job_in_background, job.id)
    return job


@router.post("/firms/{firm_id}/research", response_model=JobResponse, status_code=202)
def post_research(
    firm_id: str, body: ResearchRequest, conn: ConnDep, background: BackgroundTasks
) -> JobResponse:
    return JobResponse(job=_start_research(conn, background, firm_id, body.scope))


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, conn: ConnDep) -> JobResponse:
    job = _fetch_job(conn, job_id)
    if job is None:
        raise not_found("Job not found.", "Check the id.")
    return JobResponse(job=job)


@router.get("/firms/{firm_id}/jobs", response_model=JobsResponse)
def get_firm_jobs(firm_id: str, conn: ConnDep, limit: int = 5) -> JobsResponse:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM action_job WHERE firm_id = %s ORDER BY created_at DESC LIMIT %s",
            (firm_id, max(1, min(limit, 50))),
        )
        return JobsResponse(items=[_job_from_row(r) for r in cur.fetchall()])


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def _contact_row(conn: psycopg.Connection, contact_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, firm_id, full_name, title, role, phone_direct, linkedin_url, "
            "linkedin_headline, source, removed_at FROM contact WHERE id = %s",
            (contact_id,),
        )
        return cur.fetchone()


def _contact_response(conn: psycopg.Connection, contact_id: str) -> ContactResponse:
    row = _contact_row(conn, contact_id)
    emails = fetch_emails(conn, [row["id"]])
    return ContactResponse(contact=build_contact_summary(row, emails))


def _add_email(conn: psycopg.Connection, contact_id: Any, email: str) -> None:
    email = email.strip().lower()
    if "@" not in email or " " in email:
        raise api_error(400, "bad_request", "That is not an email address.")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status, pattern) "
            "VALUES (%s, %s, 'unverified', 'user') ON CONFLICT DO NOTHING",
            (contact_id, email),
        )


@router.post("/firms/{firm_id}/contacts", response_model=ContactResponse, status_code=201)
def post_contact(firm_id: str, body: ContactCreate, conn: ConnDep) -> ContactResponse:
    _firm_and_lead(conn, firm_id)
    name = " ".join(body.full_name.split())
    if len(name) < 3:
        raise api_error(400, "bad_request", "A name is needed.")
    contact_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact (id, firm_id, full_name, title, role, phone_direct, "
            "linkedin_url, source, confidence, enriched_at, edited_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'user', 1.0, now(), now())",
            (
                contact_id, firm_id, name, body.title, body.role or "unknown",
                norm_phone(body.phone) if body.phone else None, body.linkedin_url,
            ),
        )
    if body.email:
        _add_email(conn, contact_id, body.email)
    return _contact_response(conn, contact_id)


@router.patch("/contacts/{contact_id}", response_model=ContactResponse)
def patch_contact(contact_id: str, body: ContactPatch, conn: ConnDep) -> ContactResponse:
    row = _contact_row(conn, contact_id)
    if row is None:
        raise not_found("Contact not found.", "Check the id.")
    fields: dict[str, Any] = {}
    if body.full_name is not None:
        fields["full_name"] = " ".join(body.full_name.split())
    if body.title is not None:
        fields["title"] = body.title.strip() or None
    if body.role is not None:
        fields["role"] = body.role
    if body.phone is not None:
        fields["phone_direct"] = norm_phone(body.phone) if body.phone.strip() else None
    if body.linkedin_url is not None:
        fields["linkedin_url"] = body.linkedin_url.strip() or None
    if fields:
        fields["edited_at"] = datetime.now(UTC)
        assignments = ", ".join(f"{k} = %s" for k in fields)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE contact SET {assignments} WHERE id = %s",  # noqa: S608 -- fixed keys
                [*fields.values(), contact_id],
            )
    if body.email:
        _add_email(conn, contact_id, body.email)
    return _contact_response(conn, contact_id)


@router.post("/contacts/{contact_id}/remove", response_model=ContactResponse)
def remove_contact(contact_id: str, body: ContactRemove, conn: ConnDep) -> ContactResponse:
    row = _contact_row(conn, contact_id)
    if row is None:
        raise not_found("Contact not found.", "Check the id.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE contact SET removed_at = now(), removed_reason = %s WHERE id = %s",
            (body.reason or "wrong person", contact_id),
        )
        cur.execute(
            "UPDATE lead SET contact_id = NULL WHERE contact_id = %s AND closed_at IS NULL",
            (contact_id,),
        )
    return _contact_response(conn, contact_id)


@router.put("/leads/{lead_id}/contact", response_model=LeadDetail)
def put_primary_contact(
    lead_id: str, body: PrimaryContactRequest, conn: ConnDep
) -> LeadDetail:
    from lge.api.routes.leads import _build_lead_detail, _fetch_lead_row

    lead = _fetch_lead_row(conn, lead_id)
    if lead is None:
        raise not_found("Lead not found.", "Check the id.")
    contact = _contact_row(conn, body.contact_id)
    if contact is None or str(contact["firm_id"]) != str(lead["firm_id"]):
        raise api_error(400, "bad_request", "That contact is not at this firm.")
    if contact["removed_at"] is not None:
        raise api_error(400, "bad_request", "That contact was struck out.")
    with conn.cursor() as cur:
        cur.execute("UPDATE lead SET contact_id = %s WHERE id = %s", (body.contact_id, lead_id))
    return _build_lead_detail(conn, lead_id)


# ---------------------------------------------------------------------------
# Decisions, notes, owner
# ---------------------------------------------------------------------------


def _whitelisted(conn: psycopg.Connection, from_state: str, to_state: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM lead_transition WHERE from_state = %s AND to_state = %s",
            (from_state, to_state),
        )
        return cur.fetchone() is not None


def _has_valid_email(conn: psycopg.Connection, lead: dict) -> bool:
    if not lead.get("contact_id"):
        return False
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM contact_email WHERE contact_id = %s AND status = 'valid' LIMIT 1",
            (lead["contact_id"],),
        )
        return cur.fetchone() is not None


def _note(conn: psycopg.Connection, lead_id: Any, text: str, actor: str = "ui") -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO lead_note (lead_id, text, actor) VALUES (%s, %s, %s)",
            (lead_id, text[:2000], actor),
        )


def apply_decision(
    conn: psycopg.Connection, lead: dict, action: str, reason: str | None, until: Any
) -> str:
    """Move the lead as the decision asks, within the whitelist; always leave
    a note. Returns the message for the screen; raises api_error when the
    decision cannot apply from the lead's state."""
    state = lead["lead_state"]
    lead_id = lead["lead_id"]
    why = f" -- {reason.strip()}" if reason and reason.strip() else ""
    target: str | None = None
    message: str

    if action == "hold":
        if until is None:
            raise api_error(400, "bad_request", "`until` is required to hold a lead.")
        with conn.cursor() as cur:
            cur.execute("UPDATE lead SET cooldown_until = %s WHERE id = %s", (until, lead_id))
        _note(conn, lead_id, f"Held until {until.isoformat()}{why}")
        return f"Parked until {until.isoformat()}."

    if action == "disqualify":
        target, message = "DISQUALIFIED", "Disqualified."
    elif action == "reopen":
        if state == "DISQUALIFIED":
            target, message = "CLASSIFIED", "Reopened -- back to needing a decision."
        elif state == "LOST":
            target = "QUALIFIED_A" if _has_valid_email(conn, lead) else "QUALIFIED_B"
            message = "Reopened -- back in the pool."
        else:
            raise api_error(409, "not_closed", "Only a disqualified or lost lead can be reopened.")
    elif action == "qualify":
        if state in ("QUALIFIED_A", "QUALIFIED_B", "ARMED"):
            raise api_error(409, "already", "This lead is already qualified.")
        target = "QUALIFIED_A" if _has_valid_email(conn, lead) else "QUALIFIED_B"
        message = (
            "Qualified (grade A -- verified email)." if target == "QUALIFIED_A"
            else "Qualified (grade B -- no verified email yet; phone and LinkedIn only)."
        )
    elif action == "handoff":
        target, message = "HANDOFF", "Handed off to sales."
    else:
        raise api_error(400, "bad_request", f"Unknown decision {action!r}.")

    if state == target:
        raise api_error(409, "already", f"The lead is already {target.lower()}.")
    if not _whitelisted(conn, state, target):
        raise api_error(
            409, "not_allowed",
            f"A lead that is '{state}' cannot be moved to '{target}' from the screen.",
            "Let the engine finish its step, or disqualify and reopen.",
        )
    with lge_db.lifecycle(conn, "ui_decision", actor="ui"), conn.cursor() as cur:
        cur.execute("UPDATE lead SET state = %s WHERE id = %s", (target, lead_id))
        if action == "disqualify":
            cur.execute(
                "UPDATE lead SET close_reason = %s WHERE id = %s",
                (f"user{why}" if why else "user", lead_id),
            )
        if action == "reopen":
            cur.execute(
                "UPDATE lead SET close_reason = NULL, cooldown_until = NULL WHERE id = %s",
                (lead_id,),
            )
        if action == "qualify" and target == "QUALIFIED_B":
            cur.execute("UPDATE lead SET grade = 'B' WHERE id = %s", (lead_id,))
        if action == "qualify" and target == "QUALIFIED_A":
            cur.execute("UPDATE lead SET grade = 'A' WHERE id = %s", (lead_id,))
    _note(conn, lead_id, f"{message.rstrip('.')}{why}")
    return message


@router.post("/leads/{lead_id}/decision", response_model=DecisionResponse)
def post_decision(lead_id: str, body: DecisionRequest, conn: ConnDep) -> DecisionResponse:
    from lge.api.routes.leads import _build_lead_detail, _fetch_lead_row

    lead = _fetch_lead_row(conn, lead_id)
    if lead is None:
        raise not_found("Lead not found.", "Check the id.")
    message = apply_decision(conn, lead, body.action, body.reason, body.until)
    return DecisionResponse(lead=_build_lead_detail(conn, lead_id), message=message)


@router.post("/leads/{lead_id}/notes", response_model=LeadDetail, status_code=201)
def post_note(lead_id: str, body: NoteRequest, conn: ConnDep) -> LeadDetail:
    from lge.api.routes.leads import _build_lead_detail, _fetch_lead_row

    if _fetch_lead_row(conn, lead_id) is None:
        raise not_found("Lead not found.", "Check the id.")
    if not body.text.strip():
        raise api_error(400, "bad_request", "A note needs some text.")
    _note(conn, lead_id, body.text.strip())
    return _build_lead_detail(conn, lead_id)


@router.put("/leads/{lead_id}/owner", response_model=LeadDetail)
def put_owner(lead_id: str, body: OwnerRequest, conn: ConnDep) -> LeadDetail:
    from lge.api.routes.leads import _build_lead_detail, _fetch_lead_row

    if _fetch_lead_row(conn, lead_id) is None:
        raise not_found("Lead not found.", "Check the id.")
    owner = (body.owner or "").strip() or None
    with conn.cursor() as cur:
        cur.execute("UPDATE lead SET owner = %s WHERE id = %s", (owner, lead_id))
    _note(conn, lead_id, f"Assigned to {owner}" if owner else "Unassigned")
    return _build_lead_detail(conn, lead_id)


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


@router.post("/leads/batch", response_model=BatchResponse)
def post_batch(body: BatchRequest, conn: ConnDep, background: BackgroundTasks) -> BatchResponse:
    from lge.api.routes.leads import _fetch_lead_row

    if not body.lead_ids:
        raise api_error(400, "bad_request", "No leads selected.")
    if len(body.lead_ids) > _MAX_BATCH:
        raise api_error(400, "bad_request", f"At most {_MAX_BATCH} leads at a time.")
    results: list[BatchResult] = []
    for lead_id in body.lead_ids:
        lead = _fetch_lead_row(conn, lead_id)
        if lead is None:
            results.append(BatchResult(lead_id=lead_id, ok=False, message="Lead not found."))
            continue
        try:
            if body.action in ("research", "find_contacts"):
                scope = "full" if body.action == "research" else "contacts"
                job = _start_research(conn, background, str(lead["firm_id"]), scope)
                results.append(BatchResult(
                    lead_id=lead_id, ok=True, message=f"Job {job.status}.", job_id=job.id,
                ))
            elif body.action == "assign":
                owner = (body.owner or "").strip() or None
                with conn.cursor() as cur:
                    cur.execute("UPDATE lead SET owner = %s WHERE id = %s", (owner, lead_id))
                _note(conn, lead_id, f"Assigned to {owner}" if owner else "Unassigned")
                results.append(BatchResult(lead_id=lead_id, ok=True, message="Assigned."))
            else:
                message = apply_decision(conn, lead, body.action, body.reason, body.until)
                results.append(BatchResult(lead_id=lead_id, ok=True, message=message))
        except Exception as exc:  # noqa: BLE001 -- one lead's refusal must not stop the rest
            detail = getattr(exc, "detail", None)
            text = (
                detail.get("error", {}).get("message") if isinstance(detail, dict) else str(exc)
            )
            results.append(BatchResult(lead_id=lead_id, ok=False, message=text or str(exc)))
    return BatchResponse(results=results)
