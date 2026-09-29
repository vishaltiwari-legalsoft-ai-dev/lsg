"""The door every route stands behind (D-067). A dependency, not a
middleware, so it shares the request's connection (and, in tests, the
test's transaction).

With sign-in not configured the door is open, as it always was for the one
local operator, and `request.state.user` is None. With it configured:

    no session                  -> 401 signed_out
    not onboarded / pending /
    disabled                    -> 403 with that standing as the code
    a write by a viewer         -> 403 read_only
    the Users screen, not admin -> 403 admin_only
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from lge import auth
from lge.api.deps import ConnDep
from lge.api.errors import api_error
from lge.settings import get_settings

_WRITE = {"POST", "PUT", "PATCH", "DELETE"}
_FIX = {
    "signed_out": "Sign in with your Google account.",
    "needs_onboarding": "Fill in the short form first.",
    "awaiting_access": "Ask the admin to set your access.",
    "disabled": "Ask the admin.",
}


def current_user(request: Request, conn: ConnDep) -> auth.User | None:
    """Who is asking, or None: no session, or sign-in not configured."""
    if getattr(request.state, "user_resolved", False):
        return getattr(request.state, "user", None)
    user = None
    if get_settings().sign_in_configured():
        user = auth.user_for_session(conn, request.cookies.get(auth.SESSION_COOKIE))
    request.state.user = user
    request.state.user_resolved = True
    return user


CurrentUser = Annotated[auth.User | None, Depends(current_user)]


def actor_of(request: Request) -> str:
    """Who to write on a record: the signed-in address, else 'ui'."""
    user = getattr(request.state, "user", None)
    return user.email if user is not None else "ui"


def require_access(request: Request, user: CurrentUser) -> auth.User | None:
    """The gate on every ordinary route."""
    if not get_settings().sign_in_configured():
        return None
    if user is None:
        raise api_error(401, "signed_out", "You are not signed in.", _FIX["signed_out"])
    standing = user.standing
    if standing != "active":
        raise api_error(403, standing, _standing_message(standing), _FIX.get(standing))
    if request.method in _WRITE and not user.may("operator"):
        raise api_error(
            403, "read_only", "Your access is read-only.",
            "Ask the admin for operator access to make changes.",
        )
    return user


def require_admin(user: CurrentUser) -> auth.User:
    """The gate on the Users screen."""
    if not get_settings().sign_in_configured():
        raise api_error(
            409, "sign_in_off", "Sign-in is not configured on this engine.",
            "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env and restart.",
        )
    if user is None:
        raise api_error(401, "signed_out", "You are not signed in.", _FIX["signed_out"])
    if not user.may("admin"):
        raise api_error(403, "admin_only", "Only an admin can see or change who has access.")
    return user


def _standing_message(standing: str) -> str:
    return {
        "needs_onboarding": "Tell us who you are first.",
        "awaiting_access": "Your access has not been set yet.",
        "disabled": "Your access has been turned off.",
    }.get(standing, "You cannot use this yet.")
