"""The parsers behind px_site_facts: pure functions over one stored page.

Each reads an lxml tree (or the page's text) and returns plain data; none
touches the database or the network. What they look for is what an SDR reads
off a firm's site before writing: who works there and what they do, where the
offices are, how to reach them, what clients say, what the firm has been up
to, and what the site is missing (D-031).
"""

from __future__ import annotations

import functools
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import lxml.etree
import lxml.html
import yaml

from lge.classify.people import person_name
from lge.norm import norm_addr, norm_phone

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "site_facts.yml"

_WS_RE = re.compile(r"\s+")
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})


@functools.lru_cache(maxsize=1)
def config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _alternation(key: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in config()[key]), re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def _title_re() -> re.Pattern[str]:
    return _alternation("title_words")


@functools.lru_cache(maxsize=1)
def _support_re() -> re.Pattern[str]:
    return _alternation("support_titles")


@functools.lru_cache(maxsize=1)
def _attorney_re() -> re.Pattern[str]:
    return _alternation("attorney_titles")


@functools.lru_cache(maxsize=1)
def _not_a_person_re() -> re.Pattern[str]:
    return re.compile(
        r"\b(?:" + "|".join(f"(?:{p})" for p in config()["not_a_person_words"]) + r")\b",
        re.IGNORECASE,
    )


@functools.lru_cache(maxsize=1)
def _not_a_title_re() -> re.Pattern[str]:
    return _alternation("not_a_title_words")


@functools.lru_cache(maxsize=1)
def _profile_path_re() -> re.Pattern[str]:
    return re.compile(config()["profile_path"], re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def _growth_re() -> re.Pattern[str]:
    return _alternation("growth_cues")


@functools.lru_cache(maxsize=1)
def _chat_vendors() -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple(
        (re.compile(pat, re.IGNORECASE), name) for pat, name in config()["chat_vendors"].items()
    )


@functools.lru_cache(maxsize=1)
def _intake_markers_re() -> re.Pattern[str]:
    return _alternation("intake_form_markers")


@functools.lru_cache(maxsize=1)
def _maps_re() -> re.Pattern[str]:
    return re.compile("|".join(config()["link_platforms"]["maps"]), re.IGNORECASE)


def parse(html: str) -> lxml.html.HtmlElement | None:
    if not html or not html.strip():
        return None
    try:
        tree = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return None
    for el in list(tree.iter(*_SKIP_TAGS)):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    return tree


def clean(text: str | None) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def chunks(el: lxml.html.HtmlElement) -> list[str]:
    """The element's text as the reader sees it: one entry per text node,
    blanks dropped -- a name and the title under it come back as two
    entries, not one glued string."""
    return [c for c in (clean(t) for t in el.itertext()) if c]


def page_text(tree: lxml.html.HtmlElement) -> str:
    return " ".join(chunks(tree))


# ---------------------------------------------------------------------------
# Phones and addresses
# ---------------------------------------------------------------------------

_PHONE_TEXT_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]*)?\(?\b[2-9]\d{2}\)?[\s.-]*[2-9]\d{2}[\s.-]*\d{4}\b(?!\d)"
)


def find_phones(tree: lxml.html.HtmlElement) -> list[tuple[str, str]]:
    """(e164, as printed) in page order: tel: links first, then numbers in
    the text. A number that does not parse as a valid US line is dropped."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        e164 = norm_phone(raw)
        if e164 and e164 not in seen:
            seen.add(e164)
            out.append((e164, clean(raw)))

    for a in tree.iter("a"):
        href = (a.get("href") or "").strip()
        if href.lower().startswith("tel:"):
            add(href[4:].split("?", 1)[0])
    for m in _PHONE_TEXT_RE.finditer(page_text(tree)):
        add(m.group(0))
    return out


_STREET_WORD = (
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|place|pl|"
    r"parkway|pkwy|highway|hwy|circle|cir|plaza|square|sq|terrace|ter|trail|trl|"
    r"broadway|turnpike|tpke|route|rte|loop|expressway|expy|freeway|fwy|pike|run|row|"
    r"n|s|e|w|north|south|east|west)\.?"
)
_DIRECTION = (
    r"(?:\s+(?:n|s|e|w|ne|nw|se|sw|north|south|east|west|northeast|northwest|southeast|"
    r"southwest)\.?)?"
)
_UNIT = r"(?:\s*,?\s*(?:suite|ste\.?|unit|#|floor|fl\.?|bldg\.?|building|room|rm\.?)\s*[\w-]+)?"
# The street name is words, never a bare number: a zip that precedes the next
# office's house number on the page must not be read as that office's number.
_ADDRESS_RE = re.compile(
    r"(?P<street>\d{1,6}[a-z]?" + _DIRECTION
    + r"(?:\s+[a-z][a-z0-9'.-]*){1,5}?\s+" + _STREET_WORD + _DIRECTION + _UNIT + r")"
    r"[\s,]+(?P<city>[a-z][a-z.'-]+(?:\s+[a-z][a-z.'-]+){0,3}),?\s+"
    r"(?P<state>[a-z]{2})\.?,?\s+(?P<zip>\d{5}(?:-\d{4})?)\b",
    re.IGNORECASE,
)


def find_addresses(text: str) -> list[dict[str, Any]]:
    """Every US street address in the text, in order, each as P5's address
    claim shape plus `raw` (the address as printed) -- deduplicated on
    addr_hash, or on (city, state) when the street did not normalise."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _ADDRESS_RE.finditer(text):
        addr = norm_addr(
            m.group("street"), m.group("city"), m.group("state").upper(), m.group("zip")
        )
        if not (addr.street_norm or addr.zip5):
            continue
        key = addr.addr_hash or f"{addr.city}|{addr.state}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "street_norm": addr.street_norm, "unit": addr.unit, "city": addr.city,
            "state": addr.state, "zip5": addr.zip5, "addr_hash": addr.addr_hash,
            "raw": clean(m.group(0)),
        })
    return out


