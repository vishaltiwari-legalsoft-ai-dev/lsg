"""r1_enrich -- multi-vendor contact-enrichment adapter behind one interface
(Plane R, context/40-pipeline/02-component-register.md: "Runs only on firms
that passed the tier gate -- enriching the whole universe is the largest
avoidable cost in the system"; context/60-execution/04-risk-register.md,
same line, listed under High severity).

Selection is tier-gated AND gap-only: a firm qualifies only when its tier is
set and is not `DQ_*`, AND it currently has no owner/admin contact on file.
R2 (bar join) and r_site_contacts both run earlier in the intended pipeline
order ("R2 -> R1 -> R3 -> R4", component register) -- R1 exists to pay for
what the free/first-party sources did not already find, never to re-fetch
what they did.

No real vendor is contracted yet: `provider: none` (config/resolvers.yml,
r1_enrich) is the only implementation, so this component is inert today --
`RunResult(skipped=N)` plus a note -- but the adapter interface, tier-gated
selection, and per-firm budget/idempotency machinery are built and tested
now, so wiring a real vendor later is a new `_ADAPTERS` entry, not a
redesign. Idempotency is `ctx.once()` per firm (there is no per-firm input
to version yet -- no vendor, nothing that could change call to call); budget
is `--opt max_usd`, checked before every call, same shape as r4_verify.py's.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "r1_enrich"
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "resolvers.yml"


@dataclass(frozen=True, slots=True)
class EnrichResult:
    contacts: list[dict[str, Any]]
    cost_usd: float
    raw: dict[str, Any]


class EnrichError(Exception):
    """A vendor call did not complete."""


class EnrichAdapter(Protocol):
    def __call__(self, firm_id: Any, *, cfg: dict[str, Any]) -> EnrichResult: ...


def enrich_none(_firm_id: Any, *, cfg: dict[str, Any]) -> EnrichResult:
    raise EnrichError("the 'none' adapter never enriches -- it is only selected when inert")


_ADAPTERS: dict[str, EnrichAdapter] = {"none": enrich_none}


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["r1_enrich"]


def select_firm_ids(conn, opts: dict[str, Any]) -> list[Any]:
    """Firms past the tier gate (tier set, not DQ_*) with no owner/admin
    contact on file yet."""
    clauses = [
        "f.tier IS NOT NULL",
        "f.tier NOT LIKE 'DQ%%'",  # same convention as sql/001_schema.sql's firm index
        "NOT EXISTS (SELECT 1 FROM contact c "
        "WHERE c.firm_id = f.id AND c.role IN ('owner', 'admin'))",
    ]
    params: list[Any] = []

    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        ids = [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        clauses.append("f.id = ANY(%s)")
        params.append(ids)

    query = "SELECT f.id FROM firm f WHERE " + " AND ".join(clauses) + " ORDER BY f.id"
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 -- clauses are fixed strings, not user input
        return [r["id"] for r in cur.fetchall()]


@component(
    "r1_enrich", "R",
    "Multi-vendor contact enricher behind one adapter interface. Tier-gated, "
    "owner/admin-gap-only selection. Inert until a vendor is under contract.",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    cfg = _config()
    provider = str(opts.get("provider", cfg.get("provider", "none")))

    firm_ids = select_firm_ids(conn, opts)

    if provider == "none" or provider not in _ADAPTERS:
        return RunResult(
            skipped=len(firm_ids), notes=["inert: no enrichment provider configured"]
        )

    adapter = _ADAPTERS[provider]
    raw_max_usd = opts.get("max_usd")
    max_usd = float(raw_max_usd) if raw_max_usd not in (None, "") else None

    result = RunResult()
    spent = 0.0

    for firm_id in firm_ids:
        if max_usd is not None and spent >= max_usd:
            result.skipped += 1
            result.notes.append(f"budget stop: ${max_usd:.2f} cap reached before firm {firm_id}")
            ctx.checkpoint()
            continue
        try:
            with ctx.once(_COMPONENT_NAME, str(firm_id), "static") as should_run:
                if not should_run:
                    result.skipped += 1
                else:
                    outcome = adapter(firm_id, cfg=cfg)
                    spent += outcome.cost_usd
                    result.processed += 1
        except EnrichError as exc:
            result.failed += 1
            result.notes.append(f"{firm_id}: {exc}")
        ctx.checkpoint()

    return result
