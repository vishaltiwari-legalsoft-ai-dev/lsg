"""P1 — site mapper.

robots.txt -> sitemap(s) -> classify by page_kind -> add path probes for
missing kinds -> per-firm caps -> `site_map` (sql/030_profile.sql). Also
advances the firm's open lead DISCOVERED -> PROFILING / NO_WEB.

No component reads another component's output directly: this one reads only
firm.domain and the open lead from the store; robots state is fetched and
persisted here, not borrowed from a previous run's source_registry row (see
lge/fetch/robots.py).

Selection: `--opt firm_ids_file=<path>` (no domain filter -- this is how a
domainless firm reaches the NO_WEB path) or `--opt limit=N` (firms with an
open lead and a domain). Live network gate: `settings.live` or `--opt
live=1`; otherwise this prints the plan and fetches nothing.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import lxml.html
import psycopg
from lxml import etree

from lge.db import lifecycle
from lge.fetch.client import EmptyUserAgentError, Fetcher, HostBlockTracker
from lge.fetch.config import kind_cap, load_crawl_config, rate_defaults, wanted_kinds
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.ratelimit import HostRateLimiter
from lge.fetch.robots import RobotsCache, RobotsPolicy
from lge.fetch.robots import persist as persist_robots_policy
from lge.fetch.selection import already_done, select_firm_ids
from lge.norm import map_practice_label
from lge.registry import RunContext, RunResult, component

logger = logging.getLogger("lge.planes.p1")

# Which kinds are mapped, and in what order, is config/crawl.yml's `caps`
# (lge.fetch.config.wanted_kinds) -- there is no list of kinds in this file.


@functools.lru_cache(maxsize=1)
def _compiled_page_kinds() -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    cfg = load_crawl_config()
    out = []
    for kind, patterns in cfg["page_kinds"].items():
        out.append((kind, tuple(re.compile(p, re.IGNORECASE) for p in patterns)))
    return tuple(out)


def classify_page_kind(url: str) -> str:
    """URL path -> page_kind, per config/crawl.yml. 'other' on no match."""
    path = urlsplit(url).path or "/"
    for kind, patterns in _compiled_page_kinds():
        if any(p.search(path) for p in patterns):
            return kind
    return "other"


def probe_urls(domain: str) -> dict[str, list[str]]:
    """kind -> candidate probe URLs (unfetched), from config/crawl.yml."""
    cfg = load_crawl_config()
    base = f"https://{domain}"
    return {
        kind: [urljoin(base + "/", path.lstrip("/")) for path in paths]
        for kind, paths in cfg["probe_paths"].items()
        if kind_cap(kind) > 0  # a kind the engine does not read is not probed for
    }


def _caps() -> dict[str, int]:
    return load_crawl_config()["caps"]


def _sitemap_cap() -> int:
    return load_crawl_config()["sitemap"]["max_urls_read"]


# --------------------------------------------------------------------------
# Site-map assembly: one firm's discovered URL set, capped, before any P2
# fetch happens. `note` records what (if anything) went wrong reaching the
# host, for RunResult.notes.
# --------------------------------------------------------------------------


# Bump whenever the mapper's own logic changes (link patterns, probe paths, caps):
# it joins the domain in the idempotency key, so already-mapped firms are mapped
# again without the domain having to change. v2: hiring anchors and paths read off
# real homepages (D-026). v3: locations, testimonials and news kinds; caps to 30.
# v4: six kinds, twelve pages -- the map is what config/crawl.yml `caps` says (D-044).
MAPPER_VERSION = "4"


def mapper_input_hash(domain: str | None) -> str:
    return hashlib.sha256(f"{domain or ''}|{MAPPER_VERSION}".encode()).hexdigest()


@dataclass
class SiteMapOutcome:
    firm_id: str
    domain: str | None
    robots_state: str | None = None
    crawlable: bool = False
    # False when the host could not be judged this run: robots.txt blocked at the
    # edge or unreachable, so no policy was read. Nothing is written, the lead
    # stays DISCOVERED and the next run tries again. True for every verdict --
    # mapped, no domain, or a published rule closing the site.
    conclusive: bool = True
    urls: list[tuple[str, str, str]] = field(default_factory=list)  # (url, kind, via)
    note: str | None = None

    def input_hash(self) -> str:
        return mapper_input_hash(self.domain)


_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _parse_sitemap_xml(body: bytes) -> tuple[list[str], list[str]]:
    """Returns (url_locs, sub_sitemap_locs). A <sitemapindex> yields only
    sub_sitemap_locs; a <urlset> yields only url_locs. Malformed XML yields
    two empty lists rather than raising -- one bad sitemap must not stall
    the firm."""
    try:
        root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False))
    except etree.XMLSyntaxError:
        return [], []
    tag = etree.QName(root.tag).localname
    if tag == "sitemapindex":
        locs = [
            el.text.strip()
            for el in root.findall(".//sm:sitemap/sm:loc", _SITEMAP_NS)
            if el.text and el.text.strip()
        ]
        return [], locs
    if tag == "urlset":
        locs = [
            el.text.strip()
            for el in root.findall(".//sm:url/sm:loc", _SITEMAP_NS)
            if el.text and el.text.strip()
        ]
        return locs, []
    return [], []


async def _discover_sitemap_urls(
    fetcher: Fetcher, domain: str, robots: RobotsPolicy
) -> list[str]:
    """Sitemap: lines from robots.txt, else /sitemap.xml, else
    /sitemap_index.xml. Follows one level of index. Capped at
    sitemap.max_urls_read total <loc> entries read."""
    cap = _sitemap_cap()
    base = f"https://{domain}"
    candidates = list(robots.sitemap_urls) or [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"]

    urls: list[str] = []
    for candidate in candidates:
        if len(urls) >= cap:
            break
        result = await fetcher.fetch(candidate)
        if not result.fetch_ok or result.status != 200 or not result.body:
            continue
        top_urls, sub_sitemaps = _parse_sitemap_xml(result.body)
        urls.extend(top_urls[: cap - len(urls)])
        if len(urls) >= cap:
            break
        # Follow exactly one level of index -- do not recurse into whatever
        # the sub-sitemaps themselves claim to be.
        for sub in sub_sitemaps:
            if len(urls) >= cap:
                break
            sub_result = await fetcher.fetch(sub)
            if not sub_result.fetch_ok or sub_result.status != 200 or not sub_result.body:
                continue
            sub_urls, _ignored_deeper_index = _parse_sitemap_xml(sub_result.body)
            urls.extend(sub_urls[: cap - len(urls)])
        if urls:
            break  # a sitemap resolved -- don't also try the fallback candidates
    return urls[:cap]


# Anchor-text patterns for homepage link discovery. Small-firm sites rarely use the
# standard paths the probes guess (/our-team, /practice-areas) and many publish no
# sitemap; the live probe found only the homepage on sites whose nav plainly linked
# "Our Attorneys" and "Car Accidents". The homepage's own navigation is the most
# reliable map of a small site, so it is read before any blind probe.
#
# Careers anchors come from real homepages (D-026): "B|K is Hiring a Personal Injury
# Paralegal" was a posting linked straight from the homepage and was missed; "Join
# Us" and a bare "Employment" nav label were missed too. The traps are practice
# pages and blog posts: "Employment & Wage Litigation", "workers injured on the
# job", "Cost of Hiring a Motorcycle Accident Lawyer" -- so "job" only counts in
# its plural or listing forms, "hiring" only with a subject, and "employment" only
# alone or with "opportunities".
_ANCHOR_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("careers", re.compile(
        r"\b(?:careers?|jobs|job\s+(?:openings?|opportunit\w*|listings?)"
        r"|join\s+(?:our|the)\s+(?:team|firm)|join\s+us|employment\s+opportunit\w*"
        r"|(?:we'?re|we\s+are|is|now)\s+hiring|work\s+(?:with|for)\s+us"
        r"|open\s+positions?|positions?\s+available)\b"
        r"|^\s*employment\s*$", re.I)),
    ("attorneys", re.compile(
        r"\b(?:attorneys?|lawyers?|our (?:legal )?team"
        r"|meet (?:the|our) (?:team|attorneys|lawyers)|our people)\b", re.I)),
    ("locations", re.compile(
        r"\b(?:locations?|offices?|our offices|office locations?|areas we serve"
        r"|service areas?)\b", re.I)),
    ("testimonials", re.compile(
        r"\b(?:testimonials?|reviews?|client reviews|what (?:our )?clients say"
        r"|success stories|case results?|results|verdicts?(?: (?:&|and) settlements)?)\b",
        re.I)),
    ("news", re.compile(
        r"\b(?:blog|news|articles?|press|media|insights|firm news|updates|in the news)\b",
        re.I)),
    ("practice", re.compile(
        r"\b(?:practice areas?|areas of practice|what we do|our services|cases we handle"
        r"|practice)\b", re.I)),
    ("about", re.compile(r"\b(?:about|our firm|who we are|why choose)\b", re.I)),
    ("fees", re.compile(r"\b(?:fees?|pricing|costs?)\b", re.I)),
    ("contact", re.compile(r"\b(?:contact|free consultation)\b", re.I)),
)


def classify_link(url: str, anchor_text: str) -> str:
    """page_kind for a homepage link: URL path first (config/crawl.yml), then anchor
    text, then practice-specific pages ("Car Accidents", "/truck-accident-lawyer/")
    via the practice vocabulary. 'other' when nothing matches."""
    kind = classify_page_kind(url)
    if kind != "other":
        return kind
    text = " ".join((anchor_text or "").split())
    if text:
        for k, pattern in _ANCHOR_KINDS:
            if pattern.search(text):
                return k
        if map_practice_label(text):
            return "practice"
    slug_words = urlsplit(url).path.replace("-", " ").replace("_", " ").replace("/", " ")
    if map_practice_label(slug_words):
        return "practice"
    return "other"


def extract_homepage_links(html: bytes, base_url: str, domain: str) -> list[tuple[str, str]]:
    """(absolute_url, kind) for same-site links on the homepage, deduplicated, in
    document order. Fragments and query strings are dropped; off-site, mailto:,
    tel: and file links are ignored."""
    try:
        doc = lxml.html.fromstring(html)
    except (etree.ParserError, ValueError):
        return []
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in doc.iter("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0].split("?", 1)[0]
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            continue
        host = parts.hostname or ""
        if not (host == domain or host.endswith("." + domain)):
            continue
        if re.search(r"\.(?:pdf|jpe?g|png|gif|svg|webp|mp4|zip|docx?)$", parts.path, re.I):
            continue
        normalised = f"https://{host}{parts.path or '/'}"
        if normalised in seen or (parts.path or "/") == "/":
            continue
        seen.add(normalised)
        kind = classify_link(normalised, a.text_content())
        if kind != "other":
            out.append((normalised, kind))
    return out


def _apply_caps(by_kind: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str, str]]:
    """(url, via) grouped by kind -> capped, ordered (url, kind, via) list.
    Sitemap-discovered URLs are preferred over probes within a kind; ties
    break alphabetically for deterministic output."""
    caps = _caps()
    out: list[tuple[str, str, str]] = []

    def take(kind: str, limit: int) -> None:
        nonlocal out
        if len(out) >= caps["total"]:
            return
        rank = {"sitemap": 0, "link": 1, "probe": 2}
        entries = sorted(by_kind.get(kind, []), key=lambda e: (rank.get(e[1], 3), e[0]))
        room = caps["total"] - len(out)
        for url, via in entries[: min(limit, room)]:
            out.append((url, kind, via))

    for kind in wanted_kinds():  # config order: home first
        take(kind, kind_cap(kind))
    return out


async def _map_one_firm(
    fetcher: Fetcher, robots_cache: RobotsCache, user_agent: str, firm_id: str, domain: str | None
) -> SiteMapOutcome:
    outcome = SiteMapOutcome(firm_id=firm_id, domain=domain)
    if not domain:
        outcome.note = "no domain -- NO_WEB"
        return outcome

    host = domain
    robots = await robots_cache.get(host)
    outcome.robots_state = robots.source_state

    if not robots.crawlable():
        if robots.source_state == "policy_closed":
            outcome.note = "robots.txt closes the site to our user agent -- NO_WEB"
        else:
            # edge_blocked / unreachable: no policy was read, so there is no verdict.
            # The live probe parked 38 firms as NO_WEB on this path; one of them
            # answered 200 the next day. Draw no conclusion, retry next run.
            outcome.conclusive = False
            outcome.note = (
                f"host not judged this run (source_state={robots.source_state}) -- retry"
            )
        return outcome
    outcome.crawlable = True

    by_kind: dict[str, list[tuple[str, str]]] = {}
    # A slow host cannot be mapped within a run (sitemap + homepage would be 20
    # minutes at 600s): probes only, and P2 fetches what fits its budget (D-026).
    if robots.slow:
        outcome.note = f"slow host (Crawl-delay {robots.crawl_delay_s:g}s) -- probes only"
        sitemap_urls: list[str] = []
    else:
        sitemap_urls = await _discover_sitemap_urls(fetcher, domain, robots)
    for url in sitemap_urls:
        decision = robots.decision(url, user_agent)
        if decision == "disallowed":
            continue
        kind = classify_page_kind(url)
        by_kind.setdefault(kind, []).append((url, "sitemap"))

    # Home is not always listed in a sitemap -- ensure a candidate exists.
    if "home" not in by_kind:
        by_kind["home"] = [(f"https://{domain}/", "probe")]

    # Link discovery: read the homepage's own navigation before any blind probe,
    # whenever the sitemap left a content kind uncovered.
    wanted = ("practice", "attorneys", "team", "about", "careers", "fees",
              "locations", "testimonials", "news")
    if not robots.slow and any(not by_kind.get(k) for k in wanted):
        home_url = f"https://{domain}/"
        if robots.decision(home_url, user_agent) != "disallowed":
            home = await fetcher.fetch(home_url)
            if home.fetch_ok and home.status == 200 and home.body:
                base = home.final_url or home_url
                for url, kind in extract_homepage_links(home.body, base, domain):
                    if by_kind.get(kind) and any(v == "sitemap" for _u, v in by_kind[kind]):
                        continue  # the sitemap already covers this kind
                    if robots.decision(url, user_agent) == "disallowed":
                        continue
                    by_kind.setdefault(kind, []).append((url, "link"))

    # Path probes for any kind the sitemap didn't cover.
    for kind, candidates in probe_urls(domain).items():
        if by_kind.get(kind):
            continue
        allowed = [
            url for url in candidates if robots.decision(url, user_agent) != "disallowed"
        ]
        if allowed:
            by_kind[kind] = [(url, "probe") for url in allowed]

    outcome.urls = _apply_caps(by_kind)
    if not outcome.urls:
        outcome.note = "robots disallows every path we need -- treated as policy_closed"
        outcome.crawlable = False
    return outcome


async def _map_all_firms(
    user_agent: str,
    firms: dict[str, str | None],
    max_concurrent_hosts: int,
    default_interval_s: float,
) -> tuple[dict[str, SiteMapOutcome], dict[str, RobotsPolicy]]:
    limiter = HostRateLimiter(default_interval_s=default_interval_s)
    block_tracker = HostBlockTracker()
    async with Fetcher(
        user_agent=user_agent, limiter=limiter, block_tracker=block_tracker
    ) as fetcher:
        robots_cache = RobotsCache(fetcher, user_agent)
        factories = {
            fid: functools.partial(_map_one_firm, fetcher, robots_cache, user_agent, fid, dom)
            for fid, dom in firms.items()
        }
        outcomes = await gather_bounded(factories, max_concurrent_hosts)
        return outcomes, robots_cache.snapshot()


def _load_firm_domains(conn: psycopg.Connection, firm_ids: list[str]) -> dict[str, str | None]:
    if not firm_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, domain FROM firm WHERE id = ANY(%s)", (firm_ids,))
        rows = {str(r["id"]): r["domain"] for r in cur.fetchall()}
    return {fid: rows.get(fid) for fid in firm_ids}


def _write_site_map(
    conn: psycopg.Connection, firm_id: str, urls: list[tuple[str, str, str]]
) -> None:
    if not urls:
        return
    with conn.cursor() as cur:
        for url, kind, via in urls:
            cur.execute(
                """
                INSERT INTO site_map (firm_id, url, page_kind, discovered_via)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (firm_id, url) DO NOTHING
                """,
                (firm_id, url, kind, via),
            )


def _advance_lead(conn: psycopg.Connection, firm_id: str, *, crawlable: bool) -> None:
    to_state = "PROFILING" if crawlable else "NO_WEB"
    with lifecycle(conn, "p1_site_map"), conn.cursor() as cur:
        cur.execute(
            "UPDATE lead SET state = %s WHERE firm_id = %s AND closed_at IS NULL "
            "AND state = 'DISCOVERED'",
            (to_state, firm_id),
        )


@component("p1_site_map", "P", "Site mapper: robots -> sitemap -> page-kind classification")
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

    domains = _load_firm_domains(ctx.conn, firm_ids)
    hashes = {fid: mapper_input_hash(domains.get(fid)) for fid in firm_ids}
    done = already_done(ctx.conn, "p1_site_map", hashes)
    pending = {fid: domains[fid] for fid in firm_ids if fid not in done}
    result.skipped += len(done)

    if not pending:
        result.notes.append(f"all {len(firm_ids)} firm(s) already mapped for their current domain")
        return result

    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append(
            f"live=0: would map {len(pending)} firm(s) ({len(done)} already done); no requests made"
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
    outcomes, robots_seen = asyncio.run(
        _map_all_firms(ctx.settings.user_agent, pending, max_concurrent_hosts, default_interval_s)
    )

    for policy in robots_seen.values():
        persist_robots_policy(ctx.conn, policy)

    for firm_id, outcome in outcomes.items():
        if not outcome.conclusive:
            # Not recorded as done on purpose: the next run must try the host again.
            result.skipped += 1
            result.notes.append(f"{firm_id}: {outcome.note}")
            continue
        input_hash = outcome.input_hash()
        with ctx.once("p1_site_map", firm_id, input_hash) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            _write_site_map(ctx.conn, firm_id, outcome.urls)
            _advance_lead(ctx.conn, firm_id, crawlable=outcome.crawlable)
            result.processed += 1
            if outcome.note:
                result.notes.append(f"{firm_id}: {outcome.note}")
        ctx.checkpoint()

    return result
