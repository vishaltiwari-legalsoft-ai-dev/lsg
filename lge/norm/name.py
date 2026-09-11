"""norm_name — the trigram-matching name_stem.

Bump NORM_VERSION["norm_name"] whenever output can change for any input.

Token order is preserved throughout: trigram similarity (used downstream for fuzzy
firm-name matching) is order-sensitive, so "Jones Smith" and "Smith Jones" must not
collapse to the same stem.
"""

from __future__ import annotations

import re

# The spec's literal stopword list.
SPEC_STOPWORDS: frozenset[str] = frozenset(
    {
        "law",
        "laws",
        "legal",
        "office",
        "offices",
        "attorney",
        "attorneys",
        "firm",
        "group",
        "associates",
        "pllc",
        "pc",
        "llp",
        "llc",
        "ltd",
        "and",
        "the",
    }
)

# Extension beyond the spec list. "Law Offices of X" is the single most common
# small-firm naming pattern and stems to "of x" without dropping "of" too; Florida
# (and some other) firms commonly suffix "P.A." (professional association), which is
# otherwise indistinguishable in economic meaning from "PC"/"LLC" already in scope.
EXTENSION_STOPWORDS: frozenset[str] = frozenset(
    {
        "of",
        "pa",
        "esq",
        "esquire",
        "lawyer",
        "lawyers",
        "chartered",
        "chtd",
        "inc",
        "apc",
        "aplc",
        "plc",
        "lpa",
        "psc",
        "sc",
        "corp",
        "corporation",
        "professional",
        "association",
        "co",
        "company",
    }
)

_ALL_STOPWORDS = SPEC_STOPWORDS | EXTENSION_STOPWORDS

# Two or more single letters each followed by a period (with optional spacing) —
# "P.C.", "L.L.P.", "P. C." — joined into one token before punctuation stripping so
# they still match a stopword instead of shattering into stray single letters.
_DOTTED_ABBR_RE = re.compile(r"\b(?:[a-z]\.\s*){2,}")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _join_dotted_abbreviations(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        letters = re.findall(r"[a-z]", m.group(0))
        return "".join(letters) + " "

    return _DOTTED_ABBR_RE.sub(repl, text)


def norm_name(name: str | None) -> str:
    """Lowercase, stopword-stripped name_stem with token order preserved.

    Falls back to the (punctuation-stripped, "the"-only-removed) full name when
    stopword removal would otherwise leave nothing, or leave only single-character
    tokens — e.g. a firm literally named "The Law Offices of Law & Law".
    """
    if not name or not name.strip():
        return ""

    text = name.lower()
    text = _join_dotted_abbreviations(text)
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return ""

    tokens = text.split(" ")
    remaining = [t for t in tokens if t not in _ALL_STOPWORDS]

    if not remaining or all(len(t) == 1 for t in remaining):
        fallback_tokens = [t for t in tokens if t != "the"]
        return " ".join(fallback_tokens)

    return " ".join(remaining)
