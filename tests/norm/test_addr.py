from lge.norm.addr import norm_addr


def test_suite_number_excluded_from_addr_hash():
    a = norm_addr("123 Main Street, Suite 400", "Springfield", "IL", "62701")
    b = norm_addr("123 Main St Ste 1200", "Springfield", "IL", "62701")

    assert a.street_norm == b.street_norm == "123 MAIN ST"
    assert a.addr_hash == b.addr_hash
    assert a.addr_hash is not None
    assert a.unit == "STE 400"
    assert b.unit == "STE 1200"
    assert a.unit != b.unit


def test_addr_hash_is_sha1_of_street_norm_plus_zip5():
    import hashlib

    a = norm_addr("123 Main St", None, None, "62701")
    expected = hashlib.sha1(("123 MAIN ST" + "62701").encode()).hexdigest()
    assert a.addr_hash == expected


def test_addr_hash_none_when_street_or_zip_missing():
    assert norm_addr(None, "Springfield", "IL", "62701").addr_hash is None
    assert norm_addr("123 Main St", "Springfield", "IL", None).addr_hash is None
    assert norm_addr(None, None, None, None).addr_hash is None


def test_street_suffix_abbreviations():
    cases = {
        "123 Main Street": "123 MAIN ST",
        "456 Oak Avenue": "456 OAK AVE",
        "789 Liberty Boulevard": "789 LIBERTY BLVD",
        "12 Sunset Road": "12 SUNSET RD",
        "34 Maple Drive": "34 MAPLE DR",
        "56 Birch Lane": "56 BIRCH LN",
        "78 Justice Court": "78 JUSTICE CT",
        "90 Market Place": "90 MARKET PL",
        "11 Commerce Parkway": "11 COMMERCE PKWY",
        "22 Route Highway": "22 ROUTE HWY",
        "33 Founders Circle": "33 FOUNDERS CIR",
        "44 River Terrace": "44 RIVER TER",
        "55 Town Square": "55 TOWN SQ",
        "66 Grand Plaza": "66 GRAND PLZ",
        "77 Forest Trail": "77 FOREST TRL",
        "88 Harbor Way": "88 HARBOR WAY",
        "99 Civic Center": "99 CIVIC CTR",
        "100 Metro Expressway": "100 METRO EXPY",
        "200 Bay Freeway": "200 BAY FWY",
    }
    for raw, expected in cases.items():
        assert norm_addr(raw, None, None, None).street_norm == expected


def test_directional_abbreviations():
    cases = {
        "123 North Main St": "123 N MAIN ST",
        "123 South Main St": "123 S MAIN ST",
        "123 East Main St": "123 E MAIN ST",
        "123 West Main St": "123 W MAIN ST",
        "123 Main St Northeast": "123 MAIN ST NE",
        "123 Main St Northwest": "123 MAIN ST NW",
        "123 Main St Southeast": "123 MAIN ST SE",
        "123 Main St Southwest": "123 MAIN ST SW",
    }
    for raw, expected in cases.items():
        assert norm_addr(raw, None, None, None).street_norm == expected


def test_unit_keywords_recognised():
    cases = {
        "123 Main St, Apt 4B": "APT 4B",
        "123 Main St, Unit 2": "UNIT 2",
        "123 Main St #400": "# 400",
        "123 Main St, Floor 3": "FL 3",
        "123 Main St, Room 12": "RM 12",
        "123 Main St, Bldg C": "BLDG C",
        "123 Main St, Dept 9": "DEPT 9",
        "123 Main St, PH2": "PH 2",
        "123 Main St, Ofc 5": "OFC 5",
    }
    for raw, expected_unit in cases.items():
        result = norm_addr(raw, None, None, None)
        assert result.unit == expected_unit, f"{raw!r} -> {result.unit!r}"
        assert "APT" not in (result.street_norm or "") if "Apt" in raw else True


def test_ordinal_floor_before_keyword():
    result = norm_addr("789 Oak Dr, 3rd Floor", None, None, None)
    assert result.unit == "FL 3"
    assert result.street_norm == "789 OAK DR"

    result2 = norm_addr("22 Elm St, 21st Floor", None, None, None)
    assert result2.unit == "FL 21"


def test_zip4_parsed_when_present():
    a = norm_addr("1 Main St", None, None, "62701-1234")
    assert a.zip5 == "62701"
    assert a.zip4 == "1234"

    b = norm_addr("1 Main St", None, None, "62701")
    assert b.zip5 == "62701"
    assert b.zip4 is None


def test_city_and_state_cleaned():
    result = norm_addr("1 Main St", "  springfield ", " il. ", "62701")
    assert result.city == "SPRINGFIELD"
    assert result.state == "IL"


def test_short_unit_keywords_do_not_swallow_street_names():
    # FL/RM/PH are also ordinary word prefixes; without a digit requirement on their
    # identifier, "Philadelphia" would wrongly parse as unit "PH ILADELPHIA".
    result = norm_addr("500 Philadelphia Ave", None, None, None)
    assert result.unit is None
    assert result.street_norm == "500 PHILADELPHIA AVE"


def test_unit_never_leaks_into_street_norm():
    result = norm_addr("500 5th Ave, Suite 2000", None, None, "10110")
    assert "SUITE" not in result.street_norm
    assert "2000" not in result.street_norm
    assert result.street_norm == "500 5TH AVE"