# ---------------------------------------------------------------------------
# People and their designations
# ---------------------------------------------------------------------------

_NAME_TAGS = ("h1", "h2", "h3", "h4", "h5", "strong", "b", "a", "span", "p", "div", "dt")
# Elements whose class says "this is a person's name". Not "title" (section
# titles) and not "team"/"card" (whole cards): those brought in headings.
_NAME_CLASS_RE = re.compile(
    r"\bname\b|member-name|attorney-name|staff-name|person|author|bio", re.I
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5"})
_MAX_TITLE_CHARS = 90
_MAX_CONTAINER_CHARS = 600
_MAX_PEOPLE = 60


_NAME_PARTICLES = frozenset({"de", "da", "del", "della", "di", "van", "von", "der", "la", "le",
                             "du", "dos", "das", "bin", "al", "el", "y", "st."})


def name_like(text: str) -> str | None:
    """A person's name as printed on a page: `person_name` plus the page
    rules -- no job word in it ("Senior Litigation Paralegal" is a title, not
    a person), no heading/place/practice word ("Bronx Locations", "Premises
    Liability"), Title Case tokens ("Learn more" is a link), no punctuation
    that a name never carries, and a surname longer than one letter."""
    text = clean(text)
    if not text or ":" in text or "?" in text or "!" in text:
        return None
    name = person_name(text)
    if not name or _title_re().search(name) or _not_a_person_re().search(name):
        return None
    tokens = name.split()
    if len(tokens[-1].rstrip(".")) < 2:
        return None
    for token in tokens:
        if token.lower() in _NAME_PARTICLES or token[0].isupper():
            continue
        return None
    return name


def looks_like_title(text: str) -> bool:
    """A short line naming a job -- not a sentence about one, not a link to
    one ("View Attorney Bio"), not an organisation ("Illinois Trial Lawyers
    Association") and not a page heading ("Atlanta Wrongful Death Lawyers")."""
    text = clean(text)
    if not text or len(text) > _MAX_TITLE_CHARS or text.count(".") > 2:
        return False
    if _not_a_title_re().search(text):
        return False
    return bool(_title_re().search(text))


def title_class(title: str | None) -> str:
    """'support' | 'attorney' | 'other' -- support first, so "Litigation
    Paralegal" is support though "Litigation" alone is not a title."""
    if not title:
        return "other"
    if _support_re().search(title):
        return "support"
    if _attorney_re().search(title):
        return "attorney"
    return "other"


def _title_near(el: lxml.html.HtmlElement, name: str) -> str | None:
    """The job title printed with the name: the first title-looking chunk
    after the name (before the next person's name) in the nearest ancestor
    that holds a bounded amount of text. In the smallest container only, a
    title printed above the name counts too."""
    node = el
    for level in range(5):
        parent = node.getparent()
        if parent is None:
            break
        node = parent
        pieces = chunks(node)
        if sum(len(p) for p in pieces) > _MAX_CONTAINER_CHARS:
            break
        try:
            at = next(i for i, p in enumerate(pieces) if name in p or p in name)
        except StopIteration:
            continue
        # The title is printed right next to the name: the next few chunks,
        # up to the next person's name.
        for piece in pieces[at + 1: at + 4]:
            if name_like(piece):
                break
            if looks_like_title(piece):
                return piece
        # Inside a small card (a few chunks) the title may sit above the name.
        # Never on a flat page, where "above" is the previous person's title.
        if level == 0 and len(pieces) <= 4:
            for piece in pieces[:at]:
                if looks_like_title(piece) and not name_like(piece):
                    return piece
    return None


def _name_from_slug(url: str) -> str | None:
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    words = [w for w in slug.replace("_", "-").split("-") if w]
    if not 2 <= len(words) <= 3 or any(ch.isdigit() for ch in slug):
        return None
    return name_like(" ".join(w.capitalize() for w in words))


def find_people(
    tree: lxml.html.HtmlElement, base_url: str, *, strict: bool = True
) -> list[dict[str, Any]]:
    """{name, title, url, confidence} for every person the page presents:
    a profile link (/attorneys/jane-doe), or a heading / name-classed element
    that is a person's name, with the title printed next to it. With `strict`
    (pages that are not team pages) a person needs a title or a profile link
    to count, so a home page's client quotes are not staff."""
    people: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def add(name: str, title: str | None, url: str | None, confidence: float) -> None:
        key = name.casefold()
        found = people.get(key)
        if found is None:
            people[key] = {"name": name, "title": title, "url": url, "confidence": confidence}
            order.append(key)
            return
        if title and not found["title"]:
            found["title"] = title
            found["confidence"] = max(found["confidence"], confidence)
        if url and not found["url"]:
            found["url"] = url

    for a in tree.iter("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0].split("?", 1)[0]
        if not _profile_path_re().search(urlsplit(absolute).path):
            continue
        name = name_like(a.text_content()) or _name_from_slug(absolute)
        if not name:
            continue
        title = _title_near(a, name)
        add(name, title, absolute, 0.8 if title else 0.6)

    for el in tree.iter(*_NAME_TAGS):
        if el.tag == "a":
            continue
        name_classed = bool(
            _NAME_CLASS_RE.search((el.get("class") or "") + " " + (el.get("id") or ""))
        )
        if el.tag not in _HEADING_TAGS and not name_classed:
            continue
        text = clean(el.text_content())
        if len(text) > 60:
            continue
        name = name_like(text)
        if not name:
            continue
        title = _title_near(el, name)
        # A name with no title printed next to it counts only when the page
        # says it is a name (a name-classed element) or a profile link already
        # brought it in: a bare heading that looks like a name is a heading.
        if not title and name.casefold() not in people and (strict or not name_classed):
            continue
        add(name, title, None, 0.8 if title else 0.5)

    out = [people[k] for k in order]
    return out[:_MAX_PEOPLE]


# ---------------------------------------------------------------------------
# Testimonials and review summaries
# ---------------------------------------------------------------------------

_QUOTE_CLASS_RE = re.compile(r"testimonial|review|quote", re.I)
_AUTHOR_CLASS_RE = re.compile(r"author|cite|client|name|by\b|who", re.I)
# Parts of a quote card that are not the quote: the author line, the stars,
# the photo, the heading, the navigation around a slider.
_NOT_A_QUOTE_CLASS_RE = re.compile(
    r"author|cite|client|name|\bby\b|who|star|rating|avatar|image|img|icon|photo|title|"
    r"heading|nav|button|btn|link|meta|date|slider-arrow|dots|summary|count|badge|logo",
    re.I,
)
_NOT_A_QUOTE_TAGS = frozenset({"a", "img", "h1", "h2", "h3", "h4", "h5", "h6", "cite", "time",
                               "button", "nav", "ul", "ol"})
_TRAILING_AUTHOR_RE = re.compile(r"\s*[-–—]\s*([A-Z][\w.' -]{1,60})$")
_RATING_RE = re.compile(r"(\d(?:\.\d)?)\s*(?:/\s*5|out\s+of\s+5|stars?\b)", re.I)
_MIN_QUOTE, _MAX_QUOTE = 40, 900
_MAX_TESTIMONIALS = 20


def find_testimonials(tree: lxml.html.HtmlElement) -> list[dict[str, Any]]:
    """{quote, author, rating} for each client quote on the page: <blockquote>s
    and testimonial/review-classed elements holding one quote's worth of text
    (40-900 chars) and no nested quote of their own."""
    candidates: list[lxml.html.HtmlElement] = []
    for el in tree.iter():
        if not isinstance(el.tag, str) or el.tag in _NOT_A_QUOTE_TAGS:
            continue
        attrs = (el.get("class") or "") + " " + (el.get("id") or "")
        if el.tag == "blockquote":
            candidates.append(el)
        elif _QUOTE_CLASS_RE.search(attrs) and not _NOT_A_QUOTE_CLASS_RE.search(attrs):
            candidates.append(el)
    leaves = [
        el for el in candidates
        if not any(other is not el and el in other.iterancestors() for other in candidates)
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for el in leaves:
        pieces = chunks(el)
        author = None
        for sub in el.iter():
            if sub is el or not isinstance(sub.tag, str):
                continue
            if sub.tag == "cite" or _AUTHOR_CLASS_RE.search(
                (sub.get("class") or "") + " " + (sub.get("id") or "")
            ):
                cand = clean(sub.text_content())
                if 2 <= len(cand) <= 80 and not _RATING_RE.search(cand):
                    author = cand.strip("-–— ")
                    break
        body = [p for p in pieces if p != author and not _RATING_RE.fullmatch(p)]
        quote = clean(" ".join(body)).strip("“”\"' ")
        if author is None:
            m = _TRAILING_AUTHOR_RE.search(quote)
            if m:
                author, quote = m.group(1).strip(), quote[: m.start()].strip("“”\"' ")
        if not _MIN_QUOTE <= len(quote) <= _MAX_QUOTE:
            continue
        key = quote[:80].casefold()
        if key in seen:
            continue
        seen.add(key)
        rating = None
        rm = _RATING_RE.search(" ".join(pieces))
        if rm and float(rm.group(1)) <= 5:
            rating = float(rm.group(1))
        out.append({"quote": quote[:600], "author": author, "rating": rating})
        if len(out) >= _MAX_TESTIMONIALS:
            break
    return out


_REVIEW_COUNT_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})*|\d+)\+?\s+(?:(?:five|5)[- ]star\s+|google\s+|client\s+|verified\s+)?"
    r"(?:reviews|ratings)\b",
    re.I,
)
_REVIEW_RATING_RE = re.compile(
    r"\b(\d\.\d)\s*(?:/\s*5|out\s+of\s+5|[- ]?stars?\b|star\s+rating)", re.I
)


