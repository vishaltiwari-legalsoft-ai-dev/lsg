"""JA6 stage 1+2 -- the agency filter and support-role filter. Pure functions of
an in-memory Posting list, no DB needed -- see lge/planes/ja/ja6_agency.py.
"""

from __future__ import annotations

from datetime import timedelta

from lge.norm import norm_name
from lge.planes.ja.ja6_agency import (
    annotate_titles,
    behavioural_flags,
    classify,
    has_client_language,
    is_blind_posting,
    is_known_agency,
)
from tests.planes.ja._ja6_helpers import d, posting

# =============================================================================
# Rule 1 -- known agency
# =============================================================================


def test_known_agency_seed_list_and_csv_variants():
    assert is_known_agency("Robert Half Legal")
    assert is_known_agency("Robert Half")  # variant seen in the real job-history CSV
    assert is_known_agency("Adams & Martin")
    assert is_known_agency("Adams & Martin Group")  # "Group" stripped by norm_name
    assert is_known_agency("Beacon Hill Legal")
    assert is_known_agency("Special Counsel")
    assert is_known_agency("Vaco")
    assert is_known_agency("Lateral Link")
    assert is_known_agency("Kforce Legal")
    assert is_known_agency("Marina Sirras")
    assert is_known_agency("Latitude")
    assert is_known_agency("Hire Counsel")
    assert not is_known_agency("Smith & Associates PLLC")
    assert not is_known_agency(None)


# =============================================================================
# Rule 2 -- client language
# =============================================================================


def test_client_language_our_client_and_confidential_client():
    assert has_client_language("Paralegal", "Our client is a boutique firm seeking a paralegal.")
    assert has_client_language("Paralegal", "This confidential client needs support staff.")


def test_client_language_describes_rather_than_names_employer():
    assert has_client_language("Paralegal", "A growing law firm seeks a paralegal.")
    assert has_client_language("Paralegal", "Our established firm seeks a paralegal.")
    assert has_client_language("Paralegal", "Our boutique firm is expanding.")


def test_client_language_absent_for_a_named_firm():
    assert not has_client_language("Paralegal", "Smith Law seeks a paralegal for our office.")
    assert not has_client_language("Paralegal", None)


# =============================================================================
# Rule 5 -- blind posting (empty / named-blind / marketplace)
# =============================================================================


def test_blind_posting_empty_or_generic():
    assert is_blind_posting(None)
    assert is_blind_posting("")
    assert is_blind_posting("   ")
    assert is_blind_posting("Confidential")
    assert is_blind_posting("Stealth")
    assert is_blind_posting("Our Client")


def test_blind_posting_marketplaces():
    for name in (
        "Upwork",
        "VirtualVocations",
        "Virtual Vocations Inc",
        "Indeed",
        "ZipRecruiter",
        "LinkedIn",
        "Glassdoor",
    ):
        assert is_blind_posting(name), name
    assert not is_blind_posting("Smith & Associates PLLC")


# =============================================================================
# Rule 3 -- geographic spread (the behavioural rule, catches an unlisted agency)
# =============================================================================


def _metro_postings(company: str, metros: list[tuple[str, str]], start, step_days: int):
    return [
        posting(
            i,
            company_name=company,
            title="Paralegal",
            city=city,
            state=state,
            board_posted_date=start + timedelta(days=step_days * i),
        )
        for i, (city, state) in enumerate(metros)
    ]


_FIVE_METROS = [
    ("Denver", "CO"),
    ("Austin", "TX"),
    ("Miami", "FL"),
    ("Boise", "ID"),
    ("Reno", "NV"),
]


def test_geographic_spread_catches_a_company_not_on_any_blocklist():
    postings = _metro_postings("Totally Unheard Of Staffing", _FIVE_METROS, d(2026, 7, 1), 5)
    annotate_titles(postings)
    geo_flagged, volume_flagged = behavioural_flags(postings)
    stem = norm_name("Totally Unheard Of Staffing")
    assert stem in geo_flagged
    assert stem not in volume_flagged  # only 5 postings, well under the volume threshold

    # and classify() rejects every one of that company's support-role postings
    verdicts = classify(postings)
    assert len(verdicts) == 5
    assert all(rule == "geographic_spread" for rule, _detail in verdicts.values())


def test_geographic_spread_requires_the_90_day_window():
    postings = _metro_postings("Patient Slow Firm", _FIVE_METROS, d(2023, 1, 1), 200)
    annotate_titles(postings)
    geo_flagged, _ = behavioural_flags(postings)
    assert norm_name("Patient Slow Firm") not in geo_flagged


def test_geographic_spread_only_counts_support_role_postings():
    postings = _metro_postings("Mixed Roles Co", _FIVE_METROS, d(2026, 7, 1), 5)
    # relabel one as a non-support title -- now only 4 metros' worth of support
    # postings remain, under the threshold of 5.
    postings[0].title = "Associate Attorney"
    annotate_titles(postings)
    geo_flagged, _ = behavioural_flags(postings)
    assert norm_name("Mixed Roles Co") not in geo_flagged


def test_geographic_spread_ignores_blind_and_blank_company_names():
    postings = _metro_postings("Upwork", _FIVE_METROS, d(2026, 7, 1), 5) + _metro_postings(
        "", _FIVE_METROS, d(2026, 7, 1), 5
    )
    annotate_titles(postings)
    geo_flagged, _ = behavioural_flags(postings)
    assert geo_flagged == frozenset()


# =============================================================================
# Rule 4 -- volume
# =============================================================================


def test_volume_catches_twenty_postings_in_ninety_days_one_metro():
    postings = [
        posting(
            i,
            company_name="High Volume Co",
            title="Paralegal",
            city="Denver",
            state="CO",
            board_posted_date=d(2026, 6, 1) + timedelta(days=i),
        )
        for i in range(20)
    ]
    annotate_titles(postings)
    geo_flagged, volume_flagged = behavioural_flags(postings)
    stem = norm_name("High Volume Co")
    assert stem in volume_flagged
    assert stem not in geo_flagged  # one metro only


def test_volume_under_threshold_not_flagged():
    postings = [
        posting(
            i,
            company_name="Modest Firm",
            title="Paralegal",
            city="Denver",
            state="CO",
            board_posted_date=d(2026, 6, 1) + timedelta(days=i),
        )
        for i in range(19)
    ]
    annotate_titles(postings)
    _, volume_flagged = behavioural_flags(postings)
    assert norm_name("Modest Firm") not in volume_flagged


# =============================================================================
# classify() precedence and the not_support_role fallback
# =============================================================================


def test_known_agency_wins_over_client_language():
    p = posting(1, company_name="Robert Half", body="Our client is a boutique firm")
    verdicts = classify([p])
    assert verdicts[1][0] == "known_agency"


def test_not_support_role_rejects_attorney_titles():
    p = posting(1, company_name="Smith & Associates PLLC", title="Associate Attorney")
    verdicts = classify([p])
    assert verdicts[1][0] == "not_support_role"
    assert p.canonical_role == "attorney"
    assert p.is_support is False


def test_not_support_role_rejects_unmapped_titles():
    p = posting(1, company_name="Smith & Associates PLLC", title="Marketing Coordinator")
    verdicts = classify([p])
    assert verdicts[1][0] == "not_support_role"
    assert p.canonical_role is None


def test_a_clean_posting_passes_every_rule():
    p = posting(1, company_name="Smith & Associates PLLC", title="Paralegal", body="Join our team.")
    verdicts = classify([p])
    assert 1 not in verdicts
    assert p.canonical_role == "paralegal"
    assert p.is_support is True
