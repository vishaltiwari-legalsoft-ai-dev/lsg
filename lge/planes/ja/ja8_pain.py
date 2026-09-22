"""ja8_pain -- the Pain Point Analyzer (plan-v3 phase 4).

The brief asks for an AI, not a scraper: one call per firm over everything
the store already holds on it, naming what hurts and proving each pain with
a sentence from the record. Nothing here crawls; every block it reads was
written by an earlier component, so a re-run re-derives and never re-fetches.

`lge/llm/pain.py` holds the schema, the prompt and the grounding; this
module assembles the record from the store, calls the model, throws away
what does not ground, and writes one `pain_analysis` claim under
`llm:ja8:<prompt_rev>`. Idempotent on what it read: `ctx.once()` keyed by
the input hash, so an unchanged record costs nothing.

Selection: `--opt firm_ids_file=<path>` or `--opt limit=N` over firms with
at least one page read. `--opt max_usd=<n>` caps spend; `--opt dry_run=1`
sizes the calls and names the cost without calling anything.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from lge.llm.client import LLMCallError, call_openrouter
from lge.llm.pain import (
    SYSTEM_PROMPT,
    Block,
    PainAnalysis,
    build_record,
    build_user_message,
    claim_value,
    ground,
    parse,
)
from lge.llm.run import estimate_cost, input_hash, insert_llm_call, load_config
from lge.llm.schema import response_format_for
from lge.planes.p._claims import write_claim
from lge.registry import RunContext, RunResult, component

_COMPONENT = "ja8_pain"
_CFG_KEY = "ja8"
_DEFAULT_LIMIT = 100

_CLAIM_ATTRS = (
    "site_gaps", "site_people", "staff_listed", "staff_ratio", "testimonials",
    "site_review_summary", "search_review_snippets", "review_count", "review_profiles",
    "growth_news", "recent_posts", "latest_post_date", "copyright_year", "online_intake_form",
    "live_chat_vendor", "spanish_intake", "languages", "office_count", "office_locations",
    "attorney_count", "attorney_count_detail", "vendor_headcount_range", "google_maps_url",
    "social_links", "decision_makers", "site_emails", "general_email", "hiring_email",
)


def _latest_claims(ctx: RunContext, firm_id: str) -> dict[str, Any]:
    """The freshest value per attribute, whatever wrote it."""
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (attr) attr, value, source
            FROM firm_attribute
            WHERE firm_id = %s AND attr = ANY(%s)
            ORDER BY attr, observed_at DESC, source DESC, confidence DESC
            """,
            (firm_id, list(_CLAIM_ATTRS)),
        )
        return {row["attr"]: row["value"] for row in cur.fetchall()}


def _lines(value: Any, keys: tuple[str, ...] = (), label: str = "") -> list[str]:
    """A claim's value as lines the model can quote. Every line names what it
    is: a bare "True" is not something anyone can quote as proof."""
    said = f"{label.replace('_', ' ')}: " if label else ""
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [f"{said}{value}" if said else value]
    if isinstance(value, (int, float, bool)):
        return [f"{said}{value}"]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_lines(item, keys, label))
        return out
    if isinstance(value, dict):
        wanted = [k for k in (keys or tuple(value)) if value.get(k) not in (None, "", [], {})]
        parts = [f"{k}: {json.dumps(value[k]) if isinstance(value[k], (list, dict)) else value[k]}"
                 for k in wanted]
        return [f"{said}{'; '.join(parts)}"] if parts else []
    return []


