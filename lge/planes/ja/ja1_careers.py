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
from lge.fetch.decode import decode_html
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.ratelimit import HostRateLimiter
from lge.fetch.robots import RobotsCache
from lge.fetch.robots import persist as persist_robots_policy
from lge.fetch.selection import already_done, select_firm_ids
from lge.registry import RunContext, RunResult, component

logger = logging.getLogger("lge.planes.ja1")

# JA1's own probe list (order matters -- first non-404 wins), distinct from
# P1's page-kind probes: adds /join-our-team per the task brief.
# Bare "/employment" is NOT probed: on an employment-law firm it is a practice page
# ("Employment Law — wrongful termination…"), which the probe mis-read as careers.
_PROBE_PATHS = ("/careers", "/jobs", "/employment-opportunities", "/join-our-team")

# Bump whenever parse_careers_page can produce different postings for the same HTML.
# careers_sweep.parser_version joins the content hash in the skip-unchanged rule, so a
# parser fix re-parses pages already swept (v2: page-level job context, soft-404s;
# v3: a page that is itself the posting; v4: scripts and styles are not page text).
PARSER_VERSION = "4"

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
    final_url: str | None = None
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


# Where a site sends a URL it does not have: its root, or an error page that still
# answers 200. Seen in the probe: /404, /404?aspxerrorpath=..., index.php?error=404.
_NOT_FOUND_URL_RE = re.compile(
    r"(?:^|/)(?:404|not-?found|page-not-found|error)(?:[/.?]|$)|(?:^|[?&])error=404|aspxerrorpath=",
    re.I,
)


def redirected_away(url: str | None, final_url: str | None) -> bool:
    """A careers URL that answered 200 only because the site redirected it to its
    homepage (this host or another) or to a "not found" page. The live probe counted
    14 of 31 such pages as careers pages -- the firm has no careers page at that
    URL, so the probe cascade should keep going (D-026)."""
    if not url or not final_url:
        return False
    requested = urlsplit(url).path.rstrip("/")
    landed = urlsplit(final_url)
    landed_path = landed.path.rstrip("/")
    if not requested:
        return False
    if not landed_path:
        return True
    landed_ref = landed_path + (f"?{landed.query}" if landed.query else "")
    return bool(_NOT_FOUND_URL_RE.search(landed_ref))


async def _sweep_one_firm(
    fetcher: Fetcher,
    robots_cache: RobotsCache,
    user_agent: str,
    firm_id: str,
    info: dict,
) -> list[CareersOutcome]:
    """Every sweep made for one firm this run: one per found careers URL, or the
    single outcome of the probe cascade when the map holds no found URL."""
    domain = info.get("domain")
    if not domain:
        return [CareersOutcome(firm_id=firm_id, url=None, note="no domain -- nothing to sweep")]

    robots = await robots_cache.get(domain)
    found: list[str] = list(info.get("site_map_urls") or [])
    if robots.slow:
        found = found[:1]  # one request is all a 600s Crawl-delay affords this run
    if not robots.crawlable():
        candidate_url = found[0] if found else _probe_candidates(domain)[0]
        return [
            CareersOutcome(
                firm_id=firm_id,
                url=candidate_url,
                fetch_ok=False,
                note=f"host not crawlable (source_state={robots.source_state})",
            )
        ]

    if found:
        outcomes: list[CareersOutcome] = []
        for url in found:
            decision = robots.decision(url, user_agent)
            if decision == "disallowed":
                outcomes.append(
                    CareersOutcome(
                        firm_id=firm_id, url=url, fetch_ok=False,
                        note="robots.txt disallows the careers page",
                    )
                )
                continue
            result = await fetcher.fetch(url, robots_decision=decision)
            outcomes.append(
                CareersOutcome(
                    firm_id=firm_id, url=url, fetch_ok=result.fetch_ok, status=result.status,
                    final_url=result.final_url, body=result.body,
                    content_type_ok=result.content_type_ok, error=result.error,
                )
            )
        return outcomes

    # No found careers URL -- probe in order, stop at the first *confirmed*
    # page (any non-404 outcome that was not redirected away). Exhausting every
    # candidate at 404 is itself a definitive answer worth recording.
    last: FetchResult | None = None
    candidates = _probe_candidates(domain)[:1] if robots.slow else _probe_candidates(domain)
    last_url = candidates[-1]
    for url in candidates:
        decision = robots.decision(url, user_agent)
        if decision == "disallowed":
            continue
        result = await fetcher.fetch(url, robots_decision=decision)
        last, last_url = result, url
        if (
            result.fetch_ok
            and result.status != 404
            and not redirected_away(url, result.final_url)
        ):
            return [
                CareersOutcome(
                    firm_id=firm_id, url=url, fetch_ok=result.fetch_ok, status=result.status,
                    final_url=result.final_url, body=result.body,
                    content_type_ok=result.content_type_ok, error=result.error,
                )
            ]
        if not result.fetch_ok:
            return [
                CareersOutcome(
                    firm_id=firm_id, url=url, fetch_ok=False, status=result.status,
                    error=result.error,
                )
            ]
    if last is not None:
        return [
            CareersOutcome(
                firm_id=firm_id, url=last_url, fetch_ok=last.fetch_ok, status=last.status,
                final_url=last.final_url, body=last.body,
                content_type_ok=last.content_type_ok, error=last.error,
            )
        ]
    return [
        CareersOutcome(
            firm_id=firm_id, url=None, note="every careers probe path is disallowed by robots.txt"
        )
    ]


