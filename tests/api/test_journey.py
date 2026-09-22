"""The Email journey screen's API (D-057): the journey, its edits, the
example firm -- and edits reaching every place an email is rendered."""

from __future__ import annotations

import pytest

from lge.export.list import classify_open_scored_leads
from lge.journey.render import load_template
from tests.conftest import make_firm

from .conftest import make_lead, sequence_ready_firm

pytestmark = pytest.mark.db


def _ready_lead(db) -> str:
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm)
    return str(make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id,
                         band="SEQUENCE"))


def _template(body: dict, template_id: str) -> dict:
    return next(t for s in body["steps"] for t in s["templates"] if t["id"] == template_id)


def test_the_journey_is_nine_emails_on_their_original_days(client):
    body = client.get("/api/journey").json()
    assert [s["step"] for s in body["steps"]] == list(range(1, 10))
    assert [s["day"] for s in body["steps"]] == [0, 3, 7, 10, 14, 18, 21, 25, 28]
    assert all(s["day"] == s["original_day"] for s in body["steps"])
    assert sum(len(s["templates"]) for s in body["steps"]) == 30
    assert all(t["edited_at"] is None for s in body["steps"] for t in s["templates"])
    tracks = {t["band"]: t for t in body["tracks"]}
    assert tracks["SEQUENCE"]["steps"] == list(range(1, 10))
    assert (tracks["SEQUENCE"]["pace"], tracks["NURTURE"]["pace"]) == (1, 2)
    assert tracks["NURTURE"]["steps"] == [1, 3, 9]
    assert "Day 1 to Day 29" in tracks["SEQUENCE"]["description"]
    assert "Day 1, Day 15 and Day 57" in tracks["NURTURE"]["description"]
    assert tracks["STRIKE"]["steps"] == [] and tracks["HOLD"]["steps"] == []
    assert "replace" in body["banned_phrases"]
    assert "Legal Soft" in body["signature"]
    assert "a postal address, which US law requires" in body["sender_missing"]
    paragraph = _template(body, "1-paragraph-pi")
    assert paragraph["kind"] == "paragraph" and paragraph["subject"] is None


def test_a_new_wording_reaches_the_lead_and_the_email_list_then_restores(client, db):
    lead_id = _ready_lead(db)
    original_subject, original_body = load_template("touch3/contingency.md")

    resp = client.put("/api/journey/templates/3-contingency", json={
        "subject": "what the hours cost, {first_name}",
        "body": "{first_name} — on contingency the hours are yours to carry.\r\n",
    })
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["subject"] == "what the hours cost, {first_name}"
    assert saved["body"] == "{first_name} — on contingency the hours are yours to carry."
    assert saved["original_subject"] == original_subject
    assert saved["edited_at"] is not None

    touch3 = next(t for t in client.get(f"/api/leads/{lead_id}/drafts").json()["touches"]
                  if t["step"] == 3)
    assert touch3["subject"] == "what the hours cost, John"
    assert touch3["templates"] == ["3-contingency"]
    # The email list renders through the same edits (build_list, the vendor sheet).
    listed = next(cl for cl in classify_open_scored_leads(db).leads if cl.lead_id == lead_id)
    assert listed.journey_result.touches[2].subject == "what the hours cost, John"

    restored = client.delete("/api/journey/templates/3-contingency").json()
    assert (restored["subject"], restored["body"]) == (original_subject, original_body)
    assert restored["edited_at"] is None
    touch3 = client.get(f"/api/leads/{lead_id}/drafts").json()["touches"][2]
    assert touch3["subject"] == original_subject


def test_saving_the_original_back_is_a_restore(client):
    subject, body = load_template("touch7.md")
    client.put("/api/journey/templates/7", json={"subject": "right person, still?", "body": body})
    resp = client.put("/api/journey/templates/7", json={"subject": subject, "body": body})
    assert resp.json()["edited_at"] is None


@pytest.mark.parametrize(
    ("template_id", "payload", "words"),
    [
        ("7", {"subject": "right person?", "body": "We replace your paralegal."}, "“replace”"),
        ("7", {"subject": "right person?", "body": "Hi {city}."}, "{city} can't be filled in"),
        ("1-open-role", {"subject": "your {role} opening", "body": "No paragraph."},
         "Keep {middle_paragraph}"),
        ("7", {"subject": "", "body": "{first_name} — hi."}, "Add a subject line."),
    ],
)
def test_a_wording_that_breaks_a_rule_is_refused_and_nothing_changes(
    client, template_id, payload, words
):
    resp = client.put(f"/api/journey/templates/{template_id}", json=payload)
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "invalid_copy"
    assert words in error["message"]
    assert _template(client.get("/api/journey").json(), template_id)["edited_at"] is None


