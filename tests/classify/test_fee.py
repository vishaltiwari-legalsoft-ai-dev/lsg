from lge.classify.fee import detect_fee_model


def test_contingency_no_fee_unless_we_win():
    result = detect_fee_model([("We work on a contingency basis — no fee unless we win.", 5.0)])
    assert result.value == "contingency"
    assert result.confidence == 0.9
    assert "no fee unless we win" in result.evidence.lower()


def test_contingency_no_recovery_no_fee():
    # Realistic marketing copy: the "no recovery no fee" phrase paired with the
    # "unless" language the regex actually keys on.
    result = detect_fee_model(
        [("No recovery, no fee — you pay nothing unless we win your case.", 5.0)]
    )
    assert result.value == "contingency"
    assert result.confidence == 0.9


def test_contingency_fee_word():
    result = detect_fee_model([("We handle every case on a contingency fee basis.", 5.0)])
    assert result.value == "contingency"


def test_fee_shifting_paid_by_defendant():
    result = detect_fee_model([("In these cases, fees are paid by the defendant.", 5.0)])
    assert result.value == "fee_shifting"
    assert result.confidence == 0.9
    assert "paid by the defendant" in result.evidence.lower()


def test_flat_fee_phrase():
    result = detect_fee_model([("We offer a flat fee for uncontested divorces.", 5.0)])
    assert result.value == "flat"
    assert result.confidence == 0.9
    assert "flat fee" in result.evidence.lower()


def test_flat_dollar_amount():
    result = detect_fee_model([("A simple will is $1,500 flat, all-inclusive.", 5.0)])
    assert result.value == "flat"


def test_hourly_rate_phrase():
    result = detect_fee_model([("Our attorneys bill at an hourly rate.", 5.0)])
    assert result.value == "hourly"
    assert result.confidence == 0.9
    assert "hourly rate" in result.evidence.lower()


def test_hourly_billed_by_the_hour():
    result = detect_fee_model([("All work on this matter is billed by the hour.", 5.0)])
    assert result.value == "hourly"


def test_no_match_is_unknown():
    result = detect_fee_model([("We are a great law firm with excellent service.", 5.0)])
    assert result.value == "unknown"
    assert result.confidence == 0.0
    assert result.evidence is None
    assert result.matches == ()


def test_contingency_and_hourly_tie_is_mixed():
    result = detect_fee_model(
        [
            ("No fee unless we win.", 5.0),
            ("Business clients are billed at an hourly rate.", 5.0),
        ]
    )
    assert result.value == "mixed"
    assert result.evidence is not None


def test_contingency_and_hourly_resolved_by_real_estate():
    # PI pages (high weight) say contingency; one thin hourly-business blurb.
    result = detect_fee_model(
        [
            ("No fee unless we win your personal injury case.", 8.0),
            ("Our business law clients are billed at an hourly rate.", 2.0),
        ]
    )
    assert result.value == "contingency"
    assert result.confidence == 0.6


def test_hourly_wins_real_estate_when_dominant():
    result = detect_fee_model(
        [
            ("No fee unless we win.", 1.0),
            ("Every matter is billed at an hourly rate for our clients.", 9.0),
        ]
    )
    assert result.value == "hourly"
    assert result.confidence == 0.6


def test_two_distinct_sentences_raise_confidence():
    result = detect_fee_model(
        [
            (
                "No fee unless we win. We also offer a contingency fee arrangement "
                "for every case we accept.",
                5.0,
            )
        ]
    )
    assert result.value == "contingency"
    assert result.confidence == 0.95
    assert len({s for _f, s in result.matches}) >= 2


def test_evidence_is_the_exact_matching_sentence():
    text = "We are a full service firm. We bill at an hourly rate for these matters."
    result = detect_fee_model([(text, 5.0)])
    assert result.evidence == "We bill at an hourly rate for these matters."


def test_precedence_first_family_wins_within_one_sentence():
    # Contingency pattern and hourly pattern both technically present, but they are
    # in the SAME sentence, so contingency (earlier in precedence) wins that
    # sentence outright rather than producing two separate matches.
    text = "No fee unless we win, unlike firms that charge an hourly rate."
    result = detect_fee_model([(text, 5.0)])
    assert result.matches == (("contingency", text),)
    assert result.value == "contingency"


def test_weight_le_zero_falls_back_to_word_count():
    result = detect_fee_model([("hourly rate", 0.0)])
    assert result.value == "hourly"


def test_contingency_and_flat_uses_precedence_not_mixed():
    # A PI firm that mentions one flat-fee side service must stay contingency
    # (tier 1A). Both families make support staff overhead — no conflict.
    result = detect_fee_model(
        [
            ("No fee unless we win your injury case.", 2.0),
            ("Simple wills are handled for a flat fee.", 8.0),
        ]
    )
    assert result.value == "contingency"
    assert result.confidence == 0.8


def test_fee_shifting_and_flat_uses_precedence():
    result = detect_fee_model(
        [
            ("Your attorney fees are paid by the manufacturer under the lemon law.", 1.0),
            ("Document review is a flat fee.", 1.0),
        ]
    )
    assert result.value == "fee_shifting"


def test_flat_and_hourly_tie_is_mixed():
    # flat vs hourly has the same opposite arithmetic as contingency vs hourly.
    result = detect_fee_model(
        [
            ("Estate plans are a flat fee.", 5.0),
            ("Litigation is billed at an hourly rate.", 5.0),
        ]
    )
    assert result.value == "mixed"
