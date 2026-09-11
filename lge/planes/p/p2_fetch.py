"""P2 — page fetcher.

Fetches every `site_map` URL for a firm (robots-checked, rate-limited),
stores the raw bytes in the object store ALWAYS, and writes `document`. This
is the single most consequential table in the profile plane: a later schema,
prompt or normalizer change becomes a re-parse of stored HTML, never a
re-crawl (context/40-pipeline/02-component-register.md).

`document.word_count` here is a cheap visible-text count for the render gate
(P3) -- P4's trafilatura extraction is the careful, boilerplate-aware pass
that `document_text.main_text` is built from. A probe URL returning 404 is
recorded (fetch_ok=true, status 404) and not word-counted.

Selection, live gate and honest-UA refusal follow the same contract as P1
(lge/fetch/selection.py, lge/fetch/client.py).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
from dataclasses import dataclass

import lxml.etree
import lxml.html
import psycopg

from lge.db import writer
from lge.fetch.client import EmptyUserAgentError, Fetcher, HostBlockTracker, host_of
from lge.fetch.config import rate_defaults
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.ratelimit import HostRateLimiter
from lge.fetch.robots import RobotsCache
from lge.fetch.robots import persist as persist_robots_policy
from lge.fetch.selection import already_done, select_firm_ids
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

logger = logging.getLogger("lge.planes.p2")

_HTML_LIKE_STATUSES = range(200, 300)


@dataclass
class DocumentFetch:
    url: str
    page_kind: str
    fetch_ok: bool
    status: int | None
    final_url: str | None
    body: bytes | None
    robots_decision: str | None
    content_type_ok: bool
    error: str | None


def _quick_word_count(body: bytes) -> int | None:
    """Fast visible-text word count -- strips script/style, not a substitute
    for P4's trafilatura extraction. None on unparseable input."""
    try:
        tree = lxml.html.fromstring(body)
    except (lxml.etree.ParserError, ValueError):
        return None
    for bad in tree.xpath(".//script | .//style"):
        bad.getparent().remove(bad)
    text = tree.text_content()
    words = text.split()
    return len(words)


async def _fetch_one_firm(
    fetcher: Fetcher,
    robots_cache: RobotsCache,
    user_agent: str,
    urls: list[tuple[str, str]],
) -> list[DocumentFetch]:
    out: list[DocumentFetch] = []
    for url, kind in urls:
        host = host_of(url)
        robots = await robots_cache.get(host)
        if not robots.crawlable():
            out.append(
                DocumentFetch(
                    url=url,
                    page_kind=kind,
                    fetch_ok=False,
                    status=None,
                    final_url=None,
                    body=None,
                    robots_decision=None,
                    content_type_ok=True,
                    error=f"host not crawlable (source_state={robots.source_state})",
                )
            )
            continue

        decision = robots.decision(url, user_agent)
        if decision == "disallowed":
            out.append(
                DocumentFetch(
                    url=url,
                    page_kind=kind,
                    fetch_ok=False,
                    status=None,
                    final_url=None,
                    body=None,
                    robots_decision="disallowed",
                    content_type_ok=True,
                    error="robots.txt disallows this path",
                )
            )
            continue

        result = await fetcher.fetch(url, robots_decision=decision)
        out.append(
            DocumentFetch(
                url=url,
                page_kind=kind,
                fetch_ok=result.fetch_ok,
                status=result.status,
                final_url=result.final_url,
                body=result.body,
                robots_decision=decision,
                content_type_ok=result.content_type_ok,
                error=result.error,
            )
        )
    return out


async def _fetch_all_firms(
    user_agent: str,
    firms_urls: dict[str, list[tuple[str, str]]],
    max_concurrent_hosts: int,
    default_interval_s: float,
) -> tuple[dict[str, list[DocumentFetch]], dict]:
    limiter = HostRateLimiter(default_interval_s=default_interval_s)
    block_tracker = HostBlockTracker()
    async with Fetcher(
        user_agent=user_agent, limiter=limiter, block_tracker=block_tracker
    ) as fetcher:
        robots_cache = RobotsCache(fetcher, user_agent)
        factories = {
            fid: functools.partial(_fetch_one_firm, fetcher, robots_cache, user_agent, urls)
            for fid, urls in firms_urls.items()
        }
        fetched = await gather_bounded(factories, max_concurrent_hosts)
        return fetched, robots_cache.snapshot()


