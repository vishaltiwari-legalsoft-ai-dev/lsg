"""GET /api/overview -- the landing page: what the engine does, as five steps
with live numbers, what is running now, what needs a person (D-037).

The five steps are the ones the team thinks in:

  1 Lists     -- a sheet comes in, every website is verified
  2 Research  -- each site is read: people, offices, fee model, gaps
  3 Qualify   -- tier by fit, intent from pain
  4 People    -- the decision-maker, with an address and a profile
  5 Outreach  -- the sequence, the replies, back to the pool

Every count comes from one SQL statement each; the attention block is the
same one Today shows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from lge.api.deps import ConnDep
from lge.api.models import (
    LastRun,
    ListsSummary,
    OverviewResponse,
    PipelineStep,
    RunningJob,
    StageCount,
)
from lge.api.routes.leads import stage_counts
from lge.api.routes.today import build_attention
from lge.api.stage import STAGE_DISPLAY, STAGE_HELP, STAGE_ORDER

router = APIRouter(prefix="/api", tags=["overview"])

_RUN_LABELS: dict[str, str] = {
    "website_check": "Website check",
    "p1_site_map": "Site map",
    "p2_fetch": "Pages read",
    "p3_render": "Pages rendered",
    "p4_text": "Text extracted",
    "px_site_facts": "Site facts",
    "px_site_rules": "Practice and rules",
    "p6_fee": "Fee model",
    "r_site_contacts": "People into contacts",
    "r_site_emails": "Addresses on the site",
    "r_search_links": "LinkedIn and reviews search",
    "r_search_emails": "Address search",
    "r3_email_pattern": "Addresses minted",
    "ja1_careers": "Careers pages",
    "ja7_pain_signals": "Pain into intent",
    "reconcile": "Record reconciled",
    "score": "Scored",
    "build_list": "Lists built",
    "ingest_load": "Sheet loaded",
}


def _one(conn, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return int(row["n"] or 0) if row else 0


def _steps(conn, stages: dict[str, int]) -> list[PipelineStep]:
    firms = _one(conn, "SELECT count(*) AS n FROM firm")
    checked_ok = _one(
        conn,
        "SELECT count(DISTINCT firm_id) AS n FROM website_check "
        "WHERE outcome IN ('ok', 'corrected')",
    )
    checked_blocked = _one(
        conn, "SELECT count(DISTINCT firm_id) AS n FROM website_check WHERE outcome = 'blocked'"
    )
    researched = _one(
        conn,
        "SELECT count(DISTINCT firm_id) AS n FROM document WHERE fetch_ok AND status_code = 200",
    )
    pages = _one(conn, "SELECT count(*) AS n FROM document WHERE fetch_ok AND status_code = 200")
    people = _one(
        conn,
        "SELECT count(*) AS n FROM contact WHERE removed_at IS NULL AND source <> 'internal_firms'",
    )
    qualified = _one(
        conn,
        "SELECT count(*) AS n FROM firm WHERE tier IS NOT NULL AND tier <> 'UNCLASSIFIED' "
        "AND tier NOT LIKE 'DQ%%'",
    )
    tier_1a = _one(conn, "SELECT count(*) AS n FROM firm WHERE tier = '1A'")
    with_email = _one(
        conn,
        "SELECT count(DISTINCT c.firm_id) AS n FROM contact c JOIN contact_email e "
        "ON e.contact_id = c.id WHERE c.removed_at IS NULL AND c.role IN ('owner', 'admin')",
    )
    with_linkedin = _one(
        conn,
        "SELECT count(*) AS n FROM contact WHERE removed_at IS NULL AND linkedin_url IS NOT NULL "
        "AND source <> 'internal_firms'",
    )
    ready, outreach, replied = (
        stages.get("ready", 0), stages.get("in_outreach", 0), stages.get("replied", 0)
    )
    return [
        PipelineStep(
            key="lists", number=1, label="Lists", what=_WHAT["lists"],
            count=firms, count_label="firms on file",
            detail=f"{checked_ok:,} websites verified, {checked_blocked:,} behind a bot wall",
            href="/imports",
        ),
        PipelineStep(
            key="research", number=2, label="Research", what=_WHAT["research"],
            count=researched, count_label="firms researched",
            detail=f"{pages:,} pages read",
            href="/firms",
        ),
        PipelineStep(
            key="qualify", number=3, label="Qualify", what=_WHAT["qualify"],
            count=qualified, count_label="firms tiered",
            detail=(
                f"{tier_1a:,} tier 1A; {stages.get('needs_review', 0):,} waiting for a decision"
            ),
            href="/leads?stage=needs_review",
        ),
        PipelineStep(
            key="people", number=4, label="People", what=_WHAT["people"],
            count=people, count_label="people named",
            detail=(
                f"{with_email:,} firms with a decision-maker's address; "
                f"{with_linkedin:,} LinkedIn profiles"
            ),
            href="/leads?stage=needs_contact",
        ),
        PipelineStep(
            key="outreach", number=5, label="Outreach", what=_WHAT["outreach"],
            count=ready + outreach + replied, count_label="leads in play",
            detail=f"{ready:,} ready to reach, {outreach:,} in outreach, {replied:,} replied",
            href="/leads?stage=ready",
        ),
    ]


_WHAT: dict[str, str] = {
    "lists": (
        "A sheet in any layout comes in; every website on it is checked, and searched "
        "for when it is wrong."
    ),
    "research": (
        "Each site is read end to end: who works there, offices, fee model, practice, "
        "testimonials, news, and what the site lacks."
    ),
    "qualify": (
        "Fit from the record (fee model, practice, size); urgency from pain -- open roles, "
        "no support staff, no intake, reviews about unreturned calls."
    ),
    "people": (
        "The owner or office manager, with an address from the site, a search, or the "
        "firm's own pattern, and a LinkedIn profile."
    ),
    "outreach": (
        "Nine touches drafted from the proof; outcomes recorded; a lead that does not "
        "convert returns to the pool with its contact intact."
    ),
}


def _running(conn) -> list[RunningJob]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT j.id, j.kind, j.status, j.firm_id, f.canonical_name, j.steps, j.started_at "
            "FROM action_job j JOIN firm f ON f.id = j.firm_id "
            "WHERE j.status IN ('queued', 'running') ORDER BY j.created_at DESC LIMIT 10"
        )
        rows = cur.fetchall()
    return [
        RunningJob(
            id=str(r["id"]), kind=r["kind"], status=r["status"], firm_id=str(r["firm_id"]),
            firm_name=r["canonical_name"],
            done_steps=sum(1 for s in (r["steps"] or []) if s.get("status") == "done"),
            total_steps=len(r["steps"] or []), started_at=r["started_at"],
        )
        for r in rows
    ]


def _last_runs(conn) -> list[LastRun]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT component, max(finished_at) AS finished_at,
                   count(*) FILTER (WHERE status = 'ok') AS processed,
                   count(*) FILTER (WHERE status = 'failed') AS failed
            FROM task_run
            WHERE finished_at IS NOT NULL AND finished_at > now() - interval '7 days'
            GROUP BY component ORDER BY max(finished_at) DESC LIMIT 12
            """
        )
        rows = cur.fetchall()
    return [
        LastRun(
            component=r["component"],
            label=_RUN_LABELS.get(r["component"], r["component"].replace("_", " ")),
            finished_at=r["finished_at"], processed=r["processed"], failed=r["failed"],
        )
        for r in rows
    ]


def _lists(conn) -> ListsSummary:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n, coalesce(sum(row_count), 0) AS rows FROM import_file"
        )
        agg = cur.fetchone()
        cur.execute(
            "SELECT file_name, status, coalesce(loaded_at, created_at) AS at FROM import_file "
            "ORDER BY created_at DESC LIMIT 1"
        )
        latest = cur.fetchone()
    return ListsSummary(
        count=int(agg["n"]), rows=int(agg["rows"]),
        latest_file=latest["file_name"] if latest else None,
        latest_status=latest["status"] if latest else None,
        latest_at=latest["at"] if latest else None,
    )


@router.get("/overview", response_model=OverviewResponse)
def get_overview(conn: ConnDep) -> OverviewResponse:
    at = datetime.now(UTC)
    stages = stage_counts(conn)
    return OverviewResponse(
        steps=_steps(conn, stages),
        stages=[
            StageCount(stage=s, label=STAGE_DISPLAY[s], help=STAGE_HELP[s], count=stages[s])
            for s in STAGE_ORDER
        ],
        running=_running(conn),
        last_runs=_last_runs(conn),
        lists=_lists(conn),
        attention=build_attention(conn, at),
    )