def find_review_summary(text: str) -> dict[str, Any] | None:
    """The rating and review count a site advertises about itself ("4.9 stars
    from 312 reviews"), when it prints one."""
    rating = None
    count = None
    evidence = None
    for m in _REVIEW_RATING_RE.finditer(text):
        value = float(m.group(1))
        if 1.0 <= value <= 5.0:
            rating = value
            evidence = clean(text[max(0, m.start() - 30): m.end() + 30])
            break
    for m in _REVIEW_COUNT_RE.finditer(text):
        value = int(m.group(1).replace(",", ""))
        if value >= 5 and (count is None or value > count):
            count = value
            evidence = evidence or clean(text[max(0, m.start() - 30): m.end() + 30])
    if rating is None and count is None:
        return None
    return {"rating": rating, "count": count, "evidence": evidence}


# ---------------------------------------------------------------------------
# Links: social, review profiles, maps
# ---------------------------------------------------------------------------

_SHARE_LINK_RE = re.compile(r"/(?:sharer|share|intent|dialog)/|[?&]u=|[?&]url=", re.I)


def _host_platform(host: str, table: dict[str, str]) -> str | None:
    host = host.lower()
    for suffix, platform in table.items():
        if host == suffix or host.endswith("." + suffix):
            return platform
    return None


