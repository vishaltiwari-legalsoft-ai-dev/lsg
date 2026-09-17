"""P2 page fetcher: content-hash dedupe + object-store round trip, 404
probes recorded (not text-extracted), firm.last_crawled/content_hash under
writer('profile'), robots-disallowed and host-not-crawlable bookkeeping."""

from __future__ import annotations

import httpx
import pytest
import respx

from lge.planes.p import p2_fetch
from lge.store.objects import ObjectStore
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx, make_lead

pytestmark = pytest.mark.db

UA = "TestBot/1.0 (+https://example.com/bot)"


def insert_site_map(conn, firm_id, url, page_kind, discovered_via="sitemap"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO site_map (firm_id, url, page_kind, discovered_via) "
            "VALUES (%s, %s, %s, %s)",
            (firm_id, url, page_kind, discovered_via),
        )


def get_documents(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM document WHERE firm_id = %s ORDER BY url", (firm_id,)
        )
        return cur.fetchall()


def get_firm(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute("SELECT last_crawled, content_hash FROM firm WHERE id = %s", (firm_id,))
        return cur.fetchone()


@respx.mock
def test_live_gate_off_makes_no_requests(db, tmp_path):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")
    result = p2_fetch.run(
        ctx(db, live=False), limit=10, store=ObjectStore(tmp_path)
    )
    assert result.processed == 0
    assert get_documents(db, firm_id) == []


def test_no_site_map_rows_is_a_clean_no_op(db, tmp_path):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    result = p2_fetch.run(ctx(db, live=True), limit=10, store=ObjectStore(tmp_path))
    assert result.processed == 0
    assert "p1_site_map" in " ".join(result.notes)


@respx.mock
def test_empty_user_agent_refuses(db, tmp_path):
    from lge.fetch.client import EmptyUserAgentError

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")
    with pytest.raises(EmptyUserAgentError):
        p2_fetch.run(
            ctx(db, live=True, user_agent=""), limit=10, store=ObjectStore(tmp_path)
        )


@respx.mock
def test_successful_fetch_stores_object_and_writes_document(db, tmp_path):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(200, html="<html><body>Home page text</body></html>")
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")

    store = ObjectStore(tmp_path)
    result = p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=store, default_interval_s="0"
    )
    assert result.processed == 1

    docs = get_documents(db, firm_id)
    assert len(docs) == 1
    doc = docs[0]
    assert doc["fetch_ok"] is True
    assert doc["status_code"] == 200
    assert doc["page_kind"] == "home"
    assert doc["object_key"] == doc["content_hash"]
    assert doc["word_count"] > 0

    # object-store round trip: exact original bytes come back.
    roundtrip = store.get(doc["object_key"])
    assert roundtrip == b"<html><body>Home page text</body></html>"

    firm_row = get_firm(db, firm_id)
    assert firm_row["last_crawled"] is not None
    assert firm_row["content_hash"] == doc["content_hash"]


def test_budgeted_keeps_the_most_valuable_pages():
    urls = [("https://f.com/team", "team"), ("https://f.com/", "home"),
            ("https://f.com/careers", "careers"), ("https://f.com/about", "about")]
    # 4 pages at 2s fit easily: everything, most valuable first -- the config's order
    fetch, later = p2_fetch.budgeted(urls, 2.0)
    assert [k for _u, k in fetch] == ["home", "about", "team", "careers"] and later == []
    # 4 pages at 600s do not: one page (the homepage), the rest left for later
    fetch, later = p2_fetch.budgeted(urls, 600.0)
    assert fetch == [("https://f.com/", "home")]
    assert len(later) == 3
    # no declared delay -> no trimming
    assert p2_fetch.budgeted(urls, None)[1] == []


@respx.mock
def test_slow_host_gets_only_what_fits_the_budget(db, tmp_path, monkeypatch):
    # cavanaghlawgroup.com's shape (D-026), scaled down so the test does not wait.
    monkeypatch.setattr(p2_fetch, "HOST_TIME_BUDGET_S", 3.0)
    respx.get("https://slow.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 2\n")
    )
    home = respx.get("https://slow.example.com/").mock(
        return_value=httpx.Response(200, html="<html><body>Home page text</body></html>")
    )
    about = respx.get("https://slow.example.com/about").mock(
        return_value=httpx.Response(200, html="<html><body>About</body></html>")
    )
    contact = respx.get("https://slow.example.com/contact").mock(
        return_value=httpx.Response(200, html="<html><body>Contact</body></html>")
    )
    firm_id = make_firm(db, domain="slow.example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://slow.example.com/about", "about")
    insert_site_map(db, firm_id, "https://slow.example.com/", "home")
    insert_site_map(db, firm_id, "https://slow.example.com/contact", "contact")

    result = p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=ObjectStore(tmp_path),
        default_interval_s="0",
    )
    assert result.processed == 1
    assert (home.call_count, about.call_count, contact.call_count) == (1, 0, 0)
    docs = {d["url"]: d for d in get_documents(db, firm_id)}
    assert docs["https://slow.example.com/"]["fetch_ok"] is True
    assert docs["https://slow.example.com/about"]["fetch_ok"] is False
    assert docs["https://slow.example.com/contact"]["fetch_ok"] is False


