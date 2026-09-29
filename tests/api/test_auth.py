"""Sign-in, onboarding, access and the door (D-067). Google is never
reached: the code exchange is replaced by a fake identity. Every test that
configures sign-in clears the settings cache and restores it after."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lge import auth
from lge.api.routes import auth as auth_routes
from lge.auth.google import Identity
from lge.settings import get_settings

pytestmark = pytest.mark.db

ADMIN = "vishal.tiwari@legalsoft.com"


@pytest.fixture
def configured(monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("LGE_ADMIN_EMAILS", ADMIN)
    monkeypatch.setenv("LGE_ALLOWED_EMAIL_DOMAINS", "legalsoft.com")
    monkeypatch.setenv("LGE_PUBLIC_ORIGIN", "http://testserver")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _sign_in(client, monkeypatch, email: str, name: str = "Test Person", verified: bool = True,
             kind: str = "staff"):
    """Walk the start -> callback flow with Google's answer faked."""
    monkeypatch.setattr(
        auth_routes.google, "exchange_code",
        lambda code, **kw: Identity(sub=f"sub-{email}", email=email, email_verified=verified,
                                    name=name, picture=None),
    )
    start = client.get(f"/api/auth/google/start?next=/leads&kind={kind}", follow_redirects=False)
    assert start.status_code == 302
    assert start.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client-secret" not in start.headers["location"]
    state = client.cookies.get(auth.STATE_COOKIE)
    assert state
    back = client.get(
        f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert back.status_code == 302
    return back


def test_without_configuration_the_door_is_open_and_me_says_off(client):
    me = client.get("/api/auth/me").json()
    assert me["configured"] is False and me["standing"] == "off" and me["user"] is None
    assert client.get("/api/leads").status_code == 200
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 409
    assert client.get("/api/users").status_code == 409


def test_configured_and_signed_out_the_door_is_shut(client, configured):
    assert client.get("/api/health").status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["standing"] == "signed_out" and me["sign_in_path"] == "/api/auth/google/start"
    r = client.get("/api/leads")
    assert r.status_code == 401 and r.json()["error"]["code"] == "signed_out"
    assert client.get("/api/users").status_code == 401


def test_the_admin_address_is_admin_at_once_and_skips_the_form(client, configured, monkeypatch):
    back = _sign_in(client, monkeypatch, ADMIN, name="Vishal Tiwari")
    assert back.headers["location"] == "http://testserver/leads"
    assert client.cookies.get(auth.SESSION_COOKIE)
    me = client.get("/api/auth/me").json()
    assert me["standing"] == "active"
    assert me["user"]["email"] == ADMIN and me["user"]["access"] == "admin"
    assert client.get("/api/leads").status_code == 200
    users = client.get("/api/users").json()
    assert [u["email"] for u in users["items"]] == [ADMIN]
    assert users["items"][0]["admin_by_settings"] is True and users["waiting"] == 0


def test_a_new_person_onboards_then_waits_then_is_let_in(client, configured, monkeypatch):
    _sign_in(client, monkeypatch, "priya@legalsoft.com", name="Priya Nair")
    me = client.get("/api/auth/me").json()
    assert me["standing"] == "needs_onboarding"
    assert [f["name"] for f in me["onboarding_fields"]][:2] == ["full_name", "title"]
    r = client.get("/api/leads")
    assert r.status_code == 403 and r.json()["error"]["code"] == "needs_onboarding"

    bad = client.post("/api/auth/onboarding", json={"answers": {"full_name": "Priya"}})
    assert bad.status_code == 422
    ok = client.post("/api/auth/onboarding", json={"answers": {
        "full_name": "Priya Nair", "title": "SDR", "team": "Sales",
        "purpose": "Work the qualified leads every morning.",
    }})
    assert ok.status_code == 200 and ok.json()["standing"] == "awaiting_access"
    r = client.get("/api/leads")
    assert r.status_code == 403 and r.json()["error"]["code"] == "awaiting_access"
    assert client.get("/api/users").status_code == 403  # not an admin
    priya_id = ok.json()["user"]["id"]
    priya_cookie = client.cookies.get(auth.SESSION_COOKIE)

    # The admin signs in (another browser) and decides.
    client.cookies.clear()
    _sign_in(client, monkeypatch, ADMIN)
    users = client.get("/api/users").json()
    assert users["waiting"] == 1
    waiting = next(u for u in users["items"] if u["email"] == "priya@legalsoft.com")
    assert waiting["standing"] == "awaiting_access"
    assert waiting["onboarding"]["purpose"] == "Work the qualified leads every morning."
    set_ = client.patch(f"/api/users/{priya_id}", json={"access": "viewer"})
    assert set_.status_code == 200
    assert set_.json()["user"]["access"] == "viewer"
    assert set_.json()["user"]["access_set_by"] == ADMIN
    assert [e["kind"] for e in set_.json()["events"]][:1] == ["access_set"]

    # Priya, as a viewer: reads yes, writes no.
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, priya_cookie)
    assert client.get("/api/auth/me").json()["standing"] == "active"
    assert client.get("/api/leads").status_code == 200
    r = client.post("/api/leads/batch", json={"lead_ids": ["x"], "action": "assign"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


def test_the_admin_cannot_lock_themselves_out_and_disabling_ends_sessions(
    client, configured, monkeypatch
):
    _sign_in(client, monkeypatch, "sam@legalsoft.com")
    client.post("/api/auth/onboarding", json={"answers": {
        "full_name": "Sam", "title": "Ops", "team": "Operations", "purpose": "Loads sheets."
    }})
    sam_cookie = client.cookies.get(auth.SESSION_COOKIE)
    sam_id = client.get("/api/auth/me").json()["user"]["id"]
    client.cookies.clear()
    _sign_in(client, monkeypatch, ADMIN)
    admin_id = client.get("/api/auth/me").json()["user"]["id"]
    r = client.patch(f"/api/users/{admin_id}", json={"access": "viewer"})
    assert r.status_code == 409
    assert client.patch(f"/api/users/{sam_id}", json={"access": "operator"}).status_code == 200
    assert client.patch(f"/api/users/{sam_id}", json={"access": "disabled"}).status_code == 200
    assert client.patch("/api/users/not-a-uuid", json={"access": "viewer"}).status_code == 404
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, sam_cookie)
    assert client.get("/api/auth/me").json()["standing"] == "signed_out"  # session closed


def test_other_domains_and_bad_states_are_sent_back_with_a_reason(
    client, configured, monkeypatch
):
    back = _sign_in(client, monkeypatch, "someone@gmail.com")
    assert back.headers["location"] == "http://testserver/?signin=domain"  # home, with why
    assert not client.cookies.get(auth.SESSION_COOKIE)
    back = _sign_in(client, monkeypatch, "x@legalsoft.com", verified=False)
    assert back.headers["location"].endswith("signin=unverified")
    tampered = client.get(
        "/api/auth/google/callback?code=abc&state=not-the-cookie", follow_redirects=False
    )
    assert tampered.headers["location"].endswith("signin=state")
    cancelled = client.get("/api/auth/google/callback?error=access_denied",
                           follow_redirects=False)
    assert cancelled.headers["location"].endswith("signin=cancelled")


def test_sign_out_closes_the_session(client, configured, monkeypatch):
    _sign_in(client, monkeypatch, ADMIN)
    assert client.post("/api/auth/signout").status_code == 204
    assert client.get("/api/auth/me").json()["standing"] == "signed_out"


def test_the_vendor_door_admits_only_the_allow_list(client, configured, monkeypatch):
    # An outside account at the vendor door, not yet listed: sent back, told why.
    back = _sign_in(client, monkeypatch, "dana@sendco.com", kind="vendor")
    assert back.headers["location"] == "http://testserver/?signin=not_invited"
    assert not client.cookies.get(auth.SESSION_COOKIE)
    # The same account at the staff door is simply the wrong domain.
    back = _sign_in(client, monkeypatch, "dana@sendco.com", kind="staff")
    assert back.headers["location"].endswith("signin=domain")

    # The admin lists the vendor's whole domain.
    _sign_in(client, monkeypatch, ADMIN)
    bad = client.post("/api/users/vendors", json={"pattern": "sendco", "vendor_name": "SendCo"})
    assert bad.status_code == 422
    added = client.post("/api/users/vendors",
                        json={"pattern": "@SendCo.com", "vendor_name": "SendCo", "note": "Q4"})
    assert added.status_code == 201 and added.json()["pattern"] == "@sendco.com"
    assert added.json()["added_by"] == ADMIN
    listed = client.get("/api/users/vendors").json()["items"]
    assert [v["vendor_name"] for v in listed] == ["SendCo"]
    client.cookies.clear()

    # Now Dana gets in by the vendor door, as a vendor, and fills the form.
    back = _sign_in(client, monkeypatch, "dana@sendco.com", kind="vendor")
    assert back.headers["location"] == "http://testserver/leads"
    me = client.get("/api/auth/me").json()
    assert me["standing"] == "needs_onboarding"
    assert me["user"]["kind"] == "vendor" and me["user"]["vendor_name"] == "SendCo"
    assert me["vendor_sign_in_path"] == "/api/auth/google/start?kind=vendor"
    client.cookies.clear()

    # A Legal Soft account through the vendor door is still staff.
    _sign_in(client, monkeypatch, "priya@legalsoft.com", kind="vendor")
    assert client.get("/api/auth/me").json()["user"]["kind"] == "staff"
    client.cookies.clear()

    # Removing the entry closes the door again for a new vendor person.
    _sign_in(client, monkeypatch, ADMIN)
    allow_id = added.json()["id"]
    assert client.delete(f"/api/users/vendors/{allow_id}").status_code == 204
    assert client.delete(f"/api/users/vendors/{allow_id}").status_code == 404
    client.cookies.clear()
    back = _sign_in(client, monkeypatch, "sam@sendco.com", kind="vendor")
    assert back.headers["location"].endswith("signin=not_invited")


def test_state_tokens_are_signed_and_expire():
    s = get_settings()
    state = auth.make_state(s, "/qualified", kind="vendor")
    assert auth.check_state(s, state) == ("/qualified", "vendor")
    assert auth.check_state(s, state[:-1] + ("0" if state[-1] != "0" else "1")) is None
    assert auth.check_state(s, "garbage") is None
    # Another site as `next` is never honoured: it lands on Home instead.
    assert auth.check_state(s, auth.make_state(s, "https://evil.example")) == ("/", "staff")
    assert auth.check_state(s, auth.make_state(s, "//evil.example")) == ("/", "staff")
