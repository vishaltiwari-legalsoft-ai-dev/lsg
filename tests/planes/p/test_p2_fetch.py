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
    respx.get("https://example.com/fees").mock(return_value=httpx.Response(404, text="Not Found"))

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/fees", "fees", discovered_via="probe")

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
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")
    )
    admin_route = respx.get("https://example.com/admin")

    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_site_map(db, firm_id, "https://example.com/admin", "other", discovered_via="probe")

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
