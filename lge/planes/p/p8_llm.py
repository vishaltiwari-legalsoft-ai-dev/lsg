"""P8 — the cheap-tier LLM extractor (context/40-pipeline/03-extraction-
contract.md, context/40-pipeline/02-component-register.md).

`claude-haiku-4.5` via OpenRouter, one call per firm, structured outputs
enforced by JSON schema. Writes firm_attribute claims under source
`llm:p8:<prompt_rev>` — unknown values are written as first-class claims,
never silently dropped. See `lge/llm/run.py` for the shared engine (schema,
prompt, grounding, retries, budget, idempotency) this component drives.

Selection: `--opt firm_ids_file=<path>` (one firm id per line) or
`--opt limit=N` over firms that have at least one `document_text` row,
oldest-id first. `--opt max_usd=<n>` is a hard cost cap; `--opt dry_run=1`
prints prompt sizes and estimated cost without calling anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lge.llm.run import run_extraction
from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "p8_llm"
_CFG_KEY = "p8"

_DEFAULT_LIMIT = 100


def _select_firm_ids(ctx: RunContext, opts: dict[str, Any]) -> list[str]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        text = Path(firm_ids_file).read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]

    limit = int(opts.get("limit", _DEFAULT_LIMIT))
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT f.id
            FROM firm f
            JOIN document d ON d.firm_id = f.id
            JOIN document_text dt ON dt.document_id = d.id
            WHERE dt.main_text IS NOT NULL
            ORDER BY f.id
            LIMIT %s
            """,
            (limit,),
        )
        # str(...): firm.id is uuid; task_run.entity_id is text. Binding the
        # raw UUID object downstream sends an explicit uuid-typed parameter
        # that Postgres refuses to compare against a text column.
        return [str(row["id"]) for row in cur.fetchall()]


@component("p8_llm", "P", "LLM extractor -- claude-haiku-4.5, structured outputs")
def p8_llm(ctx: RunContext, **opts: Any) -> RunResult:
    return run_extraction(
        ctx,
        opts,
        component_name=_COMPONENT_NAME,
        cfg_key=_CFG_KEY,
        select_firm_ids=_select_firm_ids,
    )
