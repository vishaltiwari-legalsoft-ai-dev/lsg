"""P7 tech-fingerprinter component tests: CMS + intake tooling aggregated across
a firm's pages, idempotent re-run, and version-bump re-parse.

`lge.classify.tech.detect_tech`/`primary_cms` are exercised directly in
tests/classify/test_tech.py -- these tests are about the component wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lge.planes.p import p7_tech
from lge.registry import RunContext
from lge.settings import get_settings
from lge.store.objects import ObjectStore
from tests.conftest import make_firm

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"


def _insert_document(conn, firm_id, store, html, *, page_kind, fetched_at, url=None):
    key = store.put(html.encode("utf-8"))
    url = url or f"https://example.com/{page_kind}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document
                (firm_id, url, status_code, content_hash, object_key, bytes,
                 fetch_ok, page_kind, fetched_at)
            VALUES (%s, %s, 200, %s, %s, %s, true, %s, %s)
            RETURNING id
            """,
            (firm_id, url, key, key, len(html.encode("utf-8")), page_kind, fetched_at),
        )
        return cur.fetchone()["id"]


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _claims(conn, firm_id, attr):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM firm_attribute WHERE firm_id = %s AND attr = %s ORDER BY observed_at",
            (firm_id, attr),
        )
        return cur.fetchall()


def test_filevine_cms_and_intake_tool_detected(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_tech_filevine.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="contact", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    result = p7_tech.run(_ctx(db), store=store)
    assert result.processed == 1
    assert result.failed == 0

    cms = _claims(db, firm_id, "cms_detected")
    assert len(cms) == 1
    assert cms[0]["value"] == "filevine"
    assert cms[0]["source"] == "rules:p7"
    assert "filevine" in cms[0]["evidence"]

    intake = _claims(db, firm_id, "intake_tools")
    assert len(intake) == 1
    assert intake[0]["value"] == ["lawmatics"]


def test_no_tech_detected_writes_no_claims(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_minimal.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    result = p7_tech.run(_ctx(db), store=store)
    assert result.processed == 1
    assert _claims(db, firm_id, "cms_detected") == []
    assert _claims(db, firm_id, "intake_tools") == []


def test_cms_aggregated_across_pages(db, tmp_path):
    # The CMS widget only shows up on the contact page; the home page carries no
    # tech signal at all. The firm-level claim must still fire.
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    home_html = (_FIXTURES / "site_minimal.html").read_text(encoding="utf-8")
    contact_html = (_FIXTURES / "site_tech_filevine.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, home_html, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document(
        db, firm_id, store, contact_html, page_kind="contact",
        fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    result = p7_tech.run(_ctx(db), store=store)
    assert result.processed == 1
    cms = _claims(db, firm_id, "cms_detected")
    assert len(cms) == 1
    assert cms[0]["value"] == "filevine"
    assert cms[0]["observed_at"] == datetime(2026, 1, 2, tzinfo=UTC)


def test_firm_with_no_documents_is_not_selected(db, tmp_path):
    store = ObjectStore(tmp_path)
    make_firm(db)
    result = p7_tech.run(_ctx(db), store=store)
    assert result.processed == 0
    assert result.skipped == 0


def test_idempotent_rerun_writes_nothing_new(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_tech_filevine.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="contact", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    first = p7_tech.run(_ctx(db), store=store)
    assert first.processed == 1
    assert len(_claims(db, firm_id, "cms_detected")) == 1

    second = p7_tech.run(_ctx(db), store=store)
    assert second.processed == 0
    assert second.skipped == 1
    assert len(_claims(db, firm_id, "cms_detected")) == 1


def test_changed_version_reparses(db, tmp_path, monkeypatch):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_tech_filevine.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="contact", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    first = p7_tech.run(_ctx(db), store=store)
    assert first.processed == 1

    monkeypatch.setattr(p7_tech, "_VERSION", "p7:v2")
    second = p7_tech.run(_ctx(db), store=store)
    assert second.processed == 1
    assert second.skipped == 0
