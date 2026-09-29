"""The "broken" findings of the 28 Sep 2026 readiness audit, pinned: a
malformed id is 404 on every id route (never 500), a cursor from nowhere is
400 (never a silent restart at page one), a hand-check decision needs a real
firm and attribute, a batch reports a refusal in plain words and one lead's
failure does not undo another's, and an import left "loading" by a restart
is swept at startup."""

from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb

from lge.api.routes.imports import sweep_orphaned_imports
from tests.conftest import make_firm
from tests.planes.p._p_helpers import make_lead

pytestmark = pytest.mark.db

BAD_IDS = ("not-a-uuid", "12345", "00000000-0000-0000-0000-00000000000")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_malformed_id_is_not_found_on_every_id_route(client, bad):
    gets = [
        f"/api/leads/{bad}", f"/api/leads/{bad}/drafts", f"/api/firms/{bad}",
        f"/api/firms/{bad}/jobs", f"/api/jobs/{bad}", f"/api/imports/{bad}",
    ]
    for path in gets:
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "not_found", path
    posts = [
        ("post", f"/api/leads/{bad}/notes", {"text": "x"}),
        ("put", f"/api/leads/{bad}/owner", {"owner": "x"}),
        ("post", f"/api/leads/{bad}/outcome", {"action": "replied"}),
        ("post", f"/api/firms/{bad}/research", {"scope": "full"}),
        ("post", f"/api/firms/{bad}/contacts", {"full_name": "Test Person"}),
        ("patch", f"/api/contacts/{bad}", {"title": "x"}),
        ("post", f"/api/contacts/{bad}/remove", {"reason": "x"}),
        ("put", f"/api/imports/{bad}/mapping", {"overrides": {}}),
        ("post", f"/api/imports/{bad}/load", None),
        ("post", f"/api/handcheck/{bad}/fee_model", {"correct": True}),
    ]
    for method, path, body in posts:
        r = getattr(client, method)(path, json=body) if body is not None else getattr(
            client, method
        )(path)
        assert r.status_code == 404, (method, path, r.text)


def test_a_bad_cursor_is_refused_not_ignored(client):
    for path in ("/api/leads?cursor=garbage", "/api/leads?view=UNSCORED&cursor=garbage",
                 "/api/leads?stage=researching&cursor=garbage", "/api/firms?cursor=garbage",
                 "/api/leads?cursor=WyJ4IiwxLDIsMyw0XQ"):  # a 5-part cursor from nowhere
        r = client.get(path)
        assert r.status_code == 400, path
        assert r.json()["error"]["code"] == "bad_cursor", path


def test_a_hand_check_decision_needs_a_real_firm_and_attribute(client, db):
    firm_id = make_firm(db)
    # a real firm, an attribute it has no claim for
    r = client.post(f"/api/handcheck/{firm_id}/nothing_here", json={"correct": True})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, evidence, "
            "observed_at) VALUES (%s, 'fee_model', %s, 'test', 0.9, 'x', now())",
            (firm_id, Jsonb("contingency")),
        )
    r = client.post(f"/api/handcheck/{firm_id}/fee_model", json={"correct": True})
    assert r.status_code == 204
    # a well-formed id that is no firm
    r = client.post("/api/handcheck/00000000-0000-0000-0000-000000000000/fee_model",
                    json={"correct": True})
    assert r.status_code == 404


def test_a_batch_refusal_is_plain_words_and_does_not_undo_the_others(client, db):
    no_site = make_firm(db, domain=None)
    lead_no_site = make_lead(db, no_site)
    with_site = make_firm(db, domain="withsite.example")
    lead_with_site = make_lead(db, with_site)

    r = client.post("/api/leads/batch", json={
        "lead_ids": [str(lead_no_site), str(lead_with_site), "not-a-uuid"],
        "action": "assign", "owner": "Dana",
    })
    assert r.status_code == 200
    by_id = {x["lead_id"]: x for x in r.json()["results"]}
    assert by_id[str(lead_no_site)]["ok"] and by_id[str(lead_with_site)]["ok"]
    assert by_id["not-a-uuid"] == {"lead_id": "not-a-uuid", "ok": False,
                                   "message": "Lead not found.", "job_id": None}

    r = client.post("/api/leads/batch", json={
        "lead_ids": [str(lead_no_site)], "action": "research",
    })
    row = r.json()["results"][0]
    assert row["ok"] is False
    assert row["message"] == "This firm has no website on record."
    assert "{" not in row["message"] and "409" not in row["message"]


def test_an_import_left_loading_by_a_restart_is_swept(client, db):
    sheet = b"Company,Website\nDoe Law,doe.law\n"
    up = client.post("/api/imports", files={"file": ("list.csv", sheet)})
    assert up.status_code == 201, up.text
    import_id = up.json()["id"]
    with db.cursor() as cur:
        cur.execute("UPDATE import_file SET status = 'loading' WHERE id = %s", (import_id,))
    assert sweep_orphaned_imports(db) == 1
    detail = client.get(f"/api/imports/{import_id}").json()
    assert detail["status"] == "failed"
    assert any("interrupted" in n for n in detail["notes"])
    assert sweep_orphaned_imports(db) == 0