async def _sweep_all_firms(
    user_agent: str,
    candidates: dict[str, dict],
    max_concurrent_hosts: int,
    default_interval_s: float,
) -> tuple[dict[str, list[CareersOutcome]], dict]:
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


# A careers page that is ACTUALLY listing jobs says so once, in a section title or
# intro ("Employment Opportunities", "Open positions", "We're hiring") and then lists
# the roles as plain headings. v1 demanded the job word inside each heading, which
# missed Dressie Law Firm's three h3 roles ("Case Manager", "Front Desk Coordinator").
_PAGE_JOB_CONTEXT_RE = re.compile(
    r"\b(?:(?:employment|career|job)\s+opportunit\w*|open\s+positions?|current\s+"
    r"(?:openings|opportunities|positions|vacancies)|job\s+openings|we'?re\s+hiring"
    r"|now\s+hiring|join\s+(?:our|the)\s+team)\b",
    re.IGNORECASE,
)
_SECTION_HEADINGS = ("h2", "h3", "h4", "h5")
# A page that IS the posting rather than a list of them: butlerfirm.com's h1 "We are
# Hiring a Paralegal" under the title "B|K is Hiring a Personal Injury Paralegal".
# Nothing in it is a heading or list item naming a role, so v2 found nothing. The
# announcing phrase names the role; its object is the posting (v3). A subject is
# required ("we are", "is", "now") so "Hiring a car accident lawyer: what to expect"
# blog titles never match.
_SINGLE_POSTING_RE = re.compile(
    r"\b(?:we(?:'re|\s+are)|is|now)\s+hiring\b[:\s]*(?:(?:a|an|for|our\s+next)\s+)?"
    r"(?P<role>[A-Za-z][A-Za-z /&-]{2,60}?)\s*(?:$|[.!?,(|]|\s[-–—]\s|\s+(?:in|at|for)\s)",
    re.IGNORECASE,
)
_SOFT_404_RE = re.compile(r"\b(?:page\s+(?:you\s+were\s+looking\s+for\s+)?(?:could\s+not|"
                          r"cannot|can't)\s+be\s+found|page\s+not\s+found|error\s+404|404\s+error"
                          r"|^\s*404\b)", re.IGNORECASE | re.MULTILINE)


def is_soft_404(tree: lxml.html.HtmlElement) -> bool:
    """A 200 response whose content is an error page. Short pages only, so a long
    article that merely mentions a 404 is never discarded."""
    text = " ".join((tree.text_content() or "").split())
    return len(text.split()) < 250 and bool(_SOFT_404_RE.search(text))


