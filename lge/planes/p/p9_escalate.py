"""P9 — the escalation-tier LLM extractor (context/40-pipeline/03-
extraction-contract.md).

`claude-opus-5` via OpenRouter, same schema and grounding pass as P8, source
`llm:p9:<prompt_rev>`. Selects firms whose latest P8 result meets ANY of:

    fee_model.confidence        < 0.60
    attorney_count.confidence   < 0.60
    primary_practice.confidence < 0.70
    fee_model.value IN ('mixed', 'unknown')
    a row exists in reconcile_conflict for the firm (guarded: that table is
        migration 060, owned by another agent -- may not exist yet)
    firm.tier = '1A'                       -- ALWAYS, regardless of confidence

"Latest P8 result" reads the most recent `firm_attribute` row per
(firm_id, attr) with `source LIKE 'llm:p8:%'` — any prompt_rev counts, so a
prompt bump does not silently stop firms from being escalatable.

`--opt firm_ids_file=<path>` narrows the trigger query to the listed firms:
a listed firm is escalated only when a trigger above fires for it. That is
how a research job for one firm runs this step (D-054) -- the file used to
replace the trigger query, so every firm researched from the screen would
have gone to the expensive model. `--opt force=1` escalates every listed
firm regardless, for a deliberate re-run. `--opt limit=N` caps the trigger
query.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lge.llm.run import run_extraction
from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "p9_escalate"
_CFG_KEY = "p9"

_DEFAULT_LIMIT = 100


def _reconcile_conflict_exists(ctx: RunContext) -> bool:
    with ctx.conn.cursor() as cur:
        cur.execute("SELECT to_regclass('reconcile_conflict') IS NOT NULL AS present")
        row = cur.fetchone()
        return bool(row["present"])


def _select_firm_ids(ctx: RunContext, opts: dict[str, Any]) -> list[str]:
    listed: list[str] | None = None
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        text = Path(firm_ids_file).read_text(encoding="utf-8")
        listed = [line.strip() for line in text.splitlines() if line.strip()]
        if str(opts.get("force", "")).lower() in ("1", "true") or not listed:
            return listed

    limit = int(opts.get("limit", _DEFAULT_LIMIT)) if listed is None else len(listed)
    only_listed = "AND f.id::text = ANY(%s)" if listed is not None else ""

    # reconcile_conflict is created by another agent's migration (060). Guard
    # with to_regclass() rather than referencing the table unconditionally --
    # a query that names a table which does not yet exist fails to plan at
    # all, guard or no guard inside the WHERE clause, so the JOIN itself must
    # be left out of the SQL text when the table is absent.
    conflict_join = ""
    conflict_clause = ""
    if _reconcile_conflict_exists(ctx):
        conflict_join = "LEFT JOIN reconcile_conflict rc ON rc.firm_id = f.id"
        conflict_clause = "OR rc.firm_id IS NOT NULL"

    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (firm_id, attr) firm_id, attr, value, confidence
            FROM firm_attribute
            WHERE source LIKE 'llm:p8:%%'
              AND attr IN ('fee_model', 'attorney_count', 'primary_practice')
            ORDER BY firm_id, attr, observed_at DESC
        )
        SELECT DISTINCT f.id
        FROM firm f
        LEFT JOIN latest fm ON fm.firm_id = f.id AND fm.attr = 'fee_model'
        LEFT JOIN latest ac ON ac.firm_id = f.id AND ac.attr = 'attorney_count'
        LEFT JOIN latest pp ON pp.firm_id = f.id AND pp.attr = 'primary_practice'
        {conflict_join}
        WHERE ((fm.confidence IS NOT NULL AND fm.confidence < 0.60)
           OR (ac.confidence IS NOT NULL AND ac.confidence < 0.60)
           OR (pp.confidence IS NOT NULL AND pp.confidence < 0.70)
           OR (fm.value IS NOT NULL AND (fm.value #>> '{{}}') IN ('mixed', 'unknown'))
           OR f.tier = '1A'
           {conflict_clause})
          {only_listed}
        ORDER BY f.id
        LIMIT %s
    """  # noqa: S608 -- the interpolated fragments are fixed literals, never opts-derived

    params: list[Any] = [listed] if listed is not None else []
    with ctx.conn.cursor() as cur:
        cur.execute(query, [*params, limit])
        # str(...): see the matching note in p8_llm._select_firm_ids -- keeps
        # task_run.entity_id (text) comparisons well-typed downstream.
        return [str(row["id"]) for row in cur.fetchall()]


@component("p9_escalate", "P", "LLM escalator -- claude-opus-5, structured outputs")
def p9_escalate(ctx: RunContext, **opts: Any) -> RunResult:
    return run_extraction(
        ctx,
        opts,
        component_name=_COMPONENT_NAME,
        cfg_key=_CFG_KEY,
        select_firm_ids=_select_firm_ids,
    )
