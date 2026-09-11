"""r2_bar_join -- joins bar-directory attorney observations to resolved
firms on name + address (Plane R, context/40-pipeline/02-component-
register.md; context/10-icp/07-decision-makers-and-lead-record.md "the bar
directory is the differentiated move ... R2 runs before R1: free,
authoritative names first, paid enrichment for the remainder").

No bar harvester exists yet (a later milestone, D2 in Plane D) -- this is
the join FRAMEWORK, built and tested against fixture `observation` rows
with source `bar:<state>` and payload
`{name, bar_number, status, admission_date, firm_name, address}`. Matching
reads the observation's already-normalized columns (name_stem, addr_hash,
city -- computed at WRITE time by whichever loader eventually populates
them; "normalize at write time, never at query time",
context/30-data-model/02-normalization-contracts.md), never the raw payload
text -- the same convention `lge.resolve.identity` follows for its own
R3/R4 rules, which this mirrors deliberately rather than re-deriving
normalization logic a second time.

Match rule (config/resolvers.yml, r2_bar_join):
  * addr_hash equal AND similarity(name_stem) > addr_name_similarity, OR
  * same city AND similarity(name_stem) > city_name_similarity (the higher
    bar -- city alone is much weaker evidence than a matching address).
No match -> no contact. The observation is left for a later run (the firm
may not be resolved yet, or its address not yet captured) rather than
forced onto the nearest firm.

A matched observation becomes a `contact`: bar_number, role 'attorney'
unless the bar record's own status marks the attorney managing/principal
(role 'owner' then). Bar records carry no job title, so `title` stays NULL
rather than inventing one from a license-status field that isn't a title.

`first_seen_bar_admission` claims (source `bar:<state>`) are written for
SOLO firms -- a firm this run leaves with exactly one bar-sourced contact
on file -- since icp_tier()'s DQ_NOBUDGET rule ("brand-new solo ... bar
admission date, zero reviews, no ads") reads that column.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from psycopg.types.json import Jsonb

from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "r2_bar_join"
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "resolvers.yml"

# A bar record's own "status" field is a licensing/role signal here, not the
# usual active/inactive reading -- per the task contract, a status naming the
# attorney as managing or principal is the ownership signal a bar record can
# carry (bar directories have no job-title field to read instead).
_OWNER_STATUS_KEYWORDS = ("managing", "principal")


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["r2_bar_join"]


def _bar_role(status: str | None) -> str:
    low = (status or "").lower()
    return "owner" if any(kw in low for kw in _OWNER_STATUS_KEYWORDS) else "attorney"


def _select_observations(conn, opts: dict[str, Any]) -> list[dict]:
    clauses = ["o.source LIKE 'bar:%%'"]
    params: list[Any] = []

    state = opts.get("state")
    if state:
        clauses.append("o.source = %s")
        params.append(f"bar:{state}")

    query = (
        "SELECT o.id, o.source, o.payload, o.name_stem, o.addr_hash, o.city "
        "FROM observation o WHERE " + " AND ".join(clauses) + " ORDER BY o.id"
    )
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 -- clauses are fixed strings, not user input
        return cur.fetchall()


def _match_firm(conn, obs: dict, cfg: dict[str, Any]) -> Any | None:
    """addr_hash-equal branch first (stronger evidence, lower similarity
    bar), then same-city (weaker evidence, higher bar). Returns the best
    single match, or None."""
    if not obs["name_stem"]:
        return None

    if obs["addr_hash"]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM firm WHERE addr_hash = %s AND name_stem IS NOT NULL "
                "AND name_stem <> '' AND similarity(name_stem, %s) > %s "
                "ORDER BY similarity(name_stem, %s) DESC LIMIT 1",
                (
                    obs["addr_hash"], obs["name_stem"], cfg["addr_name_similarity"],
                    obs["name_stem"],
                ),
            )
            row = cur.fetchone()
            if row:
                return row["id"]

    if obs["city"]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM firm WHERE city = %s AND name_stem IS NOT NULL "
                "AND name_stem <> '' AND similarity(name_stem, %s) > %s "
                "ORDER BY similarity(name_stem, %s) DESC LIMIT 1",
                (obs["city"], obs["name_stem"], cfg["city_name_similarity"], obs["name_stem"]),
            )
            row = cur.fetchone()
            if row:
                return row["id"]

    return None


def _existing_contact(conn, firm_id: Any, bar_number: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, role FROM contact WHERE firm_id = %s AND bar_number = %s",
            (firm_id, bar_number),
        )
        return cur.fetchone()


def _bar_contact_count(conn, firm_id: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM contact WHERE firm_id = %s AND source LIKE 'bar:%%'",
            (firm_id,),
        )
        return cur.fetchone()["n"]


@component(
    "r2_bar_join", "R",
    "Joins bar-directory attorney observations to resolved firms on name+address; "
    "framework only -- no bar harvester exists yet, tested against fixtures.",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    cfg = _config()
    result = RunResult()
    now = datetime.now(UTC)
    matched_firms: dict[Any, tuple[dict, str]] = {}  # firm_id -> (payload, obs.source)

    for obs in _select_observations(conn, opts):
        try:
            payload = obs["payload"] or {}
            input_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

            with ctx.once(_COMPONENT_NAME, str(obs["id"]), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                firm_id = _match_firm(conn, obs, cfg)
                if firm_id is None:
                    result.skipped += 1
                    continue

                name = payload.get("name")
                bar_number = payload.get("bar_number")
                if not name or not bar_number:
                    result.skipped += 1
                    continue

                role = _bar_role(payload.get("status"))
                existing = _existing_contact(conn, firm_id, bar_number)

                if existing is None:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO contact
                                (id, firm_id, full_name, role, bar_number, source,
                                 confidence, enriched_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                str(uuid.uuid4()), firm_id, name, role, bar_number,
                                obs["source"], 1.0, now,
                            ),
                        )
                elif existing["role"] != role:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE contact SET role = %s, enriched_at = %s WHERE id = %s",
                            (role, now, existing["id"]),
                        )

                matched_firms[firm_id] = (payload, obs["source"])
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-observation isolation, never global
            result.failed += 1
            result.notes.append(f"r2_bar_join observation={obs['id']}: {exc}")
        ctx.checkpoint()

    for firm_id, (payload, source) in matched_firms.items():
        admission_date = payload.get("admission_date")
        if not admission_date:
            continue
        if _bar_contact_count(conn, firm_id) != 1:
            continue  # not left as a solo firm by this run's own count
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO firm_attribute
                    (firm_id, attr, value, source, confidence, evidence, observed_at)
                VALUES (%s, 'first_seen_bar_admission', %s, %s, 1.0, NULL, %s)
                ON CONFLICT (firm_id, attr, source, observed_at) DO NOTHING
                """,
                (firm_id, Jsonb(admission_date), source, now),
            )

    return result
