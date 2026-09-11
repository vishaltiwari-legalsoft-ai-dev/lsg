"""Process configuration.

A single frozen `Settings` object, loaded once from the environment (with a
minimal `.env` file as a fallback layer under it). No third-party config
library — this repo cannot add dependencies casually, and the surface here is
small enough not to need one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_DSN = "postgresql://postgres@127.0.0.1:54329/lge"
_DEFAULT_ADMIN_DSN = "postgresql://postgres@127.0.0.1:54329/postgres"


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


@dataclass(frozen=True)
class Settings:
    dsn: str
    admin_dsn: str
    object_store: Path
    user_agent: str
    anthropic_api_key: str
    openrouter_api_key: str
    live: bool


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
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load_settings()
