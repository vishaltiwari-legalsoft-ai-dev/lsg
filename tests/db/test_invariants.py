"""Every invariant I1-I7 (plus the lifecycle transition whitelist) gets a
test that tries to violate it and asserts the database refuses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lge import db as lge_db
from tests.conftest import expect_db_error, make_firm

pytestmark = pytest.mark.db


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "DISCOVERED")
    cols.setdefault("created_at", datetime.now(UTC))
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def advance(conn, lead_id, *states, trigger="test_advance"):
    with lge_db.lifecycle(conn, trigger), conn.cursor() as cur:
        for state in states:
            cur.execute("UPDATE lead SET state = %s WHERE id = %s", (state, lead_id))


def add_bench(conn, sku, *, available=3, replenish=1, as_of=None):
    as_of = as_of or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bench_inventory (sku, language, practice_exp, available, "
            "replenish_rate_30d, as_of) VALUES (%s, 'en', 'any', %s, %s, %s)",
            (sku, available, replenish, as_of),
        )


def make_signal(conn, firm_id, **cols):
    cols.setdefault("kind", "job_posting_open")
    cols.setdefault("fingerprint", "fp-" + uuid.uuid4().hex[:8])
    now = datetime.now(UTC)
    cols.setdefault("first_seen", now - timedelta(days=5))
    cols.setdefault("last_seen", now - timedelta(days=5))
    cols.setdefault("evidence", Jsonb({"q": "we need a paralegal"}))
    columns = ["firm_id", *cols.keys()]
    values = [firm_id, *cols.values()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with lge_db.writer(conn, "reconcile"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO signal ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


# =============================================================================
# I1 -- at most one open lead per firm
# =============================================================================


def test_i1_second_open_lead_refused(db):
    firm_id = make_firm(db)
    make_lead(db, firm_id)
    with expect_db_error(db, "lead_open_firm_id_uidx|duplicate key"):
        make_lead(db, firm_id)


# =============================================================================
# I2 -- no outreach_touch for a firm/domain/contact in suppression
# =============================================================================


def test_i2_domain_suppressed_blocks_touch(db):
    firm_id = make_firm(db, domain="suppressed-example.com")
    lead_id = make_lead(db, firm_id)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO suppression (scope, value, reason, added_at) "
            "VALUES ('domain', 'suppressed-example.com', 'optout', now())"
        )
    with expect_db_error(db, "I2 violation"):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO outreach_touch (lead_id, channel, step) VALUES (%s, 'phone', 1)",
                (lead_id,),
            )


def test_i2_email_suppressed_contact_blocks_touch(db):
    firm_id = make_firm(db)
    contact_id = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact (id, firm_id, full_name) VALUES (%s, %s, 'Jane Partner')",
            (contact_id, firm_id),
        )
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status) "
            "VALUES (%s, 'jane@example.com', 'valid')",
            (contact_id,),
        )
        cur.execute(
            "INSERT INTO suppression (scope, value, reason, added_at) "
            "VALUES ('email', 'jane@example.com', 'optout', now())"
        )
    lead_id = make_lead(db, firm_id, contact_id=contact_id, grade="A")
    with expect_db_error(db, "I2 violation"):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO outreach_touch (lead_id, channel, step) VALUES (%s, 'phone', 1)",
                (lead_id,),
            )


# =============================================================================
# I3 -- grade B leads may never be emailed
# =============================================================================


def test_i3_grade_b_email_refused(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id, grade="B")
    with expect_db_error(db, "I3 violation"):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO outreach_touch (lead_id, channel, step) VALUES (%s, 'email', 1)",
                (lead_id,),
            )


def test_i3_grade_a_email_allowed(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id, grade="A")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO outreach_touch (lead_id, channel, step) VALUES (%s, 'email', 1)",
            (lead_id,),
        )


# =============================================================================
# I4 -- no ARMED without fresh bench (available > 0, as_of within 48h)
# =============================================================================


def lead_ready_for_arming(db, firm_id):
    lead_id = make_lead(db, firm_id)
    advance(
        db, lead_id,
        "PROFILING", "PROFILED", "CLASSIFIED", "CONTACT_PENDING", "RESOLVED", "QUALIFIED_A",
    )
    with db.cursor() as cur:
        cur.execute(
            "UPDATE lead SET wedge_sku = %s, grade = 'A' WHERE id = %s",
            ("demand_writer", lead_id),
        )
    return lead_id


def test_i4_arm_with_no_bench_refused(db):
    firm_id = make_firm(db)
    lead_id = lead_ready_for_arming(db, firm_id)
    with expect_db_error(db, "I4 violation"):
        advance(db, lead_id, "ARMED")


def test_i4_arm_with_zero_bench_refused(db):
    firm_id = make_firm(db)
    lead_id = lead_ready_for_arming(db, firm_id)
    add_bench(db, "demand_writer", available=0)
    with expect_db_error(db, "I4 violation"):
        advance(db, lead_id, "ARMED")


def test_i4_arm_with_stale_bench_refused(db):
    firm_id = make_firm(db)
    lead_id = lead_ready_for_arming(db, firm_id)
    add_bench(db, "demand_writer", available=5, as_of=datetime.now(UTC) - timedelta(hours=49))
    with expect_db_error(db, "I4 violation"):
        advance(db, lead_id, "ARMED")


def test_i4_arm_with_fresh_bench_allowed(db):
    firm_id = make_firm(db)
    lead_id = lead_ready_for_arming(db, firm_id)
    add_bench(db, "demand_writer", available=5)
    advance(db, lead_id, "ARMED")
    with db.cursor() as cur:
        cur.execute("SELECT state FROM lead WHERE id = %s", (lead_id,))
        assert cur.fetchone()["state"] == "ARMED"


# =============================================================================
# I5 -- every state change writes exactly one lead_state_event
# =============================================================================


def test_i5_insert_writes_one_event(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id)
    with db.cursor() as cur:
        cur.execute("SELECT * FROM lead_state_event WHERE lead_id = %s", (lead_id,))
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["from_state"] is None
    assert rows[0]["to_state"] == "DISCOVERED"


def test_i5_one_event_per_transition_with_trigger_actor(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id)
    with lge_db.lifecycle(db, "p1_enqueued", actor="scheduler"), db.cursor() as cur:
        cur.execute("UPDATE lead SET state = 'PROFILING' WHERE id = %s", (lead_id,))
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM lead_state_event WHERE lead_id = %s ORDER BY id", (lead_id,)
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[1]["from_state"] == "DISCOVERED"
    assert rows[1]["to_state"] == "PROFILING"
    assert rows[1]["trigger"] == "p1_enqueued"
    assert rows[1]["actor"] == "scheduler"


def test_i5_no_event_when_state_unchanged(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id)
    with db.cursor() as cur:
        cur.execute("UPDATE lead SET state = state WHERE id = %s", (lead_id,))
        cur.execute(
            "SELECT count(*) AS n FROM lead_state_event WHERE lead_id = %s", (lead_id,)
        )
        assert cur.fetchone()["n"] == 1


# =============================================================================
# I6 -- signal immutability, signal_sighting append-only
# =============================================================================


def test_i6_update_identity_columns_refused(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)

    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute(
                "UPDATE signal SET evidence = %s WHERE id = %s",
                (Jsonb({"q": "changed"}), signal_id),
            )

    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute("UPDATE signal SET kind = 'partner_intro' WHERE id = %s", (signal_id,))

    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute("UPDATE signal SET first_seen = now() WHERE id = %s", (signal_id,))


def test_i6_delete_refused(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)
    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute("DELETE FROM signal WHERE id = %s", (signal_id,))


def test_i6_last_seen_backwards_refused(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)
    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute(
                "UPDATE signal SET last_seen = last_seen - interval '1 day' WHERE id = %s",
                (signal_id,),
            )


def test_i6_last_seen_forward_and_close_allowed(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE signal SET last_seen = last_seen + interval '1 day', closed_at = now() "
            "WHERE id = %s",
            (signal_id,),
        )
        cur.execute("SELECT closed_at FROM signal WHERE id = %s", (signal_id,))
        assert cur.fetchone()["closed_at"] is not None


def test_i6_closed_at_cannot_clear_without_advance(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE signal SET last_seen = last_seen + interval '1 day', closed_at = now() "
            "WHERE id = %s",
            (signal_id,),
        )
    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute("UPDATE signal SET closed_at = NULL WHERE id = %s", (signal_id,))


def test_i6_role_lge_app_cannot_update_evidence(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)
    with db.cursor() as cur:
        cur.execute("SET ROLE lge_app")
    try:
        with expect_db_error(db, "permission denied"):
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE signal SET evidence = %s WHERE id = %s",
                    (Jsonb({"q": "x"}), signal_id),
                )
    finally:
        with db.cursor() as cur:
            cur.execute("RESET ROLE")


def test_i6_sighting_update_and_delete_refused(db):
    firm_id = make_firm(db)
    signal_id = make_signal(db, firm_id)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO signal_sighting (signal_id, source, present, fetch_ok) "
            "VALUES (%s, 'careers_page', true, true) RETURNING id",
            (signal_id,),
        )
        sighting_id = cur.fetchone()["id"]

    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute(
                "UPDATE signal_sighting SET present = false WHERE id = %s", (sighting_id,)
            )

    with expect_db_error(db, "I6 violation"):
        with db.cursor() as cur:
            cur.execute("DELETE FROM signal_sighting WHERE id = %s", (sighting_id,))


# =============================================================================
# I7 -- reconcile()/resolve()/profile()/score() are the only writers of their
# respective firm column groups
# =============================================================================


def test_i7_no_writer_refused(db):
    with expect_db_error(db, "I7 violation"):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO firm (id, canonical_name, name_stem, first_seen) "
                "VALUES (%s, 'X', 'x', now())",
                (str(uuid.uuid4()),),
            )


def test_i7_qualification_column_wrong_writer_refused(db):
    firm_id = make_firm(db)
    with expect_db_error(db, "I7 violation"):
        with lge_db.writer(db, "resolve"), db.cursor() as cur:
            cur.execute("UPDATE firm SET fee_model = 'contingency' WHERE id = %s", (firm_id,))


def test_i7_qualification_column_reconcile_allowed(db):
    firm_id = make_firm(db)
    with lge_db.writer(db, "reconcile"), db.cursor() as cur:
        cur.execute("UPDATE firm SET fee_model = 'contingency' WHERE id = %s", (firm_id,))


def test_i7_tier_as_score_allowed(db):
    firm_id = make_firm(db)
    with lge_db.writer(db, "score"), db.cursor() as cur:
        cur.execute("UPDATE firm SET tier = '1A' WHERE id = %s", (firm_id,))


# =============================================================================
# Lifecycle transition whitelist
# =============================================================================


def test_transition_discovered_to_armed_refused(db):
    firm_id = make_firm(db)
    lead_id = make_lead(db, firm_id)
    with expect_db_error(db, "violation"):
        advance(db, lead_id, "ARMED")


def test_transition_not_in_whitelist_refused_independent_of_i4(db):
    # ARMED -> CONTACT_PENDING isn't gated by I4 (NEW.state != 'ARMED') so this
    # isolates the whitelist trigger specifically.
    firm_id = make_firm(db)
    lead_id = lead_ready_for_arming(db, firm_id)
    add_bench(db, "demand_writer", available=5)
    advance(db, lead_id, "ARMED")
    with expect_db_error(db, "not a whitelisted transition"):
        advance(db, lead_id, "CONTACT_PENDING")
