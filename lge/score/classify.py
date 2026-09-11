"""The `classify` component (plane "score") -- context/40-pipeline/
05-lead-lifecycle.md's PROFILING..QUALIFIED_* span, driven by `reconcile()`'s
output (tier, reconcile_conflict) rather than recomputing anything itself.

Every write goes through `with lifecycle(conn, 'classify')` so `lead_state_event`
(I5) and the whitelist trigger (`lead_transition`) do their job; this module
never guesses at a transition the DB doesn't already have listed.

One call per lead cascades it through as many consecutive eligible
transitions as the data supports (bounded by `_MAX_HOPS`) -- a PROFILED lead
with a resolved tier, an unsuppressed domain, and a named owner reaches
CONTACT_PENDING in one run rather than needing three. A lead whose guard does
not pass simply stops where it is; nothing here forces a transition.

Not handled (see the report this agent hands back): CLASSIFIED -> DISQUALIFIED
is "revisitable" per the source doc (an attribute change can un-disqualify a
firm), but `lead_transition` has no reverse edge and re-opening a closed lead
is identity resolution's job (a new DISCOVERED row), not classify's -- this
component only ever advances forward through `lead_transition`'s edges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lge.db import lifecycle
from lge.registry import RunContext, RunResult, component

_ADVANCEABLE_STATES: tuple[str, ...] = (
    "PROFILING", "PROFILED", "ESCALATED", "CLASSIFIED", "CONTACT_PENDING", "RESOLVED",
)

_MAX_HOPS = 8  # generous bound on one lead's cascade through one run; never expected to hit it
_CHUNK_SIZE = 500


# =============================================================================
# Guards -- one read each, named after the lifecycle table's guard column
# =============================================================================


def _has_profiled_evidence(conn, firm_id: Any) -> bool:
    """PROFILING -> PROFILED: >=1 document with document_text AND a regex:p6
    claim (the P6 fee-model detector having run is this component's proxy for
    "P4-P8 complete" -- the extraction contract's cheapest, always-run stage)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT "
            "EXISTS (SELECT 1 FROM document d JOIN document_text dt ON dt.document_id = d.id "
            "        WHERE d.firm_id = %s AND dt.main_text IS NOT NULL) AS has_text, "
            "EXISTS (SELECT 1 FROM firm_attribute "
            "        WHERE firm_id = %s AND source = 'regex:p6') AS has_regex",
            (firm_id, firm_id),
        )
        row = cur.fetchone()
        return bool(row["has_text"]) and bool(row["has_regex"])


def _tier_resolved(conn, firm_id: Any, tier: str | None) -> bool:
    """PROFILED/ESCALATED -> CLASSIFIED: tier set and not UNCLASSIFIED, and no
    OPEN reconcile_conflict for the firm (an unresolved tier-determining
    conflict keeps a lead at ESCALATED even if a tier value happens to be
    sitting on the row from before the conflict opened)."""
    if not tier or tier == "UNCLASSIFIED":
        return False
    with conn.cursor() as cur:
        cur.execute(
            "SELECT NOT EXISTS (SELECT 1 FROM reconcile_conflict "
            "WHERE firm_id = %s AND resolved_at IS NULL) AS ok",
            (firm_id,),
        )
        return bool(cur.fetchone()["ok"])


def _domain_not_suppressed(conn, firm_id: Any, domain: str | None) -> bool:
    """CLASSIFIED -> CONTACT_PENDING guard: domain scope AND firm_id scope --
    outreach's own I2 trigger checks the same two scopes at send time; this
    is the same rule checked early so a suppressed firm never even queues."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT NOT (EXISTS (SELECT 1 FROM suppression WHERE scope = 'domain' AND value = %s) "
            "OR EXISTS (SELECT 1 FROM suppression WHERE scope = 'firm_id' AND value = %s)) AS ok",
            (domain, str(firm_id)),
        )
        return bool(cur.fetchone()["ok"])


def _find_decision_maker(conn, firm_id: Any) -> dict | None:
    """CONTACT_PENDING -> RESOLVED: a named owner or admin. Owner preferred
    over admin when both exist (context/10-icp/07 -- capturing the owner AND
    the admin matters, but only one contact_id fits on the lead row), then
    most recently enriched, then id for a fully deterministic pick."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, role FROM contact WHERE firm_id = %s AND role IN ('owner', 'admin') "
            "ORDER BY (role = 'owner') DESC, enriched_at DESC NULLS LAST, id "
            "LIMIT 1",
            (firm_id,),
        )
        return cur.fetchone()


def _has_valid_email(conn, contact_id: Any) -> bool:
    """RESOLVED -> QUALIFIED_A: status = 'valid' -- OUR verification, never
    vendor_status. A purchased-dataset contact carries status='unverified'
    with vendor_status='verified' and must NOT pass this guard (R4, a later
    milestone, is what can ever flip status to 'valid')."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM contact_email WHERE contact_id = %s "
            "AND status = 'valid') AS ok",
            (contact_id,),
        )
        return bool(cur.fetchone()["ok"])


def _has_gradeb_email_and_phone(conn, contact_id: Any, firm_phone: str | None) -> bool:
    """RESOLVED -> QUALIFIED_B: status IN (catch_all, risky) AND a phone
    (contact.phone_direct, else firm.phone_e164)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM contact_email WHERE contact_id = %s "
            "AND status IN ('catch_all', 'risky')) AS has_email, "
            "(SELECT phone_direct FROM contact WHERE id = %s) AS contact_phone",
            (contact_id, contact_id),
        )
        row = cur.fetchone()
        phone = row["contact_phone"] or firm_phone
        return bool(row["has_email"]) and bool(phone)


