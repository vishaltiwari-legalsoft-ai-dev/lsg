"""JA6 stage 1+2 -- the agency filter, then the support-role filter.

context/20-signals/03-agency-filter-and-resolution.md: "the single highest-value
transform in this whole lane." Reject when ANY of known_agency, client_language,
geographic_spread, volume or blind_posting fires; then reject anything left whose
title doesn't normalize to a support role. Order fixed, first match wins -- a
posting only ever carries one `job_posting_rejected` row (its PK is
raw_posting_id), so precedence has to be decided somewhere and this is it.

Pure functions of the `Posting` list handed in -- no DB access here. Rejects are
written by the caller (ja6_normalise.py), which is also what makes "un-rejecting"
a posting on a re-run (blocklist tightened *or* loosened) just a matter of the
caller upserting-or-deleting against whatever this module returns this time.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

from lge.classify.titles import is_support_role, normalize_title
from lge.norm import norm_name
from lge.planes.ja.ja6_config import agency_blocklist, signal_rules
from lge.planes.ja.ja6_types import Posting

# context/20-signals/03-agency-filter-and-resolution.md, rule 2 verbatim.
_CLIENT_LANGUAGE_RES = (
    re.compile(r"\bour client\b|\bconfidential client\b", re.IGNORECASE),
    re.compile(
        r"\b(?:a|our)\s+(?:growing|established|boutique)\s+(?:law\s+firm|firm)\b",
        re.IGNORECASE,
    ),
)


def _norm_names(names: list[str]) -> frozenset[str]:
    return frozenset(norm_name(n) for n in names if norm_name(n))


def _known_agency_names() -> frozenset[str]:
    return _norm_names(agency_blocklist()["agencies"])


def _blind_names() -> frozenset[str]:
    cfg = agency_blocklist()
    return _norm_names(cfg["marketplaces"]) | _norm_names(cfg["blind_names"])


def annotate_titles(postings: list[Posting]) -> None:
    """Populate canonical_role / is_support on every posting. Pure per-row --
    safe to call before agency filtering (the geographic_spread/volume rules need
    is_support to scope "legal support roles" correctly)."""
    for p in postings:
        p.canonical_role = normalize_title(p.title, firm_name=p.company_name)
        p.is_support = is_support_role(p.canonical_role)


def is_known_agency(company_name: str | None) -> bool:
    stem = norm_name(company_name)
    return bool(stem) and stem in _known_agency_names()


def is_blind_posting(company_name: str | None) -> bool:
    if not company_name or not company_name.strip():
        return True
    stem = norm_name(company_name)
    return bool(stem) and stem in _blind_names()


def has_client_language(title: str, body: str | None) -> bool:
    text = f"{title}\n{body or ''}"
    return any(rx.search(text) for rx in _CLIENT_LANGUAGE_RES)


def _agency_metro_key(p: Posting) -> str | None:
    if not p.city:
        return None
    return f"{p.city.strip().lower()}|{(p.state or '').strip().upper()}"


def _sliding_window_fires(
    items: list[tuple[date, str | None]],
    window_days: int,
    *,
    min_count: int | None = None,
    min_distinct: int | None = None,
) -> bool:
    """True iff any window of `window_days` (inclusive, sliding -- not a fixed
    calendar bucket) contains >= min_count items, or items spanning
    >= min_distinct non-None keys."""
    if not items:
        return False
    ordered = sorted(items, key=lambda t: t[0])
    window = timedelta(days=window_days)
    left = 0
    key_counts: Counter[str] = Counter()
    for right, (_right_date, _key) in enumerate(ordered):
        right_key = ordered[right][1]
        if right_key is not None:
            key_counts[right_key] += 1
        while ordered[right][0] - ordered[left][0] > window:
            left_key = ordered[left][1]
            if left_key is not None:
                key_counts[left_key] -= 1
                if key_counts[left_key] <= 0:
                    del key_counts[left_key]
            left += 1
        count_in_window = right - left + 1
        if min_count is not None and count_in_window >= min_count:
            return True
        if min_distinct is not None and len(key_counts) >= min_distinct:
            return True
    return False


def behavioural_flags(postings: list[Posting]) -> tuple[frozenset[str], frozenset[str]]:
    """Rules 3 (geographic_spread) and 4 (volume): a behavioural signature, not an
    identity, computed per normalised company name over its SUPPORT-ROLE postings
    only ("Same normalised company posting legal support roles..."). Companies with
    no usable name (blank/blind) are excluded -- grouping unrelated blind postings
    under one "" key would produce meaningless spread/volume counts.

    Returns (geo_spread_flagged_company_stems, volume_flagged_company_stems).

    Precondition: `annotate_titles(postings)` has already run (`classify()` below
    always does this before calling here) -- is_support defaults to False on a
    freshly-built Posting, so calling this first would silently see zero rows.
    """
    rules = signal_rules()["agency_filter"]
    by_company: dict[str, list[tuple[date, str | None]]] = {}
    for p in postings:
        if not p.is_support or is_blind_posting(p.company_name):
            continue
        stem = norm_name(p.company_name)
        if not stem:
            continue
        effective_date = p.board_posted_date or p.fetched_at.date()
        by_company.setdefault(stem, []).append((effective_date, _agency_metro_key(p)))

    geo_flagged: set[str] = set()
    volume_flagged: set[str] = set()
    for stem, items in by_company.items():
        if _sliding_window_fires(
            items,
            rules["geographic_spread"]["window_days"],
            min_distinct=rules["geographic_spread"]["min_distinct_metros"],
        ):
            geo_flagged.add(stem)
        if _sliding_window_fires(
            items,
            rules["volume"]["window_days"],
            min_count=rules["volume"]["min_postings"],
        ):
            volume_flagged.add(stem)
    return frozenset(geo_flagged), frozenset(volume_flagged)


def classify(postings: list[Posting]) -> dict[int, tuple[str, str]]:
    """Returns {raw_posting_id: (rule, detail)} for every posting that should be
    rejected -- either by the agency filter or (rule='not_support_role') because
    its title doesn't normalize to a delegable support role. A posting absent from
    the returned dict passed both filters and is ready for resolution.
    """
    annotate_titles(postings)
    geo_flagged, volume_flagged = behavioural_flags(postings)

    verdicts: dict[int, tuple[str, str]] = {}
    for p in postings:
        # A posting read from the firm's OWN careers page is, per the spec, "the one
        # place the posting is unambiguously tied to the firm" — it cannot be an agency
        # hiding its client. The agency rules (all keyed on a company name the careers
        # watcher never needs to set) do not apply; the support-role filter still does.
        # Found in the live probe: every careers posting was rejected as blind_posting.
        if p.source == "careers" and p.firm_id:
            if not p.is_support:
                verdicts[p.id] = (
                    "not_support_role",
                    f"title {p.title!r} normalized to {p.canonical_role!r}",
                )
            continue
        stem = norm_name(p.company_name)
        if is_known_agency(p.company_name):
            verdicts[p.id] = ("known_agency", f"company matches blocklist: {p.company_name!r}")
        elif has_client_language(p.title, p.body):
            verdicts[p.id] = ("client_language", "title/body matched client-language pattern")
        elif p.is_support and stem in geo_flagged:
            verdicts[p.id] = (
                "geographic_spread",
                f"{p.company_name!r} posts support roles across "
                f">={signal_rules()['agency_filter']['geographic_spread']['min_distinct_metros']} "
                "metros within 90 days",
            )
        elif p.is_support and stem in volume_flagged:
            verdicts[p.id] = (
                "volume",
                f"{p.company_name!r} has "
                f">={signal_rules()['agency_filter']['volume']['min_postings']} "
                "support-role postings within 90 days",
            )
        elif is_blind_posting(p.company_name):
            verdicts[p.id] = ("blind_posting", f"no real employer named: {p.company_name!r}")
        elif not p.is_support:
            verdicts[p.id] = (
                "not_support_role",
                f"title {p.title!r} normalized to {p.canonical_role!r}",
            )
    return verdicts
