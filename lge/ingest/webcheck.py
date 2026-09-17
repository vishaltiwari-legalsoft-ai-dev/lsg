"""website_check -- is the site the sheet gave real, and is it this firm?

A sheet's website column is the weakest thing in it: blank, a phone number
pasted in the wrong column, a dead domain, a parked domain, or another
business entirely. Everything downstream reads the site, so the address has
to be right before the crawl.

For each firm:
  1. no website given                     -> 'missing'   -> search
  2. given, but no usable domain in it    -> 'malformed' -> search
  3. robots.txt unreachable / no answer   -> 'dead'      -> search
  4. answers 403 at the edge              -> 'blocked'   (the site exists; no search)
  5. answers, page names the firm         -> 'ok'
  6. answers, page is something else      -> 'mismatch'  -> search

The search is whatever engine lge.search answers with (D-045): "<firm name>"
<city> <state> law firm.
Directory, social and aggregator results are dropped; the best remaining
result whose title or snippet names the firm becomes the corrected domain.
A correction is written three ways: a website_check row (outcome
'corrected', with the query and every result considered), an observation
from source 'search:<engine>' (the one door), and the firm's domain itself under
the 'resolve' writer, with the old domain kept as an alias. When the found
domain already belongs to another firm record, nothing is rewritten and an
identity_review row asks a person -- that is a duplicate, not a correction.

Searches are throttled and never repeated for a firm checked within
`recheck_days`. The fetch is the crawler's own: honest identity, robots.txt
obeyed, one homepage per firm.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import lxml.html
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.fetch.client import EmptyUserAgentError, Fetcher, HostBlockTracker
from lge.fetch.config import rate_defaults
from lge.fetch.decode import decode_html
from lge.fetch.orchestrate import gather_bounded
from lge.fetch.ratelimit import HostRateLimiter
from lge.fetch.robots import RobotsCache
from lge.norm import norm_domain, norm_name
from lge.registry import RunContext, RunResult, component
from lge.search import SearchFn
from lge.search import search as web_search
from lge.search import source as search_source

DEFAULT_RECHECK_DAYS = 30
NAME_MATCH_OK = 0.5

# Results that are never the firm's own site.
_NOT_A_FIRM_SITE = (
    "avvo.com", "justia.com", "findlaw.com", "lawyers.com", "superlawyers.com",
    "martindale.com", "yelp.com", "facebook.com", "linkedin.com", "bbb.org",
    "yellowpages.com", "mapquest.com", "google.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "lawyer.com", "nolo.com", "expertise.com", "thumbtack.com",
    "legalmatch.com", "law.com", "bing.com", "duckduckgo.com", "wikipedia.org",
    "zoominfo.com", "crunchbase.com", "glassdoor.com", "indeed.com", "chamberofcommerce.com",
    "manta.com", "dnb.com", "apollo.io", "rocketreach.co", "signalhire.com",
    "lawyerlegion.com", "hg.org", "lawinfo.com", "attorneys.com", "legalzoom.com",
    "clio.com", "lawyerdb.org", "bizapedia.com", "opencorporates.com", "yellowbook.com",
    "cylex.us.com", "reddit.com", "tiktok.com", "threads.net",
    # seen in the first live run: aggregators that name the firm in a snippet
    "w9ein.com", "privco.com", "datanyze.com", "lawyerguide.com", "legalreach.com",
    "lawful.com", "attorneyatlaw.com", "websitepro.hosting", "birdeye.com", "trustpilot.com",
    "superpages.com", "citysearch.com", "local.com", "hotfrog.com", "brownbook.net",
    "ezlocal.com", "cityfos.com", "buzzfile.com", "einpresswire.com", "leadiq.com",
)
_PARKED_RE = re.compile(
    r"domain (?:is )?for sale|buy this domain|parked (?:free|domain)|this site can.t be reached"
    r"|coming soon|under construction|godaddy\.com/forsale|hugedomains|sedo\.com|dan\.com",
    re.I,
)
# Words that say nothing about WHICH firm this is.
_STOP = frozenset(
    "law lawyer lawyers attorney attorneys legal firm group office offices llc llp pc pllc ltd "
    "inc the of and & injury personal accident associates partners counsel counselors trial "
    "co company practice pa p.a a an at".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def name_tokens(firm_name: str | None) -> set[str]:
    tokens = _TOKEN_RE.findall((firm_name or "").lower())
    return {t for t in tokens if t not in _STOP and len(t) >= 3}


def name_match(firm_name: str | None, text: str | None) -> float:
    """Fraction of the firm name's distinctive tokens that appear in `text`.
    0.5 when the name has no distinctive token to test."""
    tokens = name_tokens(firm_name)
    if not tokens:
        return 0.5
    hay = (text or "").lower()
    return sum(1 for t in tokens if t in hay) / len(tokens)


def page_identity(html: str) -> dict[str, str]:
    """title, og:site_name, JSON-LD organisation names, and the first 2,000
    characters of visible text -- what a page says it is."""
    out = {"title": "", "site_name": "", "ld_names": "", "text": ""}
    if not html:
        return out
    try:
        tree = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return out
    out["title"] = " ".join((tree.findtext(".//title") or "").split())
    site_name = tree.xpath("string(//meta[@property='og:site_name']/@content)")
    out["site_name"] = " ".join(site_name.split())
    names: list[str] = []
    for s in tree.xpath("//script[@type='application/ld+json']"):
        try:
            data = json.loads(s.text or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if isinstance(node.get("name"), str):
                    names.append(node["name"])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    out["ld_names"] = " | ".join(names[:5])
    for el in tree.xpath("//script|//style|//noscript"):
        el.drop_tree()
    out["text"] = " ".join(tree.text_content().split())[:2000]
    return out


@dataclass
class SiteVerdict:
    outcome: str  # ok | dead | blocked | mismatch
    http_status: int | None = None
    title: str | None = None
    name_match: float | None = None
    note: str | None = None


async def check_site(
    fetcher: Fetcher, robots_cache: RobotsCache, domain: str, firm_name: str | None
) -> SiteVerdict:
    robots = await robots_cache.get(domain)
    if robots.source_state == "edge_blocked":
        return SiteVerdict("blocked", 403, note="robots.txt blocked at the edge")
    if not robots.crawlable():
        return SiteVerdict("dead", None, note=f"robots.txt {robots.source_state}")
    result = await fetcher.fetch(f"https://{domain}/")
    if not result.fetch_ok or result.status is None:
        return SiteVerdict("dead", None, note=result.error)
    if result.status == 403:
        return SiteVerdict("blocked", 403)
    if result.status >= 400:
        return SiteVerdict("dead", result.status, note=f"homepage answered {result.status}")
    ident = page_identity(decode_html(result.body or b""))
    head = " ".join((ident["title"], ident["site_name"], ident["ld_names"]))
    if _PARKED_RE.search(head + " " + ident["text"][:600]):
        return SiteVerdict(
            "mismatch", result.status, ident["title"], 0.0, "parked or placeholder page"
        )
    score = max(name_match(firm_name, head), 0.75 * name_match(firm_name, ident["text"]))
    if score >= NAME_MATCH_OK:
        return SiteVerdict("ok", result.status, ident["title"], round(score, 2))
    return SiteVerdict(
        "mismatch", result.status, ident["title"], round(score, 2),
        "the page does not name the firm",
    )


# ---------------------------------------------------------------------------
# Search -- the engine behind it is lge.search (D-045); this module only
# builds the query and judges the results.
# ---------------------------------------------------------------------------


def build_query(firm_name: str, city: str | None, state: str | None) -> str:
    return " ".join(p for p in (f'"{firm_name}"', city, state, "law firm") if p)


@dataclass
class SearchVerdict:
    query: str
    domain: str | None
    score: float
    results: list[dict[str, Any]] = field(default_factory=list)


def pick_site(
    firm_name: str, results: list[dict[str, str]]
) -> tuple[str | None, float, list[dict]]:
    """The best result that is a firm's own site and names this firm."""
    considered: list[dict[str, Any]] = []
    best: tuple[str | None, float] = (None, 0.0)
    for r in results:
        href = r.get("href") or ""
        host = (urlsplit(href).hostname or "").lower().removeprefix("www.")
        if any(host == bad or host.endswith("." + bad) for bad in _NOT_A_FIRM_SITE):
            considered.append({"domain": host, "title": r.get("title"), "skipped": "directory"})
            continue
        dom = norm_domain(href)
        if not dom:
            continue
        score = name_match(firm_name, f"{r.get('title', '')} {r.get('body', '')}")
        label = dom.split(".", 1)[0]
        if any(t in label for t in name_tokens(firm_name)):
            score = min(1.0, score + 0.35)  # the domain itself carries the name
        depth = len([p for p in urlsplit(href).path.split("/") if p])
        if depth >= 2:
            # A deep page is more often a listing about the firm than the firm's
            # own site, but a firm's attorney bio ranks too -- order, don't veto:
            # the candidate's own homepage is checked before anything is adopted.
            score -= 0.15
        considered.append({"domain": dom, "title": r.get("title"), "score": round(score, 2)})
        if score > best[1]:
            best = (dom, score)
    return best[0] if best[1] >= NAME_MATCH_OK else None, round(best[1], 2), considered


