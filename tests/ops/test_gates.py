from __future__ import annotations

import pytest

from lge.ops import snapshot
from lge.ops.gates import g3_tier_distribution
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db


def _ctx(db):
    return RunContext(db, get_settings())


def test_g3_passes_on_all_unclassified_pre_crawl_state(db):
    make_firm(db, tier="UNCLASSIFIED")
    make_firm(db, tier="UNCLASSIFIED")
    make_firm(db, tier="UNCLASSIFIED")

    passed, report = g3_tier_distribution(_ctx(db))
    assert passed is True
    assert "UNCLASSIFIED" in report


def test_g3_passes_on_no_firms_yet(db):
    passed, report = g3_tier_distribution(_ctx(db))
    assert passed is True
    assert "no firms yet" in report


def test_g3_fails_when_every_classified_firm_is_one_tier(db):
    make_firm(db, tier="1A")
    make_firm(db, tier="1A")
    make_firm(db, tier="1A")
    make_firm(db, tier="UNCLASSIFIED")  # exempt -- must not save the check

    passed, report = g3_tier_distribution(_ctx(db))
    assert passed is False
    assert "1A" in report
    assert "FAIL" in report


def test_g3_does_not_fail_uniformity_below_the_minimum_firm_count(db):
    # Only one classified firm -- min_firms_for_uniformity_check (2) not met.
    make_firm(db, tier="1A")
    make_firm(db, tier="UNCLASSIFIED")

    passed, _report = g3_tier_distribution(_ctx(db))
    assert passed is True


def test_g3_passes_on_a_plausible_mixed_distribution_with_no_history(db):
    make_firm(db, tier="1A")
    make_firm(db, tier="1B")
    make_firm(db, tier="2")
    make_firm(db, tier="3")

    passed, report = g3_tier_distribution(_ctx(db))
    assert passed is True
    assert "PASS" in report


def test_g3_fails_on_a_greater_than_15pct_shift_vs_previous_snapshot(db):
    ctx = _ctx(db)
    # Previous snapshot: mostly tier 2 (80%), some 1A (20%).
    for _ in range(8):
        make_firm(db, tier="2")
    for _ in range(2):
        make_firm(db, tier="1A")
    snapshot.observe_snapshot(ctx, at="2026-06-01T00:00:00+00:00")

    # Since then, tier composition shifted hard toward 1A (1A: 20% -> 70%,
    # a 50pct move) -- but NOT all the way to one tier, so this exercises
    # the shift check specifically, not the uniformity check above it.
    with db.cursor() as cur:
        cur.execute(
            "UPDATE firm SET tier = '1A' WHERE id IN "
            "(SELECT id FROM firm WHERE tier = '2' LIMIT 5)"
        )

    passed, report = g3_tier_distribution(ctx)
    assert passed is False
    assert "moved more than" in report


def test_g3_passes_when_shift_is_within_band(db):
    ctx = _ctx(db)
    for _ in range(9):
        make_firm(db, tier="2")
    make_firm(db, tier="1A")
    snapshot.observe_snapshot(ctx, at="2026-06-01T00:00:00+00:00")

    # Move one firm from 2 -> 1A: 10% shift, under the 15% threshold.
    with db.cursor() as cur:
        cur.execute(
            "UPDATE firm SET tier = '1A' "
            "WHERE id = (SELECT id FROM firm WHERE tier = '2' LIMIT 1)"
        )

    passed, _report = g3_tier_distribution(ctx)
    assert passed is True
