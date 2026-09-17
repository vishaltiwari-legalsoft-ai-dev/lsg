"""P1 site mapper: robots -> sitemap -> page-kind classification -> probes
-> per-firm caps, plus the DISCOVERED -> PROFILING/NO_WEB lifecycle."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from lge.planes.p import p1_site_map
from lge.planes.p.p1_site_map import (
    _apply_caps,
    _parse_sitemap_xml,
    classify_page_kind,
    probe_urls,
)
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx, lead_state, make_lead, site_map_rows

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"
UA = "TestBot/1.0 (+https://example.com/bot)"


# ---------------------------------------------------------------------------
# Pure functions -- no DB, no network
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/", "home"),
        ("https://example.com/about", "about"),
        ("https://example.com/about-us", "about"),
        ("https://example.com/our-attorneys", "attorneys"),
        ("https://example.com/attorney/jane-doe", "attorneys"),
        ("https://example.com/our-team", "team"),
        ("https://example.com/practice-areas/personal-injury", "practice"),
        ("https://example.com/contact-us", "contact"),
        ("https://example.com/careers", "careers"),
        ("https://example.com/jobs", "careers"),
        # paths read off real homepages in the probe (D-026)
        ("https://example.com/law-careers", "careers"),
        ("https://example.com/hiring-personal-injury-paralegal-atlanta-ga", "careers"),
        ("https://example.com/hiring-a-lawyer", "other"),
        ("https://example.com/blog/cost-of-hiring-motorcycle-accident-lawyer", "news"),
        ("https://example.com/sexual-abuse-at-farragut-career-academy-in-illinois", "other"),
        ("https://example.com/fees", "fees"),
        ("https://example.com/blog/some-post", "news"),
        ("https://example.com/random-page", "other"),
    ],
)
def test_classify_page_kind(url, expected):
    assert classify_page_kind(url) == expected


def test_probe_urls_match_the_task_brief_exactly():
    probes = probe_urls("example.com")
    assert probes["about"] == ["https://example.com/about", "https://example.com/about-us"]
    assert probes["attorneys"] == [
        "https://example.com/attorneys",
        "https://example.com/our-attorneys",
    ]
    assert probes["team"] == ["https://example.com/our-team", "https://example.com/team"]
    assert probes["contact"] == ["https://example.com/contact", "https://example.com/contact-us"]
    assert probes["careers"] == [
        "https://example.com/careers",
        "https://example.com/jobs",
        "https://example.com/employment-opportunities",
    ]
    # a kind the config does not read (cap 0) is not probed for (D-044)
    assert "practice" not in probes and "fees" not in probes and "news" not in probes


def test_apply_caps_reads_only_the_wanted_kinds():
    by_kind = {
        "home": [("https://x/", "sitemap")],
        "practice": [(f"https://x/practice-{i}", "sitemap") for i in range(6)],
        "about": [("https://x/about", "sitemap")],
        "attorneys": [("https://x/a1", "sitemap"), ("https://x/a2", "probe")],
        "team": [],
        "contact": [("https://x/contact", "sitemap")],
        "careers": [("https://x/careers", "sitemap")],
        "fees": [("https://x/fees", "sitemap")],
    }
    out = _apply_caps(by_kind)
    kinds = [k for _u, k, _v in out]
    assert kinds.count("home") == 1
    assert kinds.count("practice") == 0  # cap 0: classified, never mapped (D-044)
    assert kinds.count("fees") == 0
    assert kinds.count("attorneys") == 2  # both fit under the attorneys cap of 3
    assert len(out) <= 12


def test_apply_caps_prefers_sitemap_over_probe_within_a_kind():
    by_kind = {"about": [("https://x/about-probe", "probe"), ("https://x/about", "sitemap")]}
    out = _apply_caps(by_kind)
    # cap=2 -> both fit, but sitemap-discovered sorts first
    assert out[0] == ("https://x/about", "about", "sitemap")


def test_apply_caps_per_kind_and_total_of_12():
    by_kind: dict[str, list[tuple[str, str]]] = {}
    for kind in ("home", "practice", "about", "attorneys", "team", "contact", "careers",
                 "fees", "locations", "testimonials", "news"):
        by_kind[kind] = [(f"https://x/{kind}-{i}", "sitemap") for i in range(8)]
    out = _apply_caps(by_kind)
    kinds = [k for _u, k, _v in out]
    # home 1 + contact 1 + about 1 + attorneys 3 + team 2 + careers 2 + testimonials 2 = 12
    assert (kinds.count("news"), kinds.count("testimonials"), kinds.count("locations")) == (0, 2, 0)
    assert kinds.count("attorneys") == 3 and kinds.count("practice") == 0
    assert kinds[0] == "home"  # the config's order is the map's order
    assert len(out) == 12


@pytest.mark.parametrize(
    "url,anchor,expected",
    [
        ("https://firm.com/x/", "Our Offices", "locations"),
        ("https://firm.com/x/", "Areas We Serve", "locations"),
        ("https://firm.com/x/", "Testimonials", "testimonials"),
        ("https://firm.com/x/", "Case Results", "testimonials"),
        ("https://firm.com/x/", "Blog", "news"),
        ("https://firm.com/x/", "Firm News", "news"),
        ("https://firm.com/case-results/", "Home", "testimonials"),
        ("https://firm.com/blog/why-hire-us/", "Home", "news"),
        ("https://firm.com/locations/atlanta/", "Home", "locations"),
    ],
)
def test_new_page_kinds_from_anchor_and_path(url, anchor, expected):
    from lge.planes.p.p1_site_map import classify_link

    assert classify_link(url, anchor) == expected


def test_parse_sitemap_xml_urlset():
    body = (_FIXTURES / "sitemap_flat.xml").read_bytes()
    urls, subs = _parse_sitemap_xml(body)
    assert len(urls) == 14
    assert "https://example.com/careers" in urls
    assert subs == []


def test_parse_sitemap_xml_index():
    body = (_FIXTURES / "sitemap_index.xml").read_bytes()
    urls, subs = _parse_sitemap_xml(body)
    assert urls == []
    assert subs == [
        "https://example.com/sitemap_sub1.xml",
        "https://example.com/sitemap_sub2.xml",
    ]


def test_parse_sitemap_xml_malformed_returns_empty_not_raise():
    urls, subs = _parse_sitemap_xml(b"<not valid xml")
    assert urls == []
    assert subs == []


# ---------------------------------------------------------------------------
# Live gate / honest UA
# ---------------------------------------------------------------------------


@respx.mock
def test_live_gate_off_makes_no_requests(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    result = p1_site_map.run(ctx(db, live=False), limit=10)
    assert "live=0" in " ".join(result.notes)
    assert result.processed == 0
    assert site_map_rows(db, firm_id) == []


@respx.mock
def test_empty_user_agent_refuses_when_live(db):
    from lge.fetch.client import EmptyUserAgentError

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    with pytest.raises(EmptyUserAgentError):
        p1_site_map.run(ctx(db, live=True, user_agent=""), limit=10)


def test_no_firms_selected_is_a_clean_no_op(db):
    result = p1_site_map.run(ctx(db, live=True), limit=10)
    assert result.processed == 0
    assert "no firms selected" in " ".join(result.notes)


# ---------------------------------------------------------------------------
# Full flow -- sitemap index one level, page-kind caps, lifecycle
# ---------------------------------------------------------------------------


@respx.mock
def test_sitemap_index_one_level_and_lifecycle_to_profiling(db):
    # the mapper reads the homepage nav before blind probes
    respx.get("https://example.com/").mock(return_value=httpx.Response(200, html="<html></html>"))
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(
            200, text="User-agent: *\nSitemap: https://example.com/sitemap_index.xml\n"
        )
    )
    respx.get("https://example.com/sitemap_index.xml").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "sitemap_index.xml").read_bytes())
    )
    respx.get("https://example.com/sitemap_sub1.xml").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "sitemap_sub1.xml").read_bytes())
    )
    respx.get("https://example.com/sitemap_sub2.xml").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "sitemap_sub2.xml").read_bytes())
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)

    result = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert result.processed == 1
    assert result.failed == 0

    rows = site_map_rows(db, firm_id)
    kinds = {r["page_kind"] for r in rows}
    # sub1+sub2 cover home/about/attorneys/contact/careers via sitemap;
    # team is missing from both sub-sitemaps -> probed. practice/fees are not
    # read at all (cap 0), so they are neither taken from the sitemap nor probed.
    assert {"home", "about", "attorneys", "contact", "careers"} <= kinds
    assert "team" in kinds  # added via probe
    assert "practice" not in kinds and "fees" not in kinds
    by_url = {r["url"]: r["discovered_via"] for r in rows}
    assert by_url["https://example.com/careers"] == "sitemap"
    assert by_url["https://example.com/our-team"] == "probe"

    assert lead_state(db, firm_id) == "PROFILING"


@respx.mock
def test_a_dropped_kind_in_the_sitemap_is_not_mapped(db):
    # the mapper reads the homepage nav before blind probes
    respx.get("https://example.com/").mock(return_value=httpx.Response(200, html="<html></html>"))
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, content=(_FIXTURES / "sitemap_flat.xml").read_bytes())
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    rows = site_map_rows(db, firm_id)
    # the fixture lists six practice pages; the engine no longer reads that kind
    assert [r for r in rows if r["page_kind"] == "practice"] == []
    team_urls = [r["url"] for r in rows if r["page_kind"] == "team"]
    assert len(team_urls) == 2  # both probes fit under the team cap
    assert len(rows) <= 12
    assert all(r["discovered_via"] == "probe" for r in rows if r["page_kind"] == "team")
    # 'other' never makes it into site_map at all.
    assert not any(r["page_kind"] == "other" for r in rows)
    assert len(rows) <= 30


# ---------------------------------------------------------------------------
# NO_WEB paths
# ---------------------------------------------------------------------------


@respx.mock
def test_edge_blocked_host_is_no_verdict_and_is_retried(db):
    # A 403 on robots.txt means no policy was read. The live probe parked 38 firms
    # as NO_WEB this way and one answered 200 the next day (D-026).
    route = respx.get("https://blocked.example.com/robots.txt").mock(
        return_value=httpx.Response(403)
    )

    firm_id = make_firm(db, domain="blocked.example.com")
    make_lead(db, firm_id)
    result = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert result.processed == 0
    assert result.skipped == 1
    assert site_map_rows(db, firm_id) == []
    assert lead_state(db, firm_id) == "DISCOVERED"

    from tests.planes.p._p_helpers import source_registry_row

    reg = source_registry_row(db, "blocked.example.com")
    assert reg["source_state"] == "edge_blocked"

    # Not marked done: the next run asks the host again instead of skipping it.
    p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert route.call_count == 2


@respx.mock
def test_policy_closed_host_routes_to_no_web(db):
    # A published rule closing the site is a verdict, unlike a blocked fetch.
    respx.get("https://closed.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    )
    firm_id = make_firm(db, domain="closed.example.com")
    make_lead(db, firm_id)
    result = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert result.processed == 1
    assert site_map_rows(db, firm_id) == []
    assert lead_state(db, firm_id) == "NO_WEB"


def test_no_domain_routes_to_no_web_via_firm_ids_file(db, tmp_path):
    firm_id = make_firm(db, domain=None)
    make_lead(db, firm_id)
    ids_file = tmp_path / "firm_ids.txt"
    ids_file.write_text(f"{firm_id}\n", encoding="utf-8")

    result = p1_site_map.run(ctx(db, live=True, user_agent=UA), firm_ids_file=str(ids_file))
    assert result.processed == 1
    assert lead_state(db, firm_id) == "NO_WEB"
    assert site_map_rows(db, firm_id) == []


@respx.mock
def test_unreachable_host_stays_discovered_no_conclusion(db):
    respx.get("https://down.example.com/robots.txt").mock(
        side_effect=httpx.ConnectError("refused")
    )
    firm_id = make_firm(db, domain="down.example.com")
    make_lead(db, firm_id)
    result = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert result.processed == 0
    assert result.skipped == 1
    assert lead_state(db, firm_id) == "DISCOVERED"  # a network condition, not a verdict
    from tests.planes.p._p_helpers import source_registry_row

    assert source_registry_row(db, "down.example.com")["source_state"] == "unreachable"


# ---------------------------------------------------------------------------
# Crawl-delay persisted
# ---------------------------------------------------------------------------


@respx.mock
def test_crawl_delay_persisted_to_source_registry(db):
    # the mapper reads the homepage nav before blind probes
    respx.get("https://slow.example.com/").mock(
        return_value=httpx.Response(200, html="<html></html>")
    )
    respx.get("https://slow.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n")
    )
    respx.get("https://slow.example.com/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://slow.example.com/sitemap_index.xml").mock(return_value=httpx.Response(404))

    firm_id = make_firm(db, domain="slow.example.com")
    make_lead(db, firm_id)
    p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    from tests.planes.p._p_helpers import source_registry_row

    reg = source_registry_row(db, "slow.example.com")
    assert reg["source_state"] == "rate_limited"
    assert float(reg["crawl_delay_s"]) == 5.0
    assert lead_state(db, firm_id) == "PROFILING"  # rate_limited is still crawlable


@respx.mock
def test_slow_host_is_probed_only(db):
    # cavanaghlawgroup.com declares Crawl-delay 600 (D-026): one robots read, no
    # sitemap and no homepage this run, probes for P2 to budget.
    respx.get("https://crawl.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 600\n")
    )
    sitemap = respx.get("https://crawl.example.com/sitemap.xml").mock(
        return_value=httpx.Response(404)
    )
    home = respx.get("https://crawl.example.com/").mock(
        return_value=httpx.Response(200, html="<html></html>")
    )
    firm_id = make_firm(db, domain="crawl.example.com")
    make_lead(db, firm_id)
    result = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")

    assert result.processed == 1
    assert sitemap.call_count == 0 and home.call_count == 0
    assert lead_state(db, firm_id) == "PROFILING"
    rows = site_map_rows(db, firm_id)
    assert rows and all(r["discovered_via"] == "probe" for r in rows)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@respx.mock
def test_rerun_with_unchanged_domain_is_a_no_op(db):
    # the mapper reads the homepage nav before blind probes
    respx.get("https://example.com/").mock(return_value=httpx.Response(200, html="<html></html>"))
    robots_route = respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/sitemap_index.xml").mock(return_value=httpx.Response(404))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)

    r1 = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert r1.processed == 1
    assert robots_route.call_count == 1

    r2 = p1_site_map.run(ctx(db, live=True, user_agent=UA), limit=10, default_interval_s="0")
    assert r2.processed == 0
    assert r2.skipped == 1
    assert robots_route.call_count == 1  # no second network call at all
