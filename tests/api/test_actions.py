"""The user can act: research jobs, contact edits, decisions, notes, owner,
batch -- and every lead carries a stage and a next action."""

from __future__ import annotations

from datetime import date

import pytest

from lge.api.routes import actions
from lge.api.stage import stage_of
from tests.conftest import make_firm

from .conftest import make_contact, make_lead

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,kw,expected",
    [
        ("DISCOVERED", {}, ("researching", "Research the site")),
        ("NO_WEB", {}, ("no_website", "Find the firm's website, then research")),
        ("CLASSIFIED", {}, ("needs_review", "Review the record; qualify or disqualify")),
        ("CONTACT_PENDING", {},
         ("needs_contact", "Find a decision-maker (owner or administrator)")),
        ("QUALIFIED_B", {"contact_name": "Jane Doe"},
         ("needs_contact", "Find an email for Jane Doe")),
        ("QUALIFIED_A", {"contact_name": "Jane Doe", "has_email": True},
         ("ready", "Send touch 1 when a signal arms it, or hand off now")),
        ("ARMED", {}, ("ready", "Send touch 1")),
        ("QUALIFIED_A", {"cooldown_until": date(2999, 1, 1)},
         ("parked", "Parked until 2999-01-01")),
        ("ENGAGED", {}, ("in_outreach", "Wait for the next touch or a reply")),
        ("RESPONDED", {}, ("replied", "Read the reply; hand off, park, or opt out")),
        ("HANDOFF", {}, ("handed_off", "Sales owns it -- record won or lost")),
        ("DISQUALIFIED", {}, ("disqualified", "Reopen if the reason was wrong")),
        ("SUPPRESSED", {}, ("do_not_contact", "Nothing -- the firm opted out or bounced")),
    ],
)
def test_stage_of(state, kw, expected):
    assert stage_of(state, **kw) == expected


def test_every_lead_row_carries_stage_and_next_action(client, db):
    firm_id = make_firm(db, canonical_name="Stage Firm")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")
    body = client.get(f"/api/leads/{lead_id}").json()
    assert body["stage"] == "needs_review"
    assert body["stage_display"] == "Needs a decision"
    assert body["next_action"].startswith("Review the record")
    assert body["owner"] is None
    assert body["notes"] == [] and body["job"] is None


# ---------------------------------------------------------------------------
# Decisions, notes, owner
# ---------------------------------------------------------------------------


def _state(db, lead_id):
    with db.cursor() as cur:
        cur.execute("SELECT state, grade, cooldown_until, close_reason, owner FROM lead "
                    "WHERE id = %s", (lead_id,))
        return cur.fetchone()


