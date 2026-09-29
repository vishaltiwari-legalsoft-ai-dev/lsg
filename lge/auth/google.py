"""Google as the identity provider (D-067): the OAuth 2.0 authorization-code
flow with the OpenID scopes, and the person's identity read from Google's
own userinfo endpoint over TLS -- so no token has to be decoded or its
signature checked here, and no new dependency is needed.

Nothing in this module touches the store; `lge.auth` does that.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"


class SignInError(Exception):
    """Google, or the exchange with it, did not give a usable identity. The
    message is safe to show; it never carries a token or a secret."""


@dataclass(frozen=True, slots=True)
class Identity:
    sub: str  # Google's stable id for the account
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


def authorize_url(client_id: str, redirect_uri: str, state: str, *, hd: str | None = None) -> str:
    """Where the browser is sent to sign in. `hd` asks Google to show only
    that Workspace domain's accounts; the answer is still checked here."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    if hd:
        params["hd"] = hd
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(
    code: str, *, client_id: str, client_secret: str, redirect_uri: str,
    client: httpx.Client | None = None, timeout_s: float = 15.0,
) -> Identity:
    """The code Google sent back, exchanged for tokens, then the identity
    behind them. Raises SignInError with a plain reason on any failure."""
    own = client is None
    client = client or httpx.Client(timeout=timeout_s)
    try:
        try:
            token_resp = client.post(
                TOKEN_URL,
                data={
                    "code": code, "client_id": client_id, "client_secret": client_secret,
                    "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise SignInError("Google could not be reached to finish signing in.") from exc
        if token_resp.status_code != 200:
            raise SignInError("Google did not accept the sign-in. Try again.")
        try:
            access_token = token_resp.json().get("access_token")
        except ValueError as exc:
            raise SignInError("Google answered in a shape that could not be read.") from exc
        if not access_token:
            raise SignInError("Google did not return a token. Try again.")
        try:
            info_resp = client.get(
                USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as exc:
            raise SignInError("Google could not be reached to read the account.") from exc
        if info_resp.status_code != 200:
            raise SignInError("Google would not say who signed in. Try again.")
        try:
            info = info_resp.json()
        except ValueError as exc:
            raise SignInError("Google answered in a shape that could not be read.") from exc
    finally:
        if own:
            client.close()
    sub = str(info.get("sub") or "")
    email = str(info.get("email") or "").strip().lower()
    if not sub or not email:
        raise SignInError("Google did not return an email address for the account.")
    return Identity(
        sub=sub, email=email,
        email_verified=bool(info.get("email_verified")),
        name=(str(info.get("name")).strip() or None) if info.get("name") else None,
        picture=str(info.get("picture")) if info.get("picture") else None,
    )
