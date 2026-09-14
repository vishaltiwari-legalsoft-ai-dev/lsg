"""r_search_links -- the two web searches outreach needs (Plane R, D-032).

  * For each decision-maker without a LinkedIn URL (owner first, then admin,
    then attorney; at most four per firm):  "<firm>" "<person>" linkedin
    The result adopted must be a linkedin.com/in/ profile whose title names
    the person (both name tokens) -- a namesake at another firm is not this
    person. Only the URL is kept on contact.linkedin_url; LinkedIn itself is
    never fetched (standing rule).
  * For the firm:  "<firm>" <city> <state> google business reviews
    The result snippets are read for the listing's rating and review count
    ("4.8 (312)", "Rated 4.9 · 312 reviews") and the Google Maps URL when one
    appears. Claims under `search:ddg`: google_business_url, google_rating,
    review_count (reconciled onto the firm row; the fit score reads it) and
    search_review_snippets, which Part D reads for pain.

Every query is logged once in `search_log` with the results considered, and
a person or firm is not searched again for `recheck_days` (default 90).
Searching is network work: it runs only under live=1, throttled the same
way the website check's searches are.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from psycopg.types.json import Jsonb

from lge.ingest.webcheck import ddg_search
from lge.planes.p._claims import write_claim
from lge.registry import RunContext, RunResult, component

_COMPONENT = "r_search_links"
_SOURCE = "search:ddg"
_RECHECK_DAYS_DEFAULT = 90
_MAX_PEOPLE_PER_FIRM = 4
_MAX_RESULTS = 8
_ROLE_ORDER = {"owner": 0, "admin": 1, "attorney": 2, "unknown": 3}
_CONFIDENCE_LINKEDIN = 0.8
_CONFIDENCE_REVIEWS = 0.6

SearchFn = Callable[[str, int], list[dict[str, str]]]

_LINKEDIN_PROFILE_RE = re.compile(r"^/(?:in|pub)/[^/]+/?", re.I)
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


def linkedin_query(firm_name: str, person: str) -> str:
    return f'"{firm_name}" "{person}" linkedin'


def reviews_query(firm_name: str, city: str | None, state: str | None) -> str:
    return " ".join(p for p in (f'"{firm_name}"', city, state, "google business reviews") if p)


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", name.casefold()) if len(t) > 1]


def _firm_tokens(firm_name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", _LAW_WORDS_RE.sub(" ", firm_name).casefold())
            if len(t) > 2}


def canonical_linkedin(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") + "/"
    return urlunsplit(("https", "www.linkedin.com", path, "", ""))


def pick_linkedin(
    person: str, firm_name: str, results: list[dict[str, str]]
) -> tuple[str | None, dict[str, Any]]:
    """The profile URL that is this person, or None. A linkedin.com/in/ result
    whose title (or slug) carries the person's first and last name; the firm's
    name in the title or snippet breaks ties between namesakes."""
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
        if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
            continue
        if not _LINKEDIN_PROFILE_RE.match(parts.path):
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
            best = (score, href, {"title": r.get("title"), "href": href, "score": score})
    score, href, evidence = best
    if href is None or score < 0.8:
        return None, {**evidence, "reason": "no result names this person"} if evidence else {
            "reason": "no linkedin profile in the results"
        }
    return canonical_linkedin(href), evidence


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


def _firm_ids(conn: Any, opts: dict[str, Any], recheck_days: int) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    query = """
        SELECT DISTINCT f.id AS firm_id
        FROM firm f
        JOIN contact c ON c.firm_id = f.id
        WHERE (c.linkedin_url IS NULL
               AND NOT EXISTS (SELECT 1 FROM search_log s WHERE s.contact_id = c.id
                               AND s.kind = 'linkedin'
                               AND s.searched_at > now() - make_interval(days => %s)))
           OR NOT EXISTS (SELECT 1 FROM search_log s WHERE s.firm_id = f.id
                          AND s.kind = 'reviews'
                          AND s.searched_at > now() - make_interval(days => %s))
        ORDER BY f.id
    """
    params: list[Any] = [recheck_days, recheck_days]
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["firm_id"] for r in cur.fetchall()]


def _people_to_search(conn: Any, firm_id: Any, recheck_days: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.full_name, c.role, c.title, c.confidence
            FROM contact c
            WHERE c.firm_id = %s AND c.linkedin_url IS NULL
              AND NOT EXISTS (SELECT 1 FROM search_log s WHERE s.contact_id = c.id
                              AND s.kind = 'linkedin'
                              AND s.searched_at > now() - make_interval(days => %s))
            """,
            (firm_id, recheck_days),
        )
        rows = cur.fetchall()
    rows.sort(key=lambda r: (_ROLE_ORDER.get(r["role"] or "unknown", 3),
                             -float(r["confidence"] or 0)))
    return rows[:_MAX_PEOPLE_PER_FIRM]


