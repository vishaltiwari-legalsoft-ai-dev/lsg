"""Shared execution engine for P8 (extractor) and P9 (escalator).

Both components share one schema, one prompt template, one grounding pass
and one call/retry/budget mechanism (context/40-pipeline/03-extraction-
contract.md) — only the model, prompt_rev and firm-selection query differ.
`lge/planes/p/p8_llm.py` and `p9_escalate.py` are thin: they each supply a
`select_firm_ids` function and a config section key, and call
`run_extraction` here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from lge.fetch.config import only_wanted
from lge.llm import grounding
from lge.llm.client import LLMCallError, call_openrouter
from lge.llm.prompt import PageDoc, build_system_prompt, build_user_message, select_and_trim
from lge.llm.schema import FirmExtraction, response_format_for
from lge.registry import RunContext, RunResult

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.yml"
_PAGE_KINDS = ("home", "about", "attorneys", "team", "practice", "fees", "contact")
_RESPONSE_FORMAT = response_format_for(FirmExtraction, "firm_extraction")

FirmSelector = Callable[["RunContext", dict[str, Any]], list[str]]


def load_config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_pages(ctx: RunContext, firm_id: str) -> list[PageDoc]:
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.page_kind, d.url, dt.main_text
            FROM document d
            JOIN document_text dt ON dt.document_id = d.id
            WHERE d.firm_id = %s AND d.page_kind = ANY(%s) AND dt.main_text IS NOT NULL
            """,
            (firm_id, list(only_wanted(_PAGE_KINDS))),
        )
        rows = cur.fetchall()
    return [
        PageDoc(page_kind=r["page_kind"], url=r["url"] or "", main_text=r["main_text"] or "")
        for r in rows
    ]


def input_hash(input_text: str, prompt_rev: str, model: str) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(input_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt_rev.encode("utf-8"))
    h.update(b"\x00")
    h.update(model.encode("utf-8"))
    return h.hexdigest()


def estimate_cost(
    char_count: int, price_in: float, price_out: float, max_output_tokens: int
) -> float:
    """~4 chars/token heuristic for input; output priced at the configured
    cap as a worst case. Used only for the --opt max_usd guard and the
    --opt dry_run=1 display -- real cost comes from response.usage."""
    input_tokens = char_count / 4
    return (input_tokens / 1_000_000) * price_in + (max_output_tokens / 1_000_000) * price_out


def _task_already_ok(ctx: RunContext, component: str, entity_id: str, ihash: str) -> bool:
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM task_run WHERE component = %s AND entity_id = %s "
            "AND input_hash = %s AND status = 'ok'",
            (component, entity_id, ihash),
        )
        return cur.fetchone() is not None


def _insert_llm_call(
    ctx: RunContext,
    *,
    firm_id: str,
    component: str,
    model: str,
    prompt_rev: str,
    input_chars: int,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
    status: str,
    ungrounded_fields: list[str] | None,
    response: dict[str, Any] | None,
) -> None:
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO llm_call (firm_id, component, model, prompt_rev, input_chars,
                                   input_tokens, output_tokens, cost_usd, status,
                                   ungrounded_fields, response)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                firm_id,
                component,
                model,
                prompt_rev,
                input_chars,
                input_tokens,
                output_tokens,
                cost_usd,
                status,
                ungrounded_fields or None,
                Jsonb(response) if response is not None else None,
            ),
        )


