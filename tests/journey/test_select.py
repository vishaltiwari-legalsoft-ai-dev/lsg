"""Variant selection (journey/sequences.yml's pain_map / touch3_variants)
and the banned-phrase scanner."""

from __future__ import annotations

from datetime import UTC, datetime

from lge.journey.model import Signal
from lge.journey.select import scan_banned, select_touch1_variant, select_touch3_variant

_NOW = datetime(2026, 9, 11, tzinfo=UTC)


def _signal(kind: str, repost_count: int = 0) -> Signal:
    return Signal(
        id=1,
        kind=kind,
        first_seen=_NOW,
        last_seen=_NOW,
        closed_at=None,
        repost_count=repost_count,
        evidence={"title": "x"},
    )


class TestSelectTouch1Variant:
    def test_job_posting_open_no_repost_is_1a(self):
        assert select_touch1_variant(_signal("job_posting_open")) == "1A"

    def test_job_posting_open_with_repost_is_1b(self):
        assert select_touch1_variant(_signal("job_posting_open", repost_count=1)) == "1B"
        assert select_touch1_variant(_signal("job_posting_open", repost_count=2)) == "1B"

    def test_multi_opening_is_1c(self):
        assert select_touch1_variant(_signal("multi_opening")) == "1C"

    def test_mass_tort_campaign_is_1d(self):
        assert select_touch1_variant(_signal("mass_tort_campaign")) == "1D"

    def test_review_unreturned_call_is_1e(self):
        assert select_touch1_variant(_signal("review_unreturned_call")) == "1E"

    def test_cms_implemented_is_1f(self):
        assert select_touch1_variant(_signal("cms_implemented")) == "1F"

    def test_no_signal_is_none(self):
        assert select_touch1_variant(None) is None

    def test_unmapped_kind_is_none(self):
        assert select_touch1_variant(_signal("partner_intro")) is None
        assert select_touch1_variant(_signal("paid_ads_spike")) is None


class TestSelectTouch3Variant:
    def test_contingency(self):
        assert select_touch3_variant("contingency", "1A") == "contingency"

    def test_fee_shifting(self):
        assert select_touch3_variant("fee_shifting", "2") == "fee_shifting"

    def test_flat_default_is_1b_text(self):
        assert select_touch3_variant("flat", "1B") == "flat_1b"

    def test_flat_tier3_override(self):
        assert select_touch3_variant("flat", "3") == "flat_tier3"

    def test_hourly(self):
        assert select_touch3_variant("hourly", "4_NONBILLABLE") == "hourly"

    def test_mixed_unknown_none_all_unresolved(self):
        assert select_touch3_variant("mixed", "1A") is None
        assert select_touch3_variant("unknown", "1A") is None
        assert select_touch3_variant(None, "1A") is None

    def test_fee_model_wins_over_tier(self):
        # "Touch 3's variant always equals firm.fee_model" -- a tier-2 firm
        # that is actually billing contingency still gets the contingency
        # copy, not a tier-based lookup.
        assert select_touch3_variant("contingency", "2") == "contingency"


class TestScanBanned:
    def test_finds_banned_phrase(self):
        assert scan_banned("we can replace your paralegal") != []
        assert scan_banned("cheaper than hiring locally") != []
        assert scan_banned("this will cut costs immediately") != []
        assert scan_banned("reduce headcount this quarter") != []
        assert scan_banned("our offshore team") != []
        assert scan_banned("a virtual assistant for your firm") != []

    def test_clean_text(self):
        assert scan_banned("the records chase is what we take off your plate") == []

    def test_case_insensitive(self):
        assert scan_banned("We will REPLACE the whole workflow") != []