def find_links(tree: lxml.html.HtmlElement, base_url: str) -> dict[str, Any]:
    """{'social': {platform: url}, 'review': {platform: url}, 'maps': url|None}
    -- the first link per platform, share/intent links excluded."""
    platforms = config()["link_platforms"]
    social: dict[str, str] = {}
    review: dict[str, str] = {}
    maps: str | None = None
    for a in tree.iter("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        parts = urlsplit(url)
        host = parts.hostname or ""
        if maps is None and _maps_re().search(url):
            maps = url
            continue
        if _SHARE_LINK_RE.search(url):
            continue
        plat = _host_platform(host, platforms["social"])
        if plat and plat not in social and parts.path not in ("", "/"):
            social[plat] = url
            continue
        plat = _host_platform(host, platforms["review"])
        if plat and plat not in review:
            review[plat] = url
    return {"social": social, "review": review, "maps": maps}


# ---------------------------------------------------------------------------
# News: recent posts and growth cues
# ---------------------------------------------------------------------------

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "sept|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec"
)
_DATE_TEXT_RE = re.compile(
    rf"\b(?P<mon>{_MONTHS})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>20\d{{2}})\b"
    r"|\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>20\d{2})\b"
    r"|\b(?P<iso>20\d{2}-\d{2}-\d{2})(?!\d)",
    re.I,
)
_URL_DATE_RE = re.compile(r"/(20\d{2})/(\d{2})(?:/(\d{2}))?/")
_MONTH_INDEX = {
    name: i % 12 + 1
    for i, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
         "january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december")
    )
}
_MONTH_INDEX["sept"] = 9
_MAX_POSTS = 12


