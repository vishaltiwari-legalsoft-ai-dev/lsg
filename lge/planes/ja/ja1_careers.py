"""JA1 — careers page watcher.

`firm.domain -> raw_posting`. Best ICP coverage of any job source, free,
stable, and the one source unambiguously tied to the firm -- no name
resolution needed (context/20-signals/02-job-source-register.md). Runs
nightly; per-firm isolation means a broken site never stalls the sweep.

Every sweep is recorded in `careers_sweep` -- including a failed fetch
(fetch_ok=false, postings_found NULL) and a zero-posting sweep -- because
closure detection has to tell "fetched and absent" apart from "fetch
failed". An unchanged content hash since the last successful sweep skips
parsing entirely (parse_method='none', postings_found carried over).

Parse order, cheapest and most reliable first: JobPosting JSON-LD -> schema.org
microdata/RDFa -> embedded ATS (slug recorded for JA3, never fetched here) ->
an HTML heading/list heuristic gated through normalize_title()/is_support_role()
(lowest confidence). The first layer that yields anything wins for that page --
once a page's real postings are found, the noisier heuristic never runs on it.

Indeed, LinkedIn and ZipRecruiter are never fetched
(context/70-decisions/02-deliberate-exclusions.md) -- a link to one is only
ever recorded (raw_posting.outbound_links), never followed.

Idempotency: `ctx.once` keys on (firm_id, today's date), not on page
content -- a watcher's job is to re-check every night even when nothing
changed, which unchanged-hash-skips-parsing already handles at the content
layer. The date key only protects against double-running the same
`lge run ja1_careers` invocation twice in one calendar day.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

import lxml.etree
import lxml.html
import psycopg
from extruct import extract as extruct_extract
from psycopg.types.json import Jsonb

from lge.classify.titles import is_support_role, normalize_title
from lge.fetch.client import EmptyUserAgentError, Fetcher, FetchResult, HostBlockTracker
from lge.fetch.config import rate_defaults
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.ratelimit import HostRateLimiter
from lge.fetch.robots import RobotsCache
from lge.fetch.robots import persist as persist_robots_policy
from lge.fetch.selection import already_done, select_firm_ids
from lge.registry import RunContext, RunResult, component

logger = logging.getLogger("lge.planes.ja1")

# JA1's own probe list (order matters -- first non-404 wins), distinct from
# P1's page-kind probes: adds /join-our-team per the task brief.
_PROBE_PATHS = ("/careers", "/jobs", "/employment", "/join-our-team")

# Deliberately excluded -- context/70-decisions/02-deliberate-exclusions.md.
# Never fetched; a link to one is recorded on whatever posting we found and
# nothing more.
_EXCLUDED_BOARD_HOSTS = ("indeed.com", "linkedin.com", "ziprecruiter.com")

# host-pattern -> (platform, slug-capturing regex). Iframe/anchor src or href
# matching one of these is recorded (host + slug) for JA3 to poll later --
# never fetched from here.
_ATS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
    ("jazzhr", re.compile(r"([\w-]+)\.applytojob\.com", re.I)),
    ("bamboohr", re.compile(r"([\w-]+)\.bamboohr\.com", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
)

_JOB_CONTEXT_RE = re.compile(r"\b(?:apply|position|opening|opportunit\w*|career)\w*\b", re.I)
# Domain's last label must be letters-only so a sentence-ending period right
# after the TLD (".com." at the end of a description) is never swallowed
# into the match.
_EMAIL_RE = re.compile(r"[\w.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}")
_HEADING_AND_LIST_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "li")


# ---------------------------------------------------------------------------
# Candidate resolution: which URL is "the" careers page for this firm this
# run (site_map first, else probe in order -- see module docstring).
# ---------------------------------------------------------------------------


@dataclass
class CareersOutcome:
    firm_id: str
    url: str | None
    fetch_ok: bool = False
    status: int | None = None
    body: bytes | None = None
    content_type_ok: bool = True
    error: str | None = None
    note: str | None = None

    @property
    def content_hash(self) -> str | None:
        if self.body is None:
            return None
        return hashlib.sha256(self.body).hexdigest()


def _probe_candidates(domain: str) -> list[str]:
    base = f"https://{domain}"
    return [f"{base}{path}" for path in _PROBE_PATHS]


async def _sweep_one_firm(
    fetcher: Fetcher,
    robots_cache: RobotsCache,
    user_agent: str,
    firm_id: str,
    info: dict,
) -> CareersOutcome:
    domain = info.get("domain")
    if not domain:
        return CareersOutcome(firm_id=firm_id, url=None, note="no domain -- nothing to sweep")

    robots = await robots_cache.get(domain)
    if not robots.crawlable():
        candidate_url = info.get("site_map_url") or _probe_candidates(domain)[0]
        return CareersOutcome(
            firm_id=firm_id,
            url=candidate_url,
            fetch_ok=False,
            note=f"host not crawlable (source_state={robots.source_state})",
        )

    site_map_url = info.get("site_map_url")
    if site_map_url:
        decision = robots.decision(site_map_url, user_agent)
        if decision == "disallowed":
            return CareersOutcome(
                firm_id=firm_id, url=site_map_url, fetch_ok=False,
                note="robots.txt disallows the careers page",
            )
        result = await fetcher.fetch(site_map_url, robots_decision=decision)
        return CareersOutcome(
            firm_id=firm_id, url=site_map_url, fetch_ok=result.fetch_ok, status=result.status,
            body=result.body, content_type_ok=result.content_type_ok, error=result.error,
        )

    # No known careers URL -- probe in order, stop at the first *confirmed*
    # page (any non-404 outcome). Exhausting every candidate at 404 is
    # itself a definitive answer worth recording.
    last: FetchResult | None = None
    last_url = _probe_candidates(domain)[-1]
    for url in _probe_candidates(domain):
        decision = robots.decision(url, user_agent)
        if decision == "disallowed":
            continue
        result = await fetcher.fetch(url, robots_decision=decision)
        last, last_url = result, url
        if result.fetch_ok and result.status != 404:
            return CareersOutcome(
                firm_id=firm_id, url=url, fetch_ok=result.fetch_ok, status=result.status,
                body=result.body, content_type_ok=result.content_type_ok, error=result.error,
            )
        if not result.fetch_ok:
            return CareersOutcome(
                firm_id=firm_id, url=url, fetch_ok=False, status=result.status, error=result.error,
            )
    if last is not None:
        return CareersOutcome(
            firm_id=firm_id, url=last_url, fetch_ok=last.fetch_ok, status=last.status,
            body=last.body, content_type_ok=last.content_type_ok, error=last.error,
        )
    return CareersOutcome(
        firm_id=firm_id, url=None, note="every careers probe path is disallowed by robots.txt"
    )


async def _sweep_all_firms(
    user_agent: str,
    candidates: dict[str, dict],
    max_concurrent_hosts: int,
    default_interval_s: float,
) -> tuple[dict[str, CareersOutcome], dict]:
    limiter = HostRateLimiter(default_interval_s=default_interval_s)
    block_tracker = HostBlockTracker()
    async with Fetcher(
        user_agent=user_agent, limiter=limiter, block_tracker=block_tracker
    ) as fetcher:
        robots_cache = RobotsCache(fetcher, user_agent)
        factories = {
            fid: functools.partial(_sweep_one_firm, fetcher, robots_cache, user_agent, fid, info)
            for fid, info in candidates.items()
        }
        outcomes = await gather_bounded(factories, max_concurrent_hosts)
        return outcomes, robots_cache.snapshot()


# ---------------------------------------------------------------------------
# Parsing: JSON-LD -> microdata/RDFa -> ATS embed -> HTML heuristic. The
# first layer with a hit wins for that page.
# ---------------------------------------------------------------------------


@dataclass
class ParsedCareers:
    method: str  # 'jsonld' | 'microdata' | 'ats_embed' | 'html' | 'none'
    postings: list[dict] = field(default_factory=list)


def is_excluded_board_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in _EXCLUDED_BOARD_HOSTS)


def collect_excluded_board_links(tree: lxml.html.HtmlElement) -> list[str]:
    """Board links we deliberately never follow -- recorded, not fetched."""
    seen: set[str] = set()
    links: list[str] = []
    for el in tree.iter("a"):
        href = el.get("href")
        if not href:
            continue
        host = urlsplit(href).hostname or ""
        if is_excluded_board_host(host) and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def detect_ats_embeds(tree: lxml.html.HtmlElement) -> list[tuple[str, str, str]]:
    """Deduplicated (platform, slug, src_url) triples from iframe/anchor
    src|href. Never fetched -- JA3 polls these slugs later."""
    hrefs: list[str] = []
    for el in tree.iter("iframe"):
        src = el.get("src")
        if src:
            hrefs.append(src)
    for el in tree.iter("a"):
        href = el.get("href")
        if href:
            hrefs.append(href)

    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for href in hrefs:
        for platform, pattern in _ATS_PATTERNS:
            m = pattern.search(href)
            if m:
                key = (platform, m.group(1))
                if key not in seen:
                    seen.add(key)
                    out.append((platform, m.group(1), href))
                break
    return out


def _stringify(value: object) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("name") or value.get("value")
    if value is None or value == "":
        return None
    return str(value)


def _strip_html(text: str) -> str:
    if "<" not in text:
        return text.strip()
    try:
        return lxml.html.fromstring(text).text_content().strip()
    except (lxml.etree.ParserError, ValueError):
        return text.strip()


def _parse_date(value: object) -> date | None:
    text = _stringify(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _location_to_text(loc: object) -> str | None:
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        addr = loc.get("address", loc)
        if isinstance(addr, list):
            addr = addr[0] if addr else {}
        if isinstance(addr, dict):
            parts = [p for p in (addr.get("addressLocality"), addr.get("addressRegion")) if p]
            if parts:
                return ", ".join(str(p) for p in parts)
        name = loc.get("name")
        if name:
            return str(name)
    return None


def _extract_apply_email(text: str | None) -> str | None:
    if not text:
        return None
    m = _EMAIL_RE.search(text)
    return m.group(0) if m else None


def _posting_from_schema_node(node: dict, outbound_links: list[str]) -> dict:
    """A JobPosting-shaped dict (JSON-LD node, or a microdata item's
    `properties`) -> raw_posting fields."""
    title = _stringify(node.get("title") or node.get("name")) or "Untitled posting"
    description_raw = node.get("description")
    description = _stringify(description_raw)
    body = _strip_html(description) if description else None
    raw_type = _stringify(node.get("@type") or node.get("type"))
    return {
        "title": title,
        "body": body,
        "board_posted_date": _parse_date(node.get("datePosted")),
        "employment_type": _stringify(node.get("employmentType")),
        "location_raw": _location_to_text(node.get("jobLocation")),
        "apply_email": _extract_apply_email(body),
        "outbound_links": outbound_links,
        "payload": {"parse_method": "schema", "raw_type": raw_type},
    }


def extract_jsonld_postings(html: str, url: str) -> list[dict]:
    try:
        data = extruct_extract(html, base_url=url, syntaxes=["json-ld"], errors="log")
    except Exception as exc:  # a malformed page must not stall the firm
        logger.info("ja1_careers: json-ld extraction failed for %s: %s", url, exc)
        return []
    nodes: list[dict] = []
    for item in data.get("json-ld", []):
        if not isinstance(item, dict):
            continue
        graph = item.get("@graph")
        candidates = graph if isinstance(graph, list) else [item]
        for node in candidates:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(isinstance(t, str) and t.endswith("JobPosting") for t in types):
                nodes.append(node)
    return nodes


def extract_microdata_postings(html: str, url: str) -> list[dict]:
    try:
        data = extruct_extract(html, base_url=url, syntaxes=["microdata", "rdfa"], errors="log")
    except Exception as exc:
        logger.info("ja1_careers: microdata/rdfa extraction failed for %s: %s", url, exc)
        return []
    nodes: list[dict] = []
    for syntax in ("microdata", "rdfa"):
        for item in data.get(syntax, []):
            item_type = item.get("type") or item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(isinstance(t, str) and t.endswith("JobPosting") for t in types):
                nodes.append(item.get("properties", item))
    return nodes


def html_heuristic_postings(tree: lxml.html.HtmlElement) -> list[dict]:
    """Lowest-confidence layer: a heading or list item whose text
    normalize_title() maps to a support role, in the presence of an
    apply/position/opening/career word nearby (here: in the same element's
    own text)."""
    seen: set[str] = set()
    out: list[dict] = []
    for el in tree.iter(*_HEADING_AND_LIST_TAGS):
        text = (el.text_content() or "").strip()
        if not text or len(text) > 200:
            continue
        role = normalize_title(text)
        if not role or not is_support_role(role):
            continue
        if not _JOB_CONTEXT_RE.search(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": text,
                "body": text,
                "board_posted_date": None,
                "employment_type": None,
                "location_raw": None,
                "apply_email": _extract_apply_email(text),
                "payload": {"parse_method": "html", "confidence": 0.4, "role": role},
            }
        )
    return out


def _posting_from_ats_embed(platform: str, slug: str, src_url: str) -> dict:
    return {
        "title": f"ATS listing ({platform})",
        "body": None,
        "board_posted_date": None,
        "employment_type": None,
        "location_raw": None,
        "apply_email": None,
        "ats_slug": slug,
        "payload": {"parse_method": "ats_embed", "ats_platform": platform, "embed_url": src_url},
    }


def parse_careers_page(html: str, url: str) -> ParsedCareers:
    if not html.strip():
        return ParsedCareers(method="none")

    try:
        tree = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        tree = None

    excluded_links = collect_excluded_board_links(tree) if tree is not None else []

    nodes = extract_jsonld_postings(html, url)
    if nodes:
        postings = [_posting_from_schema_node(n, excluded_links) for n in nodes]
        return ParsedCareers(method="jsonld", postings=postings)

    nodes = extract_microdata_postings(html, url)
    if nodes:
        postings = [_posting_from_schema_node(n, excluded_links) for n in nodes]
        return ParsedCareers(method="microdata", postings=postings)

    if tree is not None:
        embeds = detect_ats_embeds(tree)
        if embeds:
            postings = [
                _posting_from_ats_embed(platform, slug, src) for platform, slug, src in embeds
            ]
            for p in postings:
                p["outbound_links"] = excluded_links
            return ParsedCareers(method="ats_embed", postings=postings)

        heuristics = html_heuristic_postings(tree)
        if heuristics:
            for p in heuristics:
                p["outbound_links"] = excluded_links
            return ParsedCareers(method="html", postings=heuristics)

    return ParsedCareers(method="none")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _load_careers_candidates(conn: psycopg.Connection, firm_ids: list[str]) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, domain FROM firm WHERE id = ANY(%s)", (firm_ids,))
        domains = {str(r["id"]): r["domain"] for r in cur.fetchall()}

        cur.execute(
            "SELECT firm_id, url FROM site_map WHERE firm_id = ANY(%s) AND page_kind = 'careers' "
            "ORDER BY firm_id, url",
            (firm_ids,),
        )
        site_map_urls: dict[str, str] = {}
        for row in cur.fetchall():
            fid = str(row["firm_id"])
            site_map_urls.setdefault(fid, row["url"])

    return {
        fid: {"domain": domains.get(fid), "site_map_url": site_map_urls.get(fid)}
        for fid in firm_ids
    }


def _previous_successful_sweep(conn: psycopg.Connection, firm_id: str, url: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content_hash, postings_found FROM careers_sweep "
            "WHERE firm_id = %s AND url = %s AND fetch_ok = true "
            "ORDER BY swept_at DESC LIMIT 1",
            (firm_id, url),
        )
        return cur.fetchone()


def _insert_sweep(
    conn: psycopg.Connection,
    firm_id: str,
    url: str,
    *,
    fetch_ok: bool,
    status_code: int | None,
    postings_found: int | None,
    content_hash: str | None,
    parse_method: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO careers_sweep (firm_id, url, fetch_ok, status_code, postings_found,
                                        content_hash, parse_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (firm_id, url, fetch_ok, status_code, postings_found, content_hash, parse_method),
        )


def _write_raw_postings(
    conn: psycopg.Connection,
    firm_id: str,
    page_url: str,
    content_hash: str | None,
    parsed: ParsedCareers,
) -> int:
    n = 0
    with conn.cursor() as cur:
        for posting in parsed.postings:
            title = posting.get("title") or "Untitled posting"
            date_posted = posting.get("board_posted_date")
            digest = hashlib.sha1(
                f"{title}{date_posted or ''}".encode()
            ).hexdigest()[:12]
            source_key = f"{page_url}#{digest}"
            payload = dict(posting.get("payload") or {})
            payload.setdefault("parse_method", parsed.method)
            cur.execute(
                """
                INSERT INTO raw_posting (source, source_key, source_url, firm_id, title, body,
                                          location_raw, apply_email, outbound_links, ats_slug,
                                          employment_type, board_posted_date, fetch_ok,
                                          content_hash, payload)
                VALUES ('careers', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)
                ON CONFLICT (source, source_key, fetched_at) DO NOTHING
                """,
                (
                    source_key,
                    page_url,
                    firm_id,
                    title,
                    posting.get("body"),
                    posting.get("location_raw"),
                    posting.get("apply_email"),
                    posting.get("outbound_links") or [],
                    posting.get("ats_slug"),
                    posting.get("employment_type"),
                    date_posted,
                    content_hash,
                    Jsonb(payload),
                ),
            )
            n += 1
    return n


def _write_sweep(conn: psycopg.Connection, firm_id: str, outcome: CareersOutcome) -> str:
    if outcome.url is None:
        return "no_url"

    if not outcome.fetch_ok:
        _insert_sweep(
            conn, firm_id, outcome.url, fetch_ok=False, status_code=outcome.status,
            postings_found=None, content_hash=None, parse_method=None,
        )
        return "fetch_failed"

    content_hash = outcome.content_hash

    if outcome.status == 404:
        _insert_sweep(
            conn, firm_id, outcome.url, fetch_ok=True, status_code=404, postings_found=0,
            content_hash=content_hash, parse_method="none",
        )
        return "not_found"

    prev = _previous_successful_sweep(conn, firm_id, outcome.url)
    if prev is not None and content_hash is not None and prev["content_hash"] == content_hash:
        _insert_sweep(
            conn, firm_id, outcome.url, fetch_ok=True, status_code=outcome.status,
            postings_found=prev["postings_found"], content_hash=content_hash, parse_method="none",
        )
        return "unchanged"

    html = outcome.body.decode("utf-8", errors="replace") if outcome.body else ""
    parsed = (
        parse_careers_page(html, outcome.url) if outcome.content_type_ok else ParsedCareers("none")
    )
    n = _write_raw_postings(conn, firm_id, outcome.url, content_hash, parsed)
    _insert_sweep(
        conn, firm_id, outcome.url, fetch_ok=True, status_code=outcome.status, postings_found=n,
        content_hash=content_hash, parse_method=parsed.method,
    )
    return "parsed"


@component(
    "ja1_careers", "JA", "Careers page watcher: fetch, parse JobPosting signals into raw_posting"
)
def run(ctx: RunContext, **opts: object) -> RunResult:
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),
        limit=opts.get("limit"),
    )
    if not firm_ids:
        result.notes.append("no firms selected")
        return result

    today = date.today().isoformat()
    hashes = {fid: hashlib.sha256(f"ja1_careers:{today}".encode()).hexdigest() for fid in firm_ids}
    done = already_done(ctx.conn, "ja1_careers", hashes)
    pending_ids = [fid for fid in firm_ids if fid not in done]
    result.skipped += len(done)

    if not pending_ids:
        result.notes.append(f"all {len(firm_ids)} firm(s) already swept today ({today})")
        return result

    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append(
            f"live=0: would sweep {len(pending_ids)} firm(s) ({len(done)} already done today); "
            "no requests made"
        )
        return result

    if not ctx.settings.user_agent.strip():
        raise EmptyUserAgentError(
            "refusing to fetch: settings.user_agent is empty -- set LGE_USER_AGENT"
        )

    candidates = _load_careers_candidates(ctx.conn, pending_ids)
    max_concurrent_hosts = int(
        opts.get("max_concurrent_hosts", rate_defaults()["max_concurrent_hosts"])
    )
    default_interval_s = float(
        opts.get("default_interval_s", rate_defaults()["default_interval_s"])
    )

    outcomes, robots_seen = asyncio.run(
        _sweep_all_firms(
            ctx.settings.user_agent, candidates, max_concurrent_hosts, default_interval_s
        )
    )

    for policy in robots_seen.values():
        persist_robots_policy(ctx.conn, policy)

    for firm_id, outcome in outcomes.items():
        input_hash = hashes[firm_id]
        with ctx.once("ja1_careers", firm_id, input_hash) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            status = _write_sweep(ctx.conn, firm_id, outcome)
            result.processed += 1
            if status == "fetch_failed":
                result.notes.append(f"{firm_id}: careers sweep fetch failed ({outcome.error})")
            elif outcome.note:
                result.notes.append(f"{firm_id}: {outcome.note}")
        ctx.checkpoint()

    return result
