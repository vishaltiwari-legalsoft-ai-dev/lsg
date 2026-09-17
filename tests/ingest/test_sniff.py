"""Column sniffing: the vendor layout, a completely different layout, generic
headers rescued by value shapes, misleading headers, and what is mandatory
(a firm name and a way to reach the firm -- nothing else, D-042)."""

from __future__ import annotations

from lge.ingest.sniff import ColumnMap, header_guess, shape_guess, sniff_columns

VENDOR_HEADERS = [
    "Company Name", "Formatted Company Name", "Company URL", "Business Email", "Full Name",
    "First Name", "Last Name", "Job Title", "Employees Range", "Industry", "Technology",
    "Company City", "City", "Country", "Business Email Quality", "Linkedin", "Description",
]


def _vendor_rows(n=5):
    return [
        {
            "Company Name": f"Smith Law {i}", "Formatted Company Name": f"Smith Law {i} LLC",
            "Company URL": f"https://smithlaw{i}.com", "Business Email": f"john{i}@smithlaw{i}.com",
            "Full Name": "John Smith", "First Name": "John", "Last Name": "Smith",
            "Job Title": "Owner", "Employees Range": "1 to 10", "Industry": "Law Practice",
            "Technology": "Clio, WordPress", "Company City": "Atlanta", "City": "Atlanta",
            "Country": "United States", "Business Email Quality": "verified",
            "Linkedin": f"https://www.linkedin.com/in/john-smith-{i}",
            "Description": "Personal injury firm",
        }
        for i in range(n)
    ]


def test_vendor_layout_maps_every_field_it_carries():
    cm = sniff_columns(VENDOR_HEADERS, _vendor_rows())
    assert cm.mapping["firm_name"] in ("Company Name", "Formatted Company Name")
    assert set(cm.columns_for("firm_name")) == {"Company Name", "Formatted Company Name"}
    assert cm.mapping["website"] == "Company URL"
    assert cm.mapping["email"] == "Business Email"
    assert cm.mapping["email_status"] == "Business Email Quality"
    assert cm.mapping["person_name"] == "Full Name"
    assert cm.mapping["first_name"] == "First Name"
    assert cm.mapping["person_title"] == "Job Title"
    assert cm.mapping["firm_size"] == "Employees Range"
    assert cm.mapping["firm_type"] in ("Industry", "Description")
    assert cm.mapping["technology"] == "Technology"
    assert cm.mapping["city"] in ("Company City", "City")
    assert cm.mapping["linkedin"] == "Linkedin"
    assert cm.missing == []
    assert cm.reader == "rules"
    # what the vendor never gives, research will: a phone, an opening
    assert "phone" in cm.research_fills and "job_post" in cm.research_fills
    assert "firm_size" not in cm.research_fills and "location" not in cm.research_fills


def test_a_different_sheet_maps_by_synonyms_and_location_free_text():
    headers = ["Law Firm", "Web", "Attorney Name", "Designation", "E-mail", "Phone Number",
               "Location", "No. of Attorneys", "Practice Areas", "Contacted?", "Last Touch"]
    rows = [
        {"Law Firm": "Doe & Roe", "Web": "doeroe.com", "Attorney Name": "Jane Doe",
         "Designation": "Managing Partner", "E-mail": "jane@doeroe.com",
         "Phone Number": "(404) 555-0100", "Location": "Atlanta, GA", "No. of Attorneys": "4",
         "Practice Areas": "Personal Injury", "Contacted?": "Yes", "Last Touch": "2026-03-01"},
    ] * 4
    cm = sniff_columns(headers, rows)
    assert cm.mapping["firm_name"] == "Law Firm"
    assert cm.mapping["website"] == "Web"
    assert cm.mapping["person_name"] == "Attorney Name"
    assert cm.mapping["person_title"] == "Designation"
    assert cm.mapping["email"] == "E-mail"
    assert cm.mapping["phone"] == "Phone Number"
    assert cm.mapping["location"] == "Location"
    assert cm.mapping["firm_size"] == "No. of Attorneys"
    assert cm.mapping["firm_type"] == "Practice Areas"
    assert cm.mapping["contacted_before"] == "Contacted?"
    assert cm.mapping["contacted_at"] == "Last Touch"
    assert cm.missing == []
    # no opening, no LinkedIn, no software on the sheet: the careers page, a search, the site's code
    assert cm.research_fills == ["job_post", "linkedin", "technology"]


