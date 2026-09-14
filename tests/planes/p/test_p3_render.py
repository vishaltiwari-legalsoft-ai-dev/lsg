"""P3 render gate: fires only when static text is under 500 words, flags
`document.render_needed`, renders through the system Chrome when there is
one, and reports "render unavailable" when there is not."""

from __future__ import annotations

import pytest

from lge.planes.p import p3_render
from lge.store.objects import ObjectStore
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx, make_lead

pytestmark = pytest.mark.db


def insert_document(conn, firm_id, *, url, word_count, fetch_ok=True, status_code=200):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document (firm_id, url, status_code, content_hash, bytes, word_count,
                                   fetch_ok, page_kind, rendered)
            VALUES (%s, %s, %s, %s, 100, %s, %s, 'home', false)
            RETURNING id
            """,
            (firm_id, url, status_code, f"hash-{url}", word_count, fetch_ok),
        )
        return cur.fetchone()["id"]


def get_document(conn, doc_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM document WHERE id = %s", (doc_id,))
        return cur.fetchone()


def test_render_available_follows_the_chrome_binary(monkeypatch, tmp_path):
    # The renderer is the system Chrome (D-030): no browser, no render.
    original = p3_render.chrome_path
    monkeypatch.setattr(p3_render, "chrome_path", lambda: None)
    assert p3_render.render_available() is False
    fake = tmp_path / "chrome.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("LGE_CHROME", str(fake))
    monkeypatch.setattr(p3_render, "chrome_path", original)
    assert p3_render.render_available() is True
    monkeypatch.setenv("LGE_CHROME", str(tmp_path / "missing.exe"))
    assert p3_render.render_available() is False


def test_no_firms_selected_is_a_clean_no_op(db):
    result = p3_render.run(ctx(db, live=True), limit=10)
    assert result.processed == 0
    assert "no firms selected" in " ".join(result.notes)


def test_thin_page_is_flagged_render_needed(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(db, firm_id, url="https://example.com/", word_count=120)

    result = p3_render.run(ctx(db, live=False), limit=10)
    assert result.processed == 1

    doc = get_document(db, doc_id)
    assert doc["render_needed"] is True
    assert doc["rendered"] is False  # never actually rendered -- live=0


def test_page_over_the_gate_is_not_flagged(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(db, firm_id, url="https://example.com/", word_count=800)

    result = p3_render.run(ctx(db, live=False), limit=10)
    assert result.processed == 0

    doc = get_document(db, doc_id)
    assert doc["render_needed"] is False


def test_failed_fetch_is_never_flagged(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(
        db, firm_id, url="https://example.com/", word_count=50, fetch_ok=False
    )
    p3_render.run(ctx(db, live=False), limit=10)
    assert get_document(db, doc_id)["render_needed"] is False


def test_404_is_never_flagged_even_with_low_word_count(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(
        db, firm_id, url="https://example.com/x", word_count=0, status_code=404
    )
    p3_render.run(ctx(db, live=False), limit=10)
    assert get_document(db, doc_id)["render_needed"] is False


def test_only_a_javascript_shell_is_flagged_a_thin_static_page_is_not(db, tmp_path):
    # With 30 pages per firm the map holds contact and office pages that say
    # little on purpose; a browser would give back the same words. Only an
    # application shell (root element, scripts, no text) is worth a render.
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    shell = store.put(
        b'<html><body><div id="root"></div><script src="/a.js"></script>'
        b"<script>window.__NEXT_DATA__={}</script></body></html>"
    )
    static = store.put(b"<html><body><h1>Contact</h1><p>Call us at 555-0100.</p></body></html>")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, status_code, content_hash, object_key, bytes, "
            "word_count, fetch_ok, page_kind, rendered) VALUES "
            "(%s, 'https://example.com/', 200, %s, %s, 100, 3, true, 'home', false), "
            "(%s, 'https://example.com/contact/', 200, %s, %s, 100, 5, true, 'contact', false)",
            (firm_id, shell, shell, firm_id, static, static),
        )

    result = p3_render.run(ctx(db, live=False), limit=10, store=store)
    assert result.processed == 1
    with db.cursor() as cur:
        cur.execute(
            "SELECT url, render_needed FROM document WHERE firm_id = %s ORDER BY url", (firm_id,)
        )
        flagged = {r["url"]: r["render_needed"] for r in cur.fetchall()}
    assert flagged == {"https://example.com/": True, "https://example.com/contact/": False}
    assert "1 thin page(s) are static" in " ".join(result.notes)


def test_reports_render_unavailable_with_a_count(db, monkeypatch):
    monkeypatch.setattr(p3_render, "render_available", lambda: False)  # no browser here
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_document(db, firm_id, url="https://example.com/a", word_count=10)
    insert_document(db, firm_id, url="https://example.com/b", word_count=20)

    result = p3_render.run(ctx(db, live=False), limit=10)
    joined = " ".join(result.notes)
    assert "render unavailable" in joined
    assert "2 page(s)" in joined


def test_gate_runs_regardless_of_live_flag_no_network_needed(db):
    """Flagging is a pure DB operation -- it must not require live=1."""
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(db, firm_id, url="https://example.com/", word_count=42)

    result = p3_render.run(ctx(db, live=False), limit=10)
    assert result.processed == 1
    assert get_document(db, doc_id)["render_needed"] is True


def test_rerun_with_unchanged_documents_is_a_no_op(db):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_document(db, firm_id, url="https://example.com/", word_count=42)

    r1 = p3_render.run(ctx(db, live=False), limit=10)
    assert r1.processed == 1

    r2 = p3_render.run(ctx(db, live=False), limit=10)
    assert r2.processed == 0
    assert r2.skipped == 1


def test_when_a_browser_is_available_and_live_it_attempts_render(db, monkeypatch, tmp_path):
    """The render function is replaced so the attempt/record-keeping path is
    proven without launching Chrome in the test."""
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(db, firm_id, url="https://example.com/", word_count=42)

    monkeypatch.setattr(p3_render, "render_available", lambda: True)
    monkeypatch.setattr(
        p3_render, "_render_page_sync", lambda url, user_agent: b"<html>rendered</html>"
    )

    result = p3_render.run(
        ctx(db, live=True, user_agent="TestBot/1.0 (+https://x)"),
        limit=10,
        store=ObjectStore(tmp_path),
    )
    assert result.processed == 1
    joined = " ".join(result.notes)
    assert "rendered 1/1" in joined

    doc = get_document(db, doc_id)
    assert doc["rendered"] is True
    assert doc["object_key"] is not None


def test_a_dom_already_on_file_for_the_url_marks_the_row_rendered_without_a_clash(
    db, monkeypatch, tmp_path
):
    # (url, content_hash) is unique: an earlier fetch already holds the DOM
    # the render produces (jonaplaw.com/careers on the probe). The thin row
    # is marked rendered and left as it was, instead of a unique violation.
    store = ObjectStore(tmp_path)
    dom = b"<html><body>" + b"<p>rendered words</p>" * 300 + b"</body></html>"
    dom_key = store.put(dom)
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, status_code, content_hash, object_key, bytes, "
            "word_count, fetch_ok, page_kind, rendered) VALUES "
            "(%s, 'https://example.com/careers', 200, %s, %s, 100, 600, true, 'careers', false)",
            (firm_id, dom_key, dom_key),
        )
    thin_id = insert_document(db, firm_id, url="https://example.com/careers", word_count=3)

    monkeypatch.setattr(p3_render, "render_available", lambda: True)
    monkeypatch.setattr(p3_render, "_render_page_sync", lambda url, user_agent: dom)
    result = p3_render.run(
        ctx(db, live=True, user_agent="TestBot/1.0 (+https://x)"), limit=10, store=store
    )
    assert result.failed == 0 and result.processed == 1, result.notes

    doc = get_document(db, thin_id)
    assert doc["rendered"] is True
    assert doc["content_hash"] == f"hash-{doc['url']}"  # unchanged: the DOM is already on file


def test_render_failure_is_caught_and_logged_not_raised(db, monkeypatch):
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(db, firm_id, url="https://example.com/", word_count=42)

    monkeypatch.setattr(p3_render, "render_available", lambda: True)

    def _boom(url, user_agent):
        raise RuntimeError("browser launch blocked by OS policy")

    monkeypatch.setattr(p3_render, "_render_page_sync", _boom)

    result = p3_render.run(ctx(db, live=True, user_agent="TestBot/1.0 (+https://x)"), limit=10)
    assert result.processed == 1  # the firm is still processed -- render is best-effort
    doc = get_document(db, doc_id)
    assert doc["rendered"] is False
