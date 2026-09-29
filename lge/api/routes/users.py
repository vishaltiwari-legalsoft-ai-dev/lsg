"""The Users screen (D-067): who has signed in, what they said about
themselves, and what the admin has decided. Admin only.

  GET   /api/users              everyone, the ones waiting first
  GET   /api/users/{user_id}    one person, with their history
  PATCH /api/users/{user_id}    set their access
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from lge import auth
from lge.api.deps import ConnDep
from lge.api.errors import api_error, is_uuid, not_found
from lge.api.gate import require_admin
from lge.api.models import (
    AuthUser,
    UserAccessRequest,
    UserDetail,
    UserEvent,
    UsersResponse,
    VendorAllow,
    VendorAllowRequest,
    VendorAllowsResponse,
)
from lge.api.routes.auth import auth_user
from lge.settings import get_settings

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])

_ACCESS_DISPLAY = {
    "admin": "Admin", "operator": "Operator", "viewer": "Viewer",
    "pending": "Waiting for access", "disabled": "Disabled",
}
_STANDING_DISPLAY = {
    "needs_onboarding": "Signed in, form not filled",
    "awaiting_access": "Waiting for you",
    "disabled": "Disabled",
    "active": "Active",
}


def _row(user: auth.User) -> AuthUser:
    out = auth_user(user)
    out.access_display = _ACCESS_DISPLAY.get(user.access, user.access)
    out.standing_display = _STANDING_DISPLAY.get(user.standing, user.standing)
    out.admin_by_settings = get_settings().is_admin_email(user.email)
    return out


def _target(conn, user_id: str) -> auth.User:
    user = auth.user_by_id(conn, user_id) if is_uuid(user_id) else None
    if user is None:
        raise not_found("User not found.", "Check the id.")
    return user


# The vendor allow list (D-068): who from an email vendor's team may sign
# in at all. Registered before /{user_id} so "vendors" is never read as an id.


@router.get("/vendors", response_model=VendorAllowsResponse)
def list_vendors(conn: ConnDep) -> VendorAllowsResponse:
    return VendorAllowsResponse(
        items=[VendorAllow(**{**r, "id": str(r["id"])}) for r in auth.list_vendor_allows(conn)]
    )


@router.post("/vendors", response_model=VendorAllow, status_code=201)
def add_vendor(
    body: VendorAllowRequest, conn: ConnDep,
    admin: auth.User = Depends(require_admin),  # noqa: B008 -- FastAPI's declaration style
) -> VendorAllow:
    try:
        row = auth.add_vendor_allow(conn, admin, body.pattern, body.vendor_name, body.note)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc)) from exc
    return VendorAllow(**{**row, "id": str(row["id"])})


@router.delete("/vendors/{allow_id}", status_code=204)
def remove_vendor(allow_id: str, conn: ConnDep) -> None:
    if not is_uuid(allow_id) or not auth.remove_vendor_allow(conn, allow_id):
        raise not_found("That allow-list entry does not exist.", "Refresh the list.")


@router.get("", response_model=UsersResponse)
def list_users(conn: ConnDep) -> UsersResponse:
    users = auth.list_users(conn)
    return UsersResponse(
        items=[_row(u) for u in users],
        waiting=sum(1 for u in users if u.standing == "awaiting_access"),
        levels=[{"value": a, "label": _ACCESS_DISPLAY[a]} for a in auth.ASSIGNABLE],
    )


@router.get("/{user_id}", response_model=UserDetail)
def get_user(user_id: str, conn: ConnDep) -> UserDetail:
    user = _target(conn, user_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind, detail, actor, at FROM app_user_event WHERE user_id = %s "
            "ORDER BY at DESC, id DESC LIMIT 100",
            (user.id,),
        )
        events = [UserEvent(**r) for r in cur.fetchall()]
    return UserDetail(user=_row(user), events=events)


@router.patch("/{user_id}", response_model=UserDetail)
def set_user_access(
    user_id: str, body: UserAccessRequest, conn: ConnDep,
    admin: auth.User = Depends(require_admin),  # noqa: B008 -- FastAPI's declaration style
) -> UserDetail:
    target = _target(conn, user_id)
    try:
        auth.set_access(conn, get_settings(), admin, target, body.access)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc)) from exc
    except PermissionError as exc:
        raise api_error(409, "not_allowed", str(exc)) from exc
    return get_user(user_id, conn)
