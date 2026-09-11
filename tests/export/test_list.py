"""build_list: the list-hygiene filters and CSV/draft/report outputs.
DB-backed -- every test inserts its own firm/lead/contact/signal rows via
SQL, per tests/conftest.py's convention (`make_firm` is provided; the rest
are local helpers below, mirroring tests/db/test_invariants.py's pattern)."""

from __future__ import annotations

import csv
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.export.list import build_list
from lge.registry import RunContext
from lge.settings import get_settings
from tests.conftest import make_firm

pytestmark = pytest.mark.db

_NOW = datetime(2026, 9, 11, tzinfo=UTC)


def make_signal(conn, firm_id, **cols):
    cols.setdefault("kind", "job_posting_open")
    cols.setdefault("fingerprint", "fp-" + uuid.uuid4().hex[:10])
    cols.setdefault("first_seen", _NOW - timedelta(days=25))
    cols.setdefault("last_seen", _NOW - timedelta(days=1))
    if "evidence" in cols and not isinstance(cols["evidence"], Jsonb):
        cols["evidence"] = Jsonb(cols["evidence"])
    cols.setdefault(
        "evidence", Jsonb({"title": "Paralegal", "canonical_role": "paralegal"})
    )
    columns = ["firm_id", *cols.keys()]
    values = [firm_id, *cols.values()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO signal ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_contact(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("full_name", "Jane Doe")
    cols.setdefault("title", "Managing Partner")
    cols.setdefault("role", "owner")
    columns = list(cols.keys())
    values = [cols[c] for c in columns]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO contact ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_contact_email(conn, contact_id, **cols):
    cols.setdefault("email", f"{uuid.uuid4().hex[:10]}@example.com")
    cols.setdefault("status", "valid")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status, vendor_status) "
            "VALUES (%s, %s, %s, %s)",
            (contact_id, cols["email"], cols["status"], cols.get("vendor_status")),
        )
    return cols["email"]


def make_lead(conn, firm_id, **cols):
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "QUALIFIED_A")
    cols.setdefault("grade", "A")
    cols.setdefault("band", "SEQUENCE")
    cols.setdefault("created_at", _NOW)
    columns = list(cols.keys())
    values = [cols[c] for c in columns]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_suppression(conn, scope, value, reason="optout"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO suppression (scope, value, reason, added_at) VALUES (%s, %s, %s, %s)",
            (scope, value, reason, _NOW),
        )


def make_firm_track(conn, firm_id, track, reason=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_track (firm_id, track, reason, set_at) VALUES (%s, %s, %s, %s)",
            (firm_id, track, reason, _NOW),
        )


def _sequence_ready_firm(conn, **firm_kwargs):
    """A firm/contact/signal combination that should pass every hygiene
    filter and render a full SEQUENCE journey."""
    firm_kwargs.setdefault("canonical_name", "Ready Law Firm")
    firm_kwargs.setdefault("domain", f"{uuid.uuid4().hex[:8]}.example.com")
    firm_kwargs.setdefault("city", "Austin")
    firm_kwargs.setdefault("state", "TX")
    firm_kwargs.setdefault("tier", "1A")
    firm_kwargs.setdefault("fee_model", "contingency")
    firm_kwargs.setdefault("primary_practice", "personal_injury")
    firm_kwargs.setdefault("cms_detected", "filevine")
    firm_id = make_firm(conn, **firm_kwargs)
    contact_id = make_contact(conn, firm_id, full_name="John Smith", role="owner")
    make_contact_email(conn, contact_id, status="valid")
    signal_id = make_signal(
        conn,
        firm_id,
        evidence=Jsonb({"title": "Demand Writer", "canonical_role": "demand_writer"}),
    )
    return firm_id, contact_id, signal_id


def _run(conn, tmp_path, **opts):
    ctx = RunContext(conn, get_settings())
    opts.setdefault("out_dir", str(tmp_path))
    opts.setdefault("now", _NOW.isoformat())
    return build_list(ctx, **opts)


