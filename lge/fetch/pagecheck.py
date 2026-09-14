"""What a fetched page is, before anyone reads it for meaning.

  looks_like_soft_404  -- a 200 whose content is an error page. The careers
                          watcher learned this the hard way (v2); every page
                          kind needs it (D-030).
  looks_like_js_shell  -- a page that is an empty application shell until
                          JavaScript runs: a root element and scripts, almost
                          no text. Worth a browser render; a thin static page
                          is not.
  visible_words        -- the cheap word count both tests share.
"""

from __future__ import annotations

import re

import lxml.etree
import lxml.html

_SOFT_404_RE = re.compile(
    r"\b(?:page\s+(?:you\s+(?:were|are)\s+looking\s+for\s+)?(?:could\s+not|cannot|can't|"
    r"couldn't)\s+be\s+found|page\s+not\s+found|error\s+404|404\s+error|404\s+not\s+found"
    r"|no\s+longer\s+(?:exists|available)|oops!?\s+(?:that|this)\s+page|^\s*404\b)",
    re.IGNORECASE | re.MULTILINE,
)
_SHELL_MARKER_RE = re.compile(
    r"""id=["'](?:root|app|__next|__nuxt|__layout|main-root|react-root|svelte)["']"""
    r"|data-reactroot|ng-version=|ng-app\b|<app-root|data-v-app|__NEXT_DATA__|window\.__NUXT__",
    re.IGNORECASE,
)

SOFT_404_MAX_WORDS = 250
SHELL_MAX_WORDS = 60
SHELL_MIN_SCRIPTS = 3


def _tree(html: str) -> lxml.html.HtmlElement | None:
    if not html or not html.strip():
        return None
    try:
        return lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return None


def visible_text(html: str) -> str:
    tree = _tree(html)
    if tree is None:
        return ""
    for el in tree.xpath("//script|//style|//noscript|//template"):
        el.drop_tree()
    # text nodes joined with a space: "<p>a</p><p>b</p>" is two words, not "ab"
    return " ".join(" ".join(tree.itertext()).split())


def visible_words(html: str) -> int:
    return len(visible_text(html).split())


def looks_like_soft_404(html: str) -> bool:
    """Short pages only, so a long article that mentions a 404 is never discarded."""
    text = visible_text(html)
    return len(text.split()) < SOFT_404_MAX_WORDS and bool(_SOFT_404_RE.search(text))


def looks_like_js_shell(html: str) -> bool:
    """Almost no visible text, and either a framework root element or several
    scripts: the page's content arrives only once JavaScript runs."""
    if not html:
        return False
    if visible_words(html) >= SHELL_MAX_WORDS:
        return False
    if _SHELL_MARKER_RE.search(html):
        return True
    return len(re.findall(r"<script\b", html, re.IGNORECASE)) >= SHELL_MIN_SCRIPTS
