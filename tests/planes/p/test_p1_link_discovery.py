"""Homepage link discovery — the live probe found only the homepage on small-firm
sites with no sitemap, because blind path probes (/our-team, /practice-areas) 404.
The homepage's own navigation is the reliable map."""

import pytest

from lge.planes.p.p1_site_map import classify_link, extract_homepage_links

HOME = b"""<html><body>
<nav>
  <a href="/">Home</a>
  <a href="/who-we-are/">About Us</a>
  <a href="/meet-the-lawyers/">Our Attorneys</a>
  <a href="/car-accidents/">Car Accidents</a>
  <a href="/truck-accident-lawyer/">Trucks</a>
  <a href="https://www.firm.com/join/">Join Our Team</a>
  <a href="/blog/news-roundup/">Blog</a>
  <a href="#main">Skip</a>
  <a href="tel:+14045551234">Call</a>
  <a href="https://facebook.com/firm">Facebook</a>
  <a href="/brochure.pdf">Brochure</a>
  <a href="/car-accidents/?utm=x">Car Accidents again</a>
</nav></body></html>"""


def test_nav_links_are_classified_by_anchor_text_and_practice_vocabulary():
    links = dict(extract_homepage_links(HOME, "https://firm.com/", "firm.com"))
    assert links["https://firm.com/who-we-are/"] == "about"
    assert links["https://firm.com/meet-the-lawyers/"] == "attorneys"
    assert links["https://firm.com/car-accidents/"] == "practice"
    assert links["https://firm.com/truck-accident-lawyer/"] == "practice"   # from the slug
    assert links["https://www.firm.com/join/"] == "careers"


def test_offsite_media_fragments_and_unclassifiable_links_are_dropped():
    urls = [u for u, _k in extract_homepage_links(HOME, "https://firm.com/", "firm.com")]
    assert not any("facebook" in u or u.endswith(".pdf") or "tel:" in u for u in urls)
    assert "https://firm.com/blog/news-roundup/" in urls   # the blog is a kind now (D-030)
    assert "https://firm.com/#main" not in urls
    assert urls.count("https://firm.com/car-accidents/") == 1  # query-string dupe collapsed


def test_path_classification_still_wins_over_anchor_text():
    assert classify_link("https://firm.com/practice-areas/", "Home") == "practice"


# Anchors read off real homepages in the live probe (D-026). The first group was
# missed -- one of them linked an open paralegal posting straight from the
# homepage. The second group are practice pages and blog posts that must not
# become careers pages.
@pytest.mark.parametrize(
    "anchor",
    [
        "B|K is Hiring a Personal Injury Paralegal",  # butlerfirm.com
        "Join Us",  # atlinjurylawgroup.com
        "Employment",  # pennlawgroup.com nav
        "Now Hiring",
        "Open Positions",
        "Job Openings",
    ],
)
def test_real_hiring_anchors_are_careers(anchor):
    assert classify_link("https://firm.com/page-x/", anchor) == "careers"


@pytest.mark.parametrize(
    "anchor",
    [
        "Employment & Wage Litigation",  # friedbonder.com
        "Employment Discrimination Lawyer",  # jtnylaw.com
        "What Is the Cost of Hiring a Motorcycle Accident Lawyer",  # kainelaw.com blog
        "workers injured on the job",  # npslaws.com
        "Hiring an attorney",  # briskmanandbriskman.com
    ],
)
def test_practice_and_blog_anchors_are_not_careers(anchor):
    assert classify_link("https://firm.com/page-x/", anchor) != "careers"


def test_broken_html_is_tolerated():
    assert extract_homepage_links(b"<a href='/about'>About<<<", "https://f.com/", "f.com") == [
        ("https://f.com/about", "about")
    ]
