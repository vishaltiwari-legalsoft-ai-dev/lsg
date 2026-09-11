"""Homepage link discovery — the live probe found only the homepage on small-firm
sites with no sitemap, because blind path probes (/our-team, /practice-areas) 404.
The homepage's own navigation is the reliable map."""

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
    assert "https://firm.com/blog/news-roundup/" not in urls   # 'other' is not kept
    assert urls.count("https://firm.com/car-accidents/") == 1  # query-string dupe collapsed


def test_path_classification_still_wins_over_anchor_text():
    assert classify_link("https://firm.com/practice-areas/", "Home") == "practice"


def test_broken_html_is_tolerated():
    assert extract_homepage_links(b"<a href='/about'>About<<<", "https://f.com/", "f.com") == [
        ("https://f.com/about", "about")
    ]
