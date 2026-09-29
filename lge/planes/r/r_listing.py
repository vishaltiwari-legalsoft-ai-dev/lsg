"""r_listing -- the Google Business Profile and its reviews (Plane R, D-062;
plan-v3 phase 3, "Google Business Profile kept whole" and "Reviews").

For every firm due, one lookup through the listings seam (`lge.listings`):
the provider -- Google's own Places API, or Serper's `/places` + `/reviews`
-- returns the firm and its namesakes, `pick_listing` adopts the one that
is this firm, and its reviews are fetched. Claims are written under
`listing:<provider>`:

  * business_listing  -- the profile whole: name, category, address, phone,
                         website, rating, review count, Maps URL, status
  * google_business_url, google_rating, review_count -- reconciled onto the
                         firm row (the fit score reads review_count)
  * phone_e164, address, city -- the listing's, normalised the same way the
                         site's are; config/precedence.yml ranks them. The
                         address claim carries the same six keys as every
                         other address claim and the printed text goes in
                         `evidence`, or two sources never "agree" (D-052)
  * google_reviews    -- the reviews as one line each (author, stars, date,
                         text); the pain analyser quotes them, and the lead
                         page shows them. Written only when the reviews were
                         actually asked for and answered: a lookup whose
                         reviews call failed keeps the reviews already on
                         file rather than replacing them with an empty list

Every lookup is logged once in `search_log` (kind 'listing', engine = the
provider) with the listing and the reviews as they came back, and
`--opt replay=1` re-derives every claim from those stored answers without
calling the provider -- a matching or address-parsing fix reaches every
firm already looked up at no cost, the way a rule change re-reads stored
HTML. A firm is not looked up again for `recheck_days` (config/listings.yml,
default 30); r_search_links skips its snippet query for reviews while that
row is fresh. Nothing is read off a Google page: no provider, no lookup --
the step says so and skips. Network work, so it runs only under live=1;
replay runs without it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from lge import listings
from lge.listings import FindFn, ReviewsFn, listing_query, pick_listing
from lge.norm import norm_addr, norm_phone
from lge.planes.p._claims import write_claim
from lge.registry import RunContext, RunResult, component
from lge.search import daily_cap_refusal, meter, paid_run_refusal

_COMPONENT = "r_listing"
_KIND = "listing"
_CONFIDENCE = 0.9  # the listing itself, through a licensed API
_MAX_CONSECUTIVE_FAILURES = 5
_MAX_CANDIDATES_LOGGED = 5

# "1 Peachtree St NE Suite 100, Atlanta, GA 30303, USA" -> its parts.
_US_ADDRESS_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+?),\s*(?P<state>[A-Z]{2})\s+"
    r"(?P<zip>\d{5}(?:-\d{4})?)(?:,\s*(?:USA|United States|US))?$"
)


def parse_address(formatted: str | None) -> dict[str, Any] | None:
    """The listing's formatted address in the shape every other address
    claim carries -- exactly street_norm, unit, city, state, zip5 and
    addr_hash, never the printed text (that is the claim's evidence) -- or
    None when it is not a US street address."""
    if not formatted:
        return None
    m = _US_ADDRESS_RE.match(" ".join(formatted.split()))
    if not m:
        return None
    addr = norm_addr(m.group("street"), m.group("city"), m.group("state"), m.group("zip"))
    if not (addr.street_norm or addr.zip5):
        return None
    return {
        "street_norm": addr.street_norm, "unit": addr.unit, "city": addr.city,
        "state": addr.state, "zip5": addr.zip5, "addr_hash": addr.addr_hash,
    }


def website_host(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url if "://" in url else f"https://{url}").hostname or ""
    return host[4:] if host.startswith("www.") else host or None


def public_listing(listing: dict[str, Any]) -> dict[str, Any]:
    """The listing without the provider's private handles (`_cid`,
    `_reviews`): what is stored and shown."""
    return {k: v for k, v in listing.items() if not k.startswith("_")}


def _select(conn: Any, opts: dict[str, Any], recheck_days: int) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    # A disqualified firm is never looked up: the listing is paid for, and
    # nothing downstream will use it. An unclassified firm still is -- the
    # AI reading that classifies it may not have run yet in this flow.
    query = """
        SELECT f.id FROM firm f
        WHERE (f.tier IS NULL OR f.tier NOT LIKE 'DQ%%')
          AND NOT EXISTS (
            SELECT 1 FROM search_log s WHERE s.firm_id = f.id AND s.kind = 'listing'
              AND s.outcome <> 'failed'
              AND s.searched_at > now() - make_interval(days => %(days)s))
        ORDER BY f.id
    """
    params: dict[str, Any] = {"days": recheck_days}
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %(limit)s"
        params["limit"] = int(limit)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["id"] for r in cur.fetchall()]


def _fresh(conn: Any, firm_id: Any, recheck_days: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM search_log WHERE firm_id = %s AND kind = 'listing' "
            "AND outcome <> 'failed' AND searched_at > now() - make_interval(days => %s) LIMIT 1",
            (firm_id, recheck_days),
        )
        return cur.fetchone() is not None


def _log(
    conn: Any, firm_id: Any, query: str, outcome: str, results: Any, provider: str, *,
    url: str | None = None, rating: float | None = None, review_count: int | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO search_log (firm_id, kind, query, outcome, url, rating, review_count, "
            "results, engine) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (firm_id, _KIND, query, outcome, url, rating, review_count, Jsonb(results), provider),
        )


def write_listing_claims(
    conn: Any, firm_id: Any, listing: dict[str, Any], reviews: list[dict[str, Any]] | None,
    source: str, now: datetime,
) -> int:
    """Every claim one listing and its reviews give. `reviews` is None when
    they were not answered this time: the listing's facts are written and
    the reviews already on file are left standing. An empty list is a real
    answer ("no reviews") and is written. Returns how many claims were
    written or changed."""
    shown = public_listing(listing)
    evidence = (
        f"Google Business Profile: {shown.get('name')}"
        f"{', ' + shown['category'] if shown.get('category') else ''}"
        f"{', ' + shown['address'] if shown.get('address') else ''}"
    )
    written = 0

    def claim(attr: str, value: Any, ev: str | None = evidence) -> None:
        nonlocal written
        if write_claim(conn, firm_id, attr, value, source, _CONFIDENCE, ev, now):
            written += 1

    claim("business_listing", shown)
    if shown.get("url"):
        claim("google_business_url", shown["url"])
    if shown.get("rating") is not None:
        claim("google_rating", shown["rating"])
    if shown.get("review_count") is not None:
        claim("review_count", shown["review_count"])
    phone = norm_phone(shown.get("phone"))
    if phone:
        claim("phone_e164", phone, f"Google Business Profile: {shown.get('phone')}")
    address = parse_address(shown.get("address"))
    if address:
        claim("address", address, f"Google Business Profile: {shown.get('address')}")
        if address.get("city"):
            claim("city", address["city"], f"Google Business Profile: {shown.get('address')}")
    if reviews is not None:
        claim("google_reviews", reviews, f"{len(reviews)} review(s) on the listing")
    return written


def _stored_answers(conn: Any, opts: dict[str, Any]) -> list[dict[str, Any]]:
    """The latest stored listing answer per firm, for a replay: the log row
    whose results hold a listing (a found lookup, or one whose reviews
    failed after the listing was read)."""
    query = """
        SELECT DISTINCT ON (firm_id) firm_id, results, engine, searched_at
        FROM search_log
        WHERE kind = 'listing' AND results ? 'listing'
        ORDER BY firm_id, searched_at DESC
    """
    firm_ids_file = opts.get("firm_ids_file")
    params: list[Any] = []
    if firm_ids_file:
        wanted = [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        query = query.replace("WHERE kind", "WHERE firm_id = ANY(%s::uuid[]) AND kind")
        params.append(wanted)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _replay(ctx: RunContext, opts: dict[str, Any]) -> RunResult:
    """Re-derive every claim from the stored answers, no provider called."""
    result = RunResult()
    for row in _stored_answers(ctx.conn, opts):
        stored = row["results"] or {}
        listing = stored.get("listing")
        if not isinstance(listing, dict) or not listing.get("name"):
            result.skipped += 1
            continue
        reviews = stored.get("reviews")
        try:
            write_listing_claims(
                ctx.conn, row["firm_id"], listing,
                reviews if isinstance(reviews, list) else None,
                f"listing:{row['engine']}", row["searched_at"],
            )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={row['firm_id']}: {exc}")
        ctx.checkpoint()
    result.notes.append(f"replayed {result.processed} stored listing answer(s); nothing looked up")
    return result


@component(
    _COMPONENT, "R",
    "Google Business Profile and reviews, through the listings provider (never scraped)",
)
def run(
    ctx: RunContext, *, find: FindFn | None = None, reviews: ReviewsFn | None = None,
    **opts: Any,
) -> RunResult:
    conn = ctx.conn
    if str(opts.get("replay", "")) in ("1", "true", "True"):
        return _replay(ctx, opts)
    result = RunResult()
    live = bool(ctx.settings.live) or str(opts.get("live", "")) in ("1", "true", "True")
    if not live:
        result.notes.append("live=0: the listing lookup is network work -- nothing looked up")
        return result
    provider = listings.provider_name(ctx.settings)
    if provider == "none" or not listings.has_provider(ctx.settings):
        result.notes.append(
            "inert: no listings provider -- set GOOGLE_PLACES_API_KEY (free tier) or "
            "SERPER_API_KEY; the Google Business Profile is never scraped"
        )
        return result
    find = find or listings.find
    reviews = reviews or listings.reviews
    spend_before = meter.snapshot()
    cfg = listings.load_listings_config().get("request") or {}
    recheck_days = int(opts.get("recheck_days") or cfg.get("recheck_days", 30))
    firm_ids = _select(conn, opts, recheck_days)
    refusal = paid_run_refusal(opts, what="the listing lookup", firms=len(firm_ids)) or (
        daily_cap_refusal(conn, opts, ctx.settings) if provider == "serper" else None
    )
    if refusal:
        result.notes.append(refusal)
        return result
    max_reviews = int(opts.get("max_reviews") or cfg.get("max_reviews", 10))
    source = listings.source(ctx.settings)
    now = datetime.now(UTC)
    counts = {"found": 0, "not_found": 0, "reviews": 0}
    consecutive_failures = 0

    for firm_id in firm_ids:
        if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            result.notes.append(
                f"stopped early: {consecutive_failures} lookups failed in a row -- "
                "the rest wait for the next run"
            )
            break
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT canonical_name, city, state, domain FROM firm WHERE id = %s",
                    (firm_id,),
                )
                firm = cur.fetchone()
            if firm is None or _fresh(conn, firm_id, recheck_days):
                result.skipped += 1
                continue
            query = listing_query(firm["canonical_name"], firm["city"], firm["state"])
            found = find(query)
            if found is None:
                consecutive_failures += 1
                _log(conn, firm_id, query, "failed", None, provider)
                result.failed += 1
                continue
            consecutive_failures = 0
            listing = pick_listing(firm["canonical_name"], found)
            if listing is None:
                _log(conn, firm_id, query, "not_found",
                     [public_listing(p) for p in found[:_MAX_CANDIDATES_LOGGED]], provider)
                counts["not_found"] += 1
                result.processed += 1
                continue
            got = reviews(listing, max_reviews)
            # The listing is worth keeping even when its reviews were not
            # answered: logged as failed so the next run asks again, and the
            # reviews already on file are left standing (None, not []).
            outcome = "found" if got is not None else "failed"
            write_listing_claims(conn, firm_id, listing, got, source, now)
            _log(
                conn, firm_id, query, outcome,
                {"listing": public_listing(listing), "reviews": got}, provider,
                url=listing.get("url"), rating=listing.get("rating"),
                review_count=listing.get("review_count"),
            )
            counts["found"] += 1
            counts["reviews"] += len(got or [])
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={firm_id}: {exc}")
        ctx.checkpoint()

    result.notes.append(
        f"listings found {counts['found']}, not found {counts['not_found']}; "
        f"reviews kept {counts['reviews']}; provider {provider}"
    )
    spent = meter.note(spend_before)
    if spent:
        result.notes.append(f"provider charged: {spent}")
    return result
