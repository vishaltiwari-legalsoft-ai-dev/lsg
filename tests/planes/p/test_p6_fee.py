"""P6 fee-model component tests: page selection/weighting, `unknown` as a
first-class claim, idempotent re-run, and version-bump re-parse.

`lge.classify.fee.detect_fee_model` itself is exercised directly in
tests/classify/test_fee.py -- these tests are about the component wiring: which
pages get read, how observed_at/source/confidence land in firm_attribute, and
that a re-run over unchanged documents is free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from lge.planes.p import p6_fee
from lge.registry import RunContext
from lge.settings import get_settings
from lge.store.objects import ObjectStore
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _insert_document(conn, firm_id, *, page_kind, fetched_at, url=None, object_key=None):
    content_hash = uuid.uuid4().hex
    url = url or f"https://example.com/{page_kind}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document
                (firm_id, url, status_code, content_hash, object_key, bytes,
                 fetch_ok, page_kind, fetched_at)
            VALUES (%s, %s, 200, %s, %s, 0, true, %s, %s)
            RETURNING id
            """,
            (firm_id, url, content_hash, object_key or content_hash, page_kind, fetched_at),
        )
        return cur.fetchone()["id"]


def _insert_document_text(conn, document_id, main_text, *, word_count=None):
    if word_count is None:
        word_count = len(main_text.split())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document_text (document_id, main_text, word_count, extractor) "
            "VALUES (%s, %s, %s, 'test')",
            (document_id, main_text, word_count),
        )


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _claims(conn, firm_id, attr):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM firm_attribute WHERE firm_id = %s AND attr = %s ORDER BY observed_at",
            (firm_id, attr),
        )
        return cur.fetchall()


def test_contingency_evidence_written(db):
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="fees", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(
        db, doc_id, "We work on a contingency basis. No fee unless we win your case."
    )

    result = p6_fee.run(_ctx(db))
    assert result.processed == 1
    assert result.failed == 0

    claims = _claims(db, firm_id, "fee_model")
    assert len(claims) == 1
    assert claims[0]["value"] == "contingency"
    assert claims[0]["source"] == "regex:p6"
    # 0.9 for one matching sentence, 0.95 for two or more distinct ones; the probe-
    # measured patterns (D-020) can match a second sentence in this fixture.
    assert float(claims[0]["confidence"]) in (0.9, 0.95)
    # the exact sentence, whichever firm-voice promise comes first on the page
    ev = claims[0]["evidence"].lower()
    assert "no fee unless we win" in ev or "contingency basis" in ev
    assert claims[0]["observed_at"] == datetime(2026, 1, 1, tzinfo=UTC)


_CHROME_HTML = (
    b"<html><head><title>Smith Injury Law | Atlanta</title>"
    b'<meta name="description" content="Serious injury lawyers."></head>'
    b"<body><nav><a href='/'>Home</a><a href='/about'>About</a>"
    b"<span>No fees unless we win!</span></nav>"
    b"<main><p>We handle serious injury cases across Georgia.</p></main>"
    b"<footer>Contingency-Based Legal Representation</footer>"
    b"<script>var fee = 'hourly rate';</script></body></html>"
)


def test_page_text_is_one_line_per_block_and_drops_scripts():
    lines = p6_fee.page_text(_CHROME_HTML.decode()).split("\n")
    # the nav is one block: its inline links and the promise share a line, spaced
    assert "Home About No fees unless we win!" in lines
    assert "Contingency-Based Legal Representation" in lines
    assert "Serious injury lawyers." in lines  # the meta description
    assert not any("hourly" in line for line in lines)  # script text is invisible
    assert p6_fee.page_text("") == ""


def test_fee_promise_in_site_chrome_is_read(db, tmp_path):
    # The probe's real shape: the promise sits in the nav/footer, which P4's main
    # text drops as boilerplate. v2 reads the stored HTML itself (D-026).
    store = ObjectStore(tmp_path)
    key = store.put(_CHROME_HTML)
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        object_key=key,
    )
    _insert_document_text(db, doc_id, "We handle serious injury cases across Georgia.")

    result = p6_fee.run(_ctx(db), store=store)
    assert result.processed == 1
    assert result.failed == 0

    claims = _claims(db, firm_id, "fee_model")
    assert claims[0]["value"] == "contingency"
    assert "no fees unless we win" in claims[0]["evidence"].lower()


def test_unknown_fee_is_still_written(db):
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="about", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(db, doc_id, "We are a great law firm with excellent service.")

    result = p6_fee.run(_ctx(db))
    assert result.processed == 1

    claims = _claims(db, firm_id, "fee_model")
    assert len(claims) == 1
    assert claims[0]["value"] == "unknown"
    assert float(claims[0]["confidence"]) == 0.0
    assert claims[0]["evidence"] is None


def test_contingency_wins_by_page_real_estate(db):
    firm_id = make_firm(db)
    practice_id = _insert_document(
        db, firm_id, page_kind="practice", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(
        db, practice_id, "No fee unless we win your personal injury case.", word_count=8
    )
    about_id = _insert_document(
        db, firm_id, page_kind="about", fetched_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    _insert_document_text(
        db, about_id, "Our business law clients are billed at an hourly rate.", word_count=2
    )

    result = p6_fee.run(_ctx(db))
    assert result.processed == 1

    claims = _claims(db, firm_id, "fee_model")
    assert len(claims) == 1
    assert claims[0]["value"] == "contingency"
    assert float(claims[0]["confidence"]) == 0.6
    # observed_at is the newest of the documents the claim was built from.
    assert claims[0]["observed_at"] == datetime(2026, 1, 2, tzinfo=UTC)


def test_page_kinds_outside_scope_are_ignored(db):
    # careers stays out of scope: job ads use "fee" in other senses
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="careers", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(db, doc_id, "No fee unless we win.")

    result = p6_fee.run(_ctx(db))
    assert result.skipped == 1
    assert result.processed == 0
    assert _claims(db, firm_id, "fee_model") == []


def test_contact_page_fee_promise_is_read(db):
    # found in the live probe: "No fee unless we win" often sits on the contact page
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="contact", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(db, doc_id, "Call today. No fee unless we win your case.")

    p6_fee.run(_ctx(db))
    claims = _claims(db, firm_id, "fee_model")
    assert claims and claims[0]["value"] == "contingency"


def test_firm_with_no_documents_is_skipped(db):
    firm_id = make_firm(db)
    result = p6_fee.run(_ctx(db))
    assert result.processed == 0
    assert result.skipped == 0  # nothing to select at all -- not even attempted
    assert _claims(db, firm_id, "fee_model") == []


def test_idempotent_rerun_writes_nothing_new(db):
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="fees", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(db, doc_id, "No fee unless we win.")

    first = p6_fee.run(_ctx(db))
    assert first.processed == 1
    assert len(_claims(db, firm_id, "fee_model")) == 1

    second = p6_fee.run(_ctx(db))
    assert second.processed == 0
    assert second.skipped == 1
    assert len(_claims(db, firm_id, "fee_model")) == 1


def test_changed_version_reparses(db, monkeypatch):
    firm_id = make_firm(db)
    doc_id = _insert_document(
        db, firm_id, page_kind="fees", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _insert_document_text(db, doc_id, "No fee unless we win.")

    first = p6_fee.run(_ctx(db))
    assert first.processed == 1

    # Same stored document, no crawl -- only the classifier/config version moves.
    monkeypatch.setattr(p6_fee, "_VERSION", "p6:v99")
    second = p6_fee.run(_ctx(db))
    assert second.processed == 1
    assert second.skipped == 0
