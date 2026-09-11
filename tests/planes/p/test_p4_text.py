"""P4 boilerplate stripper: trafilatura main-text extraction into
document_text. The footer test is the accuracy-critical one -- a footer
listing every practice area the firm ever mentioned must not reach
document_text.main_text, or it corrupts primary_practice downstream."""

from __future__ import annotations

from pathlib import Path

import pytest

from lge.planes.p import p4_text
from lge.store.objects import ObjectStore
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx, insert_document, make_lead

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"


def get_text_row(conn, document_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM document_text WHERE document_id = %s", (document_id,))
        return cur.fetchone()


def test_no_firms_selected_is_a_clean_no_op(db):
    result = p4_text.run(ctx(db), limit=10)
    assert result.processed == 0
    assert "no firms selected" in " ".join(result.notes)


def test_extractor_string_matches_installed_trafilatura_version():
    import trafilatura

    assert p4_text.EXTRACTOR == f"trafilatura:{trafilatura.__version__}"


def test_footer_practice_area_list_is_absent_from_main_text(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    html = (_FIXTURES / "car_accident_page.html").read_text(encoding="utf-8")
    doc_id = insert_document(
        db, store, firm_id, html, url="https://example.com/", page_kind="home"
    )

    result = p4_text.run(ctx(db), limit=10, store=store)
    assert result.processed == 1

    row = get_text_row(db, doc_id)
    assert row is not None
    main_text = row["main_text"]
    assert "car accident" in main_text.lower()  # the real body survives
    # None of the twelve footer practice-area labels leaked through.
    for label in [
        "Truck Accidents",
        "Motorcycle Accidents",
        "Workers Compensation",
        "Medical Malpractice",
        "Product Liability",
        "Immigration Law",
        "Family Law",
        "Bankruptcy",
    ]:
        assert label not in main_text
    assert row["extractor"] == p4_text.EXTRACTOR
    assert row["word_count"] == len(main_text.split())


def test_extraction_is_re_runnable_on_extractor_version_bump(db, tmp_path, monkeypatch):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    html = "<html><body><article><p>" + ("Hello world. " * 20) + "</p></article></body></html>"
    doc_id = insert_document(
        db, store, firm_id, html, url="https://example.com/", page_kind="home"
    )

    r1 = p4_text.run(ctx(db), limit=10, store=store)
    assert r1.processed == 1
    first_extractor = get_text_row(db, doc_id)["extractor"]

    # unchanged extractor version -> second run is a no-op. The SQL
    # eligibility filter (dt.extractor <> current) already excludes this
    # document before ctx.once is even consulted, so it's "nothing pending"
    # rather than a per-firm skip.
    r2 = p4_text.run(ctx(db), limit=10, store=store)
    assert r2.processed == 0
    assert "no documents pending extraction" in " ".join(r2.notes)

    # bump the extractor version -> re-parses from the SAME stored HTML,
    # no re-fetch needed
    monkeypatch.setattr(p4_text, "EXTRACTOR", "trafilatura:99.0-test")
    r3 = p4_text.run(ctx(db), limit=10, store=store)
    assert r3.processed == 1
    assert get_text_row(db, doc_id)["extractor"] == "trafilatura:99.0-test"
    assert first_extractor != "trafilatura:99.0-test"


def test_404_and_failed_fetches_are_excluded(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    insert_document(
        db, store, firm_id, "<html><body>gone</body></html>",
        url="https://example.com/missing", page_kind="fees", status_code=404,
    )
    insert_document(
        db, store, firm_id, "<html><body>fail</body></html>",
        url="https://example.com/broken", page_kind="about", fetch_ok=False,
    )

    result = p4_text.run(ctx(db), limit=10, store=store)
    assert result.processed == 0  # nothing eligible
    assert "no documents pending extraction" in " ".join(result.notes)


def test_missing_object_in_store_is_logged_and_skipped_not_raised(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="example.com")
    make_lead(db, firm_id)
    doc_id = insert_document(
        db, store, firm_id, "<html><body>x</body></html>",
        url="https://example.com/", page_kind="home",
    )
    # Corrupt the row to point at an object that was never stored.
    with db.cursor() as cur:
        cur.execute(
            "UPDATE document SET object_key = %s WHERE id = %s", ("deadbeef" * 8, doc_id)
        )

    result = p4_text.run(ctx(db), limit=10, store=store)
    assert result.processed == 1  # firm-level ctx.once still marks 'ok'
    assert get_text_row(db, doc_id) is None  # nothing written for the missing object
