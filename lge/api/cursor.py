"""Opaque keyset-pagination cursors. plan/api-contract.md: "cursor
pagination (`cursor`, `limit` <= 200)" and "Cursor pagination must be
stable" -- the cursor encodes the sort key(s) AND the row id, so a page
boundary never repeats or skips a row when new rows are inserted between
two requests (the failure mode of OFFSET pagination)."""

from __future__ import annotations

import base64
import json
from typing import Any


def encode_cursor(parts: list[Any]) -> str:
    raw = json.dumps(parts, separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> list[Any] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        value = json.loads(raw)
    except Exception:
        return None
    return value if isinstance(value, list) else None


def cursor_parts(cursor: str, n: int) -> list[Any]:
    """The `n` parts a cursor for this list must carry, or a 400. A cursor
    that does not decode, or one from another list, used to be ignored and
    the caller quietly restarted at page one -- a client looping on a stale
    cursor never noticed (readiness audit, 28 Sep 2026)."""
    from lge.api.errors import api_error

    decoded = decode_cursor(cursor)
    if decoded is None or len(decoded) != n:
        raise api_error(
            400, "bad_cursor", "That cursor is not one this list gave out.",
            "Start again from the first page.",
        )
    return decoded
