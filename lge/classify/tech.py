"""detect_tech — P7, the tech fingerprinter.

Bump the caller's stored tech norm/version whenever this output can change for any
input. Matches script src, link href, iframe src, form action and inline script text
against the vendor patterns in config/tech_fingerprints.yml. No vendor API needed —
this is a pure function over already-fetched HTML.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

import lxml.etree
import lxml.html
import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tech_fingerprints.yml"

_EVIDENCE_MAX_LEN = 200


@dataclass(frozen=True, slots=True)
class TechHit:
    name: str
    category: str
    evidence: str


@functools.lru_cache(maxsize=1)
def _load_config() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _compiled_tools() -> tuple[dict, ...]:
    cfg = _load_config()
    tools = []
    for tool in cfg["tools"]:
        tools.append(
            {
                "name": tool["name"],
                "category": tool["category"],
                "compiled": tuple(re.compile(p, re.IGNORECASE) for p in tool["patterns"]),
            }
        )
    return tuple(tools)


# URL- and host-shaped tokens inside an inline script. The fingerprints are
# matched against these, never against the script itself: every fingerprint
# begins with `(?:[\w-]+\.)*`, which backtracks quadratically on minified
# JavaScript ("a.b.c.d(...)" for 300 KB), and one firm's thirty pages took
# P7 minutes of CPU per page on the probe (D-034).
_URL_TOKEN_RE = re.compile(
    r"(?:https?:)?//[\w.-]+(?:/[^\s'\"<>)]*)?"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|io|app|cloud|us|ai|co|legal|law|chat|live)\b",
    re.IGNORECASE,
)
_MAX_TOKENS_PER_SCRIPT = 500


def _script_tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_TOKEN_RE.finditer(text):
        token = m.group(0)
        if token not in seen:
            seen.add(token)
            out.append(token)
            if len(out) >= _MAX_TOKENS_PER_SCRIPT:
                break
    return out


def _collect_haystacks(tree: lxml.html.HtmlElement) -> list[str]:
    haystacks: list[str] = []
    for el in tree.iter("script"):
        src = el.get("src")
        if src:
            haystacks.append(src)
        if el.text and el.text.strip():
            haystacks.extend(_script_tokens(el.text))
    for el in tree.iter("link"):
        href = el.get("href")
        if href:
            haystacks.append(href)
    for el in tree.iter("iframe"):
        src = el.get("src")
        if src:
            haystacks.append(src)
    for el in tree.iter("form"):
        action = el.get("action")
        if action:
            haystacks.append(action)
    return haystacks


def detect_tech(html: str) -> list[TechHit]:
    """Scan `html` for known legal case-management/intake tooling.

    Returns hits deduplicated by name, in config file order. Tolerates broken HTML
    (lxml's HTML parser recovers from malformed markup); an unparseable or empty
    document yields an empty list rather than raising.
    """
    if not html or not html.strip():
        return []
    try:
        tree = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return []

    haystacks = _collect_haystacks(tree)
    if not haystacks:
        return []

    hits: list[TechHit] = []
    seen: set[str] = set()
    for tool in _compiled_tools():
        if tool["name"] in seen:
            continue
        for hay in haystacks:
            for pattern in tool["compiled"]:
                m = pattern.search(hay)
                if m:
                    evidence = hay if len(hay) <= _EVIDENCE_MAX_LEN else hay[:_EVIDENCE_MAX_LEN]
                    hits.append(TechHit(tool["name"], tool["category"], evidence))
                    seen.add(tool["name"])
                    break
            if tool["name"] in seen:
                break
    return hits


def primary_cms(hits: list[TechHit]) -> str | None:
    for hit in hits:
        if hit.category == "cms":
            return hit.name
    return None