def search_site(
    firm_name: str, city: str | None, state: str | None, search: SearchFn
) -> SearchVerdict:
    query = build_query(firm_name, city, state)
    results = search(query, 8)
    domain, score, considered = pick_site(firm_name, results)
    return SearchVerdict(query, domain, score, considered)


# ---------------------------------------------------------------------------
# The component
# ---------------------------------------------------------------------------


def _select_firms(conn, opts: dict[str, Any], recheck_days: int) -> list[dict[str, Any]]:
    firm_ids_file = opts.get("firm_ids_file")
    params: dict[str, Any] = {"days": recheck_days}
    where = ["l.closed_at IS NULL"]
    if firm_ids_file:
        from pathlib import Path

        ids = [ln.strip() for ln in Path(str(firm_ids_file)).read_text().splitlines() if ln.strip()]
        where.append("f.id = ANY(%(ids)s::uuid[])")
        params["ids"] = ids
    if not opts.get("force"):
        where.append(
            "NOT EXISTS (SELECT 1 FROM website_check w WHERE w.firm_id = f.id "
            "AND w.checked_at > now() - make_interval(days => %(days)s))"
        )
    sql = f"""
        SELECT f.id, f.canonical_name, f.domain, f.city, f.state,
               (SELECT o.payload ->> 'website' FROM observation o
                 WHERE o.firm_id = f.id AND o.payload ? 'website' AND o.payload ->> 'website' <> ''
                 ORDER BY o.id LIMIT 1) AS given
        FROM firm f JOIN lead l ON l.firm_id = f.id
        WHERE {" AND ".join(where)}
        ORDER BY f.id
    """  # noqa: S608 -- fixed fragments, bound params
    limit = opts.get("limit")
    if limit not in (None, ""):
        sql += " LIMIT %(limit)s"
        params["limit"] = int(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


async def _check_all(user_agent: str, firms: list[dict], max_hosts: int, interval: float):
    limiter = HostRateLimiter(default_interval_s=interval)
    fetcher = Fetcher(user_agent=user_agent, limiter=limiter, block_tracker=HostBlockTracker())
    async with fetcher as f:
        cache = RobotsCache(f, user_agent)
        factories = {
            str(r["id"]): functools.partial(check_site, f, cache, r["domain"], r["canonical_name"])
            for r in firms
            if r["domain"]
        }
        return await gather_bounded(factories, max_hosts)


def _write_check(conn, firm: dict, outcome: str, **cols: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO website_check (firm_id, given, domain, outcome, http_status, title,
                                       name_match, corrected_domain, search_query, evidence, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                firm["id"], firm.get("given"), firm.get("domain"), outcome,
                cols.get("http_status"), cols.get("title"), cols.get("name_match"),
                cols.get("corrected_domain"), cols.get("search_query"),
                Jsonb(cols["evidence"]) if cols.get("evidence") is not None else None,
                cols.get("note"),
            ),
        )


def _apply_correction(conn, firm: dict, found: str, verdict: SearchVerdict, now: datetime) -> str:
    """Returns the outcome written: 'corrected', or 'unresolved' when the found
    domain already belongs to another firm (a review, not a rewrite)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM firm WHERE domain = %s AND id <> %s", (found, firm["id"]))
        other = cur.fetchone()
        if other:
            cur.execute(
                "SELECT 1 FROM identity_review WHERE status = 'open' AND rule = 'website_check' "
                "AND ((left_firm_id = %s AND right_firm_id = %s) "
                "  OR (left_firm_id = %s AND right_firm_id = %s))",
                (firm["id"], other["id"], other["id"], firm["id"]),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO identity_review "
                    "(rule, reason, left_firm_id, right_firm_id, similarity) "
                    "VALUES ('website_check', %s, %s, %s, %s)",
                    (
                        f"search for '{firm['canonical_name']}' found {found}, already the "
                        f"site of another firm record",
                        firm["id"], other["id"], verdict.score,
                    ),
                )
            return "unresolved"
        # the one door: the search result is an observation too
        cur.execute(
            """
            INSERT INTO observation (source, source_key, firm_id, payload, fetched_at, name_raw,
                                     name_stem, domain, norm_versions)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """,
            (
                search_source(), f"{firm['id']}:{found}", firm["id"],
                Jsonb({"query": verdict.query, "domain": found, "score": verdict.score,
                       "results": verdict.results}),
                now, firm["canonical_name"], norm_name(firm["canonical_name"]), found,
            ),
        )
        if firm.get("domain"):
            cur.execute(
                "INSERT INTO firm_alias (firm_id, alias_domain, source, merge_rule, merged_at) "
                "VALUES (%s, %s, 'website_check', 'corrected', %s)",
                (firm["id"], firm["domain"], now),
            )
    with lge_db.writer(conn, "resolve"), conn.cursor() as cur:
        cur.execute("UPDATE firm SET domain = %s WHERE id = %s", (found, firm["id"]))
    return "corrected"


@component(
    "website_check", "I",
    "Verify each firm's website answers and names the firm; search for the real one when not.",
)
def website_check(ctx: RunContext, *, search: SearchFn | None = None, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    search = search or web_search
    recheck_days = int(opts.get("recheck_days", DEFAULT_RECHECK_DAYS))
    firms = _select_firms(conn, opts, recheck_days)
    if not firms:
        return RunResult(notes=["no firms to check"])

    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        return RunResult(notes=[f"live=0: would check {len(firms)} firm(s); no requests made"])
    if not ctx.settings.user_agent.strip():
        raise EmptyUserAgentError("refusing to fetch: settings.user_agent is empty")

    verdicts = asyncio.run(
        _check_all(
            ctx.settings.user_agent, firms,
            int(opts.get("max_concurrent_hosts", rate_defaults()["max_concurrent_hosts"])),
            float(opts.get("default_interval_s", rate_defaults()["default_interval_s"])),
        )
    )
    now = datetime.now(UTC)
    counts: dict[str, int] = {}

    # Phase 1: what the current domain says. Phase 2: search for the ones that
    # failed. Phase 3: a search hit is only a candidate until ITS homepage names
    # the firm too -- the first live run "corrected" eight firms to directories
    # whose snippets mentioned them (w9ein.com, lawyerguide.com). Phase 4: write.
    decided: list[tuple[dict, str, SiteVerdict | None, SearchVerdict | None]] = []
    for firm in firms:
        fid = str(firm["id"])
        if not firm["domain"]:
            outcome = "malformed" if firm.get("given") else "missing"
            site: SiteVerdict | None = None
        else:
            site = verdicts.get(fid) or SiteVerdict("dead", note="not checked")
            outcome = site.outcome
        sv: SearchVerdict | None = None
        if outcome in ("missing", "malformed", "dead", "mismatch") and firm["canonical_name"]:
            sv = search_site(firm["canonical_name"], firm.get("city"), firm.get("state"), search)
        decided.append((firm, outcome, site, sv))

    candidates = [
        {"id": str(firm["id"]), "domain": sv.domain, "canonical_name": firm["canonical_name"]}
        for firm, _outcome, _site, sv in decided
        if sv and sv.domain and sv.domain != firm["domain"]
    ]
    candidate_verdicts = asyncio.run(
        _check_all(
            ctx.settings.user_agent, candidates,
            int(opts.get("max_concurrent_hosts", rate_defaults()["max_concurrent_hosts"])),
            float(opts.get("default_interval_s", rate_defaults()["default_interval_s"])),
        )
    ) if candidates else {}

    for firm, outcome, site, sv in decided:
        fid = str(firm["id"])
        try:
            final = outcome
            corrected_to: str | None = None
            note = site.note if site else None
            if sv is not None:
                if sv.domain and sv.domain == firm["domain"]:
                    final = "ok"  # the search agrees the given domain is the firm's
                elif sv.domain:
                    cv = candidate_verdicts.get(fid)
                    if cv is not None and cv.outcome == "ok":
                        final = _apply_correction(conn, firm, sv.domain, sv, now)
                        corrected_to = sv.domain if final == "corrected" else None
                    else:
                        note = (
                            f"search found {sv.domain}, but its homepage "
                            f"{cv.outcome if cv else 'was not checked'}: not adopted"
                        )
                        final = outcome if outcome != "missing" else "unresolved"
            _write_check(
                conn, firm, final,
                http_status=site.http_status if site else None,
                title=site.title if site else None,
                name_match=site.name_match if site else None,
                corrected_domain=corrected_to,
                search_query=sv.query if sv else None,
                evidence={
                    "site": site.note if site else None,
                    "results": sv.results if sv else None,
                    "best_score": sv.score if sv else None,
                    "candidate": (
                        {"domain": sv.domain, "verdict": candidate_verdicts[fid].outcome}
                        if sv and fid in candidate_verdicts else None
                    ),
                } if sv else None,
                note=note,
            )
            counts[final] = counts.get(final, 0) + 1
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- one firm must not sink the run
            result.failed += 1
            result.notes.append(f"{fid}: {type(exc).__name__}: {exc}")
        ctx.checkpoint()

    result.notes.insert(0, "outcomes: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return result
