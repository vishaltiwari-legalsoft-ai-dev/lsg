"""P2 — page fetcher and crawler.

Fetches every `site_map` URL for a firm (robots-checked, rate-limited), then
follows the links those pages carry to the kinds of page worth reading --
practice, careers, contact, team, locations, testimonials, news -- up to the
per-kind and per-firm caps in config/crawl.yml (D-030). Before this, only the
homepage's links were read and a firm's careers page, offices or news lived
two clicks away, unseen.

Every fetched body is stored in the object store ALWAYS and written to
`document`: a later schema, prompt or normalizer change becomes a re-parse of
stored HTML, never a re-crawl. What a fetch was is on the row: `fetch_error`
says why there is no page, `soft_404` marks a 200 that is an error page, and a
page whose content is byte-identical to one already fetched for the firm is
not written twice (the first URL stands).

`document.word_count` here is a cheap visible-text count for the render gate
(P3) -- P4's trafilatura extraction is the careful, boilerplate-aware pass
that `document_text.main_text` is built from.

Selection, live gate and honest-UA refusal follow the same contract as P1
(lge/fetch/selection.py, lge/fetch/client.py).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field

import psycopg

from lge.db import writer
from lge.fetch.client import EmptyUserAgentError, Fetcher, HostBlockTracker, host_of
from lge.fetch.config import load_crawl_config, rate_defaults
from lge.fetch.decode import decode_html
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.pagecheck import looks_like_soft_404, visible_words
from lge.fetch.ratelimit import HostRateLimiter
from lge.fetch.robots import RobotsCache
from lge.fetch.robots import persist as persist_robots_policy
from lge.fetch.selection import already_done, select_firm_ids
from lge.planes.p.p1_site_map import extract_homepage_links
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

logger = logging.getLogger("lge.planes.p2")

_HTML_LIKE_STATUSES = range(200, 300)

# Kinds worth following a link to. 'other' and 'home' are never crawled into.
WANTED_KINDS = (
    "practice", "careers", "contact", "about", "attorneys", "team",
    "locations", "testimonials", "news", "fees",
)
MAX_DEPTH = 2  # links from the initial pages, and links from those


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
    soft_404: bool = False
    duplicate_of: str | None = None  # URL whose bytes this page repeats


@dataclass
class FirmFetch:
    docs: list[DocumentFetch] = field(default_factory=list)
    discovered: list[tuple[str, str]] = field(default_factory=list)  # (url, kind) found by crawling


# The pages worth the most when a host's Crawl-delay means we cannot have them all.
_KIND_PRIORITY = {
    "home": 0, "careers": 1, "practice": 2, "contact": 3, "fees": 4, "about": 5,
    "attorneys": 6, "team": 7, "locations": 8, "testimonials": 9, "news": 10,
}
HOST_TIME_BUDGET_S = 300.0


def budgeted(
    urls: list[tuple[str, str]], crawl_delay_s: float | None
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(fetch this run, leave for later). A host asking for a long Crawl-delay is
    honoured, but must not hold the whole batch: cavanaghlawgroup.com declares 600s,
    which made one firm's 13 pages a two-hour tail behind every other host (D-026).
    What fits the per-host budget is fetched, most valuable pages first."""
    ordered = sorted(urls, key=lambda u: _KIND_PRIORITY.get(u[1], 9))
    if not crawl_delay_s or crawl_delay_s * len(ordered) <= HOST_TIME_BUDGET_S:
        return ordered, []
    keep = max(1, int(HOST_TIME_BUDGET_S // crawl_delay_s))
    return ordered[:keep], ordered[keep:]


def _not_fetched(
    url: str, kind: str, error: str, robots_decision: str | None = None
) -> DocumentFetch:
    return DocumentFetch(
        url=url, page_kind=kind, fetch_ok=False, status=None, final_url=None, body=None,
        robots_decision=robots_decision, content_type_ok=True, error=error,
    )


async def _fetch_one_firm(
    fetcher: Fetcher,
    robots_cache: RobotsCache,
    user_agent: str,
    domain: str | None,
    urls: list[tuple[str, str]],
) -> FirmFetch:
    out = FirmFetch()
    if not urls:
        return out
    domain = domain or host_of(urls[0][0])
    policy = await robots_cache.get(domain)
    initial, deferred = budgeted(urls, policy.crawl_delay_s)
    for url, kind in deferred:
        out.docs.append(_not_fetched(
            url, kind,
            f"not fetched this run: host Crawl-delay {policy.crawl_delay_s:g}s "
            "exceeds the per-host budget",
        ))

    caps = load_crawl_config()["caps"]
    # The per-host time budget bounds the crawl too, not only the map: a host
    # asking Crawl-delay 30s gets 10 pages this run, not 30 pages in 15 minutes.
    page_budget = caps["total"]
    if policy.crawl_delay_s:
        page_budget = min(page_budget, max(1, int(HOST_TIME_BUDGET_S // policy.crawl_delay_s)))
    counts: Counter[str] = Counter(kind for _u, kind in urls)
    seen_urls = {u for u, _k in urls}
    seen_hashes: dict[str, str] = {}
    frontier = list(initial)
    depth = 0
    while frontier:
        next_frontier: list[tuple[str, str]] = []
        for url, kind in frontier:
            host = host_of(url)
            robots = await robots_cache.get(host)
            if not robots.crawlable():
                out.docs.append(_not_fetched(
                    url, kind, f"host not crawlable (source_state={robots.source_state})"
                ))
                continue
            decision = robots.decision(url, user_agent)
            if decision == "disallowed":
                out.docs.append(_not_fetched(url, kind, "robots.txt disallows this path", decision))
                continue

            result = await fetcher.fetch(url, robots_decision=decision)
            doc = DocumentFetch(
                url=url, page_kind=kind, fetch_ok=result.fetch_ok, status=result.status,
                final_url=result.final_url, body=result.body, robots_decision=decision,
                content_type_ok=result.content_type_ok, error=result.error,
            )
            is_html = (
                doc.body is not None and doc.content_type_ok
                and doc.status is not None and doc.status in _HTML_LIKE_STATUSES
            )
            if is_html:
                digest = hashlib.sha256(doc.body).hexdigest()  # type: ignore[arg-type]
                if digest in seen_hashes and seen_hashes[digest] != url:
                    doc.duplicate_of = seen_hashes[digest]
                else:
                    seen_hashes[digest] = url
                    html = decode_html(doc.body)  # type: ignore[arg-type]
                    if looks_like_soft_404(html):
                        doc.soft_404 = True
                    elif not policy.slow and depth < MAX_DEPTH:
                        base = doc.final_url or url
                        for link, lkind in extract_homepage_links(doc.body, base, domain):  # type: ignore[arg-type]
                            if link in seen_urls or lkind not in WANTED_KINDS:
                                continue
                            if len(seen_urls) >= page_budget:
                                break
                            if counts[lkind] >= caps.get(lkind, caps["other"]):
                                continue
                            seen_urls.add(link)
                            counts[lkind] += 1
                            next_frontier.append((link, lkind))
                            out.discovered.append((link, lkind))
            out.docs.append(doc)
        frontier = next_frontier
        depth += 1
    return out


async def _fetch_all_firms(
    user_agent: str,
    firms: dict[str, tuple[str | None, list[tuple[str, str]]]],
    max_concurrent_hosts: int,
    default_interval_s: float,
) -> tuple[dict[str, FirmFetch], dict]:
    limiter = HostRateLimiter(default_interval_s=default_interval_s)
    block_tracker = HostBlockTracker()
    async with Fetcher(
        user_agent=user_agent, limiter=limiter, block_tracker=block_tracker
    ) as fetcher:
        robots_cache = RobotsCache(fetcher, user_agent)
        factories = {
            fid: functools.partial(_fetch_one_firm, fetcher, robots_cache, user_agent, dom, urls)
            for fid, (dom, urls) in firms.items()
        }
        fetched = await gather_bounded(factories, max_concurrent_hosts)
        return fetched, robots_cache.snapshot()


def _load_site_maps(
    conn: psycopg.Connection, firm_ids: list[str]
) -> dict[str, list[tuple[str, str, str]]]:
    """(url, kind, via) per firm. Rows the crawler itself discovered
    (via='crawl') are fetched again but never change the idempotency key,
    or every run would re-fetch everything it found the run before."""
    if not firm_ids:
        return {}
    out: dict[str, list[tuple[str, str, str]]] = {fid: [] for fid in firm_ids}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT firm_id, url, page_kind, discovered_via FROM site_map "
            "WHERE firm_id = ANY(%s) ORDER BY firm_id, url",
            (firm_ids,),
        )
        for row in cur.fetchall():
            out[str(row["firm_id"])].append((row["url"], row["page_kind"], row["discovered_via"]))
    return out


def _load_domains(conn: psycopg.Connection, firm_ids: list[str]) -> dict[str, str | None]:
    if not firm_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, domain FROM firm WHERE id = ANY(%s)", (firm_ids,))
        return {str(r["id"]): r["domain"] for r in cur.fetchall()}


def _input_hash(rows: list[tuple[str, str, str]]) -> str:
    joined = "|".join(sorted(u for u, _kind, via in rows if via != "crawl"))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _write_firm_documents(
    conn: psycopg.Connection, firm_id: str, fetched: FirmFetch, store: ObjectStore
) -> dict[str, int]:
    home_content_hash: str | None = None
    home_fetched_ok = False
    counts = {"written": 0, "duplicate": 0, "soft_404": 0, "failed": 0}

    with conn.cursor() as cur:
        for doc in fetched.docs:
            if doc.duplicate_of:
                counts["duplicate"] += 1
                continue
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
                    word_count = visible_words(decode_html(doc.body))
                if doc.page_kind == "home" and doc.fetch_ok:
                    home_fetched_ok = True
                    home_content_hash = content_hash

            cur.execute(
                """
                INSERT INTO document (firm_id, url, final_url, status_code, content_hash,
                                       object_key, bytes, word_count, fetch_ok,
                                       robots_decision, page_kind, fetch_error, soft_404)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url, content_hash) DO NOTHING
                """,
                (
                    firm_id, doc.url, doc.final_url, doc.status, content_hash, object_key,
                    len(doc.body) if doc.body is not None else None, word_count, doc.fetch_ok,
                    doc.robots_decision, doc.page_kind, doc.error, doc.soft_404,
                ),
            )
            counts["written"] += 1
            counts["soft_404"] += int(doc.soft_404)
            counts["failed"] += int(not doc.fetch_ok)

        for url, kind in fetched.discovered:
            cur.execute(
                "INSERT INTO site_map (firm_id, url, page_kind, discovered_via) "
                "VALUES (%s, %s, %s, 'crawl') ON CONFLICT (firm_id, url) DO NOTHING",
                (firm_id, url, kind),
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
            cur.execute("UPDATE firm SET last_crawled = now() WHERE id = %s", (firm_id,))
    return counts


@component("p2_fetch", "P", "Page fetcher: fetch and crawl a firm's site, store raw HTML")
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
    domains = _load_domains(ctx.conn, firm_ids)
    pending = {
        fid: (domains.get(fid), [(u, k) for u, k, _via in site_maps[fid]])
        for fid in firm_ids if fid not in done
    }
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

    totals: Counter[str] = Counter()
    for firm_id, fetched in fetched_by_firm.items():
        input_hash = hashes[firm_id]
        with ctx.once("p2_fetch", firm_id, input_hash) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            counts = _write_firm_documents(ctx.conn, firm_id, fetched, store)
            totals.update(counts)
            totals["discovered"] += len(fetched.discovered)
            result.processed += 1
            if counts["failed"]:
                result.notes.append(
                    f"{firm_id}: {counts['written'] - counts['failed']}/{counts['written']} "
                    f"page(s) fetched, {len(fetched.discovered)} found by crawling"
                )
        ctx.checkpoint()

    result.notes.insert(
        0,
        f"pages written {totals['written']}, found by crawling {totals['discovered']}, "
        f"duplicates skipped {totals['duplicate']}, soft 404s {totals['soft_404']}, "
        f"failed {totals['failed']}",
    )
    return result
