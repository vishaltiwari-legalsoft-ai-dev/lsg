"""icp_tier, decay, signal_weight, fit_score, routing_band, arming_threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import make_firm

pytestmark = pytest.mark.db

AT = datetime(2026, 1, 1, tzinfo=UTC)


def tier_of(db, **cols):
    cols.setdefault("entity_kind", "private_firm")
    cols.setdefault("country", "US")
    cols.setdefault("attorney_count", 5)
    cols.setdefault("has_inhouse_recruiter", False)
    cols.setdefault("first_seen_bar_admission", AT - timedelta(days=3650))
    cols.setdefault("paid_ads_active", True)
    firm_id = make_firm(db, **cols)
    with db.cursor() as cur:
        cur.execute("SELECT icp_tier(f, %s) AS tier FROM firm f WHERE id = %s", (AT, firm_id))
        return cur.fetchone()["tier"]


# =============================================================================
# icp_tier -- one case per branch, in evaluation order
# =============================================================================


def test_dq_ordering_entity_checked_before_size(db):
    # 60 attorneys AND not a private firm -- DQ_ENTITY must win, proving
    # disqualifiers are checked in the order they're written.
    assert tier_of(db, entity_kind="gov", attorney_count=60) == "DQ_ENTITY"


def test_dq_geo(db):
    assert tier_of(db, country="CA") == "DQ_GEO"


def test_dq_size(db):
    assert tier_of(db, attorney_count=51) == "DQ_SIZE"


def test_26_to_50_attorneys_not_disqualified(db):
    assert tier_of(db, attorney_count=40, fee_model="hourly") == "4_NONBILLABLE"


def test_dq_selfserve(db):
    assert tier_of(db, has_inhouse_recruiter=True) == "DQ_SELFSERVE"


def test_dq_novolume_appellate(db):
    assert tier_of(db, primary_practice="appellate") == "DQ_NOVOLUME"


def test_dq_nobudget_solo_recent_no_ads(db):
    t = tier_of(
        db,
        attorney_count=1,
        first_seen_bar_admission=AT - timedelta(days=180),
        paid_ads_active=False,
    )
    assert t == "DQ_NOBUDGET"


def test_solo_with_ads_is_not_nobudget(db):
    t = tier_of(
        db,
        attorney_count=1,
        first_seen_bar_admission=AT - timedelta(days=180),
        paid_ads_active=True,
        fee_model="flat",
        primary_practice="family",
    )
    assert t == "3"


def test_1a_contingency_personal_injury(db):
    assert tier_of(db, fee_model="contingency", primary_practice="personal_injury") == "1A"


def test_1a_fee_shifting_mass_tort(db):
    assert tier_of(db, fee_model="fee_shifting", primary_practice="mass_tort") == "1A"


def test_1b_flat_immigration(db):
    assert tier_of(db, fee_model="flat", primary_practice="immigration") == "1B"


def test_2_contingency_employment(db):
    assert tier_of(db, fee_model="contingency", primary_practice="employment") == "2"


def test_3_flat_family(db):
    assert tier_of(db, fee_model="flat", primary_practice="family") == "3"


def test_4_nonbillable_hourly_any_practice(db):
    assert tier_of(db, fee_model="hourly", primary_practice="business") == "4_NONBILLABLE"


def test_unclassified_mixed_or_unknown_fee(db):
    assert tier_of(db, fee_model="mixed", primary_practice="personal_injury") == "UNCLASSIFIED"
    assert tier_of(db, fee_model="unknown", primary_practice="personal_injury") == "UNCLASSIFIED"


def test_unclassified_null_practice_with_contingency(db):
    assert tier_of(db, fee_model="contingency", primary_practice=None) == "UNCLASSIFIED"


# =============================================================================
# decay -- boundaries at 7 / 30 / 90 days
# =============================================================================


def test_decay_boundaries(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT decay(7) AS d7, decay(7.01) AS d7_1, decay(30) AS d30, "
            "decay(30.01) AS d30_1, decay(90) AS d90, decay(90.01) AS d90_1"
        )
        row = cur.fetchone()
    assert float(row["d7"]) == pytest.approx(1.00)
    assert float(row["d7_1"]) == pytest.approx(0.70)
    assert float(row["d30"]) == pytest.approx(0.70)
    assert float(row["d30_1"]) == pytest.approx(0.35)
    assert float(row["d90"]) == pytest.approx(0.35)
    assert float(row["d90_1"]) == 0


# =============================================================================
# signal_weight -- boundaries at 7/21 days; closed -> 0; repost 44/48
# =============================================================================


def test_signal_weight_job_posting_boundaries(db):
    params = {
        "at": AT,
        "d7": AT - timedelta(days=7),
        "d8": AT - timedelta(days=8),
        "d21": AT - timedelta(days=21),
        "d22": AT - timedelta(days=22),
        "recent": AT - timedelta(days=1),
    }
    with db.cursor() as cur:
        cur.execute(
            "SELECT "
            "signal_weight('job_posting_open', %(d7)s, NULL, 0, %(at)s) AS d7, "
            "signal_weight('job_posting_open', %(d8)s, NULL, 0, %(at)s) AS d8, "
            "signal_weight('job_posting_open', %(d21)s, NULL, 0, %(at)s) AS d21, "
            "signal_weight('job_posting_open', %(d22)s, NULL, 0, %(at)s) AS d22, "
            "signal_weight('job_posting_open', %(recent)s, %(at)s, 0, %(at)s) AS closed, "
            "signal_weight('job_posting_open', %(recent)s, NULL, 1, %(at)s) AS repost1, "
            "signal_weight('job_posting_open', %(recent)s, NULL, 2, %(at)s) AS repost2",
            params,
        )
        row = cur.fetchone()
    assert row["d7"] == 30
    assert row["d8"] == 34
    assert row["d21"] == 34
    assert row["d22"] == 40
    assert row["closed"] == 0
    assert row["repost1"] == 44
    assert row["repost2"] == 48


def test_signal_weight_other_kinds(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT signal_weight('partner_intro', now(), NULL, 0, now()) AS a, "
            "signal_weight('made_up_kind', now(), NULL, 0, now()) AS b"
        )
        row = cur.fetchone()
    assert row["a"] == 35
    assert row["b"] == 0


# =============================================================================
# fit_score -- clamp to 0..50, including the 26-50 attorney penalty band
# =============================================================================


def test_fit_score_negative_band_clamps_to_zero(db):
    firm_id = make_firm(db, attorney_count=30, country="CA")
    with db.cursor() as cur:
        cur.execute("SELECT fit_score(f) AS s FROM firm f WHERE id = %s", (firm_id,))
        assert cur.fetchone()["s"] == 0


def test_fit_score_clamps_to_fifty(db):
    firm_id = make_firm(
        db,
        attorney_count=5,
        country="US",
        fee_model="contingency",
        tier="1A",
        review_count=100,
        staff_ratio=0.5,
        paid_ads_active=True,
        spanish_intake=True,
        has_hired_support_roles=True,
        repeat_role_count=3,
    )
    with db.cursor() as cur:
        cur.execute("SELECT fit_score(f) AS s FROM firm f WHERE id = %s", (firm_id,))
        assert cur.fetchone()["s"] == 50


def test_fit_score_nulls_contribute_nothing(db):
    # make_firm() defaults attorney_count/country -- override both back to
    # NULL so every fit_score term is actually unset.
    firm_id = make_firm(db, attorney_count=None, country=None)
    with db.cursor() as cur:
        cur.execute("SELECT fit_score(f) AS s FROM firm f WHERE id = %s", (firm_id,))
        assert cur.fetchone()["s"] == 0


# =============================================================================
# routing_band -- STRIKE only when contest <= MED
# =============================================================================


def test_routing_band_strike_requires_contest_not_high(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT routing_band(50, 40, 'MED') AS strike, "
            "routing_band(50, 40, 'HIGH') AS sequence_not_strike"
        )
        row = cur.fetchone()
    assert row["strike"] == "STRIKE"
    assert row["sequence_not_strike"] == "SEQUENCE"


def test_routing_band_thresholds(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT routing_band(40, 25, 'HIGH') AS sequence60, "
            "routing_band(25, 20, 'HIGH') AS nurture, "
            "routing_band(5, 5, 'HIGH') AS hold"
        )
        row = cur.fetchone()
    assert row["sequence60"] == "SEQUENCE"
    assert row["nurture"] == "NURTURE"
    assert row["hold"] == "HOLD"


# =============================================================================
# arming_threshold -- deep bench lowers the bar, starvation blocks entirely
# =============================================================================


def test_arming_threshold_deep_bench_lowers_bar(db):
    with db.cursor() as cur:
        cur.execute("SELECT arming_threshold(10, 5) AS t")
        assert cur.fetchone()["t"] == pytest.approx(60 - 15)


def test_arming_threshold_starvation_blocks(db):
    with db.cursor() as cur:
        cur.execute("SELECT arming_threshold(0, 0) AS t")
        assert cur.fetchone()["t"] > 900