def _record(ctx: RunContext, firm: dict, claims: dict[str, Any]) -> list[Block]:
    """Everything the store holds on the firm, in labelled blocks."""
    where = ", ".join(p for p in (firm.get("city"), firm.get("state")) if p)
    facts = [
        f"{firm['canonical_name']}{f' of {where}' if where else ''}.",
        f"Practice on file: {firm.get('primary_practice') or 'not known'}.",
        f"How it charges: {firm.get('fee_model') or 'not stated on the site'}.",
        f"Case system: {firm.get('cms_detected') or 'not known'}.",
    ]
    for label, attr in (("Attorneys", "attorney_count"), ("Support staff", "staff_ratio")):
        for line in _lines(claims.get(attr)):
            facts.append(f"{label}: {line}.")

    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT kind, evidence, first_seen, closed_at FROM signal WHERE firm_id = %s "
            "ORDER BY first_seen DESC",
            (firm["id"],),
        )
        signals = cur.fetchall()
    openings, flagged = [], []
    for s in signals:
        ev = s["evidence"] or {}
        when = s["first_seen"].date().isoformat() if s["first_seen"] else "unknown date"
        shut = " (since filled)" if s["closed_at"] else " (still open)"
        if s["kind"] in ("job_posting_open", "multi_opening"):
            for role in (ev.get("roles") or [ev]):
                title = role.get("title") or role.get("canonical_role")
                if title:
                    openings.append(f"{title}, first seen {when}{shut}.")
        else:
            quote = ev.get("quote") or ev.get("evidence")
            said = f' Quoted: "{quote}"' if quote else ""
            flagged.append(f"{s['kind']}, first seen {when}.{said}")

    return build_record([
        ("the firm", "\n".join(facts)),
        ("what the site lacks", "\n".join(_lines(claims.get("site_gaps"), ("gap", "evidence")))),
        ("what the site shows", "\n".join(
            line
            for attr in ("staff_listed", "online_intake_form", "live_chat_vendor", "spanish_intake",
                         "languages", "office_count", "office_locations", "attorney_count_detail")
            for line in _lines(claims.get(attr), label=attr)
        )),
        ("people on the site", "\n".join(
            _lines(claims.get("site_people"), ("name", "title"))
            + _lines(claims.get("decision_makers"), ("full_name", "title", "role"))
        )),
        ("testimonials on the site",
         "\n".join(_lines(claims.get("testimonials"), ("quote", "text")))),
        ("reviews", "\n".join(
            _lines(claims.get("review_count"), label="review count")
            + _lines(claims.get("site_review_summary"), ("count", "rating", "evidence"))
            + _lines(claims.get("search_review_snippets"), ("body", "url"))
        )),
        ("the business listing", "\n".join(
            _lines(claims.get("google_maps_url"), label="maps link")
            + _lines(claims.get("review_profiles"))
        )),
        ("open roles", "\n".join(openings)),
        ("news on the site", "\n".join(
            _lines(claims.get("growth_news"), ("title", "date"))
            + _lines(claims.get("recent_posts"), ("title", "date"))
            + _lines(claims.get("latest_post_date"), label="latest post")
            + _lines(claims.get("copyright_year"), label="copyright year")
        )),
        ("what the engine already flagged", "\n".join(flagged)),
    ])


def _select(ctx: RunContext, opts: dict[str, Any]) -> list[str]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        text = Path(firm_ids_file).read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    with ctx.conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT f.id FROM firm f JOIN document d ON d.firm_id = f.id "
            "ORDER BY f.id LIMIT %s",
            (int(opts.get("limit", _DEFAULT_LIMIT)),),
        )
        return [str(row["id"]) for row in cur.fetchall()]


async def _call(job: dict, cfg: dict, api_key: str) -> dict:
    async with httpx.AsyncClient() as http_client:
        try:
            response = await call_openrouter(
                http_client,
                api_key=api_key,
                model=cfg["model"],
                system=SYSTEM_PROMPT,
                user=job["user_message"],
                response_format=cfg["response_format"],
                max_tokens=cfg["max_output_tokens"],
                timeout_s=cfg["timeout_s"],
                referer=cfg["referer"],
                title=cfg["title"],
                max_retries=cfg["max_retries"],
                backoff_base_s=cfg["backoff_base_s"],
                backoff_max_s=cfg["backoff_max_s"],
            )
        except LLMCallError as exc:
            return {"kind": "failed", "error": str(exc)}
    stopped = (response.raw.get("choices") or [{}])[0].get("finish_reason")
    try:
        return {"kind": "ok", "analysis": parse(response.content), "usage": response.usage}
    except Exception as exc:  # a schema the model broke -- no claim, never a guess
        why = "the answer hit the output cap" if stopped == "length" else str(exc)
        return {"kind": "invalid", "error": why, "usage": response.usage}