def test_disqualify_reopen_and_qualify_move_the_lead_with_notes(client, db):
    firm_id = make_firm(db, canonical_name="Decide Firm")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")

    resp = client.post(f"/api/leads/{lead_id}/decision",
                       json={"action": "disqualify", "reason": "government agency"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Disqualified."
    assert resp.json()["lead"]["stage"] == "disqualified"
    row = _state(db, lead_id)
    assert row["state"] == "DISQUALIFIED" and row["close_reason"] == "user -- government agency"
    assert resp.json()["lead"]["notes"][0]["text"] == "Disqualified -- government agency"
    # the state event names the actor
    with db.cursor() as cur:
        cur.execute("SELECT trigger, actor, to_state FROM lead_state_event WHERE lead_id = %s "
                    "ORDER BY id DESC LIMIT 1", (lead_id,))
        ev = cur.fetchone()
    assert (ev["trigger"], ev["actor"], ev["to_state"]) == ("ui_decision", "ui", "DISQUALIFIED")

    resp = client.post(f"/api/leads/{lead_id}/decision", json={"action": "reopen"})
    assert resp.status_code == 200 and _state(db, lead_id)["state"] == "CLASSIFIED"
    assert _state(db, lead_id)["close_reason"] is None

    resp = client.post(f"/api/leads/{lead_id}/decision", json={"action": "qualify"})
    assert resp.status_code == 200
    assert "grade B" in resp.json()["message"]
    assert _state(db, lead_id)["state"] == "QUALIFIED_B"
    assert _state(db, lead_id)["grade"] == "B"

    again = client.post(f"/api/leads/{lead_id}/decision", json={"action": "qualify"})
    assert again.status_code == 409


def test_hold_parks_without_changing_state_and_needs_until(client, db):
    firm_id = make_firm(db, canonical_name="Hold Firm")
    lead_id = make_lead(db, firm_id, state="QUALIFIED_B")
    resp = client.post(f"/api/leads/{lead_id}/decision", json={"action": "hold"})
    assert resp.status_code == 400
    resp = client.post(f"/api/leads/{lead_id}/decision",
                       json={"action": "hold", "until": "2999-03-01", "reason": "busy season"})
    assert resp.status_code == 200
    assert resp.json()["lead"]["stage"] == "parked"
    assert _state(db, lead_id)["state"] == "QUALIFIED_B"


def test_handoff_from_a_qualified_lead_and_refused_from_a_researching_one(client, db):
    firm_id = make_firm(db, canonical_name="Hand Firm")
    lead_id = make_lead(db, firm_id, state="QUALIFIED_A")
    resp = client.post(f"/api/leads/{lead_id}/decision", json={"action": "handoff"})
    assert resp.status_code == 200 and resp.json()["lead"]["stage"] == "handed_off"

    other = make_lead(db, make_firm(db, canonical_name="Early Firm"), state="PROFILING")
    resp = client.post(f"/api/leads/{other}/decision", json={"action": "handoff"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_allowed"


def test_notes_and_owner(client, db):
    firm_id = make_firm(db, canonical_name="Note Firm")
    lead_id = make_lead(db, firm_id, state="CLASSIFIED")
    resp = client.post(f"/api/leads/{lead_id}/notes", json={"text": "Spoke to reception."})
    assert resp.status_code == 201
    assert resp.json()["notes"][0]["text"] == "Spoke to reception."
    resp = client.put(f"/api/leads/{lead_id}/owner", json={"owner": "Vishal"})
    assert resp.status_code == 200 and resp.json()["owner"] == "Vishal"
    assert resp.json()["notes"][0]["text"] == "Assigned to Vishal"
    assert client.post(f"/api/leads/{lead_id}/notes", json={"text": "  "}).status_code == 400


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def test_add_edit_remove_and_choose_a_contact(client, db):
    firm_id = make_firm(db, canonical_name="People Firm")
    lead_id = make_lead(db, firm_id, state="CONTACT_PENDING")

    resp = client.post(f"/api/firms/{firm_id}/contacts", json={
        "full_name": "  Priya   Raman ", "title": "Office Manager", "role": "admin",
        "email": "PRaman@PeopleFirm.com", "phone": "(404) 555-0142",
    })
    assert resp.status_code == 201, resp.text
    contact = resp.json()["contact"]
    assert contact["full_name"] == "Priya Raman"
    assert contact["email"] == "praman@peoplefirm.com"
    assert contact["email_status"] == "unverified"
    assert contact["phone"] == "+14045550142"
    assert contact["source_label"] != "" and contact["role"] == "admin"

    resp = client.patch(
        f"/api/contacts/{contact['id']}",
        json={"title": "Firm Administrator", "linkedin_url": "https://www.linkedin.com/in/praman/"},
    )
    assert resp.status_code == 200
    assert resp.json()["contact"]["title"] == "Firm Administrator"
    assert resp.json()["contact"]["linkedin_url"] == "https://www.linkedin.com/in/praman/"

    resp = client.put(f"/api/leads/{lead_id}/contact", json={"contact_id": contact["id"]})
    assert resp.status_code == 200
    assert resp.json()["contact"]["full_name"] == "Priya Raman"
    assert resp.json()["stage"] == "needs_contact"  # CONTACT_PENDING still; the engine resolves

    wrong = str(make_contact(db, firm_id, full_name="Bronx Locations", role="unknown"))
    resp = client.post(f"/api/contacts/{wrong}/remove", json={"reason": "not a person"})
    assert resp.status_code == 200
    names = [c["full_name"] for c in client.get(f"/api/leads/{lead_id}").json()["contacts"]]
    assert "Bronx Locations" not in names and "Priya Raman" in names

    resp = client.put(f"/api/leads/{lead_id}/contact", json={"contact_id": wrong})
    assert resp.status_code == 400


def test_contact_at_another_firm_cannot_be_the_primary(client, db):
    firm_a = make_firm(db, canonical_name="A Firm")
    firm_b = make_firm(db, canonical_name="B Firm")
    lead_id = make_lead(db, firm_a, state="CLASSIFIED")
    other = str(make_contact(db, firm_b, full_name="Someone Else"))
    resp = client.put(f"/api/leads/{lead_id}/contact", json={"contact_id": other})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Research jobs
# ---------------------------------------------------------------------------


def test_research_creates_a_job_with_the_flow_steps(client, db, monkeypatch):
    started: list[str] = []
    # the launch commits and starts a thread: neither belongs under a test transaction
    monkeypatch.setattr(actions, "_launch_jobs", lambda conn, ids: started.extend(ids))
    firm_id = make_firm(db, canonical_name="Crawl Firm", domain="crawl.example")
    lead_id = make_lead(db, firm_id, state="DISCOVERED")

    resp = client.post(f"/api/firms/{firm_id}/research", json={"scope": "full"})
    assert resp.status_code == 202, resp.text
    job = resp.json()["job"]
    assert job["status"] == "queued" and job["kind"] == "research"
    # the flow's recipe, not a list of the button's own (D-054)
    assert [s["name"] for s in job["steps"]] == list(actions.research_steps("full"))
    assert [s["name"] for s in job["steps"]][:3] == ["p1_site_map", "p2_fetch", "p3_render"]
    assert {"p8_llm", "r4_verify", "classify"} <= {s["name"] for s in job["steps"]}
    assert all(s["status"] == "pending" for s in job["steps"])
    labels = {s["name"]: s["label"] for s in job["steps"]}
    assert labels["classify"] == "Move the lead forward"
    assert all(label != name for name, label in labels.items())
    assert started == [job["id"]]

    # asking again while it is queued returns the same job
    again = client.post(f"/api/firms/{firm_id}/research", json={"scope": "full"}).json()["job"]
    assert again["id"] == job["id"]
    assert client.get(f"/api/jobs/{job['id']}").json()["job"]["id"] == job["id"]
    assert client.get(f"/api/leads/{lead_id}").json()["job"]["id"] == job["id"]
    assert client.get(f"/api/firms/{firm_id}/jobs").json()["items"][0]["id"] == job["id"]

    contacts_only = client.post(
        f"/api/firms/{make_firm(db, canonical_name='C Firm', domain='c.example')}/research",
        json={"scope": "contacts"},
    ).json()["job"]
    assert contacts_only["kind"] == "find_contacts"
    assert contacts_only["steps"][0]["name"] == "px_site_facts"
    assert [s["name"] for s in contacts_only["steps"]] == list(actions.research_steps("contacts"))


def test_research_refuses_a_firm_without_a_website(client, db):
    firm_id = make_firm(db, canonical_name="No Site", domain=None)
    resp = client.post(f"/api/firms/{firm_id}/research", json={"scope": "full"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no_domain"


def test_run_job_records_each_step(db, monkeypatch, tmp_path):
    # The real components run with the firm's id file; here two stand-ins.
    from lge.registry import ComponentSpec, RunResult

    firm_id = make_firm(db, canonical_name="Job Firm", domain="job.example")
    job = actions._create_job(db, firm_id, None, "find_contacts", ("ok_step", "bad_step"))

    def ok(ctx, **opts):
        assert opts["live"] == "1" and opts["firm_ids_file"].endswith(f"{job.id}.txt")
        return RunResult(processed=1)

    def bad(ctx, **opts):
        raise RuntimeError("boom")

    fake = {
        "ok_step": ComponentSpec(name="ok_step", plane="R", description="", fn=ok),
        "bad_step": ComponentSpec(name="bad_step", plane="R", description="", fn=bad),
    }
    monkeypatch.setattr(actions, "registered_components", lambda: fake)
    monkeypatch.setattr(actions, "discover", lambda: None)
    monkeypatch.setattr(actions, "JOB_DIR", tmp_path)

    actions.run_job(job.id, conn=db, status_conn=db)
    with db.cursor() as cur:
        cur.execute("SELECT status, steps, error FROM action_job WHERE id = %s", (job.id,))
        row = cur.fetchone()
    assert row["status"] == "failed"
    assert [s["status"] for s in row["steps"]] == ["done", "failed"]
    assert row["steps"][0]["note"].startswith("processed=1")
    assert "boom" in row["steps"][1]["note"]


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def test_batch_applies_per_lead_and_reports_each(client, db, monkeypatch):
    monkeypatch.setattr(actions, "_launch_jobs", lambda conn, ids: None)
    firm_a = make_firm(db, canonical_name="Batch A", domain="a.example")
    firm_b = make_firm(db, canonical_name="Batch B", domain="b.example")
    a = str(make_lead(db, firm_a, state="CLASSIFIED"))
    b = str(make_lead(db, firm_b, state="PROFILING"))
    missing = "00000000-0000-0000-0000-000000000000"

    resp = client.post("/api/leads/batch", json={
        "lead_ids": [a, b, missing], "action": "disqualify", "reason": "out of area",
    })
    assert resp.status_code == 200
    results = {r["lead_id"]: r for r in resp.json()["results"]}
    assert results[a]["ok"] is True and results[b]["ok"] is True
    assert results[missing]["ok"] is False
    assert _state(db, a)["state"] == "DISQUALIFIED" and _state(db, b)["state"] == "DISQUALIFIED"

    resp = client.post("/api/leads/batch", json={"lead_ids": [a, b], "action": "assign",
                                                 "owner": "Vishal"})
    assert all(r["ok"] for r in resp.json()["results"])
    assert _state(db, a)["owner"] == "Vishal"

    resp = client.post("/api/leads/batch", json={"lead_ids": [a, b], "action": "research"})
    jobs = [r["job_id"] for r in resp.json()["results"]]
    assert all(jobs) and len(set(jobs)) == 2

    empty = client.post("/api/leads/batch", json={"lead_ids": [], "action": "assign"})
    assert empty.status_code == 400


# ---------------------------------------------------------------------------
# Job launch and restart sweep
# ---------------------------------------------------------------------------


def test_launch_jobs_commits_first_then_runs_each_on_its_own_thread(monkeypatch):
    ran: list[str] = []
    events: list[str] = []

    class _Conn:
        def commit(self):
            events.append("commit")

    monkeypatch.setattr(actions, "_run_job_in_background", lambda job_id: ran.append(job_id))
    assert actions._launch_jobs(_Conn(), []) == [] and events == []  # nothing to start
    threads = actions._launch_jobs(_Conn(), ["a", "b"])
    for thread in threads:
        thread.join(timeout=5)
    assert events == ["commit"]  # once, before any worker looks for its row
    assert sorted(ran) == ["a", "b"]


def test_sweep_fails_jobs_left_queued_or_running_by_a_dead_process(db):
    firm_id = make_firm(db, canonical_name="Orphan Firm", domain="orphan.example")
    full, contacts = actions.research_steps("full"), actions.research_steps("contacts")
    queued = actions._create_job(db, firm_id, None, "research", full)
    running = actions._create_job(db, firm_id, None, "find_contacts", contacts)
    actions._set_job(running.id, {"status": "running"}, db)
    done = actions._create_job(db, firm_id, None, "find_contacts", contacts)
    actions._set_job(done.id, {"status": "done"}, db)

    assert actions.sweep_orphaned_jobs(db) == 2
    assert actions._fetch_job(db, queued.id).status == "failed"
    assert "restarted" in actions._fetch_job(db, running.id).error
    assert actions._fetch_job(db, done.id).status == "done"
