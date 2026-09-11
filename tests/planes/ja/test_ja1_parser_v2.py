"""JA1 parser v2 — fixes found by the live probe (242 PI firms, NY / Chicago / Atlanta).

1. Roles listed as plain section headings under a page-level "Employment
   Opportunities" title were missed (Dressie Law Firm: three h3 roles).
2. Soft 404s — a 200 response whose content is an error page — were parsed.
3. "Front Desk Coordinator" mapped to no role.
4. Bare /employment tagged an employment-LAW practice page as careers.
"""

import lxml.html

from lge.classify.titles import is_support_role, normalize_title
from lge.planes.ja.ja1_careers import (
    PARSER_VERSION,
    html_heuristic_postings,
    is_soft_404,
    parse_careers_page,
)
from lge.planes.p.p1_site_map import classify_page_kind

# Same structure as the real page: context once, roles as h3, sections of detail.
LISTING = """<html><body>
<h1>Careers</h1>
<h2>Employment Opportunities</h2>
<p>Want to fight for injured people in Atlanta? Call us or email hiring@examplefirm.com today!</p>
<h3>Front Desk Coordinator</h3>
<p>Qualifications</p><ul><li>Experience with high-volume calls</li><li>Must speak Spanish</li></ul>
<p>Responsibilities</p><ul><li>Conduct case intakes and ensure appropriate handling</li></ul>
<h3>Associate Attorney</h3>
<p>Three years of personal injury litigation experience.</p>
<h3>Case Manager</h3>
<p>Manage medical records requests and client communication.</p>
<h4>Get a FREE Personal Injury Case Evaluation</h4>
</body></html>"""


def test_roles_under_page_level_context_are_found():
    postings = html_heuristic_postings(lxml.html.fromstring(LISTING))
    titles = [p["title"] for p in postings]
    assert titles == ["Front Desk Coordinator", "Associate Attorney", "Case Manager"]


def test_each_role_carries_its_own_section_as_body():
    postings = {p["title"]: p for p in html_heuristic_postings(lxml.html.fromstring(LISTING))}
    assert "Must speak Spanish" in postings["Front Desk Coordinator"]["body"]
    assert "Associate Attorney" not in postings["Front Desk Coordinator"]["body"]
    assert "medical records" in postings["Case Manager"]["body"]


def test_page_email_is_the_apply_email_when_a_section_has_none():
    postings = html_heuristic_postings(lxml.html.fromstring(LISTING))
    assert {p["apply_email"] for p in postings} == {"hiring@examplefirm.com"}


def test_without_page_context_v1_strictness_holds():
    # a practice page that happens to have a "Case Manager" heading is not a job
    html = "<html><body><h2>Our team</h2><h3>Case Manager</h3><p>Maria helps clients.</p>"
    assert html_heuristic_postings(lxml.html.fromstring(html)) == []


def test_evergreen_talent_page_yields_no_posting():
    # "always looking for talent" names no role — correctly not a signal
    html = ("<html><body><h1>Careers</h1><p>We are always looking for new talent to join "
            "our growing team! Submit your resume.</p></body></html>")
    assert parse_careers_page(html, "https://x.test/careers").postings == []


def test_soft_404_is_detected_and_yields_nothing():
    html = ("<html><body><h1>404</h1><p>The page you were looking for could not be found. "
            "Back to our homepage</p></body></html>")
    assert is_soft_404(lxml.html.fromstring(html))
    parsed = parse_careers_page(html, "https://x.test/careers")
    assert parsed.method == "soft_404"
    assert parsed.postings == []


def test_a_long_page_mentioning_404_is_not_a_soft_404():
    filler = "We fight for injured workers. " * 60
    html = "<html><body><p>" + filler + "Error 404 codes aside.</p>"
    assert not is_soft_404(lxml.html.fromstring(html))


def test_front_desk_coordinator_is_a_support_role():
    role = normalize_title("Front Desk Coordinator")
    assert role == "legal_receptionist"
    assert is_support_role(role)


def test_file_clerk_is_a_support_role():
    assert normalize_title("Digital File Clerk & Backup Receptionist") == "document_collector"


def test_employment_law_page_is_not_careers():
    assert classify_page_kind("https://firm.test/employment/") != "careers"
    assert classify_page_kind("https://firm.test/employment-opportunities/") == "careers"
    assert classify_page_kind("https://firm.test/careers/") == "careers"


def test_parser_version_is_recorded_for_the_skip_rule():
    # the skip-unchanged rule compares (content_hash, parser_version); v2 must re-parse
    assert PARSER_VERSION == "2"
