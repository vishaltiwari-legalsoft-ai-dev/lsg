from lge.norm.phone import norm_phone, shared_numbers


def test_phone_stored_e164_not_formatted():
    variants = [
        "(310) 555-1234",
        "310.555.1234",
        "+1 310 555 1234",
        "310-555-1234",
        "1-310-555-1234",
    ]
    results = {norm_phone(v) for v in variants}
    assert results == {"+13105551234"}


def test_phone_handles_extensions():
    assert norm_phone("(212) 555-0147 x123") == "+12125550147"
    assert norm_phone("415-555-2671 ext. 5") == "+14155552671"
    assert norm_phone("310-555-9876 extension 12") == "+13105559876"


def test_phone_invalid_returns_none():
    assert norm_phone("555-1234") is None  # too short, no valid area code
    assert norm_phone("not a phone number") is None
    assert norm_phone(None) is None
    assert norm_phone("") is None


def test_phone_region_defaults_to_us():
    assert norm_phone("(212) 555-0147") == norm_phone("212-555-0147", region="US")


def test_shared_phone_flagged_at_4_candidates():
    number = "+13105551234"

    three_distinct = [(number, "c1"), (number, "c2"), (number, "c3")]
    assert shared_numbers(three_distinct) == set()

    four_distinct = [(number, "c1"), (number, "c2"), (number, "c3"), (number, "c4")]
    assert shared_numbers(four_distinct) == {number}

    # 5 rows but only 2 distinct candidate ids -> not shared.
    five_rows_two_ids = [
        (number, "c1"),
        (number, "c1"),
        (number, "c1"),
        (number, "c2"),
        (number, "c2"),
    ]
    assert shared_numbers(five_rows_two_ids) == set()


def test_shared_phone_custom_threshold():
    number = "+12125550147"
    pairs = [(number, "c1"), (number, "c2")]
    assert shared_numbers(pairs, threshold=2) == {number}
    assert shared_numbers(pairs, threshold=3) == set()


def test_shared_phone_only_flags_numbers_meeting_threshold():
    shared = "+13105551234"
    solo = "+12125550147"
    pairs = [
        (shared, "c1"),
        (shared, "c2"),
        (shared, "c3"),
        (shared, "c4"),
        (solo, "c5"),
    ]
    assert shared_numbers(pairs) == {shared}
