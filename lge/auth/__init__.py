"""Who may use the screens (D-067): people, sessions, access.

Google says who a person is (`lge.auth.google`); this module says what they
may do. One row per person in `app_user`; their `access` is one of

    admin     everything, including the Users screen
    operator  works the leads: research, decisions, notes, edits
    viewer    reads
    pending   signed in and onboarded, waiting for the admin to decide
    disabled  turned off by the admin

A person's *standing* on any request is derived from the row:

    needs_onboarding   signed in, never filled the form
    awaiting_access    onboarded, access still 'pending'
    disabled
    active             viewer, operator or admin

The admin addresses in settings are admins the moment they sign in and skip
the form: the owner must never wait for their own approval. Sessions are
rows keyed on the SHA-256 of a random token; the browser holds the token in
an HttpOnly cookie. Every change of standing is written to `app_user_event`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from lge.auth.google import Identity
from lge.settings import Settings

ACCESS_LEVELS = ("admin", "operator", "viewer", "pending", "disabled")
ASSIGNABLE = ("admin", "operator", "viewer", "disabled")
_RANK = {"viewer": 1, "operator": 2, "admin": 3}
SESSION_DAYS = 30
SESSION_COOKIE = "lge_session"
STATE_COOKIE = "lge_signin"
STATE_TTL_S = 600

# The form every new person fills once. The screen renders these; the
# answers are kept whole on the row and shown to the admin.
ONBOARDING_FIELDS: tuple[dict[str, Any], ...] = (
    {"name": "full_name", "label": "Your name", "kind": "text", "required": True},
    {"name": "title", "label": "Your role at Legal Soft", "kind": "text", "required": True,
     "hint": "For example SDR, account executive, operations"},
    {"name": "team", "label": "Team", "kind": "choice", "required": True,
     "options": ["Sales", "Operations", "Marketing", "Leadership", "Other"]},
    {"name": "purpose", "label": "What will you use the engine for?", "kind": "long_text",
     "required": True, "hint": "A sentence or two: what you need from it day to day"},
    {"name": "phone", "label": "Phone", "kind": "text", "required": False},
)

_process_secret = secrets.token_bytes(32)


KINDS = ("staff", "vendor")


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str
    name: str | None
    picture_url: str | None
    access: str
    onboarded_at: datetime | None
    onboarding: dict[str, Any] | None
    created_at: datetime
    last_sign_in_at: datetime | None
    access_set_by: str | None
    access_set_at: datetime | None
    kind: str = "staff"  # staff (Legal Soft) or vendor (an email vendor's team, D-068)
    vendor_name: str | None = None

    @property
    def standing(self) -> str:
        if self.access == "disabled":
            return "disabled"
        if self.onboarded_at is None:
            return "needs_onboarding"
        if self.access == "pending":
            return "awaiting_access"
        return "active"

    def may(self, level: str) -> bool:
        """Whether this person's access is at least `level`."""
        return self.standing == "active" and _RANK.get(self.access, 0) >= _RANK[level]


def _row_user(row: dict[str, Any]) -> User:
    return User(
        id=str(row["id"]), email=row["email"], name=row["name"],
        picture_url=row["picture_url"], access=row["access"],
        onboarded_at=row["onboarded_at"], onboarding=row["onboarding"],
        created_at=row["created_at"], last_sign_in_at=row["last_sign_in_at"],
        access_set_by=row["access_set_by"], access_set_at=row["access_set_at"],
        kind=row.get("kind") or "staff", vendor_name=row.get("vendor_name"),
    )


# ---------------------------------------------------------------------------
# The state of a sign-in in flight: a signed, expiring token the browser
# carries in a short-lived cookie and Google echoes back as `state`.
# ---------------------------------------------------------------------------


