"""ja8_pain's record carries the Google Business Profile and its reviews
(D-062): every review is one quotable line, the listing is short lines, and
the one disagreement the engine can see -- a listing whose website is not
the firm's domain -- is written out for the model to quote."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from lge.llm.pain import Pain, PainAnalysis, PainKind, ground
from lge.planes.ja import ja8_pain
from tests.conftest import make_firm
from tests.planes.p._p_helpers import ctx

pytestmark = pytest.mark.db


def _claim(conn, firm_id, attr, value, source="listing:google_places"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, evidence, "
            "observed_at) VALUES (%s, %s, %s, %s, 0.9, NULL, %s)",
            (firm_id, attr, Jsonb(value), source, datetime.now(UTC)),
        )


def _firm(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_name, city, state, domain, tier, fee_model, primary_practice, "
            "cms_detected FROM firm WHERE id = %s",
            (firm_id,),
        )
        return cur.fetchone()


def test_the_record_carries_the_listing_and_each_review_as_one_line(db):
    firm_id = make_firm(db, canonical_name="Hartley Injury Law", domain="hartleylaw.com",
                        city="Atlanta", state="GA")
    _claim(db, firm_id, "business_listing", {
        "name": "Hartley Injury Law, P.C.", "category": "Personal Injury Attorney",
        "address": "1 Peachtree St NE, Atlanta, GA 30303, USA", "phone": "(404) 555-0100",
        "website": "https://www.hartley-injury.com/", "rating": 3.6, "review_count": 41,
        "url": "https://maps.google.com/?cid=42", "status": "operational",
    })
    _claim(db, firm_id, "google_reviews", [
        {"author": "R. Diaz", "rating": 2, "date": "2026-07-10",
         "text": "Nobody called me back\nfor three weeks.", "url": None},
        {"author": None, "rating": 5, "date": None, "text": "Great team.", "url": None},
        {"author": "x", "rating": 3, "date": "2026-01-01", "text": "", "url": None},
    ])
    c = ctx(db)
    blocks = ja8_pain._record(c, _firm(db, firm_id), ja8_pain._latest_claims(c, firm_id))
    by_label = {b.label: b.text.splitlines() for b in blocks}

    assert by_label["reviews"] == [
        "Google review (2 stars, 2026-07-10, R. Diaz): Nobody called me back for three weeks.",
        "Google review (5 stars): Great team.",
    ]
    assert by_label["the business listing"] == [
        "Listed on Google as: Hartley Injury Law, P.C. (Personal Injury Attorney).",
        "Listing address: 1 Peachtree St NE, Atlanta, GA 30303, USA.",
        "Listing phone: (404) 555-0100.",
        "Listing website: https://www.hartley-injury.com/.",
        "Google rating: 3.6 from 41 reviews.",
        "The listing's website (hartley-injury.com) is not the firm's domain (hartleylaw.com).",
    ]

    # A review complaint grounds as one line of the reviews block, whichever
    # block the model named; the kinds the listing adds exist.
    analysis = PainAnalysis(
        summary="A client could not reach the firm.",
        pains=[
            Pain(kind=PainKind.review_complaint, headline="A client waited three weeks for a call",
                 quote="Google review (2 stars, 2026-07-10, R. Diaz): Nobody called me back for "
                       "three weeks.",
                 source="the business listing", why_it_matters="Intake is leaking.",
                 confidence=0.9),
            Pain(kind=PainKind.low_rating, headline="Rated 3.6",
                 quote="Google rating: 3.6 from 41 reviews.", source="the business listing",
                 why_it_matters="Prospects read it first.", confidence=0.8),
            Pain(kind=PainKind.other, headline="invented", quote="Nobody ever answers the phone.",
                 source="reviews", why_it_matters="x", confidence=0.9),
        ],
        nothing_found=False,
    )
    grounded, dropped = ground(analysis, blocks)
    kept = grounded.pains
    assert [p.kind for p in kept] == [PainKind.review_complaint, PainKind.low_rating]
    assert kept[0].source == "reviews"
    assert dropped == [["other", "the record never says it"]]


def test_a_firm_without_a_listing_has_no_listing_lines_and_a_matching_site_is_no_disagreement(db):
    firm_id = make_firm(db, canonical_name="Doe Law", domain="doelaw.com")
    c = ctx(db)
    blocks = ja8_pain._record(c, _firm(db, firm_id), ja8_pain._latest_claims(c, firm_id))
    assert "the business listing" not in {b.label for b in blocks}
    _claim(db, firm_id, "business_listing", {"name": "Doe Law", "website": "http://www.doelaw.com"})
    blocks = ja8_pain._record(c, _firm(db, firm_id), ja8_pain._latest_claims(c, firm_id))
    lines = {b.label: b.text for b in blocks}["the business listing"].splitlines()
    assert lines == ["Listed on Google as: Doe Law.", "Listing website: http://www.doelaw.com."]
