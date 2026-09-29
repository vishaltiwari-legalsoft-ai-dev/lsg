"""Process configuration.

A single frozen `Settings` object, loaded once from the environment (with a
minimal `.env` file as a fallback layer under it). No third-party config
library — this repo cannot add dependencies casually, and the surface here is
small enough not to need one.

Providers are chosen here and nowhere else (brain/plan/plan-v2.md, "the
seams"): a component asks `lge.ingest.columns` / `lge.search` / `lge.enrich`
for *the* reader, engine or verifier, and those modules read the choice from
this object. `auto` means "the first provider whose key is present", so a
machine with no keys still runs on the free paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_DSN = "postgresql://postgres@127.0.0.1:54329/lge"
_DEFAULT_ADMIN_DSN = "postgresql://postgres@127.0.0.1:54329/postgres"

COLUMN_READERS = ("auto", "llm", "rules")
SEARCH_ENGINES = ("auto", "serper", "brave", "ddg")
EMAIL_FINDERS = ("auto", "hunter", "none")
EMAIL_VERIFIERS = ("auto", "hunter", "neverbounce", "zerobounce", "none")
LISTINGS_PROVIDERS = ("auto", "google_places", "serper", "none")


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse `KEY=VALUE` lines from a .env file. `#` starts a comment (only at
    the start of a trimmed line — this is intentionally not a shell parser).
    Missing file -> empty dict.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # allow quoted values
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _choice(value: str, allowed: tuple[str, ...], key: str) -> str:
    v = (value or "auto").strip().lower()
    if v not in allowed:
        raise ValueError(f"{key}={value!r}: expected one of {', '.join(allowed)}")
    return v


@dataclass(frozen=True)
class Settings:
    dsn: str
    admin_dsn: str
    object_store: Path
    user_agent: str
    anthropic_api_key: str
    openrouter_api_key: str
    live: bool
    # -- the seams: which provider stands behind each interface -------------
    # Defaults are the keyless paths, so a Settings built by hand (tests,
    # helpers) behaves like a machine with no keys.
    column_reader: str = "auto"  # auto | llm | rules
    search_engine: str = "auto"  # auto | serper | brave | ddg
    serper_api_key: str = ""
    brave_api_key: str = ""
    email_finder: str = "auto"  # auto | hunter | none
    email_verifier: str = "auto"  # auto | hunter | neverbounce | zerobounce | none
    hunter_api_key: str = ""
    neverbounce_api_key: str = ""
    zerobounce_api_key: str = ""
    # The Google Business Profile and its reviews (D-062): Google's own
    # Places API when its key exists, else Serper on the search key.
    listings: str = "auto"  # auto | google_places | serper | none
    google_places_api_key: str = ""
    # -- who may use the screens (D-067) ------------------------------------
    # Google sign-in is on when the OAuth client id and secret are set; until
    # then the engine answers its one local operator as it always has.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # The people who are admins the moment they sign in, whatever the table
    # says: the owner's address, so the first sign-in needs nobody's approval.
    admin_emails: tuple[str, ...] = ("vishal.tiwari@legalsoft.com",)
    # Only addresses at these domains may sign in at all; empty = any Google
    # account may sign in (and then wait for the admin).
    allowed_email_domains: tuple[str, ...] = ("legalsoft.com",)
    # Where the screens are, for Google's redirect back: the screens' origin,
    # which proxies /api to the engine.
    public_origin: str = "http://127.0.0.1:5000"
    # Signs the short-lived state cookie of a sign-in in flight. Random per
    # process when unset (a sign-in must then finish on the process it began).
    auth_secret: str = ""

    def sign_in_configured(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret)

    def is_admin_email(self, email: str) -> bool:
        return email.strip().lower() in {e.lower() for e in self.admin_emails}

    def email_allowed(self, email: str) -> bool:
        if not self.allowed_email_domains:
            return True
        domain = email.rsplit("@", 1)[-1].lower()
        return domain in {d.lower().lstrip("@") for d in self.allowed_email_domains}

    # Resolved choices: `auto` becomes the first provider with a key. A
    # component calls these, never the raw fields, so the fallback order is
    # written once.
    def column_reader_name(self) -> str:
        if self.column_reader != "auto":
            return self.column_reader
        return "llm" if self.openrouter_api_key else "rules"

    def search_engine_name(self) -> str:
        if self.search_engine != "auto":
            return self.search_engine
        if self.serper_api_key:
            return "serper"
        if self.brave_api_key:
            return "brave"
        return "ddg"

    def email_finder_name(self) -> str:
        if self.email_finder != "auto":
            return self.email_finder
        return "hunter" if self.hunter_api_key else "none"

    def email_verifier_name(self) -> str:
        if self.email_verifier != "auto":
            return self.email_verifier
        # Verification-only services first in practice (D-050): Hunter's key
        # is never expected to be present.
        if self.hunter_api_key:
            return "hunter"
        if self.neverbounce_api_key:
            return "neverbounce"
        if self.zerobounce_api_key:
            return "zerobounce"
        return "none"

    def listings_provider_name(self) -> str:
        if self.listings != "auto":
            return self.listings
        if self.google_places_api_key:
            return "google_places"
        if self.serper_api_key:
            return "serper"
        return "none"


def _load_settings() -> Settings:
    dotenv = _read_dotenv(PROJECT_ROOT / ".env")

    def get(key: str, default: str = "") -> str:
        # env vars win over the .env file, which wins over the default.
        if key in os.environ:
            return os.environ[key]
        if key in dotenv:
            return dotenv[key]
        return default

    object_store = Path(get("LGE_OBJECT_STORE", ".local/objects"))
    if not object_store.is_absolute():
        object_store = (PROJECT_ROOT / object_store).resolve()

    return Settings(
        dsn=get("LGE_DSN", _DEFAULT_DSN),
        admin_dsn=get("LGE_ADMIN_DSN", _DEFAULT_ADMIN_DSN),
        object_store=object_store,
        user_agent=get("LGE_USER_AGENT", ""),
        anthropic_api_key=get("ANTHROPIC_API_KEY", ""),
        openrouter_api_key=get("OPENROUTER_API_KEY", ""),
        live=get("LGE_LIVE", "") == "1",
        column_reader=_choice(get("LGE_COLUMN_READER"), COLUMN_READERS, "LGE_COLUMN_READER"),
        search_engine=_choice(get("LGE_SEARCH_ENGINE"), SEARCH_ENGINES, "LGE_SEARCH_ENGINE"),
        serper_api_key=get("SERPER_API_KEY", ""),
        brave_api_key=get("BRAVE_API_KEY", ""),
        email_finder=_choice(get("LGE_EMAIL_FINDER"), EMAIL_FINDERS, "LGE_EMAIL_FINDER"),
        email_verifier=_choice(get("LGE_EMAIL_VERIFIER"), EMAIL_VERIFIERS, "LGE_EMAIL_VERIFIER"),
        hunter_api_key=get("HUNTER_API_KEY", ""),
        neverbounce_api_key=get("NEVERBOUNCE_API_KEY", ""),
        zerobounce_api_key=get("ZEROBOUNCE_API_KEY", ""),
        listings=_choice(get("LGE_LISTINGS"), LISTINGS_PROVIDERS, "LGE_LISTINGS"),
        google_places_api_key=get("GOOGLE_PLACES_API_KEY", ""),
        google_oauth_client_id=get("GOOGLE_OAUTH_CLIENT_ID", ""),
        google_oauth_client_secret=get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        admin_emails=_list(get("LGE_ADMIN_EMAILS", "vishal.tiwari@legalsoft.com")),
        allowed_email_domains=_list(get("LGE_ALLOWED_EMAIL_DOMAINS", "legalsoft.com")),
        public_origin=get("LGE_PUBLIC_ORIGIN", "http://127.0.0.1:5000").rstrip("/"),
        auth_secret=get("LGE_AUTH_SECRET", ""),
    )


def _list(value: str) -> tuple[str, ...]:
    """A comma-separated setting as a tuple, blanks dropped."""
    return tuple(v.strip() for v in value.split(",") if v.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load_settings()
