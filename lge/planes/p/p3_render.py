"""P3 — render fallback gate.

The gate fires only when a page's static main text is under 500 words
(`document.word_count`, written by P2) -- expected on 5-8% of sites.
Flagging is a pure DB read/write over already-fetched rows, so it runs
regardless of the live gate; an actual render (launching a browser) is live
network work and is gated the same way every other fetch is.

Playwright is not installed in this environment (Windows Application
Control is likely to block its browser download even if it were) -- this
component still implements the gate and the render-attempt path so it is
correct if playwright is ever added, but on THIS box it always takes the
"render unavailable" branch and reports how many pages would have
rendered, per the task brief.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging

import psycopg

from lge.fetch.client import EmptyUserAgentError
from lge.fetch.selection import select_firm_ids
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

logger = logging.getLogger("lge.planes.p3")

WORD_COUNT_GATE = 500


def render_available() -> bool:
    """True if `playwright` is importable. Does not attempt to launch a
    browser -- that can still fail separately (binaries missing, OS policy),
    which `_attempt_render` handles per-document."""
    return importlib.util.find_spec("playwright") is not None


def _render_page_sync(url: str, user_agent: str) -> bytes | None:  # pragma: no cover
    """Best-effort real render. Only ever called when render_available() is
    True, which it is not in this environment -- exercised in tests via a
    monkeypatched replacement, never this body."""
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=user_agent)
            page.goto(url, timeout=30_000, wait_until="networkidle")
            html = page.content()
        finally:
            browser.close()
    return html.encode("utf-8")


def _select_render_candidates(conn: psycopg.Connection, firm_ids: list[str]) -> list[dict]:
    if not firm_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, firm_id, url, content_hash, word_count
            FROM document
            WHERE firm_id = ANY(%s)
              AND fetch_ok = true
              AND status_code BETWEEN 200 AND 299
              AND word_count IS NOT NULL
              AND word_count < %s
              AND rendered = false
            ORDER BY firm_id, id
            """,
            (firm_ids, WORD_COUNT_GATE),
        )
        return list(cur.fetchall())


def _input_hash(rows: list[dict]) -> str:
    joined = "|".join(f"{r['id']}:{r['content_hash']}" for r in rows)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _flag_render_needed(conn: psycopg.Connection, doc_ids: list[int]) -> None:
    if not doc_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE document SET render_needed = true WHERE id = ANY(%s)",
            (doc_ids,),
        )


def _attempt_render(
    conn: psycopg.Connection, row: dict, user_agent: str, store: ObjectStore
) -> bool:
    """Best-effort. Any failure (browser missing, timeout, OS policy block)
    is caught and logged -- a broken render must never stall the firm."""
    try:
        html = _render_page_sync(row["url"], user_agent)
    except Exception as exc:  # render is best-effort by design; never stall the firm
        logger.warning("p3_render: render failed for document %s: %s", row["id"], exc)
        return False
    if not html:
        return False
    object_key = store.put(html)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE document SET rendered = true, object_key = %s, bytes = %s WHERE id = %s",
            (object_key, len(html), row["id"]),
        )
    return True


@component(
    "p3_render",
    "P",
    "Render fallback gate: flag thin-text pages, render if playwright is available",
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    store = store or get_store()
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),
        limit=opts.get("limit"),
    )
    if not firm_ids:
        result.notes.append("no firms selected")
        return result

    candidates = _select_render_candidates(ctx.conn, firm_ids)
    if not candidates:
        result.notes.append("no documents under the 500-word gate need flagging")
        return result

    by_firm: dict[str, list[dict]] = {}
    for row in candidates:
        by_firm.setdefault(str(row["firm_id"]), []).append(row)

    hashes = {fid: _input_hash(rows) for fid, rows in by_firm.items()}
    have_playwright = render_available()
    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    will_attempt_render = have_playwright and live

    if will_attempt_render and not ctx.settings.user_agent.strip():
        raise EmptyUserAgentError(
            "refusing to render: settings.user_agent is empty -- set LGE_USER_AGENT"
        )

    total_flagged = 0
    total_rendered = 0
    for firm_id, rows in by_firm.items():
        with ctx.once("p3_render", firm_id, hashes[firm_id]) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            doc_ids = [r["id"] for r in rows]
            _flag_render_needed(ctx.conn, doc_ids)
            total_flagged += len(doc_ids)
            if will_attempt_render:
                for row in rows:
                    if _attempt_render(ctx.conn, row, ctx.settings.user_agent, store):
                        total_rendered += 1
            result.processed += 1
        ctx.checkpoint()

    if have_playwright:
        if live:
            result.notes.append(
                f"flagged {total_flagged} page(s) under {WORD_COUNT_GATE} words; "
                f"rendered {total_rendered}/{total_flagged}"
            )
        else:
            result.notes.append(
                f"flagged {total_flagged} page(s) under {WORD_COUNT_GATE} words; "
                f"playwright is importable but live=0 -- no render attempted"
            )
    else:
        result.notes.append(
            f"render unavailable (playwright not importable): {total_flagged} page(s) "
            f"under {WORD_COUNT_GATE} words would have rendered"
        )

    return result
