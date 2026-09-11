"""Shared test helpers for the JA6 test files (not itself a test module --
pytest's tests/planes/ja/test_ja6*.py collection glob skips it)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from psycopg.types.json import Jsonb

from lge.planes.ja.ja6_closure import ja6_closure
from lge.planes.ja.ja6_normalise import ja6_normalise
from lge.planes.ja.ja6_types import Posting
from lge.registry import RunContext
from lge.settings import get_settings


def ctx(conn) -> RunContext:
    return RunContext(conn, get_settings())


def run_normalise(conn, **opts):
    return ja6_normalise(ctx(conn), **opts)


def run_closure(conn, **opts):
    return ja6_closure(ctx(conn), **opts)


def make_posting(conn, **cols) -> int:
    """Insert one raw_posting row, returning its id. Defaults cover every NOT
    NULL column; override anything else by keyword."""
    cols.setdefault("source", "careers")
    cols.setdefault("source_key", uuid.uuid4().hex)
    cols.setdefault("title", "Paralegal")
    # A real watcher records the company name even on a firm's own careers page
    # (it already has the firm record); default non-blank so a test that isn't
    # specifically exercising blind_posting doesn't trip it by omission.
    cols.setdefault("company_name", "Test Firm")
    cols.setdefault("fetch_ok", True)
    cols.setdefault("payload", Jsonb({}))
    cols.setdefault("fetched_at", datetime.now(UTC))

    columns = list(cols.keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [cols[c] for c in columns]
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO raw_posting ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_careers_sweep(conn, firm_id, **cols) -> int:
    cols.setdefault("url", "https://example.com/careers")
    cols.setdefault("fetch_ok", True)
    cols.setdefault("swept_at", datetime.now(UTC))
    columns = ["firm_id", *cols.keys()]
    values = [firm_id, *cols.values()]
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO careers_sweep ({col_list}) VALUES ({placeholders}) RETURNING id",  # noqa: S608
            values,
        )
        return cur.fetchone()["id"]


def make_ats_slug_map(conn, ats: str, slug: str, firm_id) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ats_slug_map (ats, slug, firm_id) VALUES (%s, %s, %s)",
            (ats, slug, firm_id),
        )


def rejected_rule(conn, raw_posting_id: int) -> str | None:
    row = fetch_one(
        conn, "SELECT rule FROM job_posting_rejected WHERE raw_posting_id = %s", (raw_posting_id,)
    )
    return row["rule"] if row else None


def has_discovery_lead(conn, raw_posting_id: int) -> bool:
    row = fetch_one(
        conn, "SELECT 1 FROM discovery_lead WHERE raw_posting_id = %s", (raw_posting_id,)
    )
    return row is not None


def resolution_row(conn, raw_posting_id: int) -> dict | None:
    return fetch_one(
        conn,
        "SELECT firm_id, rung, confidence FROM posting_resolution WHERE raw_posting_id = %s",
        (raw_posting_id,),
    )


def fetch_one(conn, sql: str, params: tuple = ()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(conn, sql: str, params: tuple = ()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


_POSTING_DEFAULTS = dict(
    source="careers",
    source_key="k",
    source_url=None,
    firm_id=None,
    company_name="Smith Law",
    title="Paralegal",
    location_raw=None,
    city=None,
    state=None,
    metro_code=None,
    body=None,
    apply_email=None,
    outbound_links=None,
    phone_raw=None,
    ats_slug=None,
    board_posted_date=None,
    first_published=None,
    updated_at_src=None,
    fetch_ok=True,
    fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def posting(id: int, **overrides) -> Posting:
    """An in-memory Posting for the pure ja6_agency.classify() tests -- no DB
    round trip needed to exercise a pure function."""
    kwargs = {**_POSTING_DEFAULTS, **overrides}
    return Posting(id=id, **kwargs)


def d(y: int, m: int, day: int) -> date:
    return date(y, m, day)
