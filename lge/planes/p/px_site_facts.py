"""px_site_facts -- what a firm's own pages say about it (Plane P, D-031).

Reads the STORED HTML of every page P2 fetched for a firm (never re-fetches)
and writes deterministic claims under source `site:page`:

  * phone_e164, address, city   -- from the contact page first, then the
                                   locations, home and about pages (reconciled
                                   onto the firm row after site:jsonld)
  * office_locations, office_count -- every distinct street address printed
  * site_people, staff_listed   -- names and designations from the attorneys,
                                   team and about pages; r_site_contacts turns
                                   them into contact rows
  * testimonials, site_review_summary -- what clients say, and the rating the
                                   site advertises about itself
  * social_links, review_profiles, google_maps_url -- where else the firm is
  * recent_posts, latest_post_date, growth_news -- what the firm has been up
                                   to; growth headlines feed Part D's signals
  * live_chat_vendor, online_intake_form, copyright_year -- what the site runs
  * site_gaps                   -- what it lacks: no careers page, no intake
                                   form, no chat, no Spanish, stale copyright,
                                   no testimonials, stale blog, no support
                                   staff listed, no social or review links

Absence is only claimed when the page that would carry the thing was read:
no home page fetched, no gap list. Idempotent per firm on the documents read
and the config; a config edit re-reads every firm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from lge.fetch.config import kinds_version, wanted_kinds
from lge.planes.p import _site_facts as sf
from lge.planes.p._claims import (
    claim_run,
    compute_input_hash,
    config_fingerprint,
    fetch_documents,
    read_html,
    select_firm_ids,
    write_claim,
)
from lge.planes.p.px_site_rules import _ES_URL_PATH_RE, _HREFLANG_ES_RE, _spanish_patterns
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

_COMPONENT = "px_site_facts"
# v5: a heading is the designation of the names under it.
# v6: a run retires what it did not re-derive (D-044).
_VERSION = "px_facts:v6"
_MAX_PEOPLE_PER_FIRM = 60
_SOURCE = "site:page"
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "site_facts.yml"

# Pages read for each fact, most authoritative first.
_CONTACT_ORDER = ("contact", "locations", "home", "about", "attorneys", "team", "other")
_PEOPLE_KINDS = ("attorneys", "team", "about", "home", "contact")
_LOOSE_PEOPLE_KINDS = ("attorneys", "team")
_NEWS_KINDS = ("news", "home")
_STALE_NEWS_DAYS = 365
_STALE_COPYRIGHT_YEARS = 2

_CONFIDENCE = 0.85
_CONFIDENCE_ADDRESS = 0.8
_CONFIDENCE_LIST = 0.8
# attorneys counted by name on the attorneys/team page: a floor the firm itself
# printed, not a statement of size. Above reconcile's 0.6 bar so it can tier;
# below the LLM's stated count, which outranks it (config/precedence.yml).
_CONFIDENCE_COUNTED = 0.65


@dataclass
class Facts:
    phone: tuple[str, str, Any] | None = None  # (e164, raw, fetched_at)
    address: tuple[dict, str, Any] | None = None  # (claim shape, raw, fetched_at)
    offices: list[dict] = field(default_factory=list)
    people: list[dict] = field(default_factory=list)
    testimonials: list[dict] = field(default_factory=list)
    review_summary: dict | None = None
    social: dict[str, str] = field(default_factory=dict)
    review_profiles: dict[str, str] = field(default_factory=dict)
    maps_url: str | None = None
    posts: list[dict] = field(default_factory=list)
    chat_vendor: str | None = None
    intake_form: bool = False
    copyright_year: int | None = None
    spanish: bool = False
    kinds_read: set[str] = field(default_factory=set)
    newest: Any = None
    people_page_url: str | None = None


def _kind_rank(kind: str) -> int:
    return _CONTACT_ORDER.index(kind) if kind in _CONTACT_ORDER else len(_CONTACT_ORDER)


def read_firm(docs: list[dict], domain: str | None, store: ObjectStore) -> Facts:
    """Every fact the stored pages hold, read once each in contact-page-first
    order so the first phone or address found is the most authoritative."""
    facts = Facts()
    people: dict[str, dict] = {}
    people_order: list[str] = []
    posts: dict[str, dict] = {}
    seen_offices: set[str] = set()
    seen_quotes: set[str] = set()

    for doc in sorted(docs, key=lambda d: (_kind_rank(d["page_kind"]), d["fetched_at"])):
        html = read_html(store, doc["object_key"])
        tree = sf.parse(html)
        if tree is None:
            continue
        kind = doc["page_kind"]
        url = doc["url"]
        fetched_at = doc["fetched_at"]
        facts.kinds_read.add(kind)
        facts.newest = max(facts.newest, fetched_at) if facts.newest else fetched_at
        text = sf.page_text(tree)

        if facts.phone is None:
            phones = sf.find_phones(tree)
            if phones:
                facts.phone = (phones[0][0], phones[0][1], fetched_at)
        for addr in sf.find_addresses(text):
            key = addr["addr_hash"] or f"{addr['city']}|{addr['state']}"
            if key in seen_offices:
                continue
            seen_offices.add(key)
            facts.offices.append({**addr, "url": url})
            if facts.address is None:
                # a copy without the printed text: the claim's value must match
                # site:jsonld's six keys exactly, or two sources printing the
                # same office never "agree" in reconcile (D-031)
                value = {k: v for k, v in addr.items() if k != "raw"}
                facts.address = (value, addr["raw"], fetched_at)

        if kind in _PEOPLE_KINDS:
            for person in sf.find_people(tree, url, strict=kind not in _LOOSE_PEOPLE_KINDS):
                if kind == "attorneys" and not person["title"]:
                    # The page itself is the designation: a name listed on the
                    # attorneys page is an attorney (hallandlampros.com lists
                    # eight with no title printed beside them).
                    person = {**person, "title": "Attorney", "title_inferred": True}
                key = person["name"].casefold()
                if key not in people:
                    people[key] = {**person, "page_url": url}
                    people_order.append(key)
                    if facts.people_page_url is None and kind in _LOOSE_PEOPLE_KINDS:
                        facts.people_page_url = url
                elif person["title"] and not people[key]["title"]:
                    people[key].update(title=person["title"], confidence=person["confidence"])

        for quote in sf.find_testimonials(tree):
            key = quote["quote"][:80].casefold()
            if key not in seen_quotes:
                seen_quotes.add(key)
                facts.testimonials.append({**quote, "url": url})
        if facts.review_summary is None:
            summary = sf.find_review_summary(text)
            if summary:
                facts.review_summary = {**summary, "url": url}

        links = sf.find_links(tree, url)
        for plat, link in links["social"].items():
            facts.social.setdefault(plat, link)
        for plat, link in links["review"].items():
            facts.review_profiles.setdefault(plat, link)
        if facts.maps_url is None:
            facts.maps_url = links["maps"]

        if kind in _NEWS_KINDS and domain:
            for post in sf.find_posts(tree, url, domain):
                posts.setdefault(post["url"], post)

        if facts.chat_vendor is None:
            facts.chat_vendor = sf.find_chat_vendor(html)
        if kind in ("contact", "home") and not facts.intake_form:
            facts.intake_form = sf.has_intake_form(tree, html)
        year = sf.copyright_year(text)
        if year and (facts.copyright_year is None or year > facts.copyright_year):
            facts.copyright_year = year
        if not facts.spanish:
            facts.spanish = bool(
                _HREFLANG_ES_RE.search(html)
                or _ES_URL_PATH_RE.search(url)
                or any(p.search(text) for p in _spanish_patterns())
            )

    # A firm has at most sixty people worth naming: those with a title and a
    # profile page first, so a directory of a hundred bare names is trimmed
    # to the ones outreach can use.
    position = {k: i for i, k in enumerate(people_order)}
    ranked = sorted(
        (people[k] for k in people_order),
        key=lambda p: (p["title"] is None, p["url"] is None, position[p["name"].casefold()]),
    )
    facts.people = ranked[:_MAX_PEOPLE_PER_FIRM]
    facts.posts = sorted(posts.values(), key=lambda p: p["date"], reverse=True)[:12]
    return facts


def site_gaps(facts: Facts, *, today: date | None = None) -> list[dict[str, str]]:
    """What the site lacks, judged only where the page that would carry the
    thing was read. Each entry names the gap and says how it was judged."""
    today = today or date.today()
    gaps: list[dict[str, str]] = []
    read = facts.kinds_read
    if not read:
        return gaps
    # A gap about a page kind is claimed only when the engine reads that kind:
    # "no news page" means nothing on a crawl that never looks for one.
    wanted = set(wanted_kinds())

    def gap(name: str, evidence: str) -> None:
        gaps.append({"gap": name, "evidence": evidence})

    if "careers" in wanted and "careers" not in read:
        gap("no_careers_page", "no careers page among the pages read")
    if read & {"contact", "home"} and not facts.intake_form:
        gap("no_online_intake", "no intake form on the contact or home page")
    if "home" in read and not facts.chat_vendor:
        gap("no_live_chat", "no live-chat script on the pages read")
    if "home" in read and not facts.spanish:
        gap("no_spanish", "no Spanish page, hreflang or phrase on the pages read")
    if facts.copyright_year and facts.copyright_year <= today.year - _STALE_COPYRIGHT_YEARS:
        gap("stale_copyright", f"footer says © {facts.copyright_year}")
    if "testimonials" in wanted and not facts.testimonials and read & {"home", "testimonials"}:
        gap("no_testimonials", "no client quotes on the pages read")
    if "news" in wanted and "news" not in read and "home" in read:
        gap("no_news", "no blog or news page among the pages read")
    elif facts.posts:
        latest = date.fromisoformat(facts.posts[0]["date"])
        if latest < today - timedelta(days=_STALE_NEWS_DAYS):
            gap("stale_news", f"latest post {latest.isoformat()}")
    if read & set(_LOOSE_PEOPLE_KINDS) and facts.people:
        if not any(sf.title_class(p["title"]) == "support" for p in facts.people):
            gap("no_support_staff_listed",
                f"{len(facts.people)} people named, none with a support title")
    if "home" in read and not facts.social:
        gap("no_social_presence", "no social profile linked from the pages read")
    if "home" in read and not (facts.maps_url or facts.review_profiles):
        gap("no_review_link", "no Google, Avvo or Yelp link on the pages read")
    return gaps


def staff_listed(people: list[dict]) -> dict[str, int]:
    counts = {"attorneys": 0, "support": 0, "other": 0}
    for person in people:
        cls = sf.title_class(person["title"])
        counts["attorneys" if cls == "attorney" else cls] += 1
    counts["total"] = len(people)
    return counts


def write_facts(conn: Any, firm_id: Any, facts: Facts) -> int:
    """One claim per fact the pages held. Returns the number of claims
    written or changed."""
    if facts.newest is None:
        return 0
    at = facts.newest
    written = 0

    def claim(
        attr: str, value: Any, confidence: float, evidence: str | None, when: Any = None
    ) -> None:
        nonlocal written
        if write_claim(conn, firm_id, attr, value, _SOURCE, confidence, evidence, when or at):
            written += 1

    if facts.phone:
        e164, raw, when = facts.phone
        claim("phone_e164", e164, _CONFIDENCE, raw, when)
    if facts.address:
        value, raw, when = facts.address
        claim("address", value, _CONFIDENCE_ADDRESS, raw, when)
        if value.get("city"):
            claim("city", value["city"], _CONFIDENCE_ADDRESS, raw, when)
    # A list fact is written whenever the pages that carry it were read --
    # empty included -- so a re-read that finds nothing replaces the earlier
    # claim instead of leaving it standing (same observed_at: updated in place).
    read = facts.kinds_read
    if facts.offices or read & {"contact", "locations"}:
        offices = [
            {k: o.get(k) for k in ("street_norm", "unit", "city", "state", "zip5", "url")}
            for o in facts.offices
        ]
        claim("office_locations", offices, _CONFIDENCE_LIST,
              facts.offices[0]["raw"] if facts.offices else "no street address on the pages read")
        claim("office_count", len(offices), _CONFIDENCE_LIST,
              "; ".join(f"{o['city']}, {o['state']}" for o in offices[:6]) or "none found")
    if facts.people or read & set(_PEOPLE_KINDS):
        claim("site_people", facts.people, _CONFIDENCE_LIST,
              f"{len(facts.people)} people named on {facts.people_page_url or 'the site'}")
        counts = staff_listed(facts.people)
        claim("staff_listed", counts, _CONFIDENCE_LIST,
              f"{counts['attorneys']} attorneys, {counts['support']} support, "
              f"{counts['other']} other")
        # The firm's own attorneys page is a source of firm size (D-044): the
        # names it lists are a floor. Only from a page that lists the team --
        # two names in a footer say nothing about how many there are.
        if counts["attorneys"] >= 1 and read & set(_LOOSE_PEOPLE_KINDS):
            claim("attorney_count", counts["attorneys"], _CONFIDENCE_COUNTED,
                  f"{counts['attorneys']} attorney(s) named on "
                  f"{facts.people_page_url or 'the site'}")
    if facts.testimonials or read & {"testimonials", "home"}:
        first = facts.testimonials[0] if facts.testimonials else None
        claim("testimonials", facts.testimonials[:10], _CONFIDENCE_LIST,
              f"{len(facts.testimonials)} quotes; first: {first['quote'][:100]}"
              if first else "no client quotes on the pages read")
    if facts.review_summary:
        claim("site_review_summary", facts.review_summary, _CONFIDENCE_LIST,
              facts.review_summary.get("evidence"))
    if facts.social:
        claim("social_links", facts.social, _CONFIDENCE, ", ".join(sorted(facts.social)))
    if facts.review_profiles:
        claim("review_profiles", facts.review_profiles, _CONFIDENCE,
              ", ".join(sorted(facts.review_profiles)))
    if facts.maps_url:
        claim("google_maps_url", facts.maps_url, _CONFIDENCE, facts.maps_url)
    if facts.posts or "news" in read:
        claim("recent_posts", facts.posts, _CONFIDENCE_LIST,
              f"{facts.posts[0]['date']}: {facts.posts[0]['title'][:80]}"
              if facts.posts else "no dated posts on the pages read")
        growth = sf.growth_news(facts.posts)
        claim("growth_news", growth, _CONFIDENCE_LIST,
              f"{growth[0]['date']}: {growth[0]['title'][:80]}" if growth else "none")
    if facts.posts:
        claim("latest_post_date", facts.posts[0]["date"], _CONFIDENCE_LIST,
              facts.posts[0]["title"][:100])
    if facts.chat_vendor:
        claim("live_chat_vendor", facts.chat_vendor, _CONFIDENCE, facts.chat_vendor)
    if facts.kinds_read & {"contact", "home"}:
        claim("online_intake_form", facts.intake_form, _CONFIDENCE,
              "a form with contact fields" if facts.intake_form else "no form found")
    if facts.copyright_year:
        claim("copyright_year", facts.copyright_year, _CONFIDENCE, f"© {facts.copyright_year}")
    gaps = site_gaps(facts)
    if facts.kinds_read:
        claim("site_gaps", gaps, _CONFIDENCE_LIST,
              ", ".join(g["gap"] for g in gaps) if gaps else "nothing missing among the pages read")
    return written


def _firm_domain(conn: Any, firm_id: Any) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT domain FROM firm WHERE id = %s", (firm_id,))
        row = cur.fetchone()
    return row["domain"] if row else None


@component(
    _COMPONENT,
    "P",
    "Site facts: phones, offices, people and designations, testimonials, news, links, gaps",
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    store = store or get_store()
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),  # type: ignore[arg-type]
        limit=opts.get("limit"),  # type: ignore[arg-type]
    )
    version = f"{_VERSION}:{config_fingerprint(_CONFIG_PATH)}:{kinds_version()}"
    claims_written = 0
    claims_retired = 0

    for firm_id in firm_ids:
        try:
            docs = fetch_documents(
                ctx.conn, firm_id, page_kinds=wanted_kinds(), status_200_only=True
            )
            if not docs:
                # no page of a kind the engine reads: nothing this reader once
                # said about the firm can stand
                with claim_run(ctx.conn, firm_id, _SOURCE) as run:
                    pass
                claims_retired += run.retired
                result.skipped += 1
                continue
            domain = _firm_domain(ctx.conn, firm_id)
            input_hash = compute_input_hash(
                [*(d["content_hash"] for d in docs), domain or ""], version
            )
            with ctx.once(_COMPONENT, str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue
                with claim_run(ctx.conn, firm_id, _SOURCE) as run:
                    facts = read_firm(docs, domain, store)
                    claims_written += write_facts(ctx.conn, firm_id, facts)
                claims_retired += run.retired
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"{_COMPONENT} firm={firm_id}: {exc}")
        ctx.checkpoint()

    result.notes.append(
        f"claims written or changed: {claims_written}; retired: {claims_retired}"
    )
    return result