def _reviews_searched_recently(conn: Any, firm_id: Any, recheck_days: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM search_log WHERE firm_id = %s AND kind = 'reviews' "
            "AND searched_at > now() - make_interval(days => %s) LIMIT 1",
            (firm_id, recheck_days),
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
            "review_count, results) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (firm_id, kind, contact_id, query, outcome, url, rating, review_count,
             Jsonb(results[:_MAX_RESULTS])),
        )


def _failed(results: list[dict]) -> bool:
    return len(results) == 1 and (results[0].get("body") or "").startswith("search failed")


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


@component(
    _COMPONENT, "R",
    "Web search: LinkedIn profiles for named decision-makers, Google reviews for the firm",
)
def run(ctx: RunContext, *, search: SearchFn | None = None, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    search = search or ddg_search
    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append("live=0: web search is network work -- nothing searched")
        return result
    recheck_days = int(opts.get("recheck_days") or _RECHECK_DAYS_DEFAULT)
    now = datetime.now(UTC)
    linkedin_found = linkedin_missed = reviews_read = 0

    for firm_id in _firm_ids(conn, opts, recheck_days):
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

            for person in _people_to_search(conn, firm_id, recheck_days):
                query = linkedin_query(firm_name, person["full_name"])
                results = search(query, _MAX_RESULTS)
                did_something = True
                if _failed(results):
                    _log(conn, firm_id, "linkedin", query, "failed", results,
                         contact_id=person["id"])
                    continue
                url, _evidence = pick_linkedin(person["full_name"], firm_name, results)
                if url:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE contact SET linkedin_url = %s, enriched_at = %s WHERE id = %s",
                            (url, now, person["id"]),
                        )
                    linkedin_found += 1
                else:
                    linkedin_missed += 1
                _log(conn, firm_id, "linkedin", query, "found" if url else "not_found", results,
                     contact_id=person["id"], url=url)

            if not _reviews_searched_recently(conn, firm_id, recheck_days):
                query = reviews_query(firm_name, firm["city"], firm["state"])
                results = search(query, _MAX_RESULTS)
                did_something = True
                if _failed(results):
                    _log(conn, firm_id, "reviews", query, "failed", results)
                else:
                    found = read_reviews(results)
                    if found["maps_url"]:
                        write_claim(conn, firm_id, "google_business_url", found["maps_url"],
                                    _SOURCE, _CONFIDENCE_REVIEWS, found["maps_url"], now)
                    if found["rating"] is not None:
                        write_claim(conn, firm_id, "google_rating", found["rating"], _SOURCE,
                                    _CONFIDENCE_REVIEWS, found["evidence"], now)
                    if found["count"] is not None:
                        write_claim(conn, firm_id, "review_count", found["count"], _SOURCE,
                                    _CONFIDENCE_REVIEWS, found["evidence"], now)
                    if found["snippets"]:
                        write_claim(conn, firm_id, "search_review_snippets", found["snippets"],
                                    _SOURCE, _CONFIDENCE_REVIEWS, query, now)
                    got = found["maps_url"] or found["rating"] is not None or found["count"]
                    _log(conn, firm_id, "reviews", query, "found" if got else "not_found",
                         results, url=found["maps_url"], rating=found["rating"],
                         review_count=found["count"])
                    reviews_read += 1 if got else 0

            if did_something:
                result.processed += 1
            else:
                result.skipped += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={firm_id}: {exc}")
        ctx.checkpoint()

    result.notes.append(
        f"linkedin profiles found {linkedin_found}, not found {linkedin_missed}; "
        f"review listings read {reviews_read}"
    )
    return result
