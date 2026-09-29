"""Sign-in and the signed-in person (D-067).

  GET  /api/auth/me                 who is asking and what they may do
  GET  /api/auth/google/start       -> Google's sign-in page
  GET  /api/auth/google/callback    <- Google; opens the session, back to the screens
  POST /api/auth/onboarding         the form a new person fills once
  POST /api/auth/signout            closes this session

The callback never answers with JSON: it lands the browser back on the
screens, with `?signin=<reason>` when something went wrong, so the screen
can say so in words.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from lge import auth
from lge.api.deps import ConnDep
from lge.api.errors import api_error
from lge.api.gate import CurrentUser
from lge.api.models import AuthStatus, AuthUser, OnboardingField, OnboardingRequest
from lge.auth import google
from lge.settings import get_settings

logger = logging.getLogger("lge.api.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

SIGN_IN_PATH = "/api/auth/google/start"


def _redirect_uri() -> str:
    return f"{get_settings().public_origin}/api/auth/google/callback"


def _secure() -> bool:
    return get_settings().public_origin.startswith("https://")


def auth_user(user: auth.User) -> AuthUser:
    return AuthUser(
        id=user.id, email=user.email, name=user.name, picture_url=user.picture_url,
        access=user.access, standing=user.standing, onboarded_at=user.onboarded_at,
        onboarding=user.onboarding, created_at=user.created_at,
        last_sign_in_at=user.last_sign_in_at, access_set_by=user.access_set_by,
        access_set_at=user.access_set_at, kind=user.kind, vendor_name=user.vendor_name,
    )


def status_for(user: auth.User | None) -> AuthStatus:
    settings = get_settings()
    configured = settings.sign_in_configured()
    if not configured:
        standing = "off"
    elif user is None:
        standing = "signed_out"
    else:
        standing = user.standing
    return AuthStatus(
        configured=configured, standing=standing,
        user=auth_user(user) if user else None,
        sign_in_path=SIGN_IN_PATH,
        vendor_sign_in_path=f"{SIGN_IN_PATH}?kind=vendor",
        onboarding_fields=[OnboardingField(**f) for f in auth.ONBOARDING_FIELDS],
        allowed_domains=list(settings.allowed_email_domains),
    )


@router.get("/me", response_model=AuthStatus)
def get_me(user: CurrentUser) -> AuthStatus:
    return status_for(user)


@router.get("/google/start")
def google_start(next: str = "/", kind: str = "staff") -> Response:  # noqa: A002 -- the screens' name
    """Two doors (D-068): `kind=staff` (the default) is a Legal Soft account
    and Google is asked to show only that domain; `kind=vendor` is a person
    from an email vendor's team, any Google account, admitted only when the
    allow list names them."""
    settings = get_settings()
    if not settings.sign_in_configured():
        raise api_error(
            409, "sign_in_off", "Sign-in is not configured on this engine.",
            "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env and restart.",
        )
    kind = kind if kind in auth.KINDS else "staff"
    state = auth.make_state(settings, next, kind=kind)
    hd = (
        settings.allowed_email_domains[0]
        if kind == "staff" and len(settings.allowed_email_domains) == 1 else None
    )
    url = google.authorize_url(settings.google_oauth_client_id, _redirect_uri(), state, hd=hd)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        auth.STATE_COOKIE, state, max_age=auth.STATE_TTL_S, httponly=True, samesite="lax",
        secure=_secure(), path="/api/auth",
    )
    return resp


def _back(reason: str | None, next_path: str = "/") -> RedirectResponse:
    origin = get_settings().public_origin
    if reason:
        sep = "&" if "?" in next_path else "?"
        next_path = f"{next_path}{sep}{urlencode({'signin': reason})}"
    resp = RedirectResponse(f"{origin}{next_path}", status_code=302)
    resp.delete_cookie(auth.STATE_COOKIE, path="/api/auth")
    return resp


@router.get("/google/callback")
def google_callback(
    request: Request, conn: ConnDep, code: str | None = None, state: str | None = None,
    error: str | None = None,
) -> Response:
    settings = get_settings()
    if not settings.sign_in_configured():
        return _back("off")
    if error:
        return _back("cancelled")
    cookie_state = request.cookies.get(auth.STATE_COOKIE)
    if not state or not cookie_state or state != cookie_state:
        return _back("state")
    checked = auth.check_state(settings, state)
    if checked is None:
        return _back("expired")
    next_path, kind = checked
    if not code:
        return _back("cancelled")
    try:
        identity = google.exchange_code(
            code, client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret, redirect_uri=_redirect_uri(),
        )
    except google.SignInError as exc:
        logger.warning("sign-in failed: %s", exc)
        return _back("google")
    if not identity.email_verified:
        return _back("unverified")
    # Which door admits this address (D-068): a Legal Soft account walks in
    # by either door; any other account only by the vendor door, and only
    # when the allow list names it or its domain.
    vendor_name: str | None = None
    if settings.email_allowed(identity.email):
        kind = "staff"
    elif kind == "vendor":
        allow = auth.vendor_allowed(conn, identity.email)
        if allow is None:
            return _back("not_invited")
        vendor_name = allow["vendor_name"]
    else:
        return _back("domain")
    user = auth.sign_in(conn, settings, identity, kind=kind, vendor_name=vendor_name)
    if user.access == "disabled":
        return _back("disabled")
    token = auth.open_session(conn, user)
    resp = _back(None, next_path)
    resp.set_cookie(
        auth.SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
        samesite="lax", secure=_secure(), path="/",
    )
    return resp


@router.post("/onboarding", response_model=AuthStatus)
def post_onboarding(body: OnboardingRequest, conn: ConnDep, user: CurrentUser) -> AuthStatus:
    if not get_settings().sign_in_configured():
        raise api_error(409, "sign_in_off", "Sign-in is not configured on this engine.")
    if user is None:
        raise api_error(401, "signed_out", "You are not signed in.", "Sign in first.")
    if user.access == "disabled":
        raise api_error(403, "disabled", "Your access has been turned off.", "Ask the admin.")
    try:
        updated = auth.complete_onboarding(conn, user, body.answers)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc)) from exc
    return status_for(updated)


@router.post("/signout", status_code=204)
def post_signout(request: Request, conn: ConnDep) -> Response:
    auth.close_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    resp = Response(status_code=204)
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp
