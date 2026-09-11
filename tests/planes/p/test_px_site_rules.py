"""px_site_rules component tests: primary_practice/practice_areas (weighted by
page real estate), spanish_intake (phrase, /es/ URL, hreflang), has_inhouse_recruiter,
and entity_kind='gov' by domain suffix. Idempotent re-run and version-bump re-parse.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lge.norm import norm_practice
from lge.planes.p import px_site_rules
from lge.registry import RunContext
from lge.settings import get_settings
from lge.store.objects import ObjectStore
from tests.conftest import make_firm

pytestmark = pytest.mark.db

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "html"

_PI_TEXT = (
    "Our firm focuses on personal injury cases. We represent victims of car "
    "accidents, truck accidents, and motorcycle accidents every day. If you "
    "were hurt in a car accident, our personal injury attorneys can help. We "
    "also handle slip and fall and premises liability claims arising from car "
    "accidents."
)
_DIVORCE_ONCE_TEXT = (
    "Welcome to Smith Law, a full-service law firm serving the community for "
    "over twenty years. Our attorneys also help families through divorce and "
    "other family matters when the need arises. Contact us today to schedule "
    "a consultation with one of our experienced attorneys."
)

_JAN1 = datetime(2026, 1, 1, tzinfo=UTC)
_JAN2 = datetime(2026, 1, 2, tzinfo=UTC)


def _insert_document(conn, firm_id, *, page_kind, fetched_at, url=None, object_key=None):
    object_key = object_key or uuid.uuid4().hex
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
            (firm_id, url, object_key, object_key, page_kind, fetched_at),
        )
        return cur.fetchone()["id"]


def _insert_document_text(conn, document_id, main_text):
    word_count = len(main_text.split())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document_text (document_id, main_text, word_count, extractor) "
            "VALUES (%s, %s, %s, 'test')",
            (document_id, main_text, word_count),
        )


def _insert_page(conn, firm_id, text, *, page_kind, fetched_at, url=None):
    doc_id = _insert_document(conn, firm_id, page_kind=page_kind, fetched_at=fetched_at, url=url)
    _insert_document_text(conn, doc_id, text)
    return doc_id


def _ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def _claims(conn, firm_id, attr):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM firm_attribute WHERE firm_id = %s AND attr = %s ORDER BY observed_at",
            (firm_id, attr),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# primary_practice / practice_areas
# ---------------------------------------------------------------------------


def test_personal_injury_wins_by_page_real_estate(db):
    firm_id = make_firm(db)
    _insert_page(db, firm_id, _PI_TEXT, page_kind="practice", fetched_at=_JAN1)
    _insert_page(
        db, firm_id, _DIVORCE_ONCE_TEXT, page_kind="home", fetched_at=_JAN2
    )

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    assert result.failed == 0

    primary = _claims(db, firm_id, "primary_practice")
    assert len(primary) == 1
    assert primary[0]["value"] == "personal_injury"
    assert primary[0]["source"] == "rules:practice"
    assert primary[0]["evidence"] is not None
    assert len(primary[0]["evidence"]) <= 90  # ~80 chars of context

    # Confidence must equal norm_practice's own confidence x 0.8 exactly.
    practice_weight = float(len(_PI_TEXT.split()))
    home_weight = float(len(_DIVORCE_ONCE_TEXT.split())) * 0.5
    expected = norm_practice([(_PI_TEXT, practice_weight), (_DIVORCE_ONCE_TEXT, home_weight)])
    assert float(primary[0]["confidence"]) == pytest.approx(expected.confidence * 0.8)

    areas = _claims(db, firm_id, "practice_areas")
    assert len(areas) == 1
    assert "personal_injury" in areas[0]["value"]


def test_footer_page_kinds_never_considered(db):
    # 'other' and 'attorneys' are not in the practice/home/about set at all.
    firm_id = make_firm(db)
    _insert_page(db, firm_id, _PI_TEXT, page_kind="other", fetched_at=_JAN1)

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    assert _claims(db, firm_id, "primary_practice") == []


# ---------------------------------------------------------------------------
# spanish_intake
# ---------------------------------------------------------------------------


def test_spanish_phrase_detected(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "Hablamos Español. Llamenos hoy para una consulta gratis.",
        page_kind="contact", fetched_at=_JAN1,
    )

    result = px_site_rules.run(_ctx(db), store=store)
    assert result.processed == 1

    claims = _claims(db, firm_id, "spanish_intake")
    assert len(claims) == 1
    assert claims[0]["value"] is True
    assert claims[0]["source"] == "rules:site"
    assert "espa" in claims[0]["evidence"].lower()


def test_spanish_url_path_detected(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "Welcome to our firm.", page_kind="home",
        fetched_at=_JAN1, url="https://example.com/es/",
    )

    result = px_site_rules.run(_ctx(db), store=store)
    assert result.processed == 1
    claims = _claims(db, firm_id, "spanish_intake")
    assert len(claims) == 1
    assert claims[0]["value"] is True
    assert "/es/" in claims[0]["evidence"]


def test_spanish_hreflang_detected(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    html = (_FIXTURES / "site_es_hreflang.html").read_text(encoding="utf-8")
    key = store.put(html.encode("utf-8"))
    doc_id = _insert_document(
        db, firm_id, page_kind="contact", fetched_at=_JAN1, object_key=key
    )
    _insert_document_text(db, doc_id, "Contact us by phone or email.")

    result = px_site_rules.run(_ctx(db), store=store)
    assert result.processed == 1
    claims = _claims(db, firm_id, "spanish_intake")
    assert len(claims) == 1
    assert claims[0]["value"] is True
    assert "hreflang" in claims[0]["evidence"].lower()


def test_no_spanish_signal_writes_no_claim(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "Welcome to our English-only firm.", page_kind="home",
        fetched_at=_JAN1,
    )

    result = px_site_rules.run(_ctx(db), store=store)
    assert result.processed == 1
    assert _claims(db, firm_id, "spanish_intake") == []


# ---------------------------------------------------------------------------
# has_inhouse_recruiter
# ---------------------------------------------------------------------------


def test_inhouse_recruiter_on_team_page(db):
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "We are growing! Our Legal Recruiter is hiring paralegals this quarter.",
        page_kind="team", fetched_at=_JAN1,
    )

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    claims = _claims(db, firm_id, "has_inhouse_recruiter")
    assert len(claims) == 1
    assert claims[0]["value"] is True
    assert claims[0]["source"] == "rules:site"
    assert "recruiter" in claims[0]["evidence"].lower()


def test_no_recruiter_mention_writes_no_claim(db):
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "Meet our attorneys and paralegal staff.", page_kind="team",
        fetched_at=_JAN1,
    )

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    assert _claims(db, firm_id, "has_inhouse_recruiter") == []


def test_recruiter_mention_outside_scoped_pages_ignored(db):
    # 'practice' is not team/careers/about.
    firm_id = make_firm(db)
    _insert_page(
        db, firm_id, "Our legal recruiter helped build this practice group.",
        page_kind="practice", fetched_at=_JAN1,
    )

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    assert _claims(db, firm_id, "has_inhouse_recruiter") == []


# ---------------------------------------------------------------------------
# entity_kind = gov
# ---------------------------------------------------------------------------


def test_gov_domain_suffix(db):
    firm_id = make_firm(db, domain="publicdefender.example.gov")
    _insert_page(db, firm_id, "Welcome.", page_kind="home", fetched_at=_JAN1)

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    claims = _claims(db, firm_id, "entity_kind")
    assert len(claims) == 1
    assert claims[0]["value"] == "gov"
    assert claims[0]["source"] == "rules:site"
    assert float(claims[0]["confidence"]) == 0.95


def test_state_gov_suffix_pattern(db):
    firm_id = make_firm(db, domain="courts.state.ca.us")
    _insert_page(db, firm_id, "Welcome.", page_kind="home", fetched_at=_JAN1)

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    claims = _claims(db, firm_id, "entity_kind")
    assert claims[0]["value"] == "gov"


def test_non_gov_domain_writes_no_gov_claim(db):
    firm_id = make_firm(db, domain="smithlaw.com")
    _insert_page(db, firm_id, "Welcome.", page_kind="home", fetched_at=_JAN1)

    result = px_site_rules.run(_ctx(db))
    assert result.processed == 1
    assert _claims(db, firm_id, "entity_kind") == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_rerun_writes_nothing_new(db, tmp_path):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db, domain="publicdefender.example.gov")
    _insert_page(db, firm_id, _PI_TEXT, page_kind="practice", fetched_at=_JAN1)
    _insert_page(
        db, firm_id, "Hablamos Español. Consulta gratis.", page_kind="contact",
        fetched_at=_JAN1,
    )
    _insert_page(
        db, firm_id, "Our Legal Recruiter is hiring.", page_kind="team",
        fetched_at=_JAN1,
    )

    first = px_site_rules.run(_ctx(db), store=store)
    assert first.processed == 1
    before = {
        attr: len(_claims(db, firm_id, attr))
        for attr in ("primary_practice", "practice_areas", "spanish_intake",
                     "has_inhouse_recruiter", "entity_kind")
    }
    assert all(n == 1 for n in before.values())

    second = px_site_rules.run(_ctx(db), store=store)
    assert second.processed == 0
    assert second.skipped == 1
    after = {
        attr: len(_claims(db, firm_id, attr))
        for attr in ("primary_practice", "practice_areas", "spanish_intake",
                     "has_inhouse_recruiter", "entity_kind")
    }
    assert after == before


def test_changed_version_reparses(db, tmp_path, monkeypatch):
    store = ObjectStore(tmp_path)
    firm_id = make_firm(db)
    _insert_page(db, firm_id, _PI_TEXT, page_kind="practice", fetched_at=_JAN1)

    first = px_site_rules.run(_ctx(db), store=store)
    assert first.processed == 1

    monkeypatch.setattr(px_site_rules, "_VERSION", "px:v2")
    second = px_site_rules.run(_ctx(db), store=store)
    assert second.processed == 1
    assert second.skipped == 0