def _read_csv(path):
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------


def test_sequence_lead_appears_on_ranked_list_and_gets_a_draft(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="SEQUENCE",
        grade="A",
        fit_score=30,
        intent_score=40,
        contest="HIGH",
        wedge_sku="demand_writer",
    )

    result = _run(db, tmp_path)
    assert result.processed == 1

    rows = _read_csv(tmp_path / "leads_ranked.csv")
    assert len(rows) == 1
    assert rows[0]["firm"] == "Ready Law Firm"
    assert rows[0]["band"] == "SEQUENCE"
    assert rows[0]["email_verified"] == "true"

    drafts = list((tmp_path / "drafts").glob("*.md"))
    assert len(drafts) == 1
    text = drafts[0].read_text(encoding="utf-8")
    assert "Ready Law Firm" in text
    assert "Touch 1" in text
    assert "your demand writer opening" in text


def test_domain_suppressed_firm_excluded_from_ranked_list_and_drafts(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db, domain="blocked.example.com")
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")
    make_suppression(db, "domain", "blocked.example.com", reason="customer")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []
    assert list((tmp_path / "drafts").glob("*.md")) == []
    report = (tmp_path / "list_report.md").read_text(encoding="utf-8")
    assert "candidate" in report.lower()


def test_firm_id_suppressed_firm_excluded(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")
    make_suppression(db, "firm_id", str(firm_id), reason="dq")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []


def test_portal_track_firm_excluded(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")
    make_firm_track(db, firm_id, "portal")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []
    assert list((tmp_path / "drafts").glob("*.md")) == []


def test_displacement_track_firm_excluded(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")
    make_firm_track(db, firm_id, "displacement")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []


@pytest.mark.parametrize("tier", ["DQ_SIZE", "DQ_GEO", "UNCLASSIFIED"])
def test_dq_and_unclassified_tier_firms_excluded(db, tmp_path, tier):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db, tier=tier)
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []


def test_grade_b_lead_goes_to_phone_list_never_email_lists(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="SEQUENCE",
        grade="B",
    )

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []
    assert _read_csv(tmp_path / "strike.csv") == []
    assert list((tmp_path / "drafts").glob("*.md")) == []

    phone_rows = _read_csv(tmp_path / "phone_list.csv")
    assert len(phone_rows) == 1
    assert phone_rows[0]["firm"] == "Ready Law Firm"


def test_cooldown_in_future_excludes_lead(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="SEQUENCE",
        cooldown_until=_NOW + timedelta(days=10),
    )

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []


def test_cooldown_in_past_does_not_exclude_lead(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="SEQUENCE",
        cooldown_until=_NOW - timedelta(days=1),
    )

    _run(db, tmp_path)

    assert len(_read_csv(tmp_path / "leads_ranked.csv")) == 1


def test_closed_lead_excluded(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="SEQUENCE",
        closed_at=_NOW - timedelta(days=1),
    )

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []


def test_unverified_email_flagged_not_excluded(db, tmp_path):
    firm_id = make_firm(
        db,
        canonical_name="Catch All Law",
        domain=f"{uuid.uuid4().hex[:8]}.example.com",
        tier="1A",
        fee_model="contingency",
        primary_practice="personal_injury",
        cms_detected="clio",
    )
    contact_id = make_contact(db, firm_id, full_name="Pat Owner", role="owner")
    make_contact_email(db, contact_id, status="catch_all", vendor_status="risky_vendor_claim")
    signal_id = make_signal(
        db,
        firm_id,
        evidence=Jsonb({"title": "Demand Writer", "canonical_role": "demand_writer"}),
    )
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")

    _run(db, tmp_path)

    rows = _read_csv(tmp_path / "leads_ranked.csv")
    assert len(rows) == 1
    assert rows[0]["email_verified"] == "false"
    assert rows[0]["vendor_email_status"] == "risky_vendor_claim"


def test_strike_band_goes_to_strike_csv_and_ranked_but_not_drafts(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="STRIKE",
        contest="LOW",
        fit_score=45,
        intent_score=40,
    )

    _run(db, tmp_path)

    ranked = _read_csv(tmp_path / "leads_ranked.csv")
    assert len(ranked) == 1
    assert ranked[0]["band"] == "STRIKE"

    strike = _read_csv(tmp_path / "strike.csv")
    assert len(strike) == 1
    assert strike[0]["firm"] == "Ready Law Firm"

    assert list((tmp_path / "drafts").glob("*.md")) == []


def test_hold_band_excluded_entirely(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="HOLD")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []
    assert _read_csv(tmp_path / "phone_list.csv") == []


def test_sequence_lead_missing_signal_evidence_excluded_and_reported(db, tmp_path):
    firm_id = make_firm(
        db,
        canonical_name="No Pain Law",
        tier="1A",
        fee_model="contingency",
        primary_practice="personal_injury",
    )
    contact_id = make_contact(db, firm_id, full_name="Sam Owner", role="owner")
    make_contact_email(db, contact_id, status="valid")
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=None, band="SEQUENCE")

    _run(db, tmp_path)

    assert _read_csv(tmp_path / "leads_ranked.csv") == []
    report = (tmp_path / "list_report.md").read_text(encoding="utf-8")
    assert "sequence_missing_signal_evidence" in report


def test_nurture_lead_renders_reduced_sequence(db, tmp_path):
    firm_id, contact_id, signal_id = _sequence_ready_firm(db)
    make_lead(
        db,
        firm_id,
        contact_id=contact_id,
        arming_signal=signal_id,
        band="NURTURE",
        fit_score=15,
        intent_score=20,
    )

    _run(db, tmp_path)

    rows = _read_csv(tmp_path / "leads_ranked.csv")
    assert len(rows) == 1
    assert rows[0]["band"] == "NURTURE"

    drafts = list((tmp_path / "drafts").glob("*.md"))
    assert len(drafts) == 1
    text = drafts[0].read_text(encoding="utf-8")
    assert "Touch 1" in text
    assert "Touch 3" in text
    assert "Touch 9" in text
    assert "Touch 2" not in text
    assert "Touch 4" not in text


def test_capture_both_owner_and_admin_when_both_have_contact_info(db, tmp_path):
    firm_id = make_firm(
        db,
        canonical_name="Both People Law",
        domain=f"{uuid.uuid4().hex[:8]}.example.com",
        tier="1A",
        fee_model="contingency",
        primary_practice="personal_injury",
        cms_detected="clio",
    )
    owner_id = make_contact(db, firm_id, full_name="Owner Person", role="owner")
    make_contact_email(db, owner_id, status="valid")
    admin_id = make_contact(db, firm_id, full_name="Admin Person", role="admin")
    make_contact_email(db, admin_id, status="valid")
    signal_id = make_signal(
        db,
        firm_id,
        evidence=Jsonb({"title": "Demand Writer", "canonical_role": "demand_writer"}),
    )
    make_lead(db, firm_id, contact_id=owner_id, arming_signal=signal_id, band="SEQUENCE")

    _run(db, tmp_path)

    rows = _read_csv(tmp_path / "leads_ranked.csv")
    assert len(rows) == 2
    names = {r["contact_name"] for r in rows}
    assert names == {"Owner Person", "Admin Person"}


def test_list_hygiene_reapplied_every_run_not_static(db, tmp_path):
    """A suppression added between two runs takes effect on the next run --
    the list is never a cached/static artifact."""
    firm_id, contact_id, signal_id = _sequence_ready_firm(db, domain="flip.example.com")
    make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id, band="SEQUENCE")

    _run(db, tmp_path)
    assert len(_read_csv(tmp_path / "leads_ranked.csv")) == 1

    make_suppression(db, "domain", "flip.example.com", reason="optout")
    _run(db, tmp_path)
    assert _read_csv(tmp_path / "leads_ranked.csv") == []