def test_generic_headers_are_rescued_by_value_shapes():
    headers = ["A", "B", "C", "D", "E"]
    rows = [
        {"A": "Acme Injury Law", "B": "info@acme.com", "C": "https://acme.com", "D": "GA",
         "E": "30309"},
        {"A": "Beta Legal", "B": "hello@beta.law", "C": "www.beta.law", "D": "NY", "E": "10001"},
        {"A": "Gamma LLP", "B": "x@gamma.com", "C": "gamma.com/about", "D": "TX", "E": "77002"},
    ]
    cm = sniff_columns(headers, rows)
    assert cm.mapping["email"] == "B"
    assert cm.mapping["website"] == "C"
    assert cm.mapping["state"] == "D"
    assert cm.mapping["zip"] == "E"
    # A is unmapped (a firm name cannot be told from values alone) -> the one thing missing
    assert cm.missing == ["firm_name"]
    # size and type are not on the sheet; that is research's job, not a gap
    assert "firm_size" in cm.research_fills and "firm_type" in cm.research_fills
    assert "location" not in cm.research_fills


def test_only_a_name_and_a_site_is_a_complete_sheet():
    headers = ["Company", "Site"]
    rows = [{"Company": f"Firm {i}", "Site": f"firm{i}.com"} for i in range(4)]
    cm = sniff_columns(headers, rows)
    assert cm.missing == []
    assert cm.research_fills[:3] == ["firm_size", "firm_type", "job_post"]
    assert "location" in cm.research_fills


def test_a_name_with_no_way_to_reach_the_firm_is_missing_reach():
    headers = ["Company", "Handle"]
    rows = [{"Company": f"Firm {i}", "Handle": f"firm-{i}"} for i in range(4)]
    cm = sniff_columns(headers, rows)
    assert cm.missing == ["reach"]
    fixed = cm.with_overrides({"Handle": "website"})
    assert fixed.missing == [] and fixed.reader == "rules"


def test_values_beat_a_misleading_header():
    headers = ["Website", "Company"]
    rows = [{"Website": f"owner{i}@firm{i}.com", "Company": f"Firm {i}"} for i in range(5)]
    cm = sniff_columns(headers, rows)
    assert cm.mapping["email"] == "Website"
    assert "website" not in cm.mapping
    guess = next(g for g in cm.guesses if g.column == "Website")
    assert "despite header" in guess.reason


def test_company_name_never_becomes_a_person():
    assert header_guess("Company Name")[0] == "firm_name"
    assert header_guess("Contact Name")[0] == "person_name"
    assert header_guess("Job Title")[0] == "person_title"
    assert header_guess("Job Posting")[0] == "job_post"
    assert header_guess("Email Status")[0] == "email_status"
    assert header_guess("Random Column XYZ") is None


def test_shape_guess_orders_from_most_specific():
    assert shape_guess(["a@b.com", "c@d.org", "e@f.net"])[0] == "email"
    assert shape_guess(["https://x.com", "y.com", "www.z.org/about"])[0] == "website"
    assert shape_guess(["1 to 10", "11-50", "50+", "200"])[0] == "firm_size"
    assert shape_guess(["Yes", "No", "yes", "no"])[0] == "contacted_before"
    assert shape_guess(["", "", ""]) is None


def test_overrides_and_round_trip():
    cm = sniff_columns(VENDOR_HEADERS, _vendor_rows())
    fixed = cm.with_overrides({"Description": "firm_type", "Industry": None})
    assert fixed.mapping["firm_type"] == "Description"
    assert "Industry" not in fixed.columns_for("firm_type")
    again = ColumnMap.from_dict(fixed.to_dict())
    assert again.mapping == fixed.mapping and again.missing == fixed.missing
    assert again.research_fills == fixed.research_fills and again.reader == "rules"


def test_a_map_stored_before_the_reader_seam_still_loads():
    old = {"guesses": [], "mapping": {"firm_name": "A"}, "secondary": {}, "missing": ["reach"]}
    cm = ColumnMap.from_dict(old)
    assert cm.reader == "rules" and cm.notes == [] and cm.research_fills == []