def _section_text(heading: lxml.html.HtmlElement, limit: int = 3000) -> str:
    """The text under a heading up to the next heading of the same or higher level."""
    level = int(heading.tag[1]) if heading.tag[1:].isdigit() else 6
    parts: list[str] = []
    for sib in heading.itersiblings():
        tag = sib.tag if isinstance(sib.tag, str) else ""
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit() and int(tag[1]) <= level:
            break
        parts.append(sib.text_content() or "")
        if sum(len(p) for p in parts) > limit:
            break
    return " ".join(" ".join(parts).split())[:limit]


def visible_text(el: lxml.html.HtmlElement) -> str:
    """The element's text with a space between text nodes, so "<h1>Paralegal</h1>
    <p>Butler Kahn…" does not read "ParalegalButler Kahn" (text_content() glues
    adjacent elements when the HTML has no whitespace between them)."""
    return " ".join(" ".join(el.itertext()).split())


def single_posting_from_page(tree: lxml.html.HtmlElement, page_text: str) -> dict | None:
    """The one posting a page announces in its h1 or <title> ("We are Hiring a
    Paralegal"), or None. Only support roles: "Is hiring a lawyer worth it?" names
    an attorney and is an article."""
    candidates = [visible_text(h) for h in tree.iter("h1")]
    title = " ".join((tree.findtext(".//title") or "").split())
    if title:
        candidates.append(re.split(r"\s[-–—|]\s", title)[0])  # drop the " - Site Name" suffix
    for text in candidates:
        m = _SINGLE_POSTING_RE.search(text)
        if not m:
            continue
        role_text = m.group("role").strip()
        role = normalize_title(role_text)
        if not role or not is_support_role(role):
            continue
        # The body starts where the announcement does, not at the nav bar, so the
        # first sentence (the quote) is the firm's own words about the role.
        start = page_text.find(text)
        body = page_text[start if start >= 0 else 0 :][:3000]
        return {
            "title": role_text,
            "body": body,
            "board_posted_date": None,
            "employment_type": None,
            "location_raw": None,
            "apply_email": _extract_apply_email(page_text),
            "payload": {
                "parse_method": "html",
                "confidence": 0.6,
                "role": role,
                "page_context": True,
                "single_posting": True,
            },
        }
    return None


