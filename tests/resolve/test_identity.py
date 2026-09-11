"""resolve_identity and g1_identity -- the hard gate. Every test inserts
synthetic observations directly with already-normalized match keys (per
context/30-data-model/02-normalization-contracts.md, normalization happens
at write time, not inside this component), and drives the component/gate
through the real `lge.registry` contract.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.norm import norm_name
from lge.registry import RunContext
from lge.resolve.identity import g1_identity, resolve_identity
from lge.settings import get_settings
from tests.conftest import expect_db_error, make_firm

pytestmark = pytest.mark.db


# =============================================================================
# Helpers
# =============================================================================


def make_observation(conn, **cols):
    cols.setdefault("source", "internal_firms")
    cols.setdefault("source_key", uuid.uuid4().hex)
    cols.setdefault("fetched_at", datetime.now(UTC))
    cols.setdefault("payload", Jsonb({}))
    cols.setdefault("name_raw", "Test Firm")
    cols.setdefault("name_stem", norm_name(cols["name_raw"]))
    cols.setdefault("norm_versions", Jsonb({}))

    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO observation ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def run_identity(conn):
    ctx = RunContext(conn, get_settings())
    return resolve_identity(ctx)


def run_gate(conn):
    ctx = RunContext(conn, get_settings())
    return g1_identity(ctx)


def firm_row(conn, firm_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM firm WHERE id = %s", (firm_id,))
        return cur.fetchone()


def obs_row(conn, obs_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM observation WHERE id = %s", (obs_id,))
        return cur.fetchone()


def firm_count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm")
        return cur.fetchone()["n"]


def alias_count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM firm_alias")
        return cur.fetchone()["n"]


def lead_count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM lead")
        return cur.fetchone()["n"]


def review_count(conn, **where):
    clauses = " AND ".join(f"{k} = %s" for k in where)
    sql = "SELECT count(*) AS n FROM identity_review"
    if clauses:
        sql += f" WHERE {clauses}"
    with conn.cursor() as cur:
        cur.execute(sql, list(where.values()))  # noqa: S608
        return cur.fetchone()["n"]


# =============================================================================
# R1 -- domain
# =============================================================================


def test_r1_merges_domain_variants(db):
    a = make_observation(db, domain="smithlaw.com", name_raw="Smith Law www")
    b = make_observation(db, domain="smithlaw.com", name_raw="Smith Law")
    run_identity(db)
    assert obs_row(db, a)["firm_id"] == obs_row(db, b)["firm_id"]
    assert firm_count(db) == 1


def test_null_domains_never_merge(db):
    a = make_observation(db, domain=None, name_raw="Alpha Firm", name_stem="alpha unique")
    b = make_observation(db, domain=None, name_raw="Beta Firm", name_stem="beta unique")
    run_identity(db)
    assert obs_row(db, a)["firm_id"] != obs_row(db, b)["firm_id"]
    assert firm_count(db) == 2


# =============================================================================
# R2 -- phone (and the shared-number exclusion)
# =============================================================================


def test_shared_phone_yields_no_r2_edge(db):
    # 4 distinct candidates (distinct domains) claiming the same number ->
    # an answering service / tracking pool, excluded from R2 entirely.
    ids = [
        make_observation(db, phone_e164="+12125551000", domain=f"tenant{i}.com")
        for i in range(4)
    ]
    run_identity(db)
    firm_ids = {obs_row(db, i)["firm_id"] for i in ids}
    assert len(firm_ids) == 4  # no merge at all


def test_non_shared_phone_merges(db):
    a = make_observation(db, phone_e164="+12125552000", domain="onlya.com")
    b = make_observation(db, phone_e164="+12125552000", domain="onlyb.com")
    run_identity(db)
    assert obs_row(db, a)["firm_id"] == obs_row(db, b)["firm_id"]
    assert firm_count(db) == 1


# =============================================================================
# R3 -- addr_hash + name similarity (both conditions)
# =============================================================================


def test_r3_office_tower_same_address_dissimilar_names_does_not_merge(db):
    a = make_observation(
        db, addr_hash="towerhash1", zip5="10001", name_raw="Smith Injury Law",
        name_stem="smith injury"
    )
    b = make_observation(
        db, addr_hash="towerhash1", zip5="10001", name_raw="Garcia Bankruptcy Firm",
        name_stem="garcia bankruptcy"
    )
    run_identity(db)
    assert obs_row(db, a)["firm_id"] != obs_row(db, b)["firm_id"]
    assert firm_count(db) == 2


def test_r3_merges_same_address_similar_names(db):
    a = make_observation(
        db, addr_hash="samehash2", zip5="20002", name_raw="Riverside Injury Partners",
        name_stem="riverside injury partners"
    )
    b = make_observation(
        db, addr_hash="samehash2", zip5="20002", name_raw="Riverside Injury Partner",
        name_stem="riverside injury partner"
    )
    run_identity(db)
    assert obs_row(db, a)["firm_id"] == obs_row(db, b)["firm_id"]
    assert firm_count(db) == 1


# =============================================================================
# R4 -- same zip5, high name similarity -- REVIEW ONLY, never merges
# =============================================================================


def test_r4_produces_review_and_no_merge(db):
    a = make_observation(
        db, zip5="30003", name_raw="Harbor Legal Group", name_stem="harbor legal group"
    )
    b = make_observation(
        db, zip5="30003", name_raw="Harbor Legal Groupe", name_stem="harbor legal groupe"
    )
    run_identity(db)
    assert obs_row(db, a)["firm_id"] != obs_row(db, b)["firm_id"]
    assert firm_count(db) == 2
    assert review_count(db, rule="R4") == 1


# =============================================================================
# Transitivity
# =============================================================================


def test_transitivity_domain_then_phone(db):
    a = make_observation(db, domain="chain.com", phone_e164=None)
    b = make_observation(db, domain="chain.com", phone_e164="+12125553000")
    c = make_observation(db, domain=None, phone_e164="+12125553000")
    run_identity(db)
    fa, fb, fc = (obs_row(db, i)["firm_id"] for i in (a, b, c))
    assert fa == fb == fc
    assert firm_count(db) == 1


# =============================================================================
# Canonical name precedence
# =============================================================================


def test_canonical_name_precedence(db):
    make_observation(
        db, domain="prec.com", source="internal_firms", name_raw="ABC Internal Name"
    )
    b = make_observation(db, domain="prec.com", source="site", name_raw="ABC Real Name")
    run_identity(db)
    firm_id = obs_row(db, b)["firm_id"]
    assert firm_row(db, firm_id)["canonical_name"] == "ABC Real Name"


# =============================================================================
# Lead lifecycle on new-firm creation
# =============================================================================


def test_new_firm_gets_one_discovered_lead_and_one_event(db):
    a = make_observation(db, domain="freshfirm.com")
    run_identity(db)
    firm_id = obs_row(db, a)["firm_id"]

    with db.cursor() as cur:
        cur.execute("SELECT id, state FROM lead WHERE firm_id = %s", (firm_id,))
        leads = cur.fetchall()
    assert len(leads) == 1
    assert leads[0]["state"] == "DISCOVERED"

    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM lead_state_event WHERE lead_id = %s", (leads[0]["id"],)
        )
        assert cur.fetchone()["n"] == 1


# =============================================================================
# Idempotency
# =============================================================================


def test_rerun_is_a_no_op(db):
    make_observation(db, domain="idem.com", name_raw="Idempotent Firm")
    make_observation(db, domain="idem.com", name_raw="Idempotent Firm Variant")
    run_identity(db)

    firms_before = firm_count(db)
    aliases_before = alias_count(db)
    leads_before = lead_count(db)

    result = run_identity(db)

    assert firm_count(db) == firms_before
    assert alias_count(db) == aliases_before
    assert lead_count(db) == leads_before
    assert result.notes[0] == "new_firms=0"


def test_new_observation_joins_existing_firm_keeps_id(db):
    a = make_observation(db, domain="grow.com")
    run_identity(db)
    firm_id_before = obs_row(db, a)["firm_id"]
    assert firm_id_before is not None

    b = make_observation(db, domain="grow.com")
    run_identity(db)

    assert obs_row(db, b)["firm_id"] == firm_id_before
    assert obs_row(db, a)["firm_id"] == firm_id_before
    assert firm_count(db) == 1


# =============================================================================
# Cross-firm component -- review, never merge
# =============================================================================


def test_cross_firm_component_reviews_never_merges(db):
    firm_a = make_firm(db, domain=None)
    firm_b = make_firm(db, domain=None)
    a = make_observation(db, domain="bridge.com", firm_id=firm_a)
    b = make_observation(db, domain="bridge.com", firm_id=firm_b)

    run_identity(db)

    assert obs_row(db, a)["firm_id"] == firm_a
    assert obs_row(db, b)["firm_id"] == firm_b
    assert firm_count(db) == 2

    with db.cursor() as cur:
        cur.execute(
            "SELECT left_firm_id, right_firm_id, reason FROM identity_review "
            "WHERE rule = 'cross_firm'"
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == "cross_firm_component"
    assert {rows[0]["left_firm_id"], rows[0]["right_firm_id"]} == {firm_a, firm_b}

    # idempotent: a second run does not duplicate the review
    run_identity(db)
    assert review_count(db, rule="cross_firm") == 1


# =============================================================================
# g1_identity
# =============================================================================


def test_gate_fails_when_two_firms_share_a_phone(db):
    # firm.domain carries its own unique partial index (sql/001_schema.sql),
    # so two firms can never literally share a domain -- that half of the
    # gate's check is already enforced structurally. phone_e164 has no such
    # constraint, so it is what actually exercises the gate's FAIL path.
    with lge_db.writer(db, "resolve"), db.cursor() as cur:
        cur.execute(
            "INSERT INTO firm (id, canonical_name, name_stem, phone_e164, first_seen) "
            "VALUES (%s, %s, %s, %s, %s)",
            (str(uuid.uuid4()), "Dup One", "dup one", "+12125559999", datetime.now(UTC)),
        )
        cur.execute(
            "INSERT INTO firm (id, canonical_name, name_stem, phone_e164, first_seen) "
            "VALUES (%s, %s, %s, %s, %s)",
            (str(uuid.uuid4()), "Dup Two", "dup two", "+12125559999", datetime.now(UTC)),
        )

    passed, report = run_gate(db)
    assert passed is False
    assert "phone_e164" in report
    assert "FAIL" in report


def test_gate_passes_on_clean_set(db):
    make_observation(db, domain="clean-a.com")
    make_observation(db, domain="clean-b.com")
    run_identity(db)

    passed, report = run_gate(db)
    assert passed is True
    assert "OK: no domain is shared" in report
    assert "OK: no phone_e164 is shared" in report


def test_gate_domain_duplicate_refused_by_schema(db):
    # Confirms the premise above: the DB itself refuses a second firm with
    # the same non-null domain, independent of this gate.
    make_firm(db, domain="onlyone.com")
    with expect_db_error(db, "duplicate key|unique"):
        make_firm(db, domain="onlyone.com")


def test_single_source_ratio_is_informational(db):
    for i in range(3):
        make_observation(db, domain=f"solo{i}.com", source="internal_firms")
    run_identity(db)

    passed, report = run_gate(db)
    assert passed is True
    assert "informational only" in report
    assert "single contact-level file" in report