@component("ja8_pain", "JA", "Pain analysis -- the AI reads the record and names what hurts")
def ja8_pain(ctx: RunContext, **opts: Any) -> RunResult:
    cfg_all = load_config()
    cfg = cfg_all[_CFG_KEY]
    req = cfg_all["request"]
    api_key = ctx.settings.openrouter_api_key
    prompt_rev = cfg["prompt_rev"]
    model = cfg["model"]
    source = f"llm:{_CFG_KEY}:{prompt_rev}"

    firm_ids = _select(ctx, opts)
    if not api_key:
        return RunResult(skipped=len(firm_ids), notes=["inert: OPENROUTER_API_KEY not set"])

    dry_run = ctx.dry_run or str(opts.get("dry_run", "")).lower() in ("1", "true")
    raw_max_usd = opts.get("max_usd")
    max_usd = float(raw_max_usd) if raw_max_usd not in (None, "") else None
    call_cfg = {
        "model": model,
        # the schema is enforced by the API, not asked for in the prompt
        "response_format": response_format_for(PainAnalysis, "pain_analysis"),
        "max_output_tokens": int(cfg.get("max_output_tokens", req["max_output_tokens"])),
        "timeout_s": float(req["timeout_s"]),
        "referer": cfg_all["referer"],
        "title": cfg_all["title"],
        "max_retries": int(req["max_retries"]),
        "backoff_base_s": float(req["backoff_base_s"]),
        "backoff_max_s": float(req["backoff_max_s"]),
    }

    result = RunResult()
    spent = 0.0
    sized = 0
    for firm_id in firm_ids:
        with ctx.conn.cursor() as cur:
            cur.execute(
                "SELECT id, canonical_name, city, state, tier, fee_model, primary_practice, "
                "cms_detected FROM firm WHERE id = %s",
                (firm_id,),
            )
            firm = cur.fetchone()
        if firm is None:
            result.skipped += 1
            continue

        blocks = _record(ctx, firm, _latest_claims(ctx, firm_id))
        # "the firm" alone is a header, not a record: nothing to analyse.
        if len(blocks) < 2:
            result.skipped += 1
            result.notes.append(f"{firm['canonical_name']}: nothing read about this firm yet")
            continue

        user_message = build_user_message(firm["canonical_name"], blocks)
        ihash = input_hash(user_message, prompt_rev, model)
        est = estimate_cost(
            len(user_message), float(cfg["price_per_mtok_input"]),
            float(cfg["price_per_mtok_output"]), call_cfg["max_output_tokens"],
        )
        if dry_run:
            result.skipped += 1
            spent += est
            sized += 1
            result.notes.append(f"{firm['canonical_name']}: {len(user_message)} chars, ~${est:.4f}")
            continue
        if max_usd is not None and spent + est > max_usd:
            result.skipped += 1
            result.notes.append(f"budget stop: ${max_usd:.2f} reached")
            continue

        try:
            with ctx.once(_COMPONENT, firm_id, ihash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue
                outcome = asyncio.run(_call({"user_message": user_message}, call_cfg, api_key))
                # Both failures raise: `ctx.once` marks the task 'ok' on a normal
                # exit, so returning quietly here would record the firm as done
                # and never ask again at this input hash.
                if outcome["kind"] in ("failed", "invalid"):
                    raise LLMCallError(f"{firm['canonical_name']}: {outcome['error']}")
                usage = outcome.get("usage") or {}
                in_tokens, out_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
                analysis, dropped = ground(outcome["analysis"], blocks)
                insert_llm_call(
                    ctx, firm_id=firm_id, component=_COMPONENT, model=model, prompt_rev=prompt_rev,
                    input_chars=len(user_message), input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    cost_usd=(
                        (in_tokens / 1_000_000) * float(cfg["price_per_mtok_input"])
                        + (out_tokens / 1_000_000) * float(cfg["price_per_mtok_output"])
                        if in_tokens is not None and out_tokens is not None
                        else est
                    ),
                    status="ungrounded" if dropped else "ok",
                    ungrounded_fields=[d[0] for d in dropped] or None, response=None,
                )
                write_claim(
                    ctx.conn, firm_id, "pain_analysis", claim_value(analysis, blocks, dropped),
                    source,
                    # the weakest pain sets the claim's confidence, not the strongest
                    min((p.confidence for p in analysis.pains), default=0.0),
                    analysis.pains[0].quote if analysis.pains else None,
                    datetime.now(UTC),
                )
                spent += est
                result.processed += 1
                if dropped:
                    result.notes.append(
                        f"{firm['canonical_name']}: {len(dropped)} pain(s) dropped, unproven"
                    )
        except LLMCallError as exc:
            # Counted and named, never fatal: 249 firms must not be lost to one.
            result.failed += 1
            result.notes.append(str(exc))
        ctx.checkpoint()

    if dry_run:
        result.notes.insert(0, f"dry_run: estimated ${spent:.4f} over {sized} firm(s)")
    return result