def html_heuristic_postings(tree: lxml.html.HtmlElement) -> list[dict]:
    """Lowest-confidence layer (after JSON-LD, microdata and ATS embeds).

    Page-level context: when the page itself announces openings, every section
    heading that normalize_title() maps to a role is a posting, with the text under
    the heading as its body (support AND attorney roles are recorded — JA6 rejects
    non-support roles with a reason, keeping the record). Without page context, the
    v1 rule stands: the job word must be inside the heading or list item itself.
    A page that is itself one posting is read from its h1/title (v3).
    """
    page_text = visible_text(tree)
    page_context = bool(_PAGE_JOB_CONTEXT_RE.search(page_text))
    page_email = _extract_apply_email(page_text)
    seen: set[str] = set()
    out: list[dict] = []
    single = single_posting_from_page(tree, page_text)
    if single is not None:
        seen.add(single["title"].lower())
        out.append(single)
    for el in tree.iter(*_HEADING_AND_LIST_TAGS):
        text = " ".join((el.text_content() or "").split())
        if not text or len(text) > 200:
            continue
        role = normalize_title(text)
        if not role:
            continue
        # Section headings under a page that announces openings: any role counts.
        # List items (and headings without page context) keep the strict v1 rule —
        # under page context a qualification bullet like "Experience as a paralegal
        # preferred" would otherwise become a false posting.
        by_context = page_context and el.tag in _SECTION_HEADINGS and len(text) <= 120
        if not by_context and (not is_support_role(role) or not _JOB_CONTEXT_RE.search(text)):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        body = _section_text(el) if by_context else text
        out.append(
            {
                "title": text,
                "body": body or text,
                "board_posted_date": None,
                "employment_type": None,
                "location_raw": None,
                "apply_email": _extract_apply_email(body) or page_email,
                "payload": {
                    "parse_method": "html",
                    "confidence": 0.6 if by_context else 0.4,
                    "role": role,
                    "page_context": page_context,
                },
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

    if tree is not None:
        # Invisible text is not page text: butlerfirm.com's posting body came
        # back as "async function cache(e,t){...}" and that became the quote (v4).
        for el in tree.xpath("//script|//style|//noscript|//template|//svg"):
            el.drop_tree()

    if tree is not None and is_soft_404(tree):
        return ParsedCareers(method="soft_404")

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


# Careers URLs the site itself published (sitemap) or linked (homepage nav) are swept,
# up to this many per firm -- a careers section can list its openings on sub-pages.
_MAX_FOUND_URLS = 3


def _load_careers_candidates(conn: psycopg.Connection, firm_ids: list[str]) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, domain FROM firm WHERE id = ANY(%s)", (firm_ids,))
        domains = {str(r["id"]): r["domain"] for r in cur.fetchall()}

        cur.execute(
            "SELECT firm_id, url, discovered_via FROM site_map "
            "WHERE firm_id = ANY(%s) AND page_kind = 'careers' ORDER BY firm_id, url",
            (firm_ids,),
        )
        found: dict[str, list[str]] = {}
        for row in cur.fetchall():
            # A probe row is the same guess the cascade makes, and the cascade tries
            # every path in turn. Trusting one guess from the map meant the
            # alphabetically-first "/careers" beat a real posting URL the sitemap
            # published, and a 404 on it ended the search (D-026).
            if row["discovered_via"] == "probe":
                continue
            found.setdefault(str(row["firm_id"]), []).append(row["url"])

    return {
        fid: {"domain": domains.get(fid), "site_map_urls": found.get(fid, [])[:_MAX_FOUND_URLS]}
        for fid in firm_ids
    }


def _previous_successful_sweep(conn: psycopg.Connection, firm_id: str, url: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content_hash, postings_found, parser_version FROM careers_sweep "
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
                                        content_hash, parse_method, parser_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (firm_id, url, fetch_ok, status_code, postings_found, content_hash, parse_method,
             PARSER_VERSION),
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

    if outcome.status == 404 or redirected_away(outcome.url, outcome.final_url):
        # A 200 that landed on the homepage or an error page is the same answer
        # as a 404: there is no careers page at this URL. Recorded as such, never
        # parsed -- a homepage's text has no openings and its size is misleading.
        _insert_sweep(
            conn, firm_id, outcome.url, fetch_ok=True, status_code=outcome.status,
            postings_found=0, content_hash=content_hash,
            parse_method="none" if outcome.status == 404 else "redirected",
        )
        return "not_found"

    prev = _previous_successful_sweep(conn, firm_id, outcome.url)
    if (
        prev is not None
        and content_hash is not None
        and prev["content_hash"] == content_hash
        and prev.get("parser_version") == PARSER_VERSION
    ):
        _insert_sweep(
            conn, firm_id, outcome.url, fetch_ok=True, status_code=outcome.status,
            postings_found=prev["postings_found"], content_hash=content_hash, parse_method="none",
        )
        return "unchanged"

    html = decode_html(outcome.body)
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

    for firm_id, firm_outcomes in outcomes.items():
        input_hash = hashes[firm_id]
        with ctx.once("ja1_careers", firm_id, input_hash) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            for outcome in firm_outcomes:
                status = _write_sweep(ctx.conn, firm_id, outcome)
                if status == "fetch_failed":
                    result.notes.append(
                        f"{firm_id}: careers sweep fetch failed ({outcome.error})"
                    )
                elif outcome.note:
                    result.notes.append(f"{firm_id}: {outcome.note}")
            result.processed += 1
        ctx.checkpoint()

    return result
