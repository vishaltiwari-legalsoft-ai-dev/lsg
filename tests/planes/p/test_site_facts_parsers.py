"""The px_site_facts parsers over fixture pages: people and designations,
phones, addresses, testimonials, review summaries, links, dated posts and
growth cues, chat vendors, intake forms, copyright years. No DB."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lge.planes.p import _site_facts as sf

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"
_BASE = "https://hartleylaw.com/"


def _page(name: str):
    html = (_FIXTURES / name).read_text(encoding="utf-8")
    return html, sf.parse(html)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


def test_team_page_yields_people_with_their_printed_titles():
    _html, tree = _page("site_team_page.html")
    people = {p["name"]: p for p in sf.find_people(tree, _BASE + "our-team/", strict=False)}

    assert people["Margaret Hartley"]["title"] == "Founding Partner & Trial Attorney"
    assert people["Margaret Hartley"]["url"] == _BASE + "our-team/margaret-hartley/"
    assert people["Luis Ortega"]["title"] == "Associate Attorney"  # ", Esq." dropped
    assert people["Dana Whitfield"]["title"] == "Senior Litigation Paralegal"
    assert people["Priya Raman"]["title"] == "Office Manager"
    # a profile link whose anchor text is "Learn more": the name comes from the slug
    assert people["Tom Becker"]["url"] == _BASE + "our-team/tom-becker/"
    assert people["Tom Becker"]["title"] is None
    # titles, link labels and the section heading are not people
    for not_a_person in ("Learn more", "Senior Litigation Paralegal", "Office Manager",
                         "Personal Injury Attorneys Serving Atlanta"):
        assert not_a_person not in people
    assert len(people) == 5


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Founding Partner & Trial Attorney", True),
        ("Senior Litigation Paralegal", True),
        ("View Attorney Bio", False),  # a link label, seen on lipkinapter.com
        ("Read Full Profile", False),
        ("Meet Our Attorneys", False),
        ("Personal Injury Attorneys Serving Atlanta", False),
        ("Contact an Attorney", False),
        ("Margaret has tried over 40 cases to verdict and leads the litigation practice.", False),
    ],
)
def test_looks_like_title(text, expected):
    assert sf.looks_like_title(text) is expected


def test_title_class_reads_support_before_attorney():
    assert sf.title_class("Senior Litigation Paralegal") == "support"
    assert sf.title_class("Office Manager") == "support"
    assert sf.title_class("Founding Partner & Trial Attorney") == "attorney"
    assert sf.title_class("Of Counsel") == "attorney"
    assert sf.title_class("Client Relations Director") == "support"
    assert sf.title_class(None) == "other"
    assert sf.title_class("Notary") == "other"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Margaret Hartley", "Margaret Hartley"),
        ("Attorney Luis Ortega, Esq.", "Luis Ortega"),
        ("Ana de la Cruz", "Ana de la Cruz"),
        ("Learn more", None),
        ("Senior Litigation Paralegal", None),
        ("Personal Injury Attorneys Serving Atlanta", None),
        ("read our reviews", None),
    ],
)
def test_name_like(text, expected):
    assert sf.name_like(text) == expected


def test_strict_mode_needs_a_title_or_a_profile_link():
    html = (
        "<html><body><h2>John Carter</h2><p>John was hit by a truck on I-75 and came to us."
        "</p><h3>Sarah Blake</h3><p class='title'>Managing Attorney</p></body></html>"
    )
    tree = sf.parse(html)
    strict = {p["name"] for p in sf.find_people(tree, _BASE, strict=True)}
    loose = {p["name"] for p in sf.find_people(tree, _BASE, strict=False)}
    assert strict == {"Sarah Blake"}
    assert loose == {"John Carter", "Sarah Blake"}


# ---------------------------------------------------------------------------
# Phones and addresses
# ---------------------------------------------------------------------------


def test_phones_from_tel_links_then_text_valid_only():
    _html, tree = _page("site_contact_page.html")
    phones = sf.find_phones(tree)
    assert phones[0] == ("+14045550142", "+1-404-555-0142")  # the tel: link comes first
    assert ("+18005550199", "800-555-0199") in phones
    assert all(e164 != "+11234567890" for e164, _raw in phones)  # not a valid US line


def test_addresses_two_offices_deduplicated_and_normalised():
    _html, tree = _page("site_contact_page.html")
    offices = sf.find_addresses(sf.page_text(tree))
    assert [(o["city"], o["state"], o["zip5"]) for o in offices] == [
        ("ATLANTA", "GA", "30326"),
        ("MARIETTA", "GA", "30060"),
    ]
    assert offices[0]["street_norm"] == "3350 PEACHTREE RD NE"
    assert offices[0]["unit"] == "STE 1200"
    assert offices[0]["raw"] == "3350 Peachtree Road NE, Suite 1200 Atlanta, GA 30326"
    assert offices[1]["street_norm"] == "145 CHURCH ST"


def test_a_previous_zip_never_becomes_the_next_house_number():
    text = "Atlanta, GA 30326 Marietta Office 145 Church Street, Marietta, GA 30060"
    offices = sf.find_addresses(text)
    assert len(offices) == 1
    assert offices[0]["street_norm"] == "145 CHURCH ST"


# ---------------------------------------------------------------------------
# Testimonials and review summaries
# ---------------------------------------------------------------------------


def test_testimonials_quotes_authors_ratings_and_no_duplicates():
    _html, tree = _page("site_testimonials_page.html")
    quotes = sf.find_testimonials(tree)
    by_author = {q["author"]: q for q in quotes}
    assert set(by_author) == {"Jamal R.", "Karen & Bill T.", "Sofia M."}
    assert by_author["Jamal R."]["rating"] == 5.0
    assert by_author["Jamal R."]["quote"].startswith("Margaret and her team answered every call")
    assert "5 stars" not in by_author["Jamal R."]["quote"]
    # "— Sofia M." is split off the end of the blockquote
    assert by_author["Sofia M."]["quote"].endswith("delivered exactly that.")
    # "Great firm. Highly recommend." is too short; the repeated quote is dropped
    assert len(quotes) == 3


def test_review_summary_reads_rating_and_count():
    _html, tree = _page("site_testimonials_page.html")
    summary = sf.find_review_summary(sf.page_text(tree))
    assert summary["rating"] == 4.9
    assert summary["count"] == 312
    assert "4.9 out of 5" in summary["evidence"]
    assert sf.find_review_summary("We have handled cases since 1998.") is None


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def test_links_social_review_and_maps_share_links_excluded():
    _html, team = _page("site_team_page.html")
    links = sf.find_links(team, _BASE + "our-team/")
    assert links["social"] == {
        "facebook": "https://www.facebook.com/hartleylaw",
        "linkedin": "https://www.linkedin.com/company/hartley-injury-law",
    }
    _html, contact = _page("site_contact_page.html")
    links = sf.find_links(contact, _BASE + "contact/")
    assert set(links["review"]) == {"avvo", "yelp"}
    assert links["maps"].startswith("https://www.google.com/maps/place/")


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def test_posts_dated_same_site_newest_first_and_growth_cues():
    _html, tree = _page("site_news_page.html")
    posts = sf.find_posts(tree, _BASE + "news/", "hartleylaw.com")
    assert [p["date"] for p in posts] == ["2026-08-12", "2026-03-03", "2025-11-01"]
    assert posts[0]["title"] == "Hartley Injury Law Opens New Marietta Office"
    assert posts[2]["url"].endswith("/2025/11/luis-ortega-joins-the-firm/")  # date from the URL
    titles = [p["title"] for p in posts]
    assert not any("Undated" in t or "External" in t for t in titles)

    growth = sf.growth_news(posts)
    assert [(g["title"][:20], g["cue"]) for g in growth] == [
        ("Hartley Injury Law O", "opens new marietta office"),
        ("Luis Ortega Joins th", "joins"),
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Posted on March 3, 2026", date(2026, 3, 3)),
        ("Sept. 9th, 2025", date(2025, 9, 9)),
        ("11/02/2024", date(2024, 11, 2)),
        ("2026-08-12T10:00:00", date(2026, 8, 12)),
        ("no date here", None),
        ("February 30, 2026", None),
    ],
)
def test_parse_date_text(text, expected):
    assert sf.parse_date_text(text) == expected


# ---------------------------------------------------------------------------
# What the site runs, and the footer
# ---------------------------------------------------------------------------


def test_chat_vendor_intake_form_and_copyright():
    html, tree = _page("site_contact_page.html")
    assert sf.find_chat_vendor(html) == "Intaker"
    assert sf.has_intake_form(tree, html) is True  # Contact Form 7 marker
    assert sf.copyright_year(sf.page_text(tree)) == 2026  # "2019-2026" -> the later year

    team_html, team = _page("site_team_page.html")
    assert sf.find_chat_vendor(team_html) is None
    assert sf.has_intake_form(team, team_html) is False
    assert sf.copyright_year(sf.page_text(team)) == 2021


def test_plain_form_with_an_email_field_is_an_intake_form():
    html = "<html><body><form><input name='n'><input type='email' name='e'></form></body></html>"
    assert sf.has_intake_form(sf.parse(html), html) is True
    search = "<html><body><form><input type='search' name='s'></form></body></html>"
    assert sf.has_intake_form(sf.parse(search), search) is False