def _secret(settings: Settings) -> bytes:
    return settings.auth_secret.encode("utf-8") if settings.auth_secret else _process_secret


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(text: str) -> str | None:
    try:
        padded = text + "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def make_state(
    settings: Settings, next_path: str, *, kind: str = "staff", now: datetime | None = None
) -> str:
    """`nonce~expires~next~kind~signature`, every part in cookie-safe
    characters (a `/` in a cookie value gets quoted on the way out and would
    not match what Google echoes back). `kind` is which door the person
    chose: staff or vendor."""
    now = now or datetime.now(UTC)
    nonce = secrets.token_urlsafe(16)
    expires = int((now + timedelta(seconds=STATE_TTL_S)).timestamp())
    kind = kind if kind in KINDS else "staff"
    body = f"{nonce}~{expires}~{_b64(_safe_next(next_path))}~{kind}"
    sig = hmac.new(_secret(settings), body.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{body}~{sig}"


def check_state(
    settings: Settings, state: str, *, now: datetime | None = None
) -> tuple[str, str] | None:
    """(next path, kind) a valid state carries, or None when the state is
    not ours, has been altered, or has expired."""
    now = now or datetime.now(UTC)
    try:
        nonce, expires, next_b64, kind, sig = state.split("~", 4)
    except ValueError:
        return None
    body = f"{nonce}~{expires}~{next_b64}~{kind}"
    want = hmac.new(_secret(settings), body.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(want, sig):
        return None
    try:
        if int(expires) < int(now.timestamp()):
            return None
    except ValueError:
        return None
    if kind not in KINDS:
        return None
    return _safe_next(_unb64(next_b64)), kind


def _safe_next(path: str | None) -> str:
    """Only a path on our own screens: never another site."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


def _event(conn: Any, user_id: str, kind: str, detail: dict[str, Any] | None, actor: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_user_event (user_id, kind, detail, actor) VALUES (%s, %s, %s, %s)",
            (user_id, kind, Jsonb(detail) if detail is not None else None, actor),
        )


def user_by_id(conn: Any, user_id: str) -> User | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM app_user WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return _row_user(row) if row else None


def user_by_email(conn: Any, email: str) -> User | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM app_user WHERE email = %s", (email.strip().lower(),))
        row = cur.fetchone()
    return _row_user(row) if row else None


def list_users(conn: Any) -> list[User]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM app_user ORDER BY (access = 'pending') DESC, created_at DESC"
        )
        return [_row_user(r) for r in cur.fetchall()]


def vendor_allowed(conn: Any, email: str) -> dict[str, Any] | None:
    """The vendor allow-list row that admits this address: the address
    itself, or its whole domain (`@sendco.com`). None when neither is listed."""
    email = email.strip().lower()
    domain = "@" + email.rsplit("@", 1)[-1]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM vendor_allow WHERE pattern = %s OR pattern = %s "
            "ORDER BY (pattern = %s) DESC LIMIT 1",
            (email, domain, email),
        )
        return cur.fetchone()


def list_vendor_allows(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM vendor_allow ORDER BY vendor_name, pattern")
        return cur.fetchall()


def add_vendor_allow(
    conn: Any, actor: User, pattern: str, vendor_name: str, note: str | None
) -> dict[str, Any]:
    """An address or a `@domain` an email vendor's people may sign in with."""
    pattern = " ".join(pattern.split()).lower()
    vendor_name = " ".join(vendor_name.split())
    if not vendor_name:
        raise ValueError("The vendor's name is required.")
    is_domain = pattern.startswith("@") and "." in pattern[1:] and " " not in pattern
    is_email = (
        pattern.count("@") == 1 and not pattern.startswith("@")
        and "." in pattern.rsplit("@", 1)[-1]
    )
    if not (is_domain or is_email):
        raise ValueError("Give a whole address (dana@sendco.com) or a whole domain (@sendco.com).")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_allow (pattern, vendor_name, note, added_by) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (pattern) DO UPDATE SET "
            "vendor_name = EXCLUDED.vendor_name, note = EXCLUDED.note RETURNING *",
            (pattern, vendor_name, (note or "").strip() or None, actor.email),
        )
        return cur.fetchone()


def remove_vendor_allow(conn: Any, allow_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_allow WHERE id = %s", (allow_id,))
        return cur.rowcount == 1


def sign_in(
    conn: Any, settings: Settings, identity: Identity, *, kind: str = "staff",
    vendor_name: str | None = None, now: datetime | None = None,
) -> User:
    """The person behind a Google identity: found or created, their sign-in
    recorded. An admin address is an admin, onboarded, from the first time.
    `kind` is which door admitted them; a vendor's row remembers the vendor."""
    now = now or datetime.now(UTC)
    admin = settings.is_admin_email(identity.email)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM app_user WHERE google_sub = %s OR email = %s",
            (identity.sub, identity.email),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                INSERT INTO app_user (email, google_sub, name, picture_url, access,
                                      onboarded_at, onboarding, access_set_by, access_set_at,
                                      last_sign_in_at, kind, vendor_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
                """,
                (
                    identity.email, identity.sub, identity.name, identity.picture,
                    "admin" if admin else "pending",
                    now if admin else None,
                    Jsonb({"full_name": identity.name or identity.email, "admin": True})
                    if admin else None,
                    "settings" if admin else None, now if admin else None, now,
                    kind if kind in KINDS else "staff", vendor_name,
                ),
            )
            row = cur.fetchone()
            _event(conn, str(row["id"]), "signed_up",
                   {"access": row["access"], "admin_by_settings": admin, "kind": row["kind"],
                    "vendor": vendor_name}, identity.email)
            return _row_user(row)
        updates: dict[str, Any] = {
            "google_sub": identity.sub, "name": identity.name or row["name"],
            "picture_url": identity.picture or row["picture_url"], "last_sign_in_at": now,
        }
        if kind == "vendor" and vendor_name and not row.get("vendor_name"):
            updates["vendor_name"] = vendor_name
        if admin and row["access"] != "admin":
            # The settings' word stands, even over an earlier demotion.
            updates.update(access="admin", access_set_by="settings", access_set_at=now)
            if row["onboarded_at"] is None:
                updates.update(onboarded_at=now)
            _event(conn, str(row["id"]), "access_set",
                   {"from": row["access"], "to": "admin", "by": "settings"}, identity.email)
        sets = ", ".join(f"{k} = %s" for k in updates)
        cur.execute(  # noqa: S608 -- fixed column names
            f"UPDATE app_user SET {sets} WHERE id = %s RETURNING *",
            [*updates.values(), row["id"]],
        )
        row = cur.fetchone()
    _event(conn, str(row["id"]), "signed_in", None, identity.email)
    return _row_user(row)


def complete_onboarding(
    conn: Any, user: User, answers: dict[str, Any], *, now: datetime | None = None
) -> User:
    """The form, filled once: kept whole, the name taken onto the row."""
    now = now or datetime.now(UTC)
    clean: dict[str, Any] = {}
    for field in ONBOARDING_FIELDS:
        value = answers.get(field["name"])
        text = " ".join(str(value).split()) if value is not None else ""
        if field["required"] and not text:
            raise ValueError(f"{field['label']} is required.")
        if field["kind"] == "choice" and text and text not in field["options"]:
            raise ValueError(f"{field['label']}: choose one of the options.")
        clean[field["name"]] = text[:2000] or None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE app_user SET onboarded_at = COALESCE(onboarded_at, %s), onboarding = %s, "
            "name = COALESCE(%s, name) WHERE id = %s RETURNING *",
            (now, Jsonb(clean), clean.get("full_name"), user.id),
        )
        row = cur.fetchone()
    _event(conn, user.id, "onboarded", clean, user.email)
    return _row_user(row)


def set_access(
    conn: Any, settings: Settings, actor: User, target: User, access: str, *,
    now: datetime | None = None,
) -> User:
    """The admin's decision on a person. The settings' admins cannot be
    demoted or disabled here (they would be admins again at their next
    sign-in), and an admin cannot lock themselves out."""
    now = now or datetime.now(UTC)
    if access not in ASSIGNABLE:
        raise ValueError(f"Access must be one of {', '.join(ASSIGNABLE)}.")
    if settings.is_admin_email(target.email) and access != "admin":
        raise PermissionError("That person is an admin by the engine's settings.")
    if target.id == actor.id and access != "admin":
        raise PermissionError("You cannot take away your own access.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE app_user SET access = %s, access_set_by = %s, access_set_at = %s "
            "WHERE id = %s RETURNING *",
            (access, actor.email, now, target.id),
        )
        row = cur.fetchone()
        if access == "disabled":
            cur.execute("DELETE FROM app_session WHERE user_id = %s", (target.id,))
    _event(conn, target.id, "access_set", {"from": target.access, "to": access}, actor.email)
    return _row_user(row)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def open_session(conn: Any, user: User, *, now: datetime | None = None) -> str:
    """A new session; returns the token for the cookie (stored only hashed)."""
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_session (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (_hash(token), user.id, now + timedelta(days=SESSION_DAYS)),
        )
    return token


def user_for_session(
    conn: Any, token: str | None, *, now: datetime | None = None
) -> User | None:
    """The person behind a cookie token, or None; a live session's expiry
    slides forward on use."""
    if not token:
        return None
    now = now or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT u.* FROM app_session s JOIN app_user u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > %s",
            (_hash(token), now),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "UPDATE app_session SET last_seen_at = %s, expires_at = %s WHERE token_hash = %s",
            (now, now + timedelta(days=SESSION_DAYS), _hash(token)),
        )
    return _row_user(row)


def close_session(conn: Any, token: str | None) -> None:
    if not token:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM app_session WHERE token_hash = %s", (_hash(token),))


def sweep_sessions(conn: Any, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM app_session WHERE expires_at <= %s", (now,))
        return cur.rowcount