@respx.mock
@respx.mock
def test_crawl_respects_the_per_host_time_budget(db, tmp_path, monkeypatch):
    # A host with a Crawl-delay gets only what fits the per-host budget, pages
    # found by crawling included -- found on the probe: one host at 30s took
    # fifteen minutes for its thirty pages.
    monkeypatch.setattr(p2_fetch, "HOST_TIME_BUDGET_S", 4)  # 4s / 2s delay -> 2 pages
    respx.get("https://slow.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 2\n")
    )
    respx.get("https://slow.example/").mock(return_value=httpx.Response(200, html=(
        '<html><body><a href="/testimonials/">Testimonials</a>'
        ' <a href="/our-offices/">Our Offices</a> <a href="/blog/">Blog</a></body></html>'
    )))
    for path in ("/testimonials/", "/our-offices/", "/blog/"):
        respx.get(f"https://slow.example{path}").mock(
            return_value=httpx.Response(200, html=f"<html><body>{path} page text</body></html>")
        )
    firm_id = make_firm(db, domain="slow.example")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://slow.example/", "home")

    p2_fetch.run(ctx(db, live=True, user_agent=UA), limit=10, store=ObjectStore(tmp_path))
    fetched = [d["url"] for d in get_documents(db, firm_id) if d["fetch_ok"]]
    assert len(fetched) == 2  # the home page and one discovered page
    assert "https://slow.example/" in fetched


@respx.mock
def test_links_on_fetched_pages_are_crawled_within_caps(db, tmp_path):
    # D-030: the firm's testimonials and team live a click or two away from
    # the homepage. D-044: a link to a kind the config does not read (offices,
    # blog) is recognised and left alone. Duplicate bytes are written once; a
    # 200 that is an error page is marked, not read.
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    testimonials_html = (
        '<html><body><blockquote>Great lawyers.</blockquote>'
        ' <a href="/our-team/">Meet the team</a></body></html>'
    )
    respx.get("https://example.com/").mock(return_value=httpx.Response(200, html=(
        '<html><body><a href="/testimonials/">Testimonials</a>'
        ' <a href="/our-offices/">Our Offices</a>'
        ' <a href="/blog/">Blog</a> <a href="/careers-old/">Careers</a>'
        ' <a href="/index.html">Home again</a></body></html>'
    )))
    respx.get("https://example.com/testimonials/").mock(
        return_value=httpx.Response(200, html=testimonials_html)
    )
    offices = respx.get("https://example.com/our-offices/").mock(
        return_value=httpx.Response(200, html="<html><body><p>Atlanta and Macon.</p></body></html>")
    )
    blog = respx.get("https://example.com/blog/").mock(
        return_value=httpx.Response(200, html="<html><body><p>Posts.</p></body></html>")
    )
    respx.get("https://example.com/careers-old/").mock(
        return_value=httpx.Response(200, html=testimonials_html)
    )
    respx.get("https://example.com/index.html").mock(
        return_value=httpx.Response(200, html="<html><body>Home page text</body></html>")
    )
    respx.get("https://example.com/our-team/").mock(
        return_value=httpx.Response(200, html="<html><body><h1>Page not found</h1></body></html>")
    )

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")

    result = p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=ObjectStore(tmp_path),
        default_interval_s="0",
    )
    assert result.processed == 1
    docs = {d["url"]: d for d in get_documents(db, firm_id)}

    # followed: testimonials (from home) and the team page (from testimonials)
    assert "https://example.com/testimonials/" in docs
    assert docs["https://example.com/our-team/"]["page_kind"] == "team"
    # a link to a kind the config does not read is recognised and never fetched
    assert "https://example.com/our-offices/" not in docs and offices.call_count == 0
    assert "https://example.com/blog/" not in docs and blog.call_count == 0
    # a 200 that is an error page is marked, and never read for meaning
    assert docs["https://example.com/our-team/"]["soft_404"] is True
    # the same bytes as /testimonials/ -> written once, the first URL stands
    assert "https://example.com/careers-old/" not in docs
    # 'home' is never crawled into (index.html), and the crawl left its map behind
    assert "https://example.com/index.html" not in docs
    with db.cursor() as cur:
        cur.execute(
            "SELECT url, page_kind FROM site_map WHERE firm_id = %s AND discovered_via = 'crawl' "
            "ORDER BY url", (firm_id,),
        )
        crawled = cur.fetchall()
    assert {r["page_kind"] for r in crawled} == {"testimonials", "careers", "team"}
    assert "found by crawling" in result.notes[0]

    # a second run: the crawl rows do not change the key, nothing is fetched again
    again = p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=ObjectStore(tmp_path),
        default_interval_s="0",
    )
    assert again.processed == 0 and again.skipped == 1


