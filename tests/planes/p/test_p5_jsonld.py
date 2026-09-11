"""P5 JSON-LD/microdata component tests: schema.org extraction into
firm_attribute claims under source `site:jsonld`, confidence 0.95 (0.8 for
entity_kind). Covers @graph flattening, microdata, JobPosting exclusion, the
`jsonld_people` informational list, and that `attorney_count` is never written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lge.norm import norm_addr, norm_phone
from lge.planes.p import p5_jsonld
from lge.registry import RunContext
from lge.settings import get_settings
from lge.store.objects import ObjectStore
from tests.conftest import make_firm

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"


def _insert_document(
    conn, firm_id, store, html, *, page_kind, fetched_at, status_code=200, url=None
):
    key = store.put(html.encode("utf-8"))
    url = url or f"https://example.com/{page_kind}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document
                (firm_id, url, status_code, content_hash, object_key, bytes,
                 fetch_ok, page_kind, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)
            RETURNING id
            """,
            (firm_id, url, status_code, key, key, len(html.encode("utf-8")), page_kind, fetched_at),
        )
        return cur.fetchone()["id"]


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _claims(conn, firm_id, attr=None):
    with conn.cursor() as cur:
        if attr is None:
            cur.execute(
                "SELECT * FROM firm_attribute WHERE firm_id = %s ORDER BY attr, observed_at",
                (firm_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM firm_attribute WHERE firm_id = %s AND attr = %s "
                "ORDER BY observed_at",
                (firm_id, attr),
            )
        return cur.fetchall()


def test_legalservice_graph_full_extraction(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_jsonld_legalservice.html").read_text(encoding="utf-8")
    fetched_at = datetime(2026, 1, 1, tzinfo=UTC)
    _insert_document(db, firm_id, store, html, page_kind="home", fetched_at=fetched_at)

    result = p5_jsonld.run(_ctx(db), store=store)
    assert result.processed == 1
    assert result.failed == 0

    name = _claims(db, firm_id, "canonical_name")
    assert len(name) == 1
    assert name[0]["value"] == "Acme Law Group"
    assert name[0]["source"] == "site:jsonld"
    assert float(name[0]["confidence"]) == 0.95

    phone = _claims(db, firm_id, "phone_e164")
    assert len(phone) == 1
    assert phone[0]["value"] == norm_phone("(212) 555-1212")

    addr = _claims(db, firm_id, "address")
    assert len(addr) == 1
    expected = norm_addr("123 Main Street Suite 400", "New York", "NY", "10001")
    assert addr[0]["value"] == {
        "street_norm": expected.street_norm,
        "unit": expected.unit,
        "city": expected.city,
        "state": expected.state,
        "zip5": expected.zip5,
        "addr_hash": expected.addr_hash,
    }

    country = _claims(db, firm_id, "country")
    assert len(country) == 1
    assert country[0]["value"] == "US"

    entity_kind = _claims(db, firm_id, "entity_kind")
    assert len(entity_kind) == 1
    assert entity_kind[0]["value"] == "private_firm"
    assert float(entity_kind[0]["confidence"]) == 0.8

    languages = _claims(db, firm_id, "languages")
    assert len(languages) == 1
    assert set(languages[0]["value"]) == {"en", "es"}

    spanish = _claims(db, firm_id, "spanish_intake")
    assert len(spanish) == 1
    assert spanish[0]["value"] is True

    people = _claims(db, firm_id, "jsonld_people")
    assert len(people) == 1
    assert {(p["name"], p["title"]) for p in people[0]["value"]} == {
        ("Jane Doe", "Managing Partner"),
        ("Bob Roe", "Associate Attorney"),
    }

    # Never, under any circumstances -- the team page (read by the LLM) is the
    # only permitted source of attorney_count.
    assert _claims(db, firm_id, "attorney_count") == []

    # The JobPosting node's own claims (a JobPosting "name" et al) never leak in.
    all_values = {row["attr"]: row["value"] for row in _claims(db, firm_id)}
    assert "Should Not Be Read By P5" not in str(all_values)


def test_microdata_extraction(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_jsonld_microdata.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    result = p5_jsonld.run(_ctx(db), store=store)
    assert result.processed == 1

    name = _claims(db, firm_id, "canonical_name")
    assert name[0]["value"] == "Micro Law Firm"

    phone = _claims(db, firm_id, "phone_e164")
    assert phone[0]["value"] == norm_phone("212-555-9999")

    country = _claims(db, firm_id, "country")
    assert country[0]["value"] == "US"


def test_no_structured_data_writes_no_claims_but_still_processes(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_minimal.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    result = p5_jsonld.run(_ctx(db), store=store)
    assert result.processed == 1
    assert _claims(db, firm_id) == []


def test_non_200_pages_are_not_read(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_jsonld_legalservice.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="home",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC), status_code=404,
    )

    result = p5_jsonld.run(_ctx(db), store=store)
    assert result.processed == 0
    assert result.skipped == 1
    assert _claims(db, firm_id) == []


def test_idempotent_rerun_writes_nothing_new(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_jsonld_legalservice.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    first = p5_jsonld.run(_ctx(db), store=store)
    assert first.processed == 1
    before = len(_claims(db, firm_id))
    assert before > 0

    second = p5_jsonld.run(_ctx(db), store=store)
    assert second.processed == 0
    assert second.skipped == 1
    assert len(_claims(db, firm_id)) == before


def test_changed_version_reparses(db, tmp_path, monkeypatch):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_jsonld_legalservice.html").read_text(encoding="utf-8")
    _insert_document(
        db, firm_id, store, html, page_kind="home", fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    first = p5_jsonld.run(_ctx(db), store=store)
    assert first.processed == 1

    monkeypatch.setattr(p5_jsonld, "_VERSION", "p5:v2")
    second = p5_jsonld.run(_ctx(db), store=store)
    assert second.processed == 1
    assert second.skipped == 0
