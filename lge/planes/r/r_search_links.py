"""r_search_links -- the web searches outreach needs (Plane R, D-032, D-038).

  * One sweep per firm finds its people at once (D-041):
        site:linkedin.com "<firm>"
    Every linkedin.com/in/ result on the page is matched against the firm's
    named people who have no profile yet (up to 60, owners first); a second
    page is asked for only when the first was full and people are still
    unmatched. A result is adopted for a person only when its title (or
    slug) carries both name tokens -- a namesake at another firm is not
    this person. The firm's company page usually rides along in the same
    results: its URL and the headcount its snippet prints ("11-50
    employees") become claims linkedin_company_url, linkedin_headcount.
  * The decision-makers the sweep did not find get one query each
    (`max_people` per firm, default 4):
        "<firm>" "<person>" linkedin
  * What the search engine shows about a profile is read off the result --
    the headline ("Partner at Freehill Hogan & Mahar") and the location are
    kept on the contact, and a title the site never printed is filled from
    the headline. LinkedIn itself is never fetched (standing rule).
  * For the firm:  "<firm>" <city> <state> google business reviews
    The result snippets are read for the listing's rating and review count
    ("4.8 (312)", "Rated 4.9 · 312 reviews") and the Google Maps URL when one
    appears. Claims under `search:ddg`: google_business_url, google_rating,
    review_count (reconciled onto the firm row; the fit score reads it) and
    search_review_snippets, which Part D reads for pain.

Every query is logged once in `search_log` with the results considered, and
a person or firm is not searched again for `recheck_days` (default 90); a
failed query is asked again next run. A run stops after `max_queries`
(default 600) or five consecutive failures. Searching is network work: it
runs only under live=1, throttled the same way the website check's searches
are.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from psycopg.types.json import Jsonb

from lge.classify.roles import classify_role
from lge.planes.p._claims import write_claim
from lge.planes.p._site_facts import looks_like_title, name_like
from lge.registry import RunContext, RunResult, component
from lge.search import engine_name
from lge.search import places as web_places
from lge.search import search as web_search
from lge.search import source as search_source

_COMPONENT = "r_search_links"
# claims are tagged with the engine that answered: lge.search.source()
_RECHECK_DAYS_DEFAULT = 90
_MAX_PEOPLE_PER_FIRM = 4  # per-person queries: the decision-makers the sweep missed
_MAX_SWEEP_PEOPLE = 60  # people a sweep's results are matched against
_SWEEP_RESULTS = 30  # a results page holds ten; ask for all it gives
_SWEEP_PAGE_FULL = 8  # this many profiles on page one: page two may hold more
_MAX_QUERIES_PER_RUN = 600
_MAX_RESULTS = 8
_MAX_LOGGED = 30
_MAX_CONSECUTIVE_FAILURES = 5
_ROLE_ORDER = {"owner": 0, "admin": 1, "attorney": 2, "unknown": 3}
_DECISION_MAKERS = ("owner", "admin")
_CONFIDENCE_LINKEDIN = 0.8
_CONFIDENCE_REVIEWS = 0.6
_CONFIDENCE_LISTING = 0.85  # the listing itself, through the engine's API, not a snippet

SearchFn = Callable[..., list[dict[str, str]]]  # (query, max_results, *, page=1)

_LINKEDIN_PROFILE_RE = re.compile(r"^/(?:in|pub)/[^/]+/?", re.I)
_LINKEDIN_COMPANY_RE = re.compile(r"^/company/[^/]+/?", re.I)
_HEADLINE_RE = re.compile(
    r"^(?P<name>[^|]+?)\s+[-–—]\s+(?P<headline>.+?)(?:\s*[|·-]\s*LinkedIn.*)?$", re.I
)
_LOCATION_RE = re.compile(r"Location:\s*([^·]+?)\s*(?:·|$)")
_EXPERIENCE_RE = re.compile(r"Experience:\s*([^·]+?)\s*(?:·|$)")
_CONNECTIONS_RE = re.compile(r"(\d[\d,]*\+?)\s+connections", re.I)
_HEADCOUNT_RE = re.compile(r"\b(\d[\d,]*(?:\s*[-–]\s*\d[\d,]*)?\+?)\s+employees\b", re.I)
_RATING_RE = re.compile(
    r"\b([1-5](?:\.\d)?)\s*(?:/\s*5|out\s+of\s+5|[- ]?stars?\b|star\s+rating|·|\(\d)", re.I
)
_RATING_PAREN_RE = re.compile(r"\b([1-5]\.\d)\s*\((\d[\d,]*)\)")
_COUNT_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})*|\d+)\+?\s+(?:google\s+|customer\s+|client\s+|verified\s+|"
    r"(?:five|5)[- ]star\s+)?(?:reviews|ratings)\b",
    re.I,
)
_MAPS_RE = re.compile(
    r"google\.com/maps|maps\.google\.|maps\.app\.goo\.gl|goo\.gl/maps|g\.page/|"
    r"search\.google\.com/local|google\.com/search\?.*(?:ludocid|lrd=)",
    re.I,
)
_LAW_WORDS_RE = re.compile(
    r"\b(?:law|legal|attorney|attorneys|lawyer|lawyers|llp|llc|pllc|pc|p\.c\.|firm|group|"
    r"associates|office|offices|the|of|and|&)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Queries and picking
# ---------------------------------------------------------------------------


def linkedin_query(firm_name: str, person: str, city: str | None = None) -> str:
    # The city keeps namesakes apart (D-042): a "John Smith" at "Smith Law" in Atlanta
    return " ".join(p for p in (f'"{firm_name}"', f'"{person}"', city, "linkedin") if p)


def sweep_query(firm_name: str, city: str | None = None) -> str:
    # The site: operator keeps the data brokers (RocketReach, ZoomInfo) out;
    # the whole domain, so the company page comes back with the people.
    return " ".join(p for p in (f'site:linkedin.com "{firm_name}"', city) if p)


def reviews_query(firm_name: str, city: str | None, state: str | None) -> str:
    return " ".join(p for p in (f'"{firm_name}"', city, state, "google business reviews") if p)


def places_query(firm_name: str, city: str | None, state: str | None) -> str:
    return " ".join(p for p in (firm_name, city, state) if p)


_LISTING_MIN_OVERLAP = 0.34
_LAW_CATEGORY_RE = re.compile(r"law|legal|attorney|lawyer", re.I)


def _listing_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", _LAW_WORDS_RE.sub(" ", text.casefold())) if len(t) > 1
    }


def pick_listing(firm_name: str, listings: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The business listing that is this firm: the best name overlap once the
    law words are set aside ("Hartley Injury Law" is "Hartley Injury Law, P.C.",
    not "Hartley Dental"), and never a listing whose category is not a law
    practice."""
    if not listings:
        return None
    firm = _listing_tokens(firm_name)
    if not firm:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for p in listings:
        category = str(p.get("category") or "")
        if category and not _LAW_CATEGORY_RE.search(category):
            continue
        name = _listing_tokens(str(p.get("name") or ""))
        if not name:
            continue
        score = len(firm & name) / len(firm | name)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= _LISTING_MIN_OVERLAP else None


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", name.casefold()) if len(t) > 1]


