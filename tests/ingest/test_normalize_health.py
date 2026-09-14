"""normalize_row: one canonical shape from any mapped row; assess: the health
report; plan_batches: contiguous 1-based ranges."""

from __future__ import annotations

from lge.ingest.batches import plan_batches, slice_rows
from lge.ingest.health import assess
from lge.ingest.normalize import (
    normalize_row,
    parse_contacted,
    parse_size,
    resolve_domain,
)
from lge.ingest.sniff import sniff_columns

HEADERS = ["Law Firm", "Web", "Attorney Name", "Designation", "E-mail", "Phone Number",
           "Location", "No. of Attorneys", "Practice Areas", "Contacted?", "Last Touch", "Memo"]


def _cm():
    rows = [{"Law Firm": "Doe & Roe", "Web": "doeroe.com", "Attorney Name": "Jane Doe",
             "Designation": "Partner", "E-mail": "jane@doeroe.com",
             "Phone Number": "(404) 555-0100",
             "Location": "Atlanta, GA 30309", "No. of Attorneys": "4",
             "Practice Areas": "Personal Injury", "Contacted?": "Yes", "Last Touch": "3/1/2026",
             "Memo": "met at conf"}] * 3
    return sniff_columns(HEADERS, rows)


def test_normalize_row_full():
    cm = _cm()
    raw = {"Law Firm": "Doe &amp; Roe, LLC", "Web": "http://www.doeroe.com/about",
           "Attorney Name": "Jane Doe, Esq.", "Designation": "Managing Partner",
           "E-mail": "Jane@DoeRoe.com", "Phone Number": "(404) 555-0100",
           "Location": "Atlanta, Georgia 30309", "No. of Attorneys": "4",
           "Practice Areas": "Personal Injury", "Contacted?": "Yes", "Last Touch": "3/1/2026",
           "Memo": "met at conf"}
    n = normalize_row(raw, cm)
    assert n["firm_name"] == "Doe & Roe, LLC"
    assert n["domain"] == "doeroe.com" and n["domain_from_email"] is False
    assert (n["city"], n["state"], n["zip"]) == ("Atlanta", "GA", "30309")
    assert n["person_name"] == "Jane Doe" and n["is_person"] is True
    assert n["person_title"] == "Managing Partner"
    assert n["email"] == "jane@doeroe.com" and n["email_valid"] is True
    assert n["phone_e164"] == "+14045550100"
    assert (n["size_min"], n["size_max"]) == (4, 4)
    assert n["firm_type"] == "Personal Injury"
    assert n["contacted_before"] is True and n["contacted_at"] == "2026-03-01"
    assert n["notes"] == "met at conf"
    assert n["extra"] == {}


def test_normalize_row_degrades_honestly():
    cm = _cm()
    raw = {"Law Firm": "Solo Practice", "Web": "513.2664",
           "Attorney Name": "Chicago Injury Attorneys",
           "E-mail": "not-an-email", "Phone Number": "", "Location": "Houston TX",
           "No. of Attorneys": "", "Practice Areas": "", "Contacted?": "", "Last Touch": "n/a"}
    n = normalize_row(raw, cm)
    assert n["website"] == "513.2664" and n["domain"] is None  # malformed, not guessed
    assert n["person_name"] is None and n["is_person"] is False
    assert n["email"] is None and n["email_valid"] is False and n["email_raw"] == "not-an-email"
    assert n["location"] == "Houston TX" and n["city"] is None  # no comma -> not split, kept raw
    assert n["contacted_before"] is None and n["contacted_at"] is None
    assert (n["size_min"], n["size_max"]) == (None, None)


def test_domain_from_email_only_when_plausible():
    assert resolve_domain(None, "john@smithlaw.com", "smith law") == ("smithlaw.com", True)
    assert resolve_domain(None, "john@mattel.com", "bernice lake") == (None, False)
    assert resolve_domain("smithlaw.com", "john@other.com", "smith law") == ("smithlaw.com", False)


def test_size_and_contacted_parsing():
    assert parse_size("1 to 10") == (1, 10)
    assert parse_size("11-50") == (11, 50)
    assert parse_size("1,000+") == (1000, None)
    assert parse_size("25") == (25, 25)
    assert parse_size("unknown") == (None, None)
    assert parse_contacted("yes") is True and parse_contacted("No") is False
    assert parse_contacted("emailed twice") is True and parse_contacted("") is None


def test_health_report_counts_and_score():
    cm = _cm()
    rows = [
        normalize_row({"Law Firm": "A Firm", "Web": "afirm.com", "Attorney Name": "Ann Lee",
                       "E-mail": "ann@afirm.com", "Location": "Atlanta, GA",
                       "No. of Attorneys": "3", "Practice Areas": "PI"}, cm),
        normalize_row({"Law Firm": "A Firm", "Web": "afirm.com", "Attorney Name": "Bob Lee",
                       "E-mail": "bob@afirm.com", "Location": "Atlanta, GA",
                       "No. of Attorneys": "3", "Practice Areas": "PI"}, cm),
        normalize_row({"Law Firm": "", "Web": "garbage", "Attorney Name": "Beattie Law Firm",
                       "E-mail": "nope", "Location": "", "No. of Attorneys": "",
                       "Practice Areas": ""}, cm),
    ]
    h = assess(rows)
    assert h.rows == 3
    assert h.firm_name_missing == 1
    assert h.website_malformed == 1 and h.website_missing == 0
    assert h.location_missing == 1 and h.size_missing == 1 and h.type_missing == 1
    assert h.junk_person_names == 1 and h.invalid_emails == 1
    assert h.distinct_domains == 1 and h.duplicate_domain_rows == 1
    assert 60 <= h.score <= 70  # two of three rows complete on every mandatory field
    assert any("not people" in n for n in h.notes)


def test_batches_cover_every_row_once():
    batches = plan_batches(1234, 500)
    assert [(b.number, b.row_start, b.row_end) for b in batches] == [
        (1, 1, 500), (2, 501, 1000), (3, 1001, 1234),
    ]
    rows = list(range(1234))
    assert sum(len(slice_rows(rows, b)) for b in batches) == 1234
    assert plan_batches(0) == []
    assert plan_batches(10, 5)[0].size == 10  # floor of 50 per batch
