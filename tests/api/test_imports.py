"""POST/GET /api/imports, PUT mapping, POST load (sync): a sheet in a
layout the engine has never seen becomes firms, claims and contacts."""

from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.db

SHEET = (
    "Law Firm,Web,Attorney Name,Designation,E-mail,Phone Number,Location,No. of Attorneys,"
    "Practice Areas,Contacted?,Last Touch\n"
    "Doe & Roe,doeroe.com,Jane Doe,Managing Partner,jane@doeroe.com,(404) 555-0100,"
    '"Atlanta, GA",4,Personal Injury,Yes,2026-03-01\n'
    "Doe & Roe,https://www.doeroe.com/,Bob Roe,Office Manager,bob@doeroe.com,,"
    '"Atlanta, GA",4,Personal Injury,No,\n'
    "Harbor Injury Law,harborinjury.com,Ann Lee,Owner,ann@harborinjury.com,,"
    '"Savannah, GA",2,Personal Injury,,\n'
    "Beattie Law Firm,,Beattie Law Firm,,info@beattie.com,,,,,\n"
)


def _upload(client, text=SHEET, name="list.csv", batch_size=50):
    return client.post(
        "/api/imports",
        files={"file": (name, io.BytesIO(text.encode("utf-8")), "text/csv")},
        data={"batch_size": str(batch_size)},
    )


def test_upload_maps_columns_and_reports_what_is_missing(client):
    resp = _upload(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["row_count"] == 4 and body["status"] == "mapped"
    assert body["batches_total"] == 1 and body["batches_loaded"] == 0
    by_col = {c["column"]: c for c in body["columns"]}
    assert by_col["Law Firm"]["field"] == "firm_name"
    assert by_col["Web"]["field"] == "website"
    assert by_col["Attorney Name"]["field"] == "person_name"
    assert by_col["Location"]["field"] == "location"
    assert by_col["No. of Attorneys"]["field"] == "firm_size"
    assert by_col["Contacted?"]["field"] == "contacted_before"
    assert body["missing"] == []
    assert body["reader"] == "rules"  # tests never call the model (conftest pins it)
    # the sheet has no LinkedIn column: research says where it gets one
    assert any(r.startswith("LinkedIn — from") for r in body["research_fills"])
    assert body["health"]["rows"] == 4 and body["health"]["junk_person_names"] == 1
    # firm type is research-fillable, not mandatory; the website is one way to reach a firm
    assert any(f["name"] == "firm_type" and f["mandatory_group"] is None and f["filled_by"]
               for f in body["fields"])
    assert any(f["name"] == "website" and f["mandatory_group"] == "reach" for f in body["fields"])

    listing = client.get("/api/imports").json()
    assert [i["id"] for i in listing["items"]] == [body["id"]]


def test_a_thin_sheet_is_not_incomplete(client):
    """Name and website only: nothing mandatory is missing, and the screen is
    told what research will fill (D-042)."""
    text = "Company,Site\nAcme Legal,acme.law\nBeta Injury,beta.law\nGamma LLP,gamma.com\n"
    body = _upload(client, text=text).json()
    assert body["missing"] == []
    fills = body["research_fills"]
    assert any(r.startswith("Firm size — from") for r in fills)
    assert any(r.startswith("Firm type — from") for r in fills)
    assert any(r.startswith("Contact name — from") for r in fills)
    assert body["health_score"] == 100


def test_missing_mandatory_is_named_and_a_correction_fixes_it(client):
    text = (
        "Company,Handle,Team Size\nAcme Legal,acme-legal,5\nBeta Law,beta-law,3\n"
        "Gamma,gamma-x,2\n"
    )
    body = _upload(client, text=text).json()
    # "Handle" is nobody's synonym and its values are not addresses -> no way to reach the firm
    assert body["missing"] == [
        "A way to reach the firm: a website, an email, or a location (city, state, ZIP or address)"
    ]
    fixed = client.put(
        f"/api/imports/{body['id']}/mapping", json={"overrides": {"Handle": "website"}}
    ).json()
    assert fixed["missing"] == []
    col = next(c for c in fixed["columns"] if c["column"] == "Handle")
    assert col["field"] == "website" and col["reason"] == "set by hand"


def test_load_sync_produces_firms_claims_and_people(client, db):
    body = _upload(client).json()
    resp = client.post(f"/api/imports/{body['id']}/load", params={"sync": "true"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "loaded"

    detail = client.get(f"/api/imports/{body['id']}").json()
    assert detail["batches"][0]["status"] == "loaded"
    assert detail["batches"][0]["rows_loaded"] == 4
    assert any("resolve_identity" in n for n in detail["notes"])

    with db.cursor() as cur:
        cur.execute("SELECT canonical_name, domain FROM firm ORDER BY canonical_name")
        firms = cur.fetchall()
        cur.execute("SELECT full_name, role FROM contact ORDER BY full_name")
        people = cur.fetchall()
        cur.execute("SELECT count(*) AS n FROM lead WHERE state = 'DISCOVERED'")
        leads = cur.fetchone()["n"]
    # Beattie's domain comes from its info@ address (the name is in it, D-017)
    assert [f["domain"] for f in firms if f["domain"]] == [
        "beattie.com", "doeroe.com", "harborinjury.com",
    ], detail["notes"]
    assert [p["full_name"] for p in people] == ["Ann Lee", "Bob Roe", "Jane Doe"]
    assert "Beattie Law Firm" not in [p["full_name"] for p in people]  # not a person
    assert leads >= 2

    # loading twice is a no-op, and the same bytes register as the same import
    again = client.post(f"/api/imports/{body['id']}/load", params={"sync": "true"}).json()
    assert again["status"] == "loaded" and "Already" in again["message"]
    assert _upload(client).json()["id"] == body["id"]


def test_rows_already_known_from_another_sheet_are_skipped(client):
    first = _upload(client).json()
    client.post(f"/api/imports/{first['id']}/load", params={"sync": "true"})
    # last quarter's sheet again, plus one new firm
    overlap = "\n".join(SHEET.splitlines()[:3]) + (
        "\nNew Harbor Law,newharbor.com,Kim Park,Owner,kim@newharbor.com,,"
        '"Macon, GA",3,Personal Injury,,\n'
    )
    second = _upload(client, text=overlap, name="q2.csv").json()
    assert second["id"] != first["id"]
    client.post(f"/api/imports/{second['id']}/load", params={"sync": "true"})
    batch = client.get(f"/api/imports/{second['id']}").json()["batches"][0]
    assert (batch["rows_loaded"], batch["rows_skipped"]) == (1, 2)


def test_bad_uploads_are_refused_with_the_error_shape(client):
    resp = client.post(
        "/api/imports", files={"file": ("notes.pdf", io.BytesIO(b"%PDF"), "application/pdf")}
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"
    empty = _upload(client, text="")
    assert empty.status_code == 422
    missing = client.get("/api/imports/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