def _firm_tokens(firm_name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", _LAW_WORDS_RE.sub(" ", firm_name).casefold())
            if len(t) > 2}


def _is_linkedin(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def canonical_linkedin(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") + "/"
    return urlunsplit(("https", "www.linkedin.com", path, "", ""))


def read_profile(result: dict[str, str]) -> dict[str, str | None]:
    """What the search engine shows about a profile: headline, company,
    location, connections. The title is "Name - Headline | LinkedIn"; the
    body carries "Experience: … · Location: … · 500+ connections"."""
    title = " ".join((result.get("title") or "").split())
    body = " ".join((result.get("body") or "").split())
    # The engine glues several page titles into one string ("… | LinkedInJoe
    # Bloggs posted on LinkedIn…"): the headline ends at the first "LinkedIn"
    # or ellipsis.
    title = re.split(r"\s*(?:\|\s*)?LinkedIn|\s*(?:\.\.\.|…)", title, maxsplit=1)[0].strip()
    headline: str | None = None
    m = _HEADLINE_RE.match(title)
    if m:
        headline = m.group("headline").strip(" -–—|·")[:120] or None
    company = None
    em = _EXPERIENCE_RE.search(body)
    if em:
        company = em.group(1).strip()[:120]
    elif headline and " at " in headline:
        company = headline.rsplit(" at ", 1)[-1].strip()[:120]
    location = None
    lm = _LOCATION_RE.search(body)
    if lm:
        location = lm.group(1).strip()[:120]
    cm = _CONNECTIONS_RE.search(body)
    return {
        "headline": headline, "company": company, "location": location,
        "connections": cm.group(1) if cm else None,
    }


def title_from_headline(headline: str | None) -> str | None:
    """The job title in a headline: "Partner at X" -> "Partner"; "Lawyer at X"
    -> "Lawyer"; a headline that is not a title ("Helping firms grow") -> None."""
    if not headline:
        return None
    part = re.split(r"\s+(?:at|@)\s+", headline, maxsplit=1)[0]
    part = re.split(r"\s*[|·]\s*", part)[0].strip(" ,")
    if not part or len(part) > 80 or not looks_like_title(part):
        return None
    return part


def pick_linkedin(
    person: str, firm_name: str, results: list[dict[str, str]]
) -> tuple[str | None, dict[str, Any]]:
    """The profile URL that is this person, or None, with what the result
    shows about them. A linkedin.com/in/ result whose title (or slug) carries
    the person's first and last name; the firm's name in the title or snippet
    breaks ties between namesakes."""
    tokens = _name_tokens(person)
    if len(tokens) < 2:
        return None, {"reason": "name too short to match"}
    first, last = tokens[0], tokens[-1]
    # An eponymous firm shares the person's surname: that token proves nothing.
    firm_tokens = _firm_tokens(firm_name) - set(tokens)
    best: tuple[float, str | None, dict] = (0.0, None, {})
    for r in results:
        href = r.get("href") or ""
        parts = urlsplit(href)
        host = (parts.hostname or "").lower()
        if not _is_linkedin(host) or not _LINKEDIN_PROFILE_RE.match(parts.path):
            continue
        title = (r.get("title") or "").casefold()
        slug = parts.path.casefold()
        body = (r.get("body") or "").casefold()
        score = 0.0
        if last in title or last in slug:
            score += 0.5
        if first in title or first in slug:
            score += 0.3
        if firm_tokens and any(t in title or t in body for t in firm_tokens):
            score += 0.2
        if score > best[0]:
            best = (score, href, {"title": r.get("title"), "href": href, "score": score,
                                  **read_profile(r)})
    score, href, evidence = best
    if href is None or score < 0.8:
        return None, {**evidence, "reason": "no result names this person"} if evidence else {
            "reason": "no linkedin profile in the results"
        }
    return canonical_linkedin(href), evidence


def is_profile(result: dict[str, str]) -> bool:
    parts = urlsplit(result.get("href") or "")
    host = (parts.hostname or "").lower()
    return _is_linkedin(host) and bool(_LINKEDIN_PROFILE_RE.match(parts.path))


def match_people(
    people: list[dict], firm_name: str, results: list[dict[str, str]]
) -> list[tuple[dict, str, dict[str, Any]]]:
    """Each person the sweep's results name, with their profile: owners
    first, one result per person, one person per result."""
    matched: list[tuple[dict, str, dict[str, Any]]] = []
    used: set[str] = set()
    for person in people:
        candidates = [r for r in results if (r.get("href") or "") not in used]
        url, profile = pick_linkedin(person["full_name"], firm_name, candidates)
        if url:
            matched.append((person, url, profile))
            used.add(profile.get("href") or "")
    return matched


def pick_company(firm_name: str, results: list[dict[str, str]]) -> dict[str, Any]:
    """The firm's LinkedIn company page and the headcount its snippet prints."""
    firm_tokens = _firm_tokens(firm_name)
    for r in results:
        href = r.get("href") or ""
        parts = urlsplit(href)
        host = (parts.hostname or "").lower()
        if not _is_linkedin(host) or not _LINKEDIN_COMPANY_RE.match(parts.path):
            continue
        text = f"{r.get('title') or ''} {r.get('body') or ''}"
        low = text.casefold()
        if firm_tokens and not any(t in low for t in firm_tokens):
            continue
        hm = _HEADCOUNT_RE.search(text)
        return {
            "url": canonical_linkedin(href),
            "headcount": hm.group(1).replace(" ", "") if hm else None,
            "evidence": " ".join(text.split())[:200],
        }
    return {"url": None, "headcount": None, "evidence": None}


def read_reviews(results: list[dict[str, str]]) -> dict[str, Any]:
    """What the result snippets say about the firm's reviews: the Google Maps
    URL when one appears, and the rating and review count -- from the maps
    result if it has them, otherwise the largest count printed anywhere."""
    maps_url: str | None = None
    rating: float | None = None
    count: int | None = None
    evidence: str | None = None
    snippets: list[dict[str, str]] = []

    def read(text: str) -> tuple[float | None, int | None]:
        m = _RATING_PAREN_RE.search(text)
        if m:
            return float(m.group(1)), int(m.group(2).replace(",", ""))
        r = _RATING_RE.search(text)
        c = _COUNT_RE.search(text)
        return (
            float(r.group(1)) if r else None,
            int(c.group(1).replace(",", "")) if c else None,
        )

    for r in results:
        href = r.get("href") or ""
        text = f"{r.get('title') or ''} {r.get('body') or ''}"
        if not href or "search failed" in text:
            continue
        snippets.append({"url": href, "title": r.get("title") or "", "body": r.get("body") or ""})
        found_rating, found_count = read(text)
        is_maps = bool(_MAPS_RE.search(href))
        if is_maps and maps_url is None:
            maps_url = href
            if found_rating or found_count:
                rating, count, evidence = found_rating, found_count, text[:200]
                continue
        if found_count and (count is None or found_count > count) and not (maps_url and evidence):
            rating, count, evidence = found_rating, found_count, text[:200]
    if rating is not None and not 1.0 <= rating <= 5.0:
        rating = None
    return {
        "maps_url": maps_url, "rating": rating, "count": count,
        "evidence": evidence, "snippets": snippets[:8],
    }


# ---------------------------------------------------------------------------
# Selection and records
# ---------------------------------------------------------------------------


def _not_searched(kind: str, column: str) -> str:
    return (
        f"NOT EXISTS (SELECT 1 FROM search_log s WHERE s.{column} = {{ref}} "
        f"AND s.kind = '{kind}' AND s.outcome <> 'failed' "
        "AND s.searched_at > now() - make_interval(days => %(days)s))"
    )


def _firm_ids(conn: Any, opts: dict[str, Any], recheck_days: int) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    person = _not_searched("linkedin", "contact_id").format(ref="c.id")
    sweep = _not_searched("sweep", "firm_id").format(ref="f.id")
    reviews = _not_searched("reviews", "firm_id").format(ref="f.id")
    # A firm is due when someone still has no profile and either the firm
    # has not been swept lately or that someone is a decision-maker who has
    # not had a query of their own.
    query = f"""
        SELECT DISTINCT f.id AS firm_id
        FROM firm f
        LEFT JOIN contact c ON c.firm_id = f.id AND c.removed_at IS NULL
        WHERE (c.id IS NOT NULL AND c.linkedin_url IS NULL AND {person}
               AND ({sweep} OR c.role IN ('owner', 'admin')))
           OR {reviews}
        ORDER BY f.id
    """  # noqa: S608 -- fixed fragments; the day count is a bound parameter
    params: dict[str, Any] = {"days": recheck_days}
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %(limit)s"
        params["limit"] = int(limit)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["firm_id"] for r in cur.fetchall()]


def _people_to_search(conn: Any, firm_id: Any, recheck_days: int, max_people: int) -> list[dict]:
    not_searched = _not_searched("linkedin", "contact_id").format(ref="c.id")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.id, c.full_name, c.role, c.title, c.confidence
            FROM contact c
            WHERE c.firm_id = %(firm_id)s AND c.linkedin_url IS NULL AND c.removed_at IS NULL
              AND {not_searched}
            """,  # noqa: S608 -- fixed fragments; values are bound parameters
            {"firm_id": firm_id, "days": recheck_days},
        )
        rows = cur.fetchall()
    # A contact whose name is not a person's ("About Us", "Our Values" -- the
    # structured-data and AI readers let a few through) is not worth a query.
    rows = [r for r in rows if name_like(r["full_name"])]
    rows.sort(key=lambda r: (_ROLE_ORDER.get(r["role"] or "unknown", 3),
                             -float(r["confidence"] or 0)))
    return rows[:max_people]


def _searched_recently(conn: Any, firm_id: Any, kind: str, recheck_days: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM search_log WHERE firm_id = %s AND kind = %s "
            "AND outcome <> 'failed' AND searched_at > now() - make_interval(days => %s) LIMIT 1",
            (firm_id, kind, recheck_days),
        )
        return cur.fetchone() is not None


def _log(
    conn: Any, firm_id: Any, kind: str, query: str, outcome: str, results: list[dict], *,
    contact_id: Any = None, url: str | None = None, rating: float | None = None,
    review_count: int | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO search_log (firm_id, kind, contact_id, query, outcome, url, rating, "
            "review_count, results, engine) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (firm_id, kind, contact_id, query, outcome, url, rating, review_count,
             Jsonb(results[:_MAX_LOGGED]), engine_name()),
        )


def _failed(results: list[dict]) -> bool:
    return len(results) == 1 and (results[0].get("body") or "").startswith("search failed")


def _write_company(conn: Any, firm_id: Any, page: dict[str, Any], now: Any) -> None:
    write_claim(conn, firm_id, "linkedin_company_url", page["url"], search_source(),
                _CONFIDENCE_LINKEDIN, page["evidence"], now)
    if page["headcount"]:
        write_claim(conn, firm_id, "linkedin_headcount", page["headcount"], search_source(),
                    _CONFIDENCE_LINKEDIN, page["evidence"], now)


def _record_profile(conn: Any, person: dict, url: str, profile: dict[str, Any], now: Any) -> None:
    """The URL and what the result showed; a title the site never printed is
    filled from the headline, and the role classified from it."""
    title = person.get("title")
    role = person.get("role") or "unknown"
    if not title:
        filled = title_from_headline(profile.get("headline"))
        if filled:
            title = filled
            if role == "unknown":
                role = classify_role(filled).role
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE contact SET linkedin_url = %s, linkedin_headline = %s, "
            "linkedin_location = %s, title = %s, role = %s, enriched_at = %s WHERE id = %s",
            (url, profile.get("headline"), profile.get("location"), title, role, now,
             person["id"]),
        )


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


def _write_listing(conn: Any, firm_id: Any, listing: dict[str, Any], now: Any) -> None:
    evidence = (
        f"{listing.get('name')}, {listing.get('address') or 'no address'}: "
        f"{listing.get('rating')} ({listing.get('review_count')} reviews)"
    )
    if listing.get("url"):
        write_claim(conn, firm_id, "google_business_url", listing["url"], search_source(),
                    _CONFIDENCE_LISTING, evidence, now)
    if listing.get("rating") is not None:
        write_claim(conn, firm_id, "google_rating", listing["rating"], search_source(),
                    _CONFIDENCE_LISTING, evidence, now)
    if listing.get("review_count") is not None:
        write_claim(conn, firm_id, "review_count", listing["review_count"], search_source(),
                    _CONFIDENCE_LISTING, evidence, now)


PlacesFn = Callable[[str], list[dict[str, Any]] | None]


@component(
    _COMPONENT, "R",
    "Web search: LinkedIn profiles for every named person, the firm's company page, Google reviews",
)
def run(
    ctx: RunContext, *, search: SearchFn | None = None, places: PlacesFn | None = None,
    **opts: Any,
) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    search = search or web_search
    places = places or web_places
    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append("live=0: web search is network work -- nothing searched")
        return result
    recheck_days = int(opts.get("recheck_days") or _RECHECK_DAYS_DEFAULT)
    max_people = int(opts.get("max_people") or _MAX_PEOPLE_PER_FIRM)
    max_queries = int(opts.get("max_queries") or _MAX_QUERIES_PER_RUN)
    now = datetime.now(UTC)
    counts = {"swept": 0, "found": 0, "not_found": 0, "titles": 0, "companies": 0,
              "reviews": 0}
    queries = 0
    # Five failures in a row is the network or the engine refusing us, not
    # five unlucky queries: stop, leave the rest for the next run.
    consecutive_failures = 0
    last_failure = ""

    def ask(query: str, n: int = _MAX_RESULTS, page: int = 1) -> list[dict[str, str]]:
        nonlocal queries, last_failure
        queries += 1
        results = search(query, n, page=page)
        if _failed(results):
            last_failure = results[0].get("body") or ""
        return results

    def budget_left() -> bool:
        return queries < max_queries and consecutive_failures < _MAX_CONSECUTIVE_FAILURES

    for firm_id in _firm_ids(conn, opts, recheck_days):
        if not budget_left():
            break
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT canonical_name, city, state FROM firm WHERE id = %s", (firm_id,)
                )
                firm = cur.fetchone()
            if firm is None:
                result.skipped += 1
                continue
            firm_name = firm["canonical_name"]
            did_something = False
            company_known = _searched_recently(conn, firm_id, "company", recheck_days)
            people = _people_to_search(conn, firm_id, recheck_days, _MAX_SWEEP_PEOPLE)

            # One query finds the firm's people at once; a second page only
            # when the first was full and someone is still unmatched.
            if people and budget_left() and not _searched_recently(
                conn, firm_id, "sweep", recheck_days
            ):
                query = sweep_query(firm_name, firm["city"])
                results = ask(query, _SWEEP_RESULTS)
                did_something = True
                if _failed(results):
                    consecutive_failures += 1
                    _log(conn, firm_id, "sweep", query, "failed", results)
                else:
                    consecutive_failures = 0
                    matched = match_people(people, firm_name, results)
                    if (budget_left() and len(matched) < len(people)
                            and sum(1 for r in results if is_profile(r)) >= _SWEEP_PAGE_FULL):
                        more = ask(query, _SWEEP_RESULTS, page=2)
                        if not _failed(more):
                            found_ids = {m[0]["id"] for m in matched}
                            left = [p for p in people if p["id"] not in found_ids]
                            matched += match_people(left, firm_name, more)
                            results = results + more
                    for person, url, profile in matched:
                        _record_profile(conn, person, url, profile, now)
                        counts["found"] += 1
                        if (not person.get("title")
                                and title_from_headline(profile.get("headline"))):
                            counts["titles"] += 1
                        _log(conn, firm_id, "linkedin", query, "found",
                             [r for r in results if r.get("href") == profile.get("href")],
                             contact_id=person["id"], url=url)
                    _log(conn, firm_id, "sweep", query, "found" if matched else "not_found",
                         results)
                    counts["swept"] += 1
                    if not company_known:
                        page = pick_company(firm_name, results)
                        if page["url"]:
                            _write_company(conn, firm_id, page, now)
                            _log(conn, firm_id, "company", query, "found", results,
                                 url=page["url"])
                            counts["companies"] += 1
                            company_known = True
                    found_ids = {m[0]["id"] for m in matched}
                    people = [p for p in people if p["id"] not in found_ids]

            # The decision-makers the sweep did not find: one query each.
            leftovers = [p for p in people if (p["role"] or "unknown") in _DECISION_MAKERS]
            for person in leftovers[:max_people]:
                if not budget_left():
                    break
                query = linkedin_query(firm_name, person["full_name"], firm["city"])
                results = ask(query)
                did_something = True
                if _failed(results):
                    consecutive_failures += 1
                    _log(conn, firm_id, "linkedin", query, "failed", results,
                         contact_id=person["id"])
                    continue
                consecutive_failures = 0
                url, profile = pick_linkedin(person["full_name"], firm_name, results)
                if url:
                    _record_profile(conn, person, url, profile, now)
                    counts["found"] += 1
                    if not person.get("title") and title_from_headline(profile.get("headline")):
                        counts["titles"] += 1
                else:
                    counts["not_found"] += 1
                _log(conn, firm_id, "linkedin", query, "found" if url else "not_found", results,
                     contact_id=person["id"], url=url)
                # The firm's company page often rides along in a person's
                # results: take it when it does, and spare the company query.
                if not company_known:
                    page = pick_company(firm_name, results)
                    if page["url"]:
                        _write_company(conn, firm_id, page, now)
                        _log(conn, firm_id, "company", query, "found", results, url=page["url"])
                        counts["companies"] += 1
                        company_known = True

            if budget_left() and not _searched_recently(conn, firm_id, "reviews", recheck_days):
                # The listing itself when the engine has a listings endpoint
                # (Google Business Profile through the API, D-045); the
                # snippets of an ordinary query otherwise.
                query = places_query(firm_name, firm["city"], firm["state"])
                listings = places(query)
                if listings is not None:
                    queries += 1
                listing = pick_listing(firm_name, listings)
                did_something = True
                if listing is not None:
                    consecutive_failures = 0
                    _write_listing(conn, firm_id, listing, now)
                    _log(conn, firm_id, "reviews", query, "found", [listing],
                         url=listing.get("url"), rating=listing.get("rating"),
                         review_count=listing.get("review_count"))
                    counts["reviews"] += 1
                    results = None
                else:
                    query = reviews_query(firm_name, firm["city"], firm["state"])
                    results = ask(query)
                if results is None:
                    pass
                elif _failed(results):
                    consecutive_failures += 1
                    _log(conn, firm_id, "reviews", query, "failed", results)
                else:
                    consecutive_failures = 0
                    found = read_reviews(results)
                    if found["maps_url"]:
                        write_claim(conn, firm_id, "google_business_url", found["maps_url"],
                                    search_source(), _CONFIDENCE_REVIEWS, found["maps_url"], now)
                    if found["rating"] is not None:
                        write_claim(conn, firm_id, "google_rating", found["rating"],
                                    search_source(),
                                    _CONFIDENCE_REVIEWS, found["evidence"], now)
                    if found["count"] is not None:
                        write_claim(conn, firm_id, "review_count", found["count"], search_source(),
                                    _CONFIDENCE_REVIEWS, found["evidence"], now)
                    if found["snippets"]:
                        write_claim(conn, firm_id, "search_review_snippets", found["snippets"],
                                    search_source(), _CONFIDENCE_REVIEWS, query, now)
                    got = found["maps_url"] or found["rating"] is not None or found["count"]
                    _log(conn, firm_id, "reviews", query, "found" if got else "not_found",
                         results, url=found["maps_url"], rating=found["rating"],
                         review_count=found["count"])
                    counts["reviews"] += 1 if got else 0

            if did_something:
                result.processed += 1
            else:
                result.skipped += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={firm_id}: {exc}")
        ctx.checkpoint()

    if not budget_left():
        reason = (
            f"{consecutive_failures} searches failed in a row ({last_failure})"
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES
            else f"the run's budget of {max_queries} queries"
        )
        result.notes.append(f"stopped early: {reason} -- the rest wait for the next run")
    result.notes.append(
        f"firms swept {counts['swept']}; linkedin profiles found {counts['found']}, "
        f"not found {counts['not_found']}, titles filled from headlines {counts['titles']}; "
        f"company pages {counts['companies']}; review listings read {counts['reviews']}; "
        f"{queries} queries"
    )
    return result