@respx.mock
def test_failed_fetch_records_its_reason(db, tmp_path):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    )
    respx.get("https://example.com/").mock(side_effect=httpx.ConnectTimeout("slow"))
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")
    insert_site_map(db, firm_id, "https://example.com/private", "about")

    p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=ObjectStore(tmp_path),
        default_interval_s="0",
    )
    docs = {d["url"]: d for d in get_documents(db, firm_id)}
    assert docs["https://example.com/"]["fetch_ok"] is False
    assert "ConnectTimeout" in docs["https://example.com/"]["fetch_error"]
    assert docs["https://example.com/private"]["fetch_error"] == "robots.txt disallows this path"


@respx.mock
def test_same_url_same_hash_produces_no_duplicate_row(db, tmp_path):
    body = b"<html><body>Stable content</body></html>"
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/").mock(return_value=httpx.Response(200, content=body))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")
    store = ObjectStore(tmp_path)
    key = store.put(body)

    # Pre-existing row with the SAME (url, content_hash) P2 is about to fetch.
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document (firm_id, url, status_code, content_hash, object_key, bytes,
                                   fetch_ok, page_kind)
            VALUES (%s, %s, 200, %s, %s, %s, true, 'home')
            """,
            (firm_id, "https://example.com/", key, key, len(body)),
        )

    p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=store, default_interval_s="0"
    )

    docs = get_documents(db, firm_id)
    assert len(docs) == 1  # ON CONFLICT (url, content_hash) DO NOTHING -- no duplicate


@respx.mock
def test_404_probe_is_fetch_ok_and_not_text_extracted(db, tmp_path):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/about").mock(return_value=httpx.Response(404, text="Not Found"))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/about", "about", discovered_via="probe")

    p2_fetch.run(
        ctx(db, live=True, user_agent=UA),
        limit=10,
        store=ObjectStore(tmp_path),
        default_interval_s="0",
    )

    docs = get_documents(db, firm_id)
    assert len(docs) == 1
    assert docs[0]["fetch_ok"] is True
    assert docs[0]["status_code"] == 404
    assert docs[0]["word_count"] is None  # not text-extracted


@respx.mock
def test_robots_disallowed_path_is_recorded_not_fetched(db, tmp_path):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /contact\n")
    )
    admin_route = respx.get("https://example.com/contact")

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/contact", "contact", discovered_via="probe")

    p2_fetch.run(
        ctx(db, live=True, user_agent=UA),
        limit=10,
        store=ObjectStore(tmp_path),
        default_interval_s="0",
    )

    assert admin_route.call_count == 0
    docs = get_documents(db, firm_id)
    assert len(docs) == 1
    assert docs[0]["fetch_ok"] is False
    assert docs[0]["robots_decision"] == "disallowed"
    assert docs[0]["object_key"] is None


@respx.mock
def test_host_not_crawlable_records_every_url_as_failed(db, tmp_path):
    respx.get("https://blocked.example.com/robots.txt").mock(return_value=httpx.Response(403))

    firm_id = make_firm(db, domain="blocked.example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://blocked.example.com/", "home")
    insert_site_map(db, firm_id, "https://blocked.example.com/about", "about")

    p2_fetch.run(
        ctx(db, live=True, user_agent=UA),
        limit=10,
        store=ObjectStore(tmp_path),
        default_interval_s="0",
    )

    docs = get_documents(db, firm_id)
    assert len(docs) == 2
    assert all(not d["fetch_ok"] for d in docs)
    firm_row = get_firm(db, firm_id)
    assert firm_row["last_crawled"] is not None
    assert firm_row["content_hash"] is None


@respx.mock
def test_rerun_with_unchanged_site_map_is_a_no_op(db, tmp_path):
    route = respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\n")
    )
    respx.get("https://example.com/").mock(return_value=httpx.Response(200, text="hi"))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/", "home")
    store = ObjectStore(tmp_path)

    r1 = p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=store, default_interval_s="0"
    )
    assert r1.processed == 1
    assert route.call_count == 1

    r2 = p2_fetch.run(
        ctx(db, live=True, user_agent=UA), limit=10, store=store, default_interval_s="0"
    )
    assert r2.processed == 0
    assert r2.skipped == 1
    assert route.call_count == 1  # no second network call
