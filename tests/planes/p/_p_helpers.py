"""Shared test helpers for the P1-P4 test files (not itself a test module --
pytest's default `test_*.py` collection glob skips it, same convention as
tests/planes/ja/_ja6_helpers.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from lge import db as lge_db
from lge.registry import RunContext
from lge.settings import Settings, get_settings


def ctx(conn, **overrides) -> RunContext:
    """A RunContext over the real configured Settings (LGE_USER_AGENT etc.
    come from .env, same as every other plane's tests) unless a field is
    overridden -- e.g. ctx(db, live=True) or ctx(db, user_agent="")."""
    base = get_settings()
    if overrides:
        base = Settings(
            dsn=overrides.get("dsn", base.dsn),
            admin_dsn=overrides.get("admin_dsn", base.admin_dsn),
            object_store=overrides.get("object_store", base.object_store),
            user_agent=overrides.get("user_agent", base.user_agent),
            anthropic_api_key=overrides.get("anthropic_api_key", base.anthropic_api_key),
            openrouter_api_key=overrides.get("openrouter_api_key", base.openrouter_api_key),
            live=overrides.get("live", base.live),
        )
    return RunContext(conn, base)


def make_lead(conn, firm_id, **cols) -> str:
    """Insert one open lead for `firm_id`, defaulting to DISCOVERED --
    mirrors tests/db/test_invariants.py's local make_lead."""
    cols.setdefault("id", str(uuid.uuid4()))
    cols["firm_id"] = firm_id
    cols.setdefault("state", "DISCOVERED")
    cols.setdefault("created_at", datetime.now(UTC))
    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with lge_db.lifecycle(conn, "test_setup"), conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO lead ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def lead_state(conn, firm_id) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM lead WHERE firm_id = %s AND closed_at IS NULL", (firm_id,)
        )
        row = cur.fetchone()
        return row["state"] if row else None


def insert_document(
    conn, store, firm_id, html: bytes | str, *, url, page_kind, status_code=200, fetch_ok=True
) -> int:
    body = html.encode("utf-8") if isinstance(html, str) else html
    key = store.put(body)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document (firm_id, url, status_code, content_hash, object_key, bytes,
                                   word_count, fetch_ok, page_kind)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (firm_id, url, status_code, key, key, len(body), None, fetch_ok, page_kind),
        )
        return cur.fetchone()["id"]


def source_registry_row(conn, host: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM source_registry WHERE host = %s", (host,))
        return cur.fetchone()


def site_map_rows(conn, firm_id) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT url, page_kind, discovered_via FROM site_map WHERE firm_id = %s ORDER BY url",
            (firm_id,),
        )
        return cur.fetchall()
