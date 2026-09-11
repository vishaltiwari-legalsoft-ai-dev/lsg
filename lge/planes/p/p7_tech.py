"""P7 -- tech fingerprinter (context/40-pipeline/02-component-register.md P7).

`lge.classify.tech.detect_tech` does the actual host-pattern matching; this module
scans every fetched page's raw HTML, picks the CMS that wins `primary_cms` on the
page it was first found on, and unions every distinct intake-category tool name
seen across the firm's pages.

No vendor API needed -- script/link/iframe/form hosts only, exactly like P7's own
docstring says. Confidence 0.9: a deterministic hostname-anchored pattern match,
same tier as a single-family P6 match, one notch below P5's schema.org claim.
"""

from __future__ import annotations

from pathlib import Path

from lge.classify.tech import detect_tech, primary_cms
from lge.planes.p._claims import (
    compute_input_hash,
    config_fingerprint,
    fetch_documents,
    read_html,
    select_firm_ids,
    write_claim,
)
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

_VERSION = "p7:v1"
_SOURCE = "rules:p7"
_CONFIDENCE = 0.9
# Mirrors lge/classify/tech.py's own _CONFIG_PATH -- see p6_fee.py for why this is
# computed independently rather than importing that module's private constant.
_TECH_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "tech_fingerprints.yml"


@component(
    "p7_tech", "P", "Tech fingerprinter: CMS + intake tooling from script/link/iframe/form hosts"
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    store = store or get_store()
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),  # type: ignore[arg-type]
        limit=opts.get("limit"),  # type: ignore[arg-type]
    )
    version = f"{_VERSION}:{config_fingerprint(_TECH_CONFIG_PATH)}"

    for firm_id in firm_ids:
        try:
            docs = fetch_documents(ctx.conn, firm_id)
            if not docs:
                result.skipped += 1
                continue

            input_hash = compute_input_hash((d["content_hash"] for d in docs), version)
            with ctx.once("p7_tech", str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                cms_hit = None
                cms_fetched_at = None
                # name -> (evidence, fetched_at of the first page it showed up on)
                intake_seen: dict[str, tuple[str, object]] = {}

                for doc in docs:
                    html = read_html(store, doc["object_key"])
                    if not html:
                        continue
                    hits = detect_tech(html)

                    if cms_hit is None:
                        cms_name = primary_cms(hits)
                        if cms_name:
                            cms_hit = next(h for h in hits if h.name == cms_name)
                            cms_fetched_at = doc["fetched_at"]

                    for hit in hits:
                        if hit.category == "intake" and hit.name not in intake_seen:
                            intake_seen[hit.name] = (hit.evidence, doc["fetched_at"])

                if cms_hit is not None:
                    write_claim(
                        ctx.conn,
                        firm_id,
                        "cms_detected",
                        cms_hit.name,
                        _SOURCE,
                        _CONFIDENCE,
                        cms_hit.evidence,
                        cms_fetched_at,
                    )
                if intake_seen:
                    newest = max(fetched_at for _evidence, fetched_at in intake_seen.values())
                    write_claim(
                        ctx.conn,
                        firm_id,
                        "intake_tools",
                        sorted(intake_seen),
                        _SOURCE,
                        _CONFIDENCE,
                        None,
                        newest,
                    )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"p7_tech firm={firm_id}: {exc}")

    return result
