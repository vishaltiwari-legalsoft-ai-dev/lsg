"""GET /api/qualified: only a lead with every step done is ready; one or two
steps short is almost, with what is missing named; disqualified firms never
appear; the CSV carries the ready ones only -- and nothing the list rules
hold back (D-054)."""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import make_firm

from .conftest import (
    make_contact,
    make_contact_email,
    make_lead,
    make_suppression,
    sequence_ready_firm,
)

pytestmark = pytest.mark.db


def _page_read(conn, firm_id, kind="home"):
    key = uuid.uuid4().hex
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, status_code, content_hash, object_key, bytes, "
            "fetch_ok, page_kind) VALUES (%s, %s, 200, %s, %s, 10, true, %s)",
            (firm_id, f"https://{key[:8]}.example/{kind}", key, key, kind),
        )


def _linkedin(conn, contact_id, url="https://www.linkedin.com/in/john-smith"):
    with conn.cursor() as cur:
        cur.execute("UPDATE contact SET linkedin_url = %s WHERE id = %s", (url, contact_id))


def _ready_lead(db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    _page_read(db, firm_id)
    _linkedin(db, contact_id)
    lead_id = make_lead(db, firm_id, arming_signal=signal_id)
    return firm_id, contact_id, lead_id


def _almost_lead(db):
    firm_id = make_firm(db, canonical_name="Nearly Law", domain="nearly.example", tier="1A",
                        fee_model="contingency", primary_practice="personal_injury", city="Boise",
                        state="ID")
    contact_id = make_contact(db, firm_id, full_name="Ann Near", title="Owner", role="owner")
    make_contact_email(db, contact_id, email="ann@nearly.example", status="unverified")
    _linkedin(db, contact_id, "https://www.linkedin.com/in/ann-near")
    lead_id = make_lead(db, firm_id, state="RESOLVED", grade=None, band="HOLD")
    return firm_id, contact_id, lead_id


def test_a_lead_with_every_step_done_is_ready(client, db):
    _firm_id, _contact_id, lead_id = _ready_lead(db)

    body = client.get("/api/qualified", params={"only": "all"}).json()
    assert body["items"] and body["items"][0]["ready"], body["items"][0]["checks"]
    body = client.get("/api/qualified").json()
    assert body["counts"] == {"ready": 1, "almost": 0, "checked": 1,
                              "missing_by_check": {k: 0 for k in (
                                  "site_read", "fit", "person", "email", "email_verified",
                                  "linkedin", "journey")},
                              "withheld": []}
    assert [i["id"] for i in body["items"]] == [str(lead_id)]
    row = body["items"][0]
    assert row["ready"] is True and row["missing"] == [] and row["why_now"] is True
    assert [c["key"] for c in row["checks"]] == [
        "site_read", "fit", "person", "email", "email_verified", "linkedin", "journey",
    ]
    assert all(c["ok"] for c in row["checks"])
    by_key = {c["key"]: c for c in row["checks"]}
    assert by_key["person"]["detail"] == "John Smith, Managing Partner"
    assert by_key["email_verified"]["detail"] == "Verified"
    assert by_key["journey"]["detail"].endswith("touches drafted")
    assert row["firm"]["name"] == "Ready Law Firm" and row["contact"]["email_status"] == "valid"


def test_one_or_two_steps_short_is_almost_with_what_is_missing_named(client, db):
    _ready_lead(db)
    _firm, _contact, almost_id = _almost_lead(db)
    make_lead(db, make_firm(db, tier="DQ_SIZE"))  # disqualified: never in the count

    body = client.get("/api/qualified", params={"only": "almost"}).json()
    assert body["counts"]["ready"] == 1 and body["counts"]["almost"] == 1
    assert body["counts"]["checked"] == 2
    assert body["counts"]["missing_by_check"]["site_read"] == 1
    assert body["counts"]["missing_by_check"]["email_verified"] == 1
    assert body["counts"]["missing_by_check"]["journey"] == 1
    assert [i["id"] for i in body["items"]] == [str(almost_id)]
    row = body["items"][0]
    assert row["ready"] is False
    assert row["missing"] == ["Website read", "Address verified", "Journey drafted"]
    by_key = {c["key"]: c for c in row["checks"]}
    assert by_key["person"]["ok"] and by_key["person"]["detail"] == "Ann Near, Owner"
    assert by_key["email"]["ok"] and by_key["email"]["detail"] == "ann@nearly.example"
    assert by_key["email_verified"]["detail"] == "Unverified"
    assert by_key["journey"]["detail"] == "Asked once the rest is done"

    ready_only = client.get("/api/qualified").json()
    assert [i["ready"] for i in ready_only["items"]] == [True]
    everything = client.get("/api/qualified", params={"only": "all", "limit": 1}).json()
    assert len(everything["items"]) == 1 and everything["next_offset"] == 1
    second = client.get("/api/qualified", params={"only": "all", "limit": 1, "offset": 1}).json()
    assert second["items"][0]["id"] == str(almost_id) and second["next_offset"] is None


def test_search_narrows_and_a_journey_that_cannot_render_is_not_ready(client, db):
    firm_id, _contact_id, lead_id = _ready_lead(db)
    with db.cursor() as cur:  # a Hold band: everything else done, not on the email list
        cur.execute("UPDATE lead SET band = 'HOLD' WHERE id = %s", (lead_id,))
    body = client.get("/api/qualified", params={"only": "all", "q": "ready law"}).json()
    assert body["counts"] == {"ready": 0, "almost": 1, "checked": 1,
                              "missing_by_check": {"site_read": 0, "fit": 0, "person": 0,
                                                   "email": 0, "email_verified": 0,
                                                   "linkedin": 0, "journey": 1},
                              "withheld": []}
    row = body["items"][0]
    assert row["missing"] == ["Journey drafted"]
    assert row["checks"][-1]["detail"] == "Not on the email list yet (Hold)"
    assert client.get("/api/qualified", params={"q": "zzz"}).json()["counts"]["checked"] == 0


def test_the_csv_carries_the_ready_leads_only(client, db):
    _ready_lead(db)
    _almost_lead(db)
    resp = client.get("/api/qualified/export.csv")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == ("firm,website,city,state,tier,decision_maker,title,email,email_status,"
                        "linkedin,why_now,fit,urgency,lead")
    assert len(lines) == 2
    assert lines[1].startswith("Ready Law Firm,") and "John Smith" in lines[1]
    assert "Verified" in lines[1] and "linkedin.com/in/john-smith" in lines[1]
    assert "Nearly Law" not in resp.text


def test_a_decision_maker_with_no_address_at_all_is_almost_not_gone(client, db):
    # Site read, fit, a named owner, a LinkedIn profile -- four of six -- and no
    # address on file. The address check was NULL rather than false, the sum
    # of the checks NULL, and the lead dropped out of the panel entirely.
    firm_id = make_firm(db, canonical_name="No Address Law", domain="noaddr.example",
                        tier="1A", fee_model="contingency", primary_practice="personal_injury")
    _page_read(db, firm_id)
    contact_id = make_contact(db, firm_id, full_name="Ned Noaddr", title="Owner", role="owner")
    _linkedin(db, contact_id, "https://www.linkedin.com/in/ned-noaddr")
    lead_id = make_lead(db, firm_id, state="CONTACT_PENDING", grade=None)

    body = client.get("/api/qualified", params={"only": "almost"}).json()
    assert [i["id"] for i in body["items"]] == [str(lead_id)]
    assert body["items"][0]["missing"] == [
        "Address on file", "Address verified", "Journey drafted",
    ]
    assert body["counts"]["missing_by_check"]["email"] == 1


def _hold_back(db, firm_id, lead_id, rule):
    with db.cursor() as cur:
        if rule == "domain":
            cur.execute("SELECT domain FROM firm WHERE id = %s", (firm_id,))
            make_suppression(db, "domain", cur.fetchone()["domain"], reason="customer")
        elif rule == "firm_id":
            make_suppression(db, "firm_id", str(firm_id), reason="dq")
        elif rule == "cooldown":
            cur.execute(
                "UPDATE lead SET cooldown_until = now() + interval '30 days' WHERE id = %s",
                (lead_id,),
            )
        else:
            cur.execute(
                "INSERT INTO firm_track (firm_id, track, set_at) VALUES (%s, %s, now())",
                (firm_id, rule),
            )


@pytest.mark.parametrize(
    "rule,label",
    [
        ("domain", "Do not contact"),  # a paying customer's domain
        ("firm_id", "Do not contact"),
        ("cooldown", "Parked"),
        ("portal", "Existing portal customer"),
        ("displacement", "Competitor's customer"),
    ],
)
def test_the_list_rules_hold_a_ready_lead_off_the_panel_and_the_vendor_sheet(
    client, db, rule, label
):
    # Every step done -- and still not ready: the rule every list applies holds
    # it back, and the vendor sheet reads the same query (it once read none).
    firm_id, _contact_id, lead_id = _ready_lead(db)
    _hold_back(db, firm_id, lead_id, rule)

    body = client.get("/api/qualified", params={"only": "all"}).json()
    assert body["items"] == []
    assert (body["counts"]["ready"], body["counts"]["almost"]) == (0, 0)
    assert body["counts"]["withheld"] == [{"label": label, "count": 1}]
    assert client.get("/api/qualified/export.csv").text.strip().splitlines()[1:] == []


def test_held_back_counts_group_by_rule_most_first(client, db):
    for rule in ("domain", "firm_id", "cooldown"):
        firm_id, _contact_id, lead_id = _ready_lead(db)
        _hold_back(db, firm_id, lead_id, rule)
    _ready_lead(db)  # one lead no rule touches

    counts = client.get("/api/qualified").json()["counts"]
    assert counts["ready"] == 1
    assert counts["withheld"] == [
        {"label": "Do not contact", "count": 2}, {"label": "Parked", "count": 1},
    ]


def test_an_address_on_the_do_not_contact_list_is_not_an_address_on_file(client, db):
    _firm_id, contact_id, _lead_id = _ready_lead(db)
    with db.cursor() as cur:
        cur.execute("SELECT email FROM contact_email WHERE contact_id = %s", (contact_id,))
        bounced = cur.fetchone()["email"]
    make_suppression(db, "email", bounced, reason="bounce")

    body = client.get("/api/qualified", params={"only": "all"}).json()
    row = body["items"][0]
    assert row["ready"] is False
    assert row["missing"] == ["Address on file", "Address verified", "Journey drafted"]
    assert body["counts"]["withheld"] == []  # the firm is fine; that address is not
    assert bounced not in client.get("/api/qualified/export.csv").text
