from lge.norm.practice import _compiled_patterns, map_practice_label, norm_practice

_ALL_SLUGS = (
    "personal_injury",
    "mass_tort",
    "immigration",
    "ssdi",
    "workers_comp",
    "lemon_law",
    "employment",
    "consumer",
    "bankruptcy",
    "family",
    "criminal",
    "estate",
    "appellate",
    "patent_prosecution",
    "complex_commercial",
)

_POSITIVE_SAMPLES = {
    "personal_injury": "We handle car accident and slip and fall cases every day.",
    "mass_tort": "Our firm is handling Camp Lejeune and Roundup mass tort claims.",
    "immigration": "We assist with green card applications and asylum cases.",
    "ssdi": "We help clients with social security disability and SSDI appeals.",
    "workers_comp": "Our firm handles workers' compensation and workplace injury claims.",
    "lemon_law": "We are experienced lemon law attorneys.",
    "employment": "We handle wrongful termination and unpaid overtime claims.",
    "consumer": "We fight FDCPA and TCPA violations for consumers.",
    "bankruptcy": "We file Chapter 7 and Chapter 13 bankruptcy cases.",
    "family": "Our family law attorneys handle divorce and child custody.",
    "criminal": "We defend DUI and criminal defense cases.",
    "estate": "We handle estate planning, wills, and trusts.",
    "appellate": "Our appellate practice handles appeals court matters.",
    "patent_prosecution": "We handle patent prosecution and USPTO filings.",
    "complex_commercial": "We litigate complex commercial litigation disputes.",
}


def test_closed_vocabulary_has_exactly_15_slugs():
    patterns = _compiled_patterns()
    assert set(patterns.keys()) == set(_ALL_SLUGS)
    assert len(_ALL_SLUGS) == 15


def test_every_slug_has_at_least_one_positive_match():
    assert set(_POSITIVE_SAMPLES.keys()) == set(_ALL_SLUGS)
    for slug, text in _POSITIVE_SAMPLES.items():
        result = norm_practice([(text, 1.0)])
        assert result.primary == slug, f"{slug}: got {result.primary} for {text!r}"


def test_unmatched_text_returns_none():
    result = norm_practice([("We love puppies and sunshine and long walks.", 1.0)])
    assert result.primary is None
    assert result.confidence == 0.0
    assert result.areas == ()


def test_empty_sections_returns_none():
    result = norm_practice([])
    assert result.primary is None
    assert result.confidence == 0.0


def test_real_estate_beats_first_listed():
    # Footer lists many areas with low weight; a dedicated high-weight page is 100%
    # personal injury. The footer-listed-first area must NOT win.
    footer = (
        "Practice Areas: Immigration, Bankruptcy, Family Law, Criminal Defense, "
        "Estate Planning, Employment Law, Consumer Protection, Workers Compensation.",
        1.0,
    )
    pi_page = (
        "Our personal injury attorneys handle car accident, truck accident, "
        "motorcycle accident, and wrongful death cases. We know personal injury "
        "law inside and out, from slip and fall to catastrophic injury claims.",
        20.0,
    )
    result = norm_practice([footer, pi_page])
    assert result.primary == "personal_injury"


def test_footer_spam_case_many_slugs_low_weight():
    footer_spam = (
        "Immigration Bankruptcy Family Criminal Estate Employment Consumer "
        "Workers Compensation Lemon Law SSDI Appellate Patent Prosecution",
        1.0,
    )
    main_page = (
        "Camp Lejeune water contamination victims may qualify for compensation. "
        "Our mass tort attorneys are currently evaluating Roundup and Camp "
        "Lejeune claims for veterans and their families nationwide.",
        15.0,
    )
    result = norm_practice([footer_spam, main_page])
    assert result.primary == "mass_tort"


def test_tie_break_is_alphabetical_slug():
    # Two slugs matched exactly once each, in a single section (equal share) ->
    # deterministic alphabetical tie-break.
    text = "We handle bankruptcy matters and also lemon law claims."
    result = norm_practice([(text, 1.0)])
    slugs_in_result = {slug for slug, _ in result.areas}
    assert slugs_in_result == {"bankruptcy", "lemon_law"}
    # "bankruptcy" < "lemon_law" alphabetically.
    assert result.primary == "bankruptcy"
    assert result.areas[0][0] == "bankruptcy"
    assert result.areas[1][0] == "lemon_law"


def test_areas_sum_to_one():
    text = "Personal injury and car accident and immigration and bankruptcy."
    result = norm_practice([(text, 1.0)])
    total = sum(share for _slug, share in result.areas)
    assert abs(total - 1.0) < 1e-9


def test_weight_le_zero_falls_back_to_word_count():
    short_but_relevant = ("personal injury", 0.0)
    long_irrelevant = ("the quick brown fox jumps over the lazy dog again and again", 0.0)
    result = norm_practice([short_but_relevant, long_irrelevant])
    assert result.primary == "personal_injury"


def test_mass_tort_excludes_bare_class_action():
    # "class action" alone must not be classified as mass_tort — it isn't even a
    # pattern in the mass_tort list, so this should match nothing at all.
    result = norm_practice([("We handle class action lawsuits.", 1.0)])
    assert result.primary is None


def test_map_practice_label_known_labels():
    assert map_practice_label("Personal Injury") == "personal_injury"
    assert map_practice_label("Immigration") == "immigration"
    assert map_practice_label("Employment") == "employment"
    assert map_practice_label("Family") == "family"
    assert map_practice_label("Criminal") == "criminal"
    assert map_practice_label("Bankruptcy") == "bankruptcy"
    assert map_practice_label("Workers Compensation") == "workers_comp"


def test_map_practice_label_null_labels():
    assert map_practice_label("Litigation") is None
    assert map_practice_label("IP") is None


def test_map_practice_label_unknown_and_empty():
    assert map_practice_label("Some Random Category") is None
    assert map_practice_label(None) is None
    assert map_practice_label("") is None


def test_map_practice_label_falls_back_to_patterns():
    assert map_practice_label("Bankruptcy Chapter 7 Services") == "bankruptcy"


# Ordinary-word traps found by the live probe (aleemlaw.com and arringtonphillips.com,
# both personal-injury firms, were classified "estate" off "attorneys who will work...").
import pytest  # noqa: E402

from lge.norm import norm_practice as _np  # noqa: E402


@pytest.mark.parametrize(
    "text",
    [
        "Our attorneys will work to maximize the money you recover.",
        "You can trust us to fight for you.",
        "We accept Visa, MasterCard and American Express.",
        "Read our weekly news roundup for firm updates.",
    ],
)
def test_ordinary_words_do_not_classify(text):
    assert _np([(text, 0)]).primary is None


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("We draft wills and trusts for Georgia families.", "estate"),
        ("A revocable trust avoids probate.", "estate"),
        ("We handle work visa and family visa petitions.", "immigration"),
        ("Roundup weed killer lawsuits are now being filed.", "mass_tort"),
    ],
)
def test_service_phrases_still_classify(text, slug):
    assert _np([(text, 0)]).primary == slug
