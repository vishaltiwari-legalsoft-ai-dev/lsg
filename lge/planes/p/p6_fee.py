"""P6 -- fee-model detector (context/10-icp/03-fee-model.md, component-register P6).

Pure regex over stored page text (`lge.classify.fee.detect_fee_model` does the actual
precedence/real-estate resolution -- this module's only job is picking the sections,
weighting them by word count, and writing exactly one `fee_model` claim per firm.

`unknown` is written like any other value (0.0 confidence, no evidence) -- per
context/40-pipeline/03-extraction-contract.md, a silent non-write here would be
indistinguishable from "P6 hasn't run yet" at reconciliation time. It must be
reachable, not absent.
"""

from __future__ import annotations

from pathlib import Path

from lge.classify.fee import detect_fee_model
from lge.planes.p._claims import (
    compute_input_hash,
    config_fingerprint,
    fetch_documents_with_text,
    select_firm_ids,
    write_claim,
)
from lge.registry import RunContext, RunResult, component

_VERSION = "p6:v1"
_PAGE_KINDS = ("practice", "fees", "home", "about", "other")
_SOURCE = "regex:p6"
# Mirrors lge/classify/fee.py's own _CONFIG_PATH -- computed independently rather
# than importing that module's private constant, so an edit to fee_patterns.yml
# (owned by lge.classify.fee, not this module) still busts our idempotency key.
_FEE_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "fee_patterns.yml"


@component("p6_fee", "P", "Fee-model detector: regex over page text, precedence-ordered")
def run(ctx: RunContext, **opts: object) -> RunResult:
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),  # type: ignore[arg-type]
        limit=opts.get("limit"),  # type: ignore[arg-type]
    )
    version = f"{_VERSION}:{config_fingerprint(_FEE_CONFIG_PATH)}"

    for firm_id in firm_ids:
        try:
            rows = fetch_documents_with_text(ctx.conn, firm_id, page_kinds=_PAGE_KINDS)
            if not rows:
                result.skipped += 1
                continue

            input_hash = compute_input_hash((r["content_hash"] for r in rows), version)
            with ctx.once("p6_fee", str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                sections = [(r["main_text"] or "", float(r["word_count"] or 0)) for r in rows]
                fee = detect_fee_model(sections)
                observed_at = max(r["fetched_at"] for r in rows)

                write_claim(
                    ctx.conn,
                    firm_id,
                    "fee_model",
                    fee.value,
                    _SOURCE,
                    fee.confidence,
                    fee.evidence,
                    observed_at,
                )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"p6_fee firm={firm_id}: {exc}")

    return result
