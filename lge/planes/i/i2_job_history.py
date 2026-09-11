"""I2 -- job history loader (`i2_job_history_load`).

`export -> raw_posting`, one-shot, re-runnable. context/50-first-party/
05-job-history.md: the file lists companies that posted roles but carries **no
post link, no company URL** -- it is a seed for JA6's resolution ladder and a fit
attribute source, never a signal (see JA6, which is what turns these rows into
`has_hired_support_roles` / `repeat_role_count` firm_attribute claims -- this
component only loads the raw rows).

Idempotency: `raw_posting` is an append-only fetch log (UNIQUE on
(source, source_key, fetched_at), where fetched_at defaults to now() on every
insert) -- built for a watcher that re-sees the same posting on every sweep. A
one-shot file loader re-run on the same CSV is not a new sweep, so idempotency is
enforced here instead, on `source_key` alone: `source_key = sha1(the row)`, and a
row whose source_key already exists under source='internal_jobs' is skipped
rather than reinserted. Bulk-fetching existing keys once, rather than one
SELECT per row or lge.registry.RunContext.once() per row, keeps a 2,730-row load
to two round trips instead of thousands -- and `once()`'s task_run bookkeeping is
built for a long-lived, resumable job; this is a single pass over a static file
where "already have this row" is a complete idempotency story on its own.
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

from dateutil import parser as dateutil_parser
from psycopg.types.json import Jsonb

from lge.registry import RunContext, RunResult, component
from lge.settings import PROJECT_ROOT

DEFAULT_PATH = "data/in/job_history_2026-08-27.csv"

_SOURCE = "internal_jobs"

# "City, ST" only -- context/50-first-party/05-job-history.md's Firm Location
# column is otherwise free text ("United States", "Remote", "United States (+2
# others)", a bare state name or abbreviation with no city). Parsing any of those
# as a city would hand JA6 a false "usable city" and risk a wrong firm match that
# "writes a false hiring history onto a real firm permanently" -- so this is
# deliberately narrow: two tokens, comma-separated, the second a real USPS state
# or territory code.
_CITY_STATE_RE = re.compile(r"^\s*([^,]+?),\s*([A-Za-z]{2})\s*$")

# 50 states + DC + the territories firm.state (char(2)) is expected to hold.
_VALID_STATE_CODES = frozenset(
    """
    AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
    MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY
    DC PR VI GU AS MP
    """.split()
)


def _parse_city_state(location_raw: str) -> tuple[str | None, str | None]:
    m = _CITY_STATE_RE.match(location_raw or "")
    if not m:
        return None, None
    city, state = m.group(1).strip(), m.group(2).strip().upper()
    if not city or state not in _VALID_STATE_CODES:
        return None, None
    return city, state


def _parse_post_date(raw: str):
    if not raw or not raw.strip():
        return None
    try:
        return dateutil_parser.parse(raw.strip()).date()
    except (ValueError, OverflowError):
        return None


def _row_source_key(row: dict[str, str]) -> str:
    # Every column, in file order, joined by a delimiter that cannot appear in a
    # CSV field value once parsed (the \x1f unit separator) -- two rows with the
    # same visible text but different raw bytes are not expected here, but this
    # avoids "Denver, CO" + "" colliding with "Denver" + ", CO" the way a plain
    # "|".join could.
    payload = "\x1f".join(row.get(k, "") for k in row)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()  # noqa: S324 (identity key, not security)


def _existing_source_keys(ctx: RunContext) -> set[str]:
    with ctx.conn.cursor() as cur:
        cur.execute("SELECT source_key FROM raw_posting WHERE source = %s", (_SOURCE,))
        return {row["source_key"] for row in cur.fetchall()}


@component(
    "i2_job_history_load",
    "i",
    "Load the internal job-history CSV into raw_posting (source='internal_jobs'). "
    "One-shot, idempotent on source_key = sha1(row).",
)
def i2_job_history_load(ctx: RunContext, **opts: object) -> RunResult:
    path_opt = opts.get("path", DEFAULT_PATH)
    csv_path = Path(str(path_opt))
    if not csv_path.is_absolute():
        csv_path = (PROJECT_ROOT / csv_path).resolve()

    limit_opt = opts.get("limit")
    limit = int(limit_opt) if limit_opt is not None else None

    result = RunResult()
    if not csv_path.is_file():
        result.failed += 1
        result.notes.append(f"CSV not found: {csv_path}")
        return result

    existing = _existing_source_keys(ctx)
    seen_in_file: set[str] = set()
    duplicate_in_file = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break

            try:
                title = (row.get("Job Title") or "").strip()
                if not title:
                    raise ValueError("empty Job Title")

                source_key = _row_source_key(row)
                if source_key in seen_in_file:
                    # An exact duplicate row within the same file (same identity
                    # for every column) -- nothing to write, so it counts as
                    # skipped like any other row whose key is already accounted
                    # for. Tallied separately in the notes: real source data, not
                    # a defect in this loader.
                    duplicate_in_file += 1
                    result.skipped += 1
                    continue
                seen_in_file.add(source_key)

                if source_key in existing:
                    result.skipped += 1
                    continue

                company_name = (row.get("Company") or "").strip() or None
                location_raw = (row.get("Firm Location") or "").strip() or None
                city, state = _parse_city_state(location_raw or "")
                board_posted_date = _parse_post_date(row.get("Post Date") or "")

                with ctx.conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO raw_posting (
                            source, source_key, source_url, company_name, title,
                            location_raw, city, state, board_posted_date, payload
                        ) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            _SOURCE,
                            source_key,
                            company_name,
                            title,
                            location_raw,
                            city,
                            state,
                            board_posted_date,
                            Jsonb(dict(row)),
                        ),
                    )
                existing.add(source_key)
                result.processed += 1
            except Exception as exc:  # noqa: BLE001 -- one bad row must not sink the load
                result.failed += 1
                ctx.log.warning("i2_job_history_load: row %d failed: %s", i, exc)

    result.notes.append(
        f"path={csv_path} processed={result.processed} skipped={result.skipped} "
        f"failed={result.failed} (of which duplicate rows within this file: "
        f"{duplicate_in_file})"
    )
    return result
