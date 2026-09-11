from lge.classify.tech import detect_tech, primary_cms


def test_detects_clio_script_src():
    html = '<html><body><script src="https://grow.clio.com/widget.js"></script></body></html>'
    hits = detect_tech(html)
    names = {h.name for h in hits}
    assert "clio" in names
    hit = next(h for h in hits if h.name == "clio")
    assert hit.category == "cms"
    assert "clio.com" in hit.evidence


def test_detects_lead_docket_iframe_src():
    html = '<html><body><iframe src="https://intake.leaddocket.com/form"></iframe></body></html>'
    hits = detect_tech(html)
    names = {h.name for h in hits}
    assert "lead_docket" in names
    hit = next(h for h in hits if h.name == "lead_docket")
    assert hit.category == "intake"


def test_detects_law_ruler_form_action():
    html = '<html><body><form action="https://app.lawruler.com/submit"></form></body></html>'
    hits = detect_tech(html)
    names = {h.name for h in hits}
    assert "law_ruler" in names


def test_detects_inline_script_text():
    html = """
    <html><body>
    <script>loadWidget("https://intake.mycase.com/widget.js", "abc123");</script>
    </body></html>
    """
    hits = detect_tech(html)
    names = {h.name for h in hits}
    assert "mycase" in names


def test_detects_link_href():
    html = '<html><head><link rel="stylesheet" href="https://cdn.filevine.com/app.css">'
    hits = detect_tech(html)
    names = {h.name for h in hits}
    assert "filevine" in names


def test_no_tech_detected_returns_empty_list():
    html = "<html><body><h1>Smith Law Firm</h1><p>We help clients.</p></body></html>"
    assert detect_tech(html) == []


def test_empty_and_none_html():
    assert detect_tech("") == []
    assert detect_tech(None) == []


def test_broken_html_tolerated():
    # Unclosed tags, missing quotes -- lxml's HTML parser must still recover.
    html = "<html><body><div><script src=mycase.com><p>oops"
    hits = detect_tech(html)
    names = {h.name for h in hits}
    assert "mycase" in names


def test_dedup_by_name_multiple_matches():
    html = """
    <html><body>
    <script src="https://grow.clio.com/a.js"></script>
    <script src="https://app.clio.com/b.js"></script>
    </body></html>
    """
    hits = detect_tech(html)
    clio_hits = [h for h in hits if h.name == "clio"]
    assert len(clio_hits) == 1


def test_evidence_truncated_to_200_chars():
    long_path = "https://grow.clio.com/" + ("x" * 400)
    html = f'<html><body><script src="{long_path}"></script></body></html>'
    hits = detect_tech(html)
    hit = next(h for h in hits if h.name == "clio")
    assert len(hit.evidence) <= 200


def test_primary_cms_returns_first_cms_hit():
    html = """
    <html><body>
    <iframe src="https://intake.leaddocket.com/form"></iframe>
    <script src="https://grow.clio.com/widget.js"></script>
    </body></html>
    """
    hits = detect_tech(html)
    assert primary_cms(hits) == "clio"


def test_primary_cms_none_when_no_cms_hits():
    html = '<html><body><iframe src="https://intake.leaddocket.com/form"></iframe></body></html>'
    hits = detect_tech(html)
    assert all(h.category != "cms" for h in hits)
    assert primary_cms(hits) is None


def test_needles_does_not_match_needless():
    html = '<html><body><p data-x="its needless to worry"></p></body></html>'
    # attribute text isn't scanned at all (only script/link/iframe/form attrs +
    # inline script text), so this is a control case proving no false positive.
    hits = detect_tech(html)
    assert "needles" not in {h.name for h in hits}


def test_bare_brand_words_in_links_do_not_fire():
    # Hostname-anchored patterns: a slug or page copy containing a brand word is
    # not a case-management system. This is the false positive the anchoring fixes.
    html = """<html><body>
      <a href="/how-we-prevail">How we prevail</a>
      <a href="/practice-areas/needles-and-syringe-injuries">Needle injuries</a>
      <a href="/mycase-status">Check my case status</a>
      <script>var msg = "we will prevail for you";</script>
    </body></html>"""
    names = {h.name for h in detect_tech(html)}
    assert names == set()


def test_brand_inside_hostname_fires():
    html = """<html><body>
      <script src="https://cdn.filevine.com/embed.js"></script>
      <iframe src="https://forms.smartadvocate.com/intake?id=9"></iframe>
      <form action="https://app.goclio.com/grow/forms/123"></form>
    </body></html>"""
    names = {h.name for h in detect_tech(html)}
    assert {"filevine", "smartadvocate", "clio"} <= names
