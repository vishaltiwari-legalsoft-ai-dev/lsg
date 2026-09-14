"""ja7_pain_signals: site gaps, unreachable-firm review snippets and growth
headlines become signals the intent score reads; a filled gap closes its
signal; a re-run over unchanged claims writes nothing."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from lge.planes.ja import ja7_pain
from tests.conftest import make_firm
from tests.planes.ja._ja6_helpers import ctx
from tests.planes.r.test_r_site_contacts import _write_claim

pytestmark = pytest.mark.db

_SEEN = datetime(2026, 9, 10, tzinfo=UTC)


def _signals(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, kind, first_seen, last_seen, closed_at, evidence, "
            "signal_weight(kind, first_seen, closed_at, repost_count, now()) AS weight, "
            "contest_level(kind) AS contest FROM signal WHERE firm_id = %s ORDER BY kind, id",
            (firm_id,),
        )
        return cur.fetchall()


def _sightings(conn, firm_id) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM signal_sighting ss JOIN signal s ON s.id = ss.signal_id "
            "WHERE s.firm_id = %s",
            (firm_id,),
        )
        return cur.fetchone()["n"]


def _gaps(*names: str) -> list[dict]:
    return [{"gap": n, "evidence": f"judged: {n}"} for n in names]


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Great at first, then they never called me back. Avoid.", "never called me back"),
        ("No communication for three months.", "no communication"),
        ("It took months to get a response from the paralegal.", "took months"),
        ("Very hard to reach anyone at the office.", "hard to reach"),
        ("They never failed to call me back the same day.", None),
        ("Always returned my calls within the hour. Wonderful firm.", None),
        ("No communication issues at all, very responsive.", None),
    ],
)
def test_pain_sentence(text, expected):
    found = ja7_pain.pain_sentence(text)
    assert (found[1] if found else None) == expected


def test_gap_kinds_need_both_intake_gaps_and_either_stale_gap():
    present = ja7_pain.gap_kinds_present(_gaps("no_online_intake"))
    assert present == {}
    present = ja7_pain.gap_kinds_present(
        _gaps("no_online_intake", "no_live_chat", "stale_news", "no_support_staff_listed")
    )
    assert set(present) == {"no_intake_channel", "stale_site", "no_support_staff_listed"}
    assert [g["gap"] for g in present["no_intake_channel"]] == [
        "no_online_intake", "no_live_chat"
    ]


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


def test_gaps_reviews_and_growth_become_weighted_signals(db):
    firm_id = make_firm(db, canonical_name="Hartley Injury Law")
    _write_claim(
        db, firm_id, "site_gaps",
        _gaps("no_online_intake", "no_live_chat", "no_support_staff_listed", "stale_copyright"),
        "site:page", 0.8, _SEEN,
    )
    _write_claim(
        db, firm_id, "search_review_snippets",
        [
            {"url": "https://www.avvo.com/x", "title": "Hartley Injury Law reviews",
             "body": "Nice people but they never called me back after the consult."},
            {"url": "https://www.yelp.com/y", "title": "Hartley Injury Law - Yelp",
             "body": "Always returned my calls. Five stars."},
            {"url": "https://www.other.com/z", "title": "Smith & Jones reviews",
             "body": "They never called me back."},  # not this firm
        ],
        "search:ddg", 0.6, _SEEN,
    )
    recent = (date.today() - timedelta(days=30)).isoformat()
    old = (date.today() - timedelta(days=400)).isoformat()
    _write_claim(
        db, firm_id, "growth_news",
        [
            {"title": "Hartley Injury Law Opens New Marietta Office", "date": recent,
             "url": "https://hartleylaw.com/blog/new-office/", "cue": "opens new marietta office"},
            {"title": "Luis Ortega Joins the Firm", "date": old,
             "url": "https://hartleylaw.com/2025/luis/", "cue": "joins"},
        ],
        "site:page", 0.8, _SEEN,
    )

    result = ja7_pain.run(ctx(db))
    assert result.processed == 1 and result.failed == 0, result.notes

    by_kind: dict[str, list[dict]] = {}
    for s in _signals(db, firm_id):
        by_kind.setdefault(s["kind"], []).append(s)
    assert set(by_kind) == {
        "no_intake_channel", "no_support_staff_listed", "stale_site",
        "review_unreturned_call", "new_office_or_lateral",
    }
    assert by_kind["no_intake_channel"][0]["weight"] == 6
    assert by_kind["no_intake_channel"][0]["contest"] == "NONE"
    assert by_kind["no_support_staff_listed"][0]["weight"] == 8
    assert by_kind["stale_site"][0]["first_seen"] == _SEEN

    review = by_kind["review_unreturned_call"]
    assert len(review) == 1  # praise and the other firm's complaint are not signals
    assert review[0]["evidence"]["quote"].startswith("Nice people but they never called")
    assert review[0]["evidence"]["url"] == "https://www.avvo.com/x"
    assert review[0]["weight"] == 15

    growth = by_kind["new_office_or_lateral"]
    assert len(growth) == 1  # the 400-day-old post is not news
    assert growth[0]["first_seen"].date().isoformat() == recent
    assert growth[0]["evidence"]["headline"].startswith("Hartley Injury Law Opens")

    assert _sightings(db, firm_id) == 5
    with db.cursor() as cur:
        cur.execute("SELECT intent_score(%s) AS s", (firm_id,))
        assert cur.fetchone()["s"] > 0


def test_a_filled_gap_closes_its_signal_and_a_closed_signal_weighs_nothing(db):
    firm_id = make_firm(db)
    _write_claim(db, firm_id, "site_gaps", _gaps("no_online_intake", "no_live_chat"),
                 "site:page", 0.8, _SEEN)
    ja7_pain.run(ctx(db))
    assert [s["kind"] for s in _signals(db, firm_id)] == ["no_intake_channel"]

    later = _SEEN + timedelta(days=30)
    _write_claim(db, firm_id, "site_gaps", _gaps("no_live_chat"), "site:page", 0.8, later)
    result = ja7_pain.run(ctx(db))
    assert result.processed == 1
    assert "closed 1" in " ".join(result.notes)
    signal = _signals(db, firm_id)[0]
    assert signal["closed_at"] is not None
    assert signal["weight"] == 0


def test_rerun_over_unchanged_claims_writes_nothing(db):
    firm_id = make_firm(db)
    _write_claim(db, firm_id, "site_gaps", _gaps("stale_news"), "site:page", 0.8, _SEEN)
    first = ja7_pain.run(ctx(db))
    assert first.processed == 1
    second = ja7_pain.run(ctx(db))
    assert second.processed == 0 and second.skipped == 1
    assert _sightings(db, firm_id) == 1


def test_no_claims_is_skipped(db):
    firm_id = make_firm(db)
    result = ja7_pain.run(ctx(db), firm_ids_file=None)
    assert result.processed == 0
    assert _signals(db, firm_id) == []
