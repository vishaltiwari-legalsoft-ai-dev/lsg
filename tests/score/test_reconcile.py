"""reconcile() -- every branch in context/30-data-model/04-attribute-
reconciliation.md, plus the bulk `reconcile` component's set-based path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lge.registry import RunContext
from lge.score import reconcile as rc
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

AT = datetime(2026, 1, 1, tzinfo=UTC)


def add_claim(conn, firm_id, attr, value, source, confidence, *, evidence=None, at=AT, age_days=0):
    observed_at = at - timedelta(days=age_days)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, "
            "evidence, observed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (firm_id, attr, Jsonb(value), source, confidence, evidence, observed_at),
        )


def firm_row(conn, firm_id, *cols):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM firm WHERE id = %s", (firm_id,))  # noqa: S608
        return cur.fetchone()


# =============================================================================
# Pure resolver -- resolve_claims()
# =============================================================================


def test_no_claims_is_null_and_stale():
    out = rc.resolve_claims("fee_model", [])
    assert out.value is None
    assert out.stale is True
    assert out.conflict is False


def test_one_source_wins_outright():
    claims = [rc.Claim("site:jsonld", "Smith Law", 0.95, AT)]
    out = rc.resolve_claims("canonical_name", claims)
    assert out.value == "Smith Law"
    assert out.source == "site:jsonld"
    assert out.stale is False


def test_agreement_takes_max_confidence():
    claims = [
        rc.Claim("site:jsonld", "contingency", 0.9, AT),
        rc.Claim("rules:practice", "contingency", 0.99, AT),
    ]
    out = rc.resolve_claims("fee_model", claims)
    assert out.value == "contingency"
    assert out.confidence == pytest.approx(0.99)


def test_two_sources_printing_the_same_office_agree():
    # An address claim is a dict; with site:jsonld and site:page both writing
    # one (D-031) the agreement check must compare dicts, not hash them.
    office = {"street_norm": "3350 PEACHTREE RD NE", "unit": "STE 1200", "city": "ATLANTA",
              "state": "GA", "zip5": "30326", "addr_hash": "abc"}
    claims = [
        rc.Claim("site:jsonld", dict(office), 0.9, AT),
        rc.Claim("site:page", dict(office), 0.8, AT),
    ]
    out = rc.resolve_claims("address", claims)
    assert out.value == office
    assert out.conflict is False
    assert out.confidence == pytest.approx(0.9)

    other = {**office, "zip5": "30060", "addr_hash": "def"}
    out = rc.resolve_claims(
        "address", [rc.Claim("site:jsonld", office, 0.9, AT), rc.Claim("site:page", other, 0.8, AT)]
    )
    assert out.value == office  # precedence: site:jsonld above site:page


def test_disagreement_precedence_wins():
    # canonical_name: site > bar > places > directory(internal_firms)
    claims = [
        rc.Claim("internal_firms", "Fulton Jeang PLLC", 0.5, AT),
        rc.Claim("site:jsonld", "Fulton & Jeang, PLLC", 0.95, AT),
    ]
    out = rc.resolve_claims("canonical_name", claims)
    assert out.value == "Fulton & Jeang, PLLC"
    assert out.source == "site:jsonld"


def test_internal_firms_loses_canonical_name_to_site_jsonld():
    claims = [
        rc.Claim("site:jsonld", "The Real Name LLP", 0.95, AT),
        rc.Claim("internal_firms", "Vendor's Stale Name", 0.5, AT),
        rc.Claim("bar", "Bar Registry Name", 0.7, AT - timedelta(days=1)),
    ]
    out = rc.resolve_claims("canonical_name", claims)
    assert out.value == "The Real Name LLP"
    assert out.source == "site:jsonld"


def test_low_confidence_winner_on_tier_field_conflicts():
    # primary_practice is tier-determining. llm:p9 outranks llm:p8, but at
    # confidence 0.4 it must not silently win.
    claims = [
        rc.Claim("llm:p9:v1", "personal_injury", 0.4, AT),
        rc.Claim("llm:p8:v1", "mass_tort", 0.9, AT),
    ]
    out = rc.resolve_claims("primary_practice", claims)
    assert out.conflict is True
    assert out.value is None
    assert "confidence" in out.conflict_reason


def test_fee_model_regex_llm_disagreement_escalates_until_p9():
    claims = [
        rc.Claim("regex:p6", "hourly", 0.9, AT),
        rc.Claim("llm:p8:v1", "contingency", 0.9, AT),
    ]
    out = rc.resolve_claims("fee_model", claims)
    assert out.conflict is True
    assert out.value is None
    assert "escalate" in out.conflict_reason

    # Once a p9 claim exists, the standard rule applies -- regex still tops
    # fee_model's own precedence list, so a confident regex match wins.
    claims_with_p9 = [*claims, rc.Claim("llm:p9:v1", "contingency", 0.9, AT)]
    out2 = rc.resolve_claims("fee_model", claims_with_p9)
    assert out2.conflict is False
    assert out2.value == "hourly"
    assert out2.source == "regex:p6"


def test_unknown_never_beats_a_real_value():
    claims = [
        rc.Claim("regex:p6", "unknown", 0.0, AT),
        rc.Claim("llm:p8:v1", "flat", 0.85, AT),
    ]
    out = rc.resolve_claims("fee_model", claims)
    assert out.value == "flat"
    assert out.source == "llm:p8:v1"


def test_all_unknown_resolves_to_unknown_for_fee_model():
    claims = [rc.Claim("regex:p6", "unknown", 0.0, AT)]
    out = rc.resolve_claims("fee_model", claims)
    assert out.value == "unknown"
    assert out.stale is False


def test_all_none_resolves_to_null_and_stale_for_non_unknown_capable_attr():
    claims = [rc.Claim("site:jsonld", None, 0.0, AT)]
    out = rc.resolve_claims("canonical_name", claims)
    assert out.value is None
    assert out.stale is True


def test_attorney_count_ignores_non_llm_sources():
    claims = [
        rc.Claim("internal_firms", 300, 0.5, AT),  # vendor headcount trap
        rc.Claim("regex:p6", 5, 0.9, AT),
        rc.Claim("llm:p8:v1", 7, 0.85, AT),
    ]
    out = rc.resolve_claims("attorney_count", claims)
    assert out.value == 7
    assert out.source == "llm:p8:v1"


def test_address_fan_out_shape():
    value = {
        "street_norm": "123 MAIN ST", "unit": "STE 400", "city": "Austin",
        "state": "TX", "zip5": "78701", "addr_hash": "deadbeef",
    }
    claims = [rc.Claim("site:jsonld", value, 0.95, AT)]
    out = rc.resolve_claims("address", claims)
    row = rc._address_row(out.value)
    assert row == {
        "street_norm": "123 MAIN ST", "addr_unit": "STE 400", "addr_hash": "deadbeef",
        "zip5": "78701", "state": "TX", "city": "Austin",
    }


def test_newest_claim_wins_within_same_source():
    claims = [
        rc.Claim("llm:p8:v1", "immigration", 0.7, AT - timedelta(days=10)),
        rc.Claim("llm:p8:v1", "family", 0.7, AT),
    ]
    out = rc.resolve_claims("primary_practice", claims)
    assert out.value == "family"


# Found before the first paid P8 run: config named llm:p8:v1 while P8 writes
# llm:p8:v2, so exclusive attrs dropped every AI claim and the p9 loop-breaker
# never fired. Precedence ranks the tier; the prompt revision is not part of it.


def test_current_prompt_revision_counts_for_exclusive_attrs():
    claims = [rc.Claim("internal_firms", 300, 0.5, AT), rc.Claim("llm:p8:v2", 7, 0.85, AT)]
    out = rc.resolve_claims("attorney_count", claims)
    assert out.value == 7
    assert out.source == "llm:p8:v2"


def test_current_prompt_revision_keeps_its_rank():
    claims = [
        rc.Claim("internal_firms", "family", 0.9, AT),
        rc.Claim("llm:p8:v2", "personal_injury", 0.8, AT),
    ]
    out = rc.resolve_claims("primary_practice", claims)
    assert out.value == "personal_injury"


def test_p9_at_current_revision_breaks_the_escalation_loop():
    claims = [
        rc.Claim("regex:p6", "hourly", 0.9, AT),
        rc.Claim("llm:p8:v2", "contingency", 0.9, AT),
        rc.Claim("llm:p9:v2", "contingency", 0.9, AT),
    ]
    out = rc.resolve_claims("fee_model", claims)
    assert out.conflict is False
    assert out.source == "regex:p6"


def test_newer_prompt_revision_supersedes_older_at_same_observation():
    claims = [
        rc.Claim("llm:p8:v1", "immigration", 0.9, AT),
        rc.Claim("llm:p8:v2", "personal_injury", 0.7, AT),
    ]
    out = rc.resolve_claims("primary_practice", claims)
    assert out.value == "personal_injury"
    assert out.conflict is False


# =============================================================================
# DB-facing single-firm reconcile()
# =============================================================================


def test_reconcile_writes_firm_column_and_marks_stale_when_empty(db):
    firm_id = make_firm(db, fee_model=None)
    out = rc.reconcile(db, firm_id, "fee_model", at=AT)
    assert out.stale is True
    row = firm_row(db, firm_id, "fee_model")
    assert row["fee_model"] is None
    with db.cursor() as cur:
        cur.execute(
            "SELECT stale FROM firm_attr_state WHERE firm_id=%s AND attr='fee_model'", (firm_id,)
        )
        assert cur.fetchone()["stale"] is True


def test_reconcile_opens_and_later_resolves_conflict(db):
    firm_id = make_firm(db)
    add_claim(db, firm_id, "primary_practice", "personal_injury", "llm:p9:v1", 0.4, at=AT)
    add_claim(db, firm_id, "primary_practice", "mass_tort", "llm:p8:v1", 0.9, at=AT)
    out = rc.reconcile(db, firm_id, "primary_practice", at=AT)
    assert out.conflict is True
    with db.cursor() as cur:
        cur.execute(
            "SELECT resolved_at FROM reconcile_conflict "
            "WHERE firm_id=%s AND attr='primary_practice'",
            (firm_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["resolved_at"] is None

    # A later run with a confident, agreeing claim resolves it.
    add_claim(db, firm_id, "primary_practice", "personal_injury", "llm:p9:v1", 0.9,
              at=AT + timedelta(days=1))
    add_claim(db, firm_id, "primary_practice", "personal_injury", "llm:p8:v1", 0.9,
              at=AT + timedelta(days=1))
    out2 = rc.reconcile(db, firm_id, "primary_practice", at=AT + timedelta(days=1))
    assert out2.conflict is False
    assert out2.value == "personal_injury"
    with db.cursor() as cur:
        cur.execute(
            "SELECT resolved_at FROM reconcile_conflict "
            "WHERE firm_id=%s AND attr='primary_practice'",
            (firm_id,),
        )
        assert cur.fetchone()["resolved_at"] is not None


def test_reconcile_idempotent_rerun(db):
    firm_id = make_firm(db)
    add_claim(db, firm_id, "fee_model", "contingency", "regex:p6", 0.9, at=AT)
    out1 = rc.reconcile(db, firm_id, "fee_model", at=AT)
    out2 = rc.reconcile(db, firm_id, "fee_model", at=AT)
    assert out1.value == out2.value == "contingency"
    row = firm_row(db, firm_id, "fee_model")
    assert row["fee_model"] == "contingency"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM reconcile_conflict WHERE firm_id=%s", (firm_id,))
        assert cur.fetchone()["n"] == 0


def test_reconcile_address_fanout_writes_columns(db):
    firm_id = make_firm(db)
    value = {
        "street_norm": "500 MAIN ST", "unit": None, "city": "Dallas",
        "state": "TX", "zip5": "75201", "addr_hash": "abc123",
    }
    add_claim(db, firm_id, "address", value, "site:jsonld", 0.95, at=AT)
    rc.reconcile(db, firm_id, "address", at=AT)
    row = firm_row(db, firm_id, "street_norm", "addr_unit", "addr_hash", "zip5", "state", "city")
    assert row["street_norm"] == "500 MAIN ST"
    assert row["zip5"] == "75201"
    assert row["state"] == "TX"
    assert row["city"] == "Dallas"


def test_city_attr_does_not_null_address_derived_city(db):
    firm_id = make_firm(db)
    value = {
        "street_norm": "1 ELM ST", "unit": None, "city": "Houston",
        "state": "TX", "zip5": "77001", "addr_hash": "h1",
    }
    add_claim(db, firm_id, "address", value, "site:jsonld", 0.95, at=AT)
    rc.reconcile(db, firm_id, "address", at=AT)
    # No standalone 'city' claims at all -- reconciling 'city' must not wipe
    # out the city the address fan-out just set.
    rc.reconcile(db, firm_id, "city", at=AT)
    row = firm_row(db, firm_id, "city")
    assert row["city"] == "Houston"


# =============================================================================
# Bulk component -- chunked, set-based; tier + fit recomputed
# =============================================================================


def _ctx(db):
    return RunContext(db, get_settings())


def test_reconcile_component_recomputes_tier_and_fit(db):
    firm_id = make_firm(db)
    add_claim(db, firm_id, "fee_model", "contingency", "regex:p6", 0.9, at=AT)
    add_claim(db, firm_id, "primary_practice", "personal_injury", "llm:p9:v1", 0.9, at=AT)

    # Freeze "now" for the component by monkeypatching datetime? Simpler:
    # claims dated at AT are within 90 days of a real now() call as long as
    # the test runs before 2026-04-01 -- instead, drive it directly through
    # the internal chunk helper with an explicit `at`, exactly like the
    # single-firm path above, so the test has no wall-clock dependency.
    cfg = rc.load_precedence()
    tier_changed = rc._reconcile_chunk(db, [firm_id], AT, cfg)
    assert tier_changed == 1

    row = firm_row(db, firm_id, "tier", "fit_score", "fee_model", "primary_practice")
    assert row["tier"] == "1A"
    assert row["fit_score"] is not None and row["fit_score"] > 0


def test_reconcile_component_ignores_informational_attrs(db):
    firm_id = make_firm(db)
    add_claim(db, firm_id, "vendor_headcount_range", "1 to 10", "internal_firms", 0.5, at=AT)
    cfg = rc.load_precedence()
    # Must not raise, and must not attempt to write a "vendor_headcount_range"
    # column (there isn't one).
    rc._reconcile_chunk(db, [firm_id], AT, cfg)


def test_ai_practice_areas_shape_writes_slugs(db):
    # The real P8 claim shape. It outranks rules:practice, and a dict reaching
    # psycopg aborted the first real reconcile run after P8.
    firm_id = make_firm(db)
    add_claim(db, firm_id, "practice_areas", ["criminal", "personal_injury"], "rules:practice", 0.9)
    add_claim(
        db, firm_id, "practice_areas",
        [{"area": "workers_comp", "weight": 0.3}, {"area": "personal_injury", "weight": 0.6}],
        "llm:p8:v2", 0.7,
    )
    rc._reconcile_chunk(db, [firm_id], AT, rc.load_precedence())

    row = firm_row(db, firm_id, "practice_areas")
    assert row["practice_areas"] == ["personal_injury", "workers_comp"]


def test_reconcile_component_via_registry(db):
    # The component uses real datetime.now(UTC) internally (it is the actual
    # nightly entry point, not a test seam) -- claims must be fresh against
    # wall-clock "now", unlike the rest of this file which pins AT.
    now = datetime.now(UTC)
    firm_id = make_firm(db)
    add_claim(db, firm_id, "fee_model", "flat", "regex:p6", 0.9, at=now)
    add_claim(db, firm_id, "primary_practice", "immigration", "llm:p9:v1", 0.9, at=now)
    ctx = _ctx(db)
    result = rc.reconcile_component(ctx, limit=10)
    assert result.processed >= 1
    assert result.failed == 0

    row = firm_row(db, firm_id, "tier")
    assert row["tier"] == "1B"