def test_a_paragraph_is_edited_without_a_subject(client, db):
    lead_id = _ready_lead(db)
    resp = client.put("/api/journey/templates/1-paragraph-pi", json={
        "subject": "ignored", "body": "One person, your cases, inside {cms}.",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["subject"] is None
    touch1 = client.get(f"/api/leads/{lead_id}/drafts").json()["touches"][0]
    assert "One person, your cases, inside Filevine." in touch1["body"]
    assert touch1["templates"] == ["1-open-role", "1-paragraph-pi"]


def test_an_unknown_template_is_not_found(client):
    assert client.put("/api/journey/templates/nope", json={"body": "x"}).status_code == 404
    assert client.delete("/api/journey/templates/nope").status_code == 404


def test_new_days_reach_the_lead_and_the_tracks_then_restore(client, db):
    lead_id = _ready_lead(db)
    days = [{"step": s, "day": s - 1} for s in range(2, 10)]  # Day 1, 2, 3 ... 9
    resp = client.put("/api/journey/days", json={"days": days})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [s["day"] for s in body["steps"]] == list(range(0, 9))
    assert "Day 1 to Day 9" in body["tracks"][0]["description"]

    drafts = client.get(f"/api/leads/{lead_id}/drafts").json()
    assert [t["day"] for t in drafts["touches"] if not t["skipped_reason"]] == list(range(0, 9))

    # Leaving an email out puts it back on its original day.
    body = client.put("/api/journey/days", json={"days": [{"step": 2, "day": 1}]}).json()
    assert [s["day"] for s in body["steps"]] == [0, 1, 7, 10, 14, 18, 21, 25, 28]

    body = client.delete("/api/journey/days").json()
    assert [s["day"] for s in body["steps"]] == [0, 3, 7, 10, 14, 18, 21, 25, 28]


@pytest.mark.parametrize(
    ("days", "words"),
    [
        ([{"step": 3, "day": 3}], "Email 3 must come after email 2, which goes on Day 4."),
        ([{"step": 1, "day": 2}], "Email 1 always goes on Day 1."),
        ([{"step": 9, "day": 200}], "Email 9 must go between Day 2 and Day 91."),
        ([{"step": 2, "day": 2}, {"step": 2, "day": 3}], "Each email can have one day."),
    ],
)
def test_days_out_of_order_are_refused(client, days, words):
    resp = client.put("/api/journey/days", json={"days": days})
    assert resp.status_code == 422
    assert words in resp.json()["error"]["message"]
    assert [s["day"] for s in client.get("/api/journey").json()["steps"]][:3] == [0, 3, 7]


def test_the_example_firm_is_rendered_by_the_engine(client):
    body = client.get("/api/journey/example").json()
    assert body["firm"] == "An invented personal injury firm in Atlanta, on Filevine"
    assert body["drafts"]["excluded_display"] is None
    touches = body["drafts"]["touches"]
    assert [t["step"] for t in touches] == list(range(1, 10))
    assert touches[0]["subject"] == "Your paralegal opening, and a faster way to fill it"
    assert touches[0]["templates"] == ["1-open-role", "1-paragraph-pi"]
    assert touches[0]["body"].startswith("Hi Dana,")
    # every email is signed, and says how to stop (D-060)
    assert touches[0]["body"].rstrip().endswith(
        "Reply with the word stop and I won't write to you again."
    )


def test_the_example_shows_the_nurture_pace_and_the_tier_copy(client):
    body = client.get("/api/journey/example", params={
        "tier": "4_NONBILLABLE", "pain": "reviews", "band": "NURTURE",
    }).json()
    touches = body["drafts"]["touches"]
    assert [(t["step"], t["day"]) for t in touches] == [(1, 0), (3, 14), (9, 56)]
    assert touches[0]["templates"] == ["1-hourly"]
    assert touches[1]["templates"] == ["3-hourly"]


def test_the_example_says_in_words_why_a_firm_gets_nothing(client):
    body = client.get("/api/journey/example", params={
        "pain": "new_system", "system": "false",
    }).json()
    assert body["drafts"]["touches"] == []
    assert body["drafts"]["excluded_reason"] == "unresolved_token:cms"
    assert body["drafts"]["excluded_display"] == (
        "An email needs the case system, and it is not known"
    )


def test_a_lead_without_emails_says_why_in_words(client, db):
    firm_id, contact_id, signal_id = sequence_ready_firm(db, make_firm, fee_model="mixed")
    lead_id = make_lead(db, firm_id, contact_id=contact_id, arming_signal=signal_id,
                        band="SEQUENCE")
    body = client.get(f"/api/leads/{lead_id}/drafts").json()
    assert body["excluded_reason"] == "fee_model_unresolved:mixed"
    assert body["excluded_display"] == "Fee model unknown, so the third email can't be written"


def test_the_example_reflects_edits(client):
    client.put("/api/journey/templates/9", json={
        "subject": "closing the loop, {first_name}", "body": "{first_name} — I'll stop here.",
    })
    touch9 = client.get("/api/journey/example").json()["drafts"]["touches"][-1]
    assert touch9["subject"] == "closing the loop, Dana"
