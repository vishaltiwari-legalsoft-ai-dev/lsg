from lge.norm.name import EXTENSION_STOPWORDS, SPEC_STOPWORDS, norm_name


def test_name_stem_preserves_token_order():
    assert norm_name("Jones Smith") == "jones smith"
    assert norm_name("Smith Jones") == "smith jones"
    assert norm_name("Jones Smith") != norm_name("Smith Jones")


def test_everything_does_not_become_smith():
    assert norm_name("Smith Law Group PLLC") == "smith"
    assert norm_name("Smith & Jones LLP") == "smith jones"
    assert norm_name("Law Offices of John Smith") == "john smith"


def test_law_and_law_fallback_is_non_empty_and_distinctive():
    # The spec's own worked example of a name that breaks the naive version.
    stem = norm_name("The Law Offices of Law & Law")
    assert stem != ""
    assert stem == "law offices of law law"


def test_fallback_only_removes_the_not_every_stopword():
    # "The Firm": both tokens are SPEC_STOPWORDS, so stopword removal empties out and
    # the fallback engages — it must keep "firm" (only "the" is dropped), not return "".
    assert norm_name("The Firm") == "firm"


def test_dotted_abbreviations_pc_llp_pa():
    assert norm_name("Smith, P.C.") == "smith"
    assert norm_name("Smith, P. C.") == "smith"
    assert norm_name("Jones & Associates, L.L.P.") == "jones"
    assert norm_name("Ramirez Immigration, P.A.") == "ramirez immigration"


def test_ampersand_and_punctuation_stripped():
    assert norm_name("Brown & Williams") == "brown williams"
    assert norm_name("O'Neill, Carter, and Doyle") == "o neill carter doyle"


def test_stopwords_are_dropped():
    assert norm_name("Downtown Legal Associates LLC") == "downtown"


def test_extension_stopwords_documented_and_separate():
    assert "pa" in EXTENSION_STOPWORDS
    assert "of" in EXTENSION_STOPWORDS
    assert "pllc" in SPEC_STOPWORDS
    assert SPEC_STOPWORDS.isdisjoint(EXTENSION_STOPWORDS)


def test_empty_and_none_input():
    assert norm_name(None) == ""
    assert norm_name("") == ""
    assert norm_name("   ") == ""


def test_only_initials_triggers_fallback():
    # Every remaining token after stopword removal is a single character.
    stem = norm_name("A B The")
    assert stem == "a b"
