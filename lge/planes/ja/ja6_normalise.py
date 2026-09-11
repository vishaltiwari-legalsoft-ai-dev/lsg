"""JA6 -- the normaliser. `raw_posting -> signal` (live sources) or
`raw_posting -> firm_attribute` (internal_jobs). Order fixed: agency filter ->
support-role filter -> resolve -> write. See context/20-signals/
03-agency-filter-and-resolution.md and context/40-pipeline/02-component-register.md
("Why JA6 is separate").

A PURE FUNCTION over whatever is currently in `raw_posting`: every run reprocesses
every row from scratch (no "only new rows" shortcut) and upserts/deletes
job_posting_rejected, posting_resolution and discovery_lead to match this run's
verdict -- so tuning the blocklist, the synonym map or a resolution threshold and
re-running is the entire remediation, never a re-crawl. `signal` and
`signal_sighting` writes go through lge.planes.ja.ja6_signals, which respects the
I6 immutability trigger by construction (computes whether a write is even needed
before issuing one) rather than by catching its exception.
"""

from __future__ import annotations

from lge.planes.ja.ja6_agency import classify as agency_classify
from lge.planes.ja.ja6_resolve import resolve as resolve_posting
from lge.planes.ja.ja6_signals import (
    write_internal_jobs_fit_claims,
    write_job_posting_open_signals,
    write_multi_opening_signals,
)
from lge.planes.ja.ja6_types import Posting, posting_from_row
from lge.registry import RunContext, RunResult, component

_SELECT_POSTINGS = """
    SELECT id, source, source_key, source_url, firm_id, company_name, title,
           location_raw, city, state, metro_code, body, apply_email,
           outbound_links, phone_raw, ats_slug, board_posted_date, first_published,
           updated_at_src, fetch_ok, fetched_at
    FROM raw_posting
    ORDER BY id
"""


def _fetch_postings(conn, limit: int | None) -> list[Posting]:
    sql = _SELECT_POSTINGS
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [posting_from_row(row) for row in cur.fetchall()]


def _upsert_reject(conn, raw_posting_id: int, rule: str, detail: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO job_posting_rejected (raw_posting_id, rule, detail) "
            "VALUES (%s, %s, %s) ON CONFLICT (raw_posting_id) "
            "DO UPDATE SET rule = EXCLUDED.rule, detail = EXCLUDED.detail",
            (raw_posting_id, rule, detail),
        )


def _clear_reject(conn, raw_posting_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM job_posting_rejected WHERE raw_posting_id = %s", (raw_posting_id,))


def _upsert_resolution(
    conn, raw_posting_id: int, firm_id: str | None, rung: int, confidence: float, detail: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posting_resolution (raw_posting_id, firm_id, rung, confidence, detail) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (raw_posting_id) DO UPDATE SET "
            "firm_id = EXCLUDED.firm_id, rung = EXCLUDED.rung, "
            "confidence = EXCLUDED.confidence, detail = EXCLUDED.detail",
            (raw_posting_id, firm_id, rung, confidence, detail),
        )


def _upsert_discovery_lead(conn, p: Posting) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO discovery_lead (company_name, city, state, source, raw_posting_id) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (raw_posting_id) DO UPDATE SET "
            "company_name = EXCLUDED.company_name, city = EXCLUDED.city, "
            "state = EXCLUDED.state, source = EXCLUDED.source",
            (p.company_name, p.city, p.state, p.source, p.id),
        )


def _clear_discovery_lead(conn, raw_posting_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM discovery_lead WHERE raw_posting_id = %s", (raw_posting_id,))


def _fetch_firm_row(conn, firm_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, city, state FROM firm WHERE id = %s", (firm_id,))
        return cur.fetchone()


@component(
    "ja6_normalise",
    "ja",
    "Agency filter -> support-role filter -> resolve -> signal/fit-claims. "
    "Pure function over raw_posting -- fully re-runnable without re-fetching.",
)
def ja6_normalise(ctx: RunContext, **opts: object) -> RunResult:
    limit_opt = opts.get("limit")
    limit = int(limit_opt) if limit_opt is not None else None

    result = RunResult()
    postings = _fetch_postings(ctx.conn, limit)
    if not postings:
        result.notes.append("no raw_posting rows on disk")
        return result

    rejects = agency_classify(postings)  # also annotates canonical_role/is_support in place

    firm_cache: dict[str, dict | None] = {}

    def firm_row(firm_id: str) -> dict | None:
        if firm_id not in firm_cache:
            firm_cache[firm_id] = _fetch_firm_row(ctx.conn, firm_id)
        return firm_cache[firm_id]

    resolved_live: list[tuple[Posting, dict]] = []
    resolved_internal: list[tuple[Posting, dict]] = []
    n_agency_rejected = n_resolved = n_unresolved = n_name_only = 0

    for p in postings:
        try:
            if p.id in rejects:
                rule, detail = rejects[p.id]
                _upsert_reject(ctx.conn, p.id, rule, detail)
                _clear_discovery_lead(ctx.conn, p.id)
                n_agency_rejected += 1
                result.processed += 1
                continue

            res = resolve_posting(ctx.conn, p)
            _upsert_resolution(ctx.conn, p.id, res.firm_id, res.rung, res.confidence, res.detail)
            p.resolution_rung = res.rung

            if res.firm_id is None:
                if res.rung == 7:
                    _upsert_reject(ctx.conn, p.id, "name_only", res.detail)
                    _clear_discovery_lead(ctx.conn, p.id)
                    n_name_only += 1
                else:
                    _upsert_reject(ctx.conn, p.id, "unresolved", res.detail)
                    _upsert_discovery_lead(ctx.conn, p)
                    n_unresolved += 1
                result.processed += 1
                continue

            _clear_reject(ctx.conn, p.id)
            _clear_discovery_lead(ctx.conn, p.id)
            n_resolved += 1
            p.firm_id = res.firm_id  # was NULL on the row for every rung but 0

            row = firm_row(res.firm_id) or {}
            if p.source == "internal_jobs":
                resolved_internal.append((p, row))
            else:
                resolved_live.append((p, row))
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- one bad row must not sink the run
            result.failed += 1
            ctx.log.warning("ja6_normalise: raw_posting %s failed: %s", p.id, exc)

    signals_created, signals_updated, sightings = write_job_posting_open_signals(
        ctx.conn, resolved_live
    )
    multi_created, multi_updated = write_multi_opening_signals(ctx.conn)
    claims_written = write_internal_jobs_fit_claims(ctx.conn, resolved_internal)

    result.notes.append(
        f"agency_rejected={n_agency_rejected} name_only={n_name_only} "
        f"unresolved={n_unresolved} resolved={n_resolved} "
        f"job_posting_open(created={signals_created} updated={signals_updated}) "
        f"multi_opening(created={multi_created} updated={multi_updated}) "
        f"sightings_appended={sightings} internal_jobs_claims_written={claims_written}"
    )
    return result
