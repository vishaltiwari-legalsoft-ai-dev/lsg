"""GET /api/overview: the five steps with live numbers, every stage counted,
running jobs, recent runs, the lists. And GET /api/leads?stage=: the work
queue pages by stage in the database."""

from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb

from tests.conftest import make_firm

from .conftest import make_contact, make_contact_email, make_lead

pytestmark = pytest.mark.db


def test_overview_counts_the_pipeline(client, db):
    a = make_firm(db, canonical_name="Alpha Law", domain="alpha.example", tier="1A")
    b = make_firm(db, canonical_name="Beta Law", domain="beta.example", tier="UNCLASSIFIED")
    owner = make_contact(db, a, full_name="Ann Alpha", role="owner", source="site:page")
    make_contact_email(db, owner, email="ann@alpha.example", status="unverified")
    make_lead(db, a, state="QUALIFIED_B", band="NURTURE")
    make_lead(db, b, state="DISCOVERED")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO document (firm_id, url, status_code, content_hash, bytes, word_count, "
            "fetch_ok, page_kind) VALUES (%s, 'https://alpha.example/', 200, 'h', 10, 300, true, "
            "'home')",
            (a,),
        )
        cur.execute(
            "INSERT INTO website_check (firm_id, outcome) VALUES (%s, 'ok'), (%s, 'blocked')",
            (a, b),
        )
        cur.execute(
            "INSERT INTO action_job (id, kind, firm_id, status, steps) VALUES "
            "('11111111-1111-1111-1111-111111111111', 'research', %s, 'running', %s)",
            (a, Jsonb([{"name": "p1_site_map", "status": "done"},
                       {"name": "p2_fetch", "status": "running"}])),
        )

    resp = client.get("/api/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    steps = {s["key"]: s for s in body["steps"]}
    assert [s["number"] for s in body["steps"]] == [1, 2, 3, 4, 5]
    assert steps["lists"]["count"] == 2 and "1 websites verified" in steps["lists"]["detail"]
    assert steps["research"]["count"] == 1 and "1 pages read" in steps["research"]["detail"]
    assert steps["qualify"]["count"] == 1 and "1 tier 1A" in steps["qualify"]["detail"]
    assert steps["people"]["count"] == 1
    assert "1 firms with a decision-maker's address" in steps["people"]["detail"]
    assert steps["outreach"]["count"] == 1  # Alpha: qualified, owner with an address -> ready

    stages = {s["stage"]: s for s in body["stages"]}
    assert stages["ready"]["count"] == 1 and stages["researching"]["count"] == 1
    assert stages["ready"]["label"] == "Ready to reach" and stages["ready"]["help"]
    assert len(body["stages"]) == 14

    assert body["running"][0]["firm_name"] == "Alpha Law"
    assert (body["running"][0]["done_steps"], body["running"][0]["total_steps"]) == (1, 2)
    assert body["lists"]["count"] == 0
    assert "queues" in body["attention"]


def test_work_queue_pages_by_stage(client, db):
    a = make_firm(db, canonical_name="Decide Me", tier="1A")
    b = make_firm(db, canonical_name="Find Someone", tier="1A")
    c = make_firm(db, canonical_name="Reach Me", tier="1A")
    lead_a = make_lead(db, a, state="CLASSIFIED")
    lead_b = make_lead(db, b, state="QUALIFIED_B")
    owner = make_contact(db, c, full_name="Cara Reach", role="owner")
    make_contact_email(db, owner, email="cara@reach.example", status="valid")
    lead_c = make_lead(db, c, state="QUALIFIED_A", contact_id=owner, band="SEQUENCE")

    resp = client.get("/api/leads", params={"stage": "needs_review"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [i["id"] for i in body["items"]] == [str(lead_a)]
    assert body["items"][0]["stage"] == "needs_review"
    assert body["stage_counts"]["needs_review"] == 1
    assert body["stage_counts"]["needs_contact"] == 1
    assert body["stage_counts"]["ready"] == 1

    contact = client.get("/api/leads", params={"stage": "needs_contact"}).json()
    assert [i["id"] for i in contact["items"]] == [str(lead_b)]
    assert contact["items"][0]["next_action"] == "Find a decision-maker"

    ready = client.get("/api/leads", params={"stage": "ready", "band": "SEQUENCE"}).json()
    assert [i["id"] for i in ready["items"]] == [str(lead_c)]
    assert ready["items"][0]["contact"]["email"] == "cara@reach.example"
    none = client.get("/api/leads", params={"stage": "ready", "band": "STRIKE"}).json()
    assert none["items"] == []
    assert client.get("/api/leads", params={"stage": "nope"}).status_code == 400