def parse_date_text(text: str) -> date | None:
    m = _DATE_TEXT_RE.search(text or "")
    if not m:
        return None
    try:
        if m.group("iso"):
            return date.fromisoformat(m.group("iso"))
        if m.group("mon"):
            return date(
                int(m.group("year")), _MONTH_INDEX[m.group("mon").lower()], int(m.group("day"))
            )
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
    except (ValueError, KeyError):
        return None


def _date_in(el: lxml.html.HtmlElement, url: str) -> date | None:
    for t in el.iter("time"):
        for cand in (t.get("datetime"), clean(t.text_content())):
            d = parse_date_text(cand or "")
            if d:
                return d
    m = _URL_DATE_RE.search(url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except ValueError:
            pass
    return parse_date_text(" ".join(chunks(el))[:400])


def find_posts(tree: lxml.html.HtmlElement, base_url: str, domain: str) -> list[dict[str, Any]]:
    """{title, url, date} for dated articles listed on the page, newest first.
    An <article> (or a heading with a same-site link) is a post when a date
    is printed with it or in its URL; undated links are not news."""
    posts: dict[str, dict[str, Any]] = {}
    containers = list(tree.iter("article"))
    if not containers:
        containers = [h for h in tree.iter("h1", "h2", "h3", "h4") if h.find(".//a") is not None]
    for el in containers:
        link = el.find(".//a[@href]")
        if link is None:
            continue
        url = urljoin(base_url, link.get("href")).split("#", 1)[0]
        host = urlsplit(url).hostname or ""
        if not (host == domain or host.endswith("." + domain)):
            continue
        if el.tag in ("h1", "h2", "h3", "h4"):
            title = clean(el.text_content())
            scope = el.getparent() if el.getparent() is not None else el
        else:
            heading = next((h for h in el.iter("h1", "h2", "h3", "h4")), None)
            title = clean((heading if heading is not None else link).text_content())
            scope = el
        if not title or len(title) < 8:
            continue
        posted = _date_in(scope, url)
        if posted is None or posted > date.today():
            continue
        if url not in posts:
            posts[url] = {"title": title[:200], "url": url, "date": posted.isoformat()}
    ordered = sorted(posts.values(), key=lambda p: p["date"], reverse=True)
    return ordered[:_MAX_POSTS]


def growth_news(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The posts whose headline describes growth -- a new office, a hire, a
    promotion -- with the cue that matched."""
    out = []
    for post in posts:
        m = _growth_re().search(post["title"])
        if m:
            out.append({**post, "cue": m.group(0).lower()})
    return out


# ---------------------------------------------------------------------------
# What the site runs, and what it lacks
# ---------------------------------------------------------------------------

_COPYRIGHT_RE = re.compile(
    r"(?:©|&copy;|\(c\)|copyright)\s*(?:\(c\)\s*)?(?:(?:19|20)\d{2}\s*[-–]\s*)?((?:19|20)\d{2})\b",
    re.I,
)
_INTAKE_FIELD_RE = re.compile(r"name|phone|email|message", re.I)


def find_chat_vendor(html: str) -> str | None:
    """The live-chat vendor whose script or iframe is on the page, if any."""
    for pattern, vendor in _chat_vendors():
        if pattern.search(html):
            return vendor
    return None


def has_intake_form(tree: lxml.html.HtmlElement, html: str) -> bool:
    """A form a prospective client can fill in: a form-builder embed, or a
    plain <form> with an email/phone/message field."""
    if _intake_markers_re().search(html):
        return True
    for form in tree.iter("form"):
        for inp in form.iter("input", "textarea"):
            kind = (inp.get("type") or "text").lower()
            name = (inp.get("name") or "") + " " + (inp.get("placeholder") or "")
            if inp.tag == "textarea" or kind in ("email", "tel"):
                return True
            if kind == "text" and _INTAKE_FIELD_RE.search(name):
                return True
    return any(_intake_markers_re().search(f.get("src") or "") for f in tree.iter("iframe"))


def copyright_year(text: str) -> int | None:
    years = [int(m.group(1)) for m in _COPYRIGHT_RE.finditer(text)]
    years = [y for y in years if 1990 <= y <= date.today().year + 1]
    return max(years) if years else None