def write_claims(
    ctx: RunContext,
    firm_id: str,
    extraction: FirmExtraction,
    source: str,
    observed_at: datetime,
    *,
    default_field_confidence: float,
) -> None:
    """Write one firm_attribute row per field. Unknown values ARE written —
    'unknown'/null with confidence 0 is a legitimate claim, not a skip.

    Fields with no per-field confidence in the contract (practice_areas,
    languages, entity_kind) are written at `default_field_confidence`
    (config: request.default_field_confidence) rather than 1.0 -- the model
    asserted them outright, but "asserted" and "certain" are not the same
    thing, and 1.0 reads as certainty reconcile() would trust unconditionally.

    spanish_intake / has_inhouse_recruiter are asserted-presence flags with
    no confidence field either: after grounding, `value` is True only when
    the claim's evidence actually grounds (grounding.ground() forces False +
    no evidence otherwise) — so a claim is written for either ONLY when
    value is True; a False/ungrounded reading writes no claim at all rather
    than asserting an unconfident negative."""
    pp = extraction.primary_practice.model_dump(mode="json")
    fm = extraction.fee_model.model_dump(mode="json")
    ac = extraction.attorney_count.model_dump(mode="json")
    sr = extraction.staff_ratio.model_dump(mode="json")
    si = extraction.spanish_intake.model_dump(mode="json")
    ek = extraction.entity_kind.model_dump(mode="json")
    hr = extraction.has_inhouse_recruiter.model_dump(mode="json")
    practice_areas = [pa.model_dump(mode="json") for pa in extraction.practice_areas]
    decision_makers = [dm.model_dump(mode="json") for dm in extraction.decision_makers]

    rows: list[tuple[str, Any, float, str | None]] = [
        ("primary_practice", pp["value"], pp["confidence"], pp["evidence"]),
        ("practice_areas", practice_areas, default_field_confidence, None),
        ("fee_model", fm["value"], fm["confidence"], fm["evidence"]),
        ("attorney_count", ac["value"], ac["confidence"], ac["evidence"]),
        (
            "attorney_count_detail",
            {
                "method": ac["method"],
                "excluded": ac["excluded"],
                "attorney_names": ac["attorney_names"],
            },
            ac["confidence"],
            None,
        ),
        ("staff_ratio", sr["value"], sr["confidence"], None),
        ("languages", list(extraction.languages), default_field_confidence, None),
        ("entity_kind", ek["value"], default_field_confidence, None),
        # decision_makers is untouched by this follow-up -- not in the
        # coordinator's named list, kept at 1.0 as before.
        ("decision_makers", decision_makers, 1.0, None),
    ]
    if si["value"]:
        rows.append(("spanish_intake", True, default_field_confidence, si["evidence"]))
    if hr["value"]:
        rows.append(("has_inhouse_recruiter", True, default_field_confidence, hr["evidence"]))

    with ctx.conn.cursor() as cur:
        for attr, value, confidence, evidence in rows:
            cur.execute(
                """
                INSERT INTO firm_attribute
                    (firm_id, attr, value, source, confidence, evidence, observed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (firm_id, attr, Jsonb(value), source, confidence, evidence, observed_at),
            )


@dataclass(frozen=True, slots=True)
class _CallOutcome:
    firm_id: str
    kind: str  # "ok" | "invalid" | "failed"
    extraction: FirmExtraction | None
    usage: dict[str, Any] | None
    raw: dict[str, Any] | None
    error: str | None


async def _run_one(
    sem: asyncio.Semaphore,
    http_client: httpx.AsyncClient,
    job: dict[str, Any],
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    max_output_tokens: int,
    timeout_s: float,
    max_retries: int,
    backoff_base_s: float,
    backoff_max_s: float,
    referer: str,
    title: str,
) -> _CallOutcome:
    async with sem:
        last_usage: dict[str, Any] | None = None
        last_raw: dict[str, Any] | None = None
        # One initial attempt plus one retry on a pydantic validation
        # failure (the extraction contract's "retry ONCE" rule) -- distinct
        # from the transport-level retries inside call_openrouter itself.
        for parse_attempt in range(2):
            try:
                resp = await call_openrouter(
                    http_client,
                    api_key=api_key,
                    model=model,
                    system=system_prompt,
                    user=job["user_message"],
                    response_format=_RESPONSE_FORMAT,
                    max_tokens=max_output_tokens,
                    timeout_s=timeout_s,
                    max_retries=max_retries,
                    backoff_base_s=backoff_base_s,
                    backoff_max_s=backoff_max_s,
                    referer=referer,
                    title=title,
                )
            except LLMCallError as exc:
                return _CallOutcome(job["firm_id"], "failed", None, last_usage, last_raw, str(exc))

            last_usage = resp.usage
            last_raw = resp.raw
            try:
                extraction = FirmExtraction.model_validate_json(resp.content)
            except ValidationError as exc:
                if parse_attempt == 0:
                    continue
                return _CallOutcome(job["firm_id"], "invalid", None, last_usage, last_raw, str(exc))
            else:
                return _CallOutcome(job["firm_id"], "ok", extraction, last_usage, last_raw, None)
        raise AssertionError("unreachable")  # pragma: no cover


async def _gather(
    jobs: list[dict[str, Any]], concurrency: int, **worker_kwargs: Any
) -> list[_CallOutcome]:
    async with httpx.AsyncClient() as http_client:
        sem = asyncio.Semaphore(concurrency)
        tasks = [_run_one(sem, http_client, job, **worker_kwargs) for job in jobs]
        return await asyncio.gather(*tasks)


def run_extraction(
    ctx: RunContext,
    opts: dict[str, Any],
    *,
    component_name: str,
    cfg_key: str,
    select_firm_ids: FirmSelector,
) -> RunResult:
    api_key = ctx.settings.openrouter_api_key
    cfg = load_config()
    comp_cfg = cfg[cfg_key]
    req_cfg = cfg["request"]

    use_batch = str(opts.get("batch", comp_cfg.get("use_batch", False))).lower() in ("1", "true")
    model = comp_cfg["model_batch"] if use_batch else comp_cfg["model"]
    prompt_rev = comp_cfg["prompt_rev"]
    source = f"llm:{cfg_key}:{prompt_rev}"

    firm_ids = select_firm_ids(ctx, opts)

    if not api_key:
        return RunResult(skipped=len(firm_ids), notes=["inert: OPENROUTER_API_KEY not set"])

    dry_run = ctx.dry_run or str(opts.get("dry_run", "")).lower() in ("1", "true")

    char_budget = int(opts.get("char_budget", req_cfg["char_budget"]))
    max_output_tokens = int(req_cfg["max_output_tokens"])
    timeout_s = float(req_cfg["timeout_s"])
    concurrency = max(1, int(req_cfg["concurrency"]))
    max_retries = int(req_cfg["max_retries"])
    backoff_base_s = float(req_cfg["backoff_base_s"])
    backoff_max_s = float(req_cfg["backoff_max_s"])
    referer = cfg["referer"]
    title = cfg["title"]
    price_in = float(comp_cfg["price_per_mtok_input"])
    price_out = float(comp_cfg["price_per_mtok_output"])
    default_field_confidence = float(req_cfg.get("default_field_confidence", 0.7))

    raw_max_usd = opts.get("max_usd")
    max_usd = float(raw_max_usd) if raw_max_usd not in (None, "") else None

    system_prompt = build_system_prompt()

    result = RunResult()
    jobs: list[dict[str, Any]] = []
    spent_estimate = 0.0

    for firm_id in firm_ids:
        pages = load_pages(ctx, firm_id)
        if not pages:
            result.skipped += 1
            continue

        selected_pages = select_and_trim(pages, char_budget)
        user_message = build_user_message(selected_pages)
        ihash = input_hash(user_message, prompt_rev, model)

        if _task_already_ok(ctx, component_name, firm_id, ihash):
            result.skipped += 1
            continue

        est_cost = estimate_cost(len(user_message), price_in, price_out, max_output_tokens)

        if dry_run:
            result.notes.append(f"{firm_id}: {len(user_message)} chars, est ${est_cost:.4f}")
            result.skipped += 1
            spent_estimate += est_cost
            continue

        if max_usd is not None and spent_estimate + est_cost > max_usd:
            result.skipped += 1
            result.notes.append(f"budget stop: ${max_usd:.2f} cap reached before firm {firm_id}")
            continue

        jobs.append(
            {
                "firm_id": firm_id,
                "user_message": user_message,
                "input_hash": ihash,
                "est_cost": est_cost,
            }
        )
        spent_estimate += est_cost

    if dry_run:
        result.notes.insert(
            0,
            f"dry_run: {len(result.notes)} firm(s) sized, "
            f"estimated total cost ${spent_estimate:.4f}",
        )
        return result

    if not jobs:
        return result

    outcomes = asyncio.run(
        _gather(
            jobs,
            concurrency,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s,
            max_retries=max_retries,
            backoff_base_s=backoff_base_s,
            backoff_max_s=backoff_max_s,
            referer=referer,
            title=title,
        )
    )

    now = datetime.now(UTC)

    for job, outcome in zip(jobs, outcomes, strict=True):
        firm_id = job["firm_id"]
        # ctx.checkpoint() always runs AFTER the `with ctx.once(...)` block has
        # exited (normally or via the re-raise below), never inside it -- the
        # task_run 'ok'/'failed' marker is only written on __exit__, so
        # checkpointing mid-block would commit claims/llm_call rows with the
        # row still 'running' and re-run them on a crash. One checkpoint per
        # firm, at the per-firm boundary the coordinator asked for.
        try:
            with ctx.once(component_name, firm_id, job["input_hash"]) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                usage = outcome.usage or {}
                input_tokens = usage.get("prompt_tokens")
                output_tokens = usage.get("completion_tokens")
                if input_tokens is not None and output_tokens is not None:
                    cost_usd = (input_tokens / 1_000_000) * price_in + (
                        output_tokens / 1_000_000
                    ) * price_out
                else:
                    cost_usd = job["est_cost"]

                if outcome.kind == "failed":
                    _insert_llm_call(
                        ctx,
                        firm_id=firm_id,
                        component=component_name,
                        model=model,
                        prompt_rev=prompt_rev,
                        input_chars=len(job["user_message"]),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                        status="failed",
                        ungrounded_fields=None,
                        response=outcome.raw,
                    )
                    raise LLMCallError(outcome.error or "llm call failed")

                if outcome.kind == "invalid":
                    _insert_llm_call(
                        ctx,
                        firm_id=firm_id,
                        component=component_name,
                        model=model,
                        prompt_rev=prompt_rev,
                        input_chars=len(job["user_message"]),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                        status="invalid",
                        ungrounded_fields=None,
                        response=outcome.raw,
                    )
                    result.notes.append(
                        f"{firm_id}: invalid response after retry, no claims written"
                    )
                    result.failed += 1
                else:
                    assert outcome.extraction is not None
                    grounded, ungrounded_fields = grounding.ground(
                        outcome.extraction, job["user_message"]
                    )
                    status = grounding.call_status(ungrounded_fields)
                    _insert_llm_call(
                        ctx,
                        firm_id=firm_id,
                        component=component_name,
                        model=model,
                        prompt_rev=prompt_rev,
                        input_chars=len(job["user_message"]),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                        status=status,
                        ungrounded_fields=ungrounded_fields,
                        response=outcome.raw,
                    )
                    write_claims(
                        ctx,
                        firm_id,
                        grounded,
                        source,
                        now,
                        default_field_confidence=default_field_confidence,
                    )
                    result.processed += 1
        except LLMCallError as exc:
            result.failed += 1
            result.notes.append(f"{firm_id}: llm call failed after retries: {exc}")

        ctx.checkpoint()

    return result