# =============================================================================
# One lead's next transition
# =============================================================================


def _fetch_lead(conn, lead_id: Any) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT l.id, l.firm_id, l.state, l.contact_id, l.closed_at, "
            "f.domain, f.tier, f.phone_e164 "
            "FROM lead l JOIN firm f ON f.id = l.firm_id WHERE l.id = %s",
            (lead_id,),
        )
        return cur.fetchone()


def _next_transition(conn, lead: dict) -> tuple[str, dict] | None:
    """(new_state, extra_columns_to_write) for the one transition `lead`'s
    current state is eligible for right now, or None if no guard passes."""
    state = lead["state"]
    firm_id = lead["firm_id"]

    if state == "PROFILING":
        if _has_profiled_evidence(conn, firm_id):
            return "PROFILED", {}
        return None

    if state == "PROFILED":
        if _tier_resolved(conn, firm_id, lead["tier"]):
            return "CLASSIFIED", {}
        return "ESCALATED", {}

    if state == "ESCALATED":
        if _tier_resolved(conn, firm_id, lead["tier"]):
            return "CLASSIFIED", {}
        return None

    if state == "CLASSIFIED":
        tier = lead["tier"] or ""
        if tier.startswith("DQ_"):
            return "DISQUALIFIED", {"close_reason": tier}
        if _domain_not_suppressed(conn, firm_id, lead["domain"]):
            return "CONTACT_PENDING", {}
        return None

    if state == "CONTACT_PENDING":
        contact = _find_decision_maker(conn, firm_id)
        if contact:
            return "RESOLVED", {"contact_id": contact["id"]}
        return None

    if state == "RESOLVED":
        contact_id = lead["contact_id"]
        if contact_id is None:
            return None
        if _has_valid_email(conn, contact_id):
            return "QUALIFIED_A", {"grade": "A"}
        if _has_gradeb_email_and_phone(conn, contact_id, lead["phone_e164"]):
            return "QUALIFIED_B", {"grade": "B"}
        return None

    return None


def _apply_transition(conn, lead_id: Any, new_state: str, extra: dict) -> None:
    sets = ["state = %s"]
    params: list[Any] = [new_state]
    if "contact_id" in extra:
        sets.append("contact_id = %s")
        params.append(extra["contact_id"])
    if "grade" in extra:
        sets.append("grade = %s")
        params.append(extra["grade"])
    if "close_reason" in extra:
        sets.append("close_reason = %s")
        params.append(extra["close_reason"])
        sets.append("closed_at = now()")
    params.append(lead_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE lead SET {', '.join(sets)} WHERE id = %s", params)  # noqa: S608


def advance_lead(conn, lead_id: Any) -> int:
    """Cascade one lead through every consecutive eligible transition.
    Returns the number of transitions applied (0 if the lead's current state's
    guard did not pass)."""
    hops = 0
    for _ in range(_MAX_HOPS):
        lead = _fetch_lead(conn, lead_id)
        if lead is None or lead["closed_at"] is not None:
            break
        step = _next_transition(conn, lead)
        if step is None:
            break
        new_state, extra = step
        _apply_transition(conn, lead_id, new_state, extra)
        hops += 1
        if new_state == "DISQUALIFIED":
            break  # lead is now closed; nothing further to evaluate this run
    return hops


# =============================================================================
# Component
# =============================================================================


def _select_lead_ids(conn, opts: dict[str, Any]) -> list[Any]:
    clauses = ["l.closed_at IS NULL", "l.state = ANY(%(states)s)"]
    params: dict[str, Any] = {"states": list(_ADVANCEABLE_STATES)}

    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        path = Path(str(firm_ids_file))
        ids = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        clauses.append("l.firm_id = ANY(%(firm_ids)s)")
        params["firm_ids"] = ids

    query = f"SELECT l.id FROM lead l WHERE {' AND '.join(clauses)} ORDER BY l.id"  # noqa: S608
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %(limit)s"
        params["limit"] = int(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["id"] for r in cur.fetchall()]


@component(
    "classify", "score",
    "Advance open leads through the classification lifecycle "
    "(PROFILING..QUALIFIED_*), guarded by reconcile()'s tier/conflict output.",
)
def classify(ctx: RunContext, **opts: Any) -> RunResult:
    lead_ids = _select_lead_ids(ctx.conn, opts)
    result = RunResult()

    for i in range(0, len(lead_ids), _CHUNK_SIZE):
        chunk = lead_ids[i : i + _CHUNK_SIZE]
        with lifecycle(ctx.conn, "classify"):
            for lead_id in chunk:
                try:
                    hops = advance_lead(ctx.conn, lead_id)
                except Exception as exc:  # noqa: BLE001 -- one bad lead must not sink the run
                    result.failed += 1
                    ctx.log.warning("classify: lead %s failed: %s", lead_id, exc)
                    continue
                if hops:
                    result.processed += 1
                else:
                    result.skipped += 1
        ctx.checkpoint()

    result.notes.append(
        f"leads advanced: {result.processed}, unchanged: {result.skipped}, failed: {result.failed}"
    )
    return result