def _load_site_maps(
    conn: psycopg.Connection, firm_ids: list[str]
) -> dict[str, list[tuple[str, str]]]:
    if not firm_ids:
        return {}
    out: dict[str, list[tuple[str, str]]] = {fid: [] for fid in firm_ids}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT firm_id, url, page_kind FROM site_map WHERE firm_id = ANY(%s) "
            "ORDER BY firm_id, url",
            (firm_ids,),
        )
        for row in cur.fetchall():
            out[str(row["firm_id"])].append((row["url"], row["page_kind"]))
    return out


def _input_hash(urls: list[tuple[str, str]]) -> str:
    joined = "|".join(sorted(u for u, _kind in urls))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _write_firm_documents(
    conn: psycopg.Connection, firm_id: str, fetched: list[DocumentFetch], store: ObjectStore
) -> None:
    home_content_hash: str | None = None
    home_fetched_ok = False

    with conn.cursor() as cur:
        for doc in fetched:
            object_key: str | None = None
            word_count: int | None = None
            content_hash: str | None = None

            if doc.body is not None:
                object_key = store.put(doc.body)  # content-addressed; idempotent
                content_hash = object_key
                is_html = doc.content_type_ok and (
                    doc.status is not None and doc.status in _HTML_LIKE_STATUSES
                )
                if is_html:
                    word_count = _quick_word_count(doc.body)
                if doc.page_kind == "home" and doc.fetch_ok:
                    home_fetched_ok = True
                    home_content_hash = content_hash

            cur.execute(
                """
                INSERT INTO document (firm_id, url, final_url, status_code, content_hash,
                                       object_key, bytes, word_count, fetch_ok,
                                       robots_decision, page_kind)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url, content_hash) DO NOTHING
                """,
                (
                    firm_id,
                    doc.url,
                    doc.final_url,
                    doc.status,
                    content_hash,
                    object_key,
                    len(doc.body) if doc.body is not None else None,
                    word_count,
                    doc.fetch_ok,
                    doc.robots_decision,
                    doc.page_kind,
                ),
            )

    # last_crawled always advances -- this firm was attempted this pass.
    # content_hash only moves when the home page was actually fetched this
    # run; a transient home-page failure must not null out a known-good
    # hash (W7 liveness reads a *change* in this value as "re-profile").
    with writer(conn, "profile"), conn.cursor() as cur:
        if home_fetched_ok:
            cur.execute(
                "UPDATE firm SET last_crawled = now(), content_hash = %s WHERE id = %s",
                (home_content_hash, firm_id),
            )
        else:
            cur.execute(
                "UPDATE firm SET last_crawled = now() WHERE id = %s",
                (firm_id,),
            )


@component("p2_fetch", "P", "Page fetcher: fetch site_map URLs, store raw HTML, write document")
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

    site_maps = _load_site_maps(ctx.conn, firm_ids)
    firm_ids = [fid for fid in firm_ids if site_maps.get(fid)]
    if not firm_ids:
        result.notes.append("no site_map rows for any selected firm -- run p1_site_map first")
        return result

    hashes = {fid: _input_hash(site_maps[fid]) for fid in firm_ids}
    done = already_done(ctx.conn, "p2_fetch", hashes)
    pending = {fid: site_maps[fid] for fid in firm_ids if fid not in done}
    result.skipped += len(done)

    if not pending:
        result.notes.append(
            f"all {len(firm_ids)} firm(s) already fetched for their current site_map"
        )
        return result

    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append(
            f"live=0: would fetch {len(pending)} firm(s) ({len(done)} already done); "
            "no requests made"
        )
        return result

    if not ctx.settings.user_agent.strip():
        raise EmptyUserAgentError(
            "refusing to fetch: settings.user_agent is empty -- set LGE_USER_AGENT"
        )

    max_concurrent_hosts = int(
        opts.get("max_concurrent_hosts", rate_defaults()["max_concurrent_hosts"])
    )
    default_interval_s = float(
        opts.get("default_interval_s", rate_defaults()["default_interval_s"])
    )
    fetched_by_firm, robots_seen = asyncio.run(
        _fetch_all_firms(ctx.settings.user_agent, pending, max_concurrent_hosts, default_interval_s)
    )

    for policy in robots_seen.values():
        persist_robots_policy(ctx.conn, policy)

    for firm_id, fetched in fetched_by_firm.items():
        input_hash = hashes[firm_id]
        with ctx.once("p2_fetch", firm_id, input_hash) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            _write_firm_documents(ctx.conn, firm_id, fetched, store)
            result.processed += 1
            n_ok = sum(1 for d in fetched if d.fetch_ok)
            if n_ok < len(fetched):
                result.notes.append(
                    f"{firm_id}: {n_ok}/{len(fetched)} page(s) fetched successfully"
                )
        ctx.checkpoint()

    return result
