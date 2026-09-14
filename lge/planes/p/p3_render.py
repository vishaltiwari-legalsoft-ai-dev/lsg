"""P3 — render fallback gate.

The gate fires only when a page's static main text is under 500 words
(`document.word_count`, written by P2) -- expected on 5-8% of sites.
Flagging is a pure DB read/write over already-fetched rows, so it runs
regardless of the live gate; an actual render (launching a browser) is live
network work and is gated the same way every other fetch is.

The renderer is the system Chrome (`--headless --dump-dom`, under our own
honest User-Agent), found via LGE_CHROME or the usual install paths (D-030).
Playwright's own browser download is blocked by Windows Application Control
on this machine; the installed Chrome is not. With no browser at all the
component still flags pages and reports how many would have rendered.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from pathlib import Path

import psycopg

from lge.fetch.client import EmptyUserAgentError
from lge.fetch.decode import decode_html
from lge.fetch.pagecheck import looks_like_js_shell, visible_words
from lge.fetch.selection import select_firm_ids
from lge.planes.p._claims import read_html
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

logger = logging.getLogger("lge.planes.p3")

WORD_COUNT_GATE = 500


_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
RENDER_TIMEOUT_S = 45


def chrome_path() -> str | None:
    """The system Chrome, if there is one (LGE_CHROME overrides). Playwright's
    own browser download is blocked on this machine; the installed Chrome is
    not, and `--headless --dump-dom` is all a render needs (D-030)."""
    override = os.environ.get("LGE_CHROME")
    if override:
        return override if Path(override).is_file() else None
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def render_available() -> bool:
    """True when a browser can be launched. A launch can still fail (OS
    policy, a hung page), which `_attempt_render` handles per document."""
    return chrome_path() is not None


def _render_page_sync(url: str, user_agent: str) -> bytes | None:  # pragma: no cover
    """The page's DOM after JavaScript ran, from headless Chrome under our own
    honest identity. Exercised in tests via a monkeypatched replacement."""
    binary = chrome_path()
    if binary is None:
        return None
    proc = subprocess.run(
        [
            binary, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars",
            f"--user-agent={user_agent}", "--virtual-time-budget=8000",
            f"--timeout={(RENDER_TIMEOUT_S - 10) * 1000}", "--dump-dom", url,
        ],
        capture_output=True, timeout=RENDER_TIMEOUT_S, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"chrome exited {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[-200:]}"
        )
    return proc.stdout


def _select_render_candidates(conn: psycopg.Connection, firm_ids: list[str]) -> list[dict]:
    if not firm_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, firm_id, url, content_hash, word_count, object_key
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


def worth_rendering(store: ObjectStore, row: dict) -> bool:
    """A thin page is worth a browser only when it is an application shell --
    a root element and scripts, almost no text. A contact page that simply
    says little is static; rendering it would give back the same words. With
    nothing stored to judge by, the word-count gate alone decides."""
    html = read_html(store, row.get("object_key"))
    if not html:
        return True
    return looks_like_js_shell(html)


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
        # The same DOM may already be on file for this URL (an earlier render,
        # or a fetch that got the rendered page): (url, content_hash) is unique,
        # so this row is marked rendered and left as it was.
        cur.execute(
            "SELECT 1 FROM document WHERE url = %s AND content_hash = %s AND id <> %s",
            (row["url"], object_key, row["id"]),
        )
        if cur.fetchone() is not None:
            cur.execute("UPDATE document SET rendered = true WHERE id = %s", (row["id"],))
            return True
        # The rendered DOM is the document now: new bytes, new hash, new word
        # count -- and no extracted text, so P4 reads it again.
        cur.execute(
            "UPDATE document SET rendered = true, object_key = %s, content_hash = %s, "
            "bytes = %s, word_count = %s WHERE id = %s",
            (object_key, object_key, len(html), visible_words(decode_html(html)), row["id"]),
        )
        cur.execute("DELETE FROM document_text WHERE document_id = %s", (row["id"],))
    return True


@component(
    "p3_render",
    "P",
    "Render fallback gate: flag thin-text pages, render JavaScript shells with the system Chrome",
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

    thin = _select_render_candidates(ctx.conn, firm_ids)
    candidates = [row for row in thin if worth_rendering(store, row)]
    static_thin = len(thin) - len(candidates)
    if not candidates:
        result.notes.append(
            f"no JavaScript shells under the {WORD_COUNT_GATE}-word gate need flagging "
            f"({static_thin} thin page(s) are static -- nothing to render)"
        )
        return result

    by_firm: dict[str, list[dict]] = {}
    for row in candidates:
        by_firm.setdefault(str(row["firm_id"]), []).append(row)

    hashes = {fid: _input_hash(rows) for fid, rows in by_firm.items()}
    have_browser = render_available()
    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    will_attempt_render = have_browser and live

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

    if static_thin:
        result.notes.append(f"{static_thin} thin page(s) are static -- nothing to render")
    if have_browser:
        if live:
            result.notes.append(
                f"flagged {total_flagged} page(s) under {WORD_COUNT_GATE} words; "
                f"rendered {total_rendered}/{total_flagged}"
            )
        else:
            result.notes.append(
                f"flagged {total_flagged} page(s) under {WORD_COUNT_GATE} words; "
                f"a browser is available but live=0 -- no render attempted"
            )
    else:
        result.notes.append(
            f"render unavailable (no Chrome found; set LGE_CHROME): {total_flagged} page(s) "
            f"under {WORD_COUNT_GATE} words would have rendered"
        )

    return result
