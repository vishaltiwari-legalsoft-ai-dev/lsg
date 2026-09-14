"""Personalization tokens -> column mapping (plan/outreach-journey.md
"Personalization tokens -> columns"). Pure functions only -- no DB access
here, so every resolution rule is unit-testable without Postgres.

A token that cannot resolve is represented as None. The renderer (render.py
/ build.py) is what turns "required token is None" into a lead exclusion --
this module never raises and never guesses.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

# ---------------------------------------------------------------------------
# {first_name} <- contact.full_name
# ---------------------------------------------------------------------------

# Prefixes only (per the task: "Dr.", "Mr." style honorifics). Deliberately
# narrow -- this is a greeting-line parser, not a general name library.
_HONORIFICS = frozenset(
    {"dr", "mr", "mrs", "ms", "miss", "mx", "prof", "professor", "atty", "attorney"}
)

_WHITESPACE_RE = re.compile(r"\s+")


def resolve_first_name(full_name: str | None) -> str | None:
    """First given name for the greeting line.

    Handles three shapes:
      "Dr. John Smith"  -> "John"   (leading honorific stripped)
      "Smith, John Q."  -> "John"   ("Last, First [Middle]" comma format)
      "John Smith"      -> "John"
      "Mr. Smith"       -> None     (honorific + a single bare token is a
                                      surname-only record -- we do not know
                                      the first name, so this must resolve
                                      to None, not "Smith")
      "" / None         -> None     (missing -- excluded upstream)
    """
    if not full_name or not full_name.strip():
        return None
    name = _WHITESPACE_RE.sub(" ", full_name.strip())

    if "," in name:
        _, _, rest = name.partition(",")
        tokens = [t for t in rest.strip().split(" ") if t]
        # A comma-formatted name occasionally still carries a title after the
        # comma ("Smith, Dr. John") -- strip it the same way.
        tokens = [t for t in tokens if t.strip(".").lower() not in _HONORIFICS]
        if not tokens:
            return None
        first = tokens[0].strip(".,")
        return first or None

    tokens = [t for t in name.split(" ") if t]
    if not tokens:
        return None

    had_honorific = tokens[0].strip(".").lower() in _HONORIFICS
    if had_honorific:
        tokens = tokens[1:]
        if len(tokens) < 1:
            return None
        if len(tokens) == 1:
            # honorific + exactly one remaining token == surname only
            # ("Mr. Smith") -- the first name is genuinely unknown.
            return None
        first = tokens[0].strip(".,")
        return first or None

    first = tokens[0].strip(".,")
    return first or None


# ---------------------------------------------------------------------------
# {role} / {role_2} <- signal.evidence -> normalize_title() slug, humanised
# ---------------------------------------------------------------------------


def humanize_role(canonical_role: str | None) -> str | None:
    """Slug -> human text. Every role slug in config/title_synonyms.yml reads
    fine as `slug.replace("_", " ")` ("demand_writer" -> "demand writer",
    "document_collector" -> "document collector", "paralegal" -> "paralegal")."""
    if not canonical_role or not canonical_role.strip():
        return None
    return canonical_role.strip().replace("_", " ")


def role_from_evidence(evidence: dict | None) -> str | None:
    """{role} <- evidence.canonical_role, humanised; falls back to the raw
    evidence.title when canonical_role is absent or unmapped (plan's own
    fallback rule)."""
    if not evidence:
        return None
    humanised = humanize_role(evidence.get("canonical_role"))
    if humanised:
        return humanised
    title = evidence.get("title")
    if title and str(title).strip():
        return str(title).strip()
    return None


# ---------------------------------------------------------------------------
# {practice} <- firm.primary_practice, humanised
# ---------------------------------------------------------------------------

_PRACTICE_HUMAN: dict[str, str] = {
    "personal_injury": "personal injury",
    "mass_tort": "mass tort",
    "immigration": "immigration",
    "ssdi": "SSDI",
    "workers_comp": "workers compensation",
    "lemon_law": "lemon law",
    "employment": "employment",
    "consumer": "consumer law",
    "bankruptcy": "bankruptcy",
    "family": "family law",
    "criminal": "criminal defense",
    "estate": "estate planning",
    "appellate": "appellate",
    "patent_prosecution": "patent prosecution",
    "complex_commercial": "complex commercial litigation",
}


def humanize_practice(slug: str | None) -> str | None:
    if not slug or not slug.strip():
        return None
    key = slug.strip().lower()
    return _PRACTICE_HUMAN.get(key, key.replace("_", " "))


# ---------------------------------------------------------------------------
# {cms} <- firm.cms_detected, humanised (vendor display names, not slugs)
# ---------------------------------------------------------------------------

_CMS_HUMAN: dict[str, str] = {
    "filevine": "Filevine",
    "clio": "Clio",
    "casepeer": "CASEpeer",
    "mycase": "MyCase",
    "litify": "Litify",
    "smartadvocate": "SmartAdvocate",
    "lawmatics": "Lawmatics",
    "practicepanther": "PracticePanther",
    "cosmolex": "CosmoLex",
    "needles": "Needles",
    "neos": "Neos",
    "prevail": "Prevail",
}


def humanize_cms(slug: str | None) -> str | None:
    if not slug or not slug.strip():
        return None
    key = slug.strip().lower()
    return _CMS_HUMAN.get(key, slug.strip().capitalize())


# ---------------------------------------------------------------------------
# {posted_date} <- signal.first_seen (OURS, never the board's), "14 August"
# {repost_month} <- month of the first repost sighting, "August"
# {days_open} <- days between signal.first_seen and `at`
# ---------------------------------------------------------------------------


def format_posted_date(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    return f"{dt.day} {dt.strftime('%B')}"


def format_month_name(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%B")


def _utc_date(value: datetime | date) -> date:
    # A timestamptz comes back from the store in the session's zone (+05:30 on
    # this machine) while `at` is UTC; taking each one's own calendar date made a
    # role found just after local midnight "open -1 days". One calendar: UTC.
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).date()
    return value


def days_open(first_seen: datetime | date | None, at: datetime | date) -> str | None:
    if first_seen is None:
        return None
    return str((_utc_date(at) - _utc_date(first_seen)).days)


# ---------------------------------------------------------------------------
# {tort} <- signal.evidence (mass_tort_campaign only)
# ---------------------------------------------------------------------------


def tort_from_evidence(evidence: dict | None) -> str | None:
    if not evidence:
        return None
    tort = evidence.get("tort")
    if tort and str(tort).strip():
        return str(tort).strip()
    title = evidence.get("title")
    if title and str(title).strip():
        return str(title).strip()
    return None
