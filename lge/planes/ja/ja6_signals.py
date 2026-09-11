"""JA6 stage 4+5 -- turning resolved postings into signals (live sources) or fit
attributes (internal_jobs). context/20-signals/04-dedupe-dates-and-closure.md +
context/50-first-party/05-job-history.md: **never the same thing**. internal_jobs
has no link and cannot be verified as still-open, so it never creates a `signal`
-- it only ever writes `firm_attribute` claims tagged source='internal_jobs'.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta

from psycopg.types.json import Jsonb

from lge.planes.ja.ja6_config import signal_rules
from lge.planes.ja.ja6_types import Posting

# ─── shared date/fingerprint helpers ──────────────────────────────────────────


def floor_to_week(d: date) -> date:
    """Monday of `d`'s ISO week -- the bucket in the dedupe fingerprint."""
    return d - timedelta(days=d.weekday())


def effective_date(p: Posting) -> date:
    """The best available date for a posting when board_posted_date is missing.
    Order: the board's own claimed date, then an ATS's updated_at/first_published,
    then our own fetch date. Never used for `signal.first_seen` -- only to seed
    the fingerprint's week bucket and to detect a repost."""
    if p.board_posted_date:
        return p.board_posted_date
    if p.updated_at_src:
        return p.updated_at_src.date()
    if p.first_published:
        return p.first_published.date()
    return p.fetched_at.date()


def metro_code_for(p: Posting, firm_row: dict) -> str:
    """No CBSA dataset is available offline (context/20-signals/04, sql/001
    header). `lower(city)|STATE` from the posting's own location, or the firm's
    when the posting has none (a careers-page posting rarely repeats the firm's
    own city in its body)."""
    city = p.city or firm_row.get("city") or ""
    state = p.state or firm_row.get("state") or ""
    return f"{city.strip().lower()}|{state.strip().upper()}"


def posting_fingerprint(
    firm_id: str, canonical_role: str, metro_code: str, anchor_date: date
) -> str:
    raw = "|".join([firm_id, canonical_role, metro_code, floor_to_week(anchor_date).isoformat()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 (identity key)


def repost_count_for(rows: list[Posting], anchor_date: date) -> int:
    """"Same fingerprint, board_posted_date moved forward while our first_seen
    stayed put" (context/20-signals/04-dedupe-dates-and-closure.md) -- counted as
    the number of DISTINCT effective dates strictly after the group's anchor
    (its earliest). Where an ATS gives first_published/updated_at directly, a row
    whose updated_at_src outruns first_published contributes its own later
    effective_date here too, so the ATS-direct case and the inferred case share
    one formula."""
    later_dates = {d for r in rows if (d := effective_date(r)) > anchor_date}
    return len(later_dates)


def first_sentence(body: str | None, limit: int = 240) -> str:
    if not body or not body.strip():
        return ""
    text = body.strip()
    for stop in (".", "!", "?"):
        idx = text.find(stop)
        if 0 < idx < limit:
            return text[: idx + 1].strip()
    return text[:limit].strip()


# ─── job_posting_open / multi_opening (live sources only) ────────────────────


def _upsert_signal(
    conn,
    firm_id: str,
    kind: str,
    fingerprint: str,
    first_seen: datetime,
    last_seen: datetime,
    repost_count: int,
    evidence: dict,
) -> tuple[int, bool]:
    """Insert-once on (firm_id, kind, fingerprint); afterwards only ever advances
    last_seen/repost_count and, if the signal was closed, clears closed_at -- but
    ONLY alongside a last_seen advance, exactly what the I6 trigger allows.
    Computes whether an UPDATE is even needed first so a re-run over unchanged
    data issues no write at all (never mind an illegal one)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, last_seen, repost_count, closed_at FROM signal "
            "WHERE firm_id = %s AND kind = %s AND fingerprint = %s",
            (firm_id, kind, fingerprint),
        )
        existing = cur.fetchone()

        if existing is None:
            cur.execute(
                "INSERT INTO signal (firm_id, kind, fingerprint, first_seen, last_seen, "
                "evidence, repost_count) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (firm_id, kind, fingerprint, first_seen, last_seen, Jsonb(evidence), repost_count),
            )
            return cur.fetchone()["id"], True

        signal_id = existing["id"]
        new_last_seen = max(existing["last_seen"], last_seen)
        new_repost = max(existing["repost_count"], repost_count)
        advanced = new_last_seen > existing["last_seen"]
        clear_closed = existing["closed_at"] is not None and advanced

        if advanced or new_repost > existing["repost_count"] or clear_closed:
            cur.execute(
                "UPDATE signal SET last_seen = %s, repost_count = %s, "
                "closed_at = CASE WHEN %s THEN NULL ELSE closed_at END WHERE id = %s",
                (new_last_seen, new_repost, clear_closed, signal_id),
            )
        return signal_id, False


def _append_sighting(conn, signal_id: int, row: Posting) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO signal_sighting "
            "(signal_id, source, url, board_posted_date, present, fetch_ok, raw_posting_id) "
            "VALUES (%s, %s, %s, %s, true, %s, %s) "
            "ON CONFLICT (signal_id, raw_posting_id) WHERE raw_posting_id IS NOT NULL DO NOTHING",
            (signal_id, row.source, row.source_url, row.board_posted_date, row.fetch_ok, row.id),
        )


def write_job_posting_open_signals(
    conn, resolved_live: list[tuple[Posting, dict]]
) -> tuple[int, int, int]:
    """`resolved_live` is (posting, firm_row) for every support-role posting from
    a live source (source != 'internal_jobs') that resolved to a firm. Groups by
    (firm_id, canonical_role, metro_code) -- one signal per group, one sighting
    per contributing raw_posting. Returns (signals_created, signals_updated,
    sightings_appended)."""
    groups: dict[tuple[str, str, str], list[tuple[Posting, dict]]] = defaultdict(list)
    for p, firm_row in resolved_live:
        metro = metro_code_for(p, firm_row)
        groups[(p.firm_id, p.canonical_role, metro)].append((p, firm_row))

    created = updated = sightings = 0
    for (firm_id, canonical_role, metro), members in groups.items():
        rows = [p for p, _ in members]
        anchor = min(effective_date(r) for r in rows)
        our_first_seen = min(r.fetched_at for r in rows)
        our_last_seen = max(r.fetched_at for r in rows)
        repost = repost_count_for(rows, anchor)
        fp = posting_fingerprint(firm_id, canonical_role, metro, anchor)

        # canonical_url / title preference: the firm's own careers page first,
        # then earliest sighting -- context/20-signals/04, "Merge policy on
        # collision".
        canonical = min(
            rows, key=lambda r: (0 if r.source == "careers" else 1, r.fetched_at)
        )
        evidence = {
            "title": canonical.title,
            "canonical_role": canonical_role,
            "posted_date": anchor.isoformat(),
            "url": canonical.source_url,
            "sources": sorted({r.source for r in rows}),
            "quote": first_sentence(canonical.body),
        }

        signal_id, was_created = _upsert_signal(
            conn, firm_id, "job_posting_open", fp, our_first_seen, our_last_seen, repost, evidence
        )
        created += int(was_created)
        updated += int(not was_created)

        for r in rows:
            _append_sighting(conn, signal_id, r)
            sightings += 1

    return created, updated, sightings


def write_multi_opening_signals(conn) -> tuple[int, int]:
    """>= N distinct OPEN job_posting_open signals for one firm -> one
    multi_opening signal. Recomputed fresh every run from the current state of
    `signal` -- purely derived, no separate bookkeeping needed."""
    min_open = signal_rules()["signals"]["multi_opening_min_open_roles"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT firm_id, min(first_seen) AS first_seen, max(last_seen) AS last_seen, "
            "count(*) AS n, "
            # The open roles themselves travel in the evidence: the 1C opener is "you
            # have {role} and {role_2} both posted", and signal evidence is immutable
            # once written, so it has to be complete at insert.
            "jsonb_agg(jsonb_build_object("
            "'canonical_role', evidence->>'canonical_role', 'title', evidence->>'title', "
            "'posted_date', evidence->>'posted_date', 'url', evidence->>'url') "
            "ORDER BY first_seen) AS roles "
            "FROM signal WHERE kind = 'job_posting_open' AND closed_at IS NULL "
            "GROUP BY firm_id HAVING count(*) >= %s",
            (min_open,),
        )
        groups = cur.fetchall()

    created = updated = 0
    for g in groups:
        week = floor_to_week(g["last_seen"].date())
        fp = hashlib.sha1(f"{g['firm_id']}|{week.isoformat()}".encode()).hexdigest()  # noqa: S324
        evidence = {"open_job_posting_count": g["n"], "roles": g["roles"]}
        _, was_created = _upsert_signal(
            conn, g["firm_id"], "multi_opening", fp, g["first_seen"], g["last_seen"], 0, evidence
        )
        created += int(was_created)
        updated += int(not was_created)
    return created, updated


# ─── internal_jobs fit attributes (never a signal) ────────────────────────────

_RUNG_CONFIDENCE = {1: 0.9, 2: 0.9, 3: 0.9, 4: 0.9, 6: 0.6}


def _repeat_role_count(rows: list[Posting], firm_row: dict) -> int:
    """"Same role posted N times" -- max, over roles, of the number of DISTINCT
    fingerprints (firm+role+metro+week-of-earliest, the identical formula used
    for a live job_posting_open signal) that role's postings in this history fall
    into. internal_jobs postings never get an actual `signal` row, but reusing
    the fingerprint formula is what makes three postings of "paralegal" spread
    across three genuinely different hiring windows count as churn (3), while
    three postings that are really one still-being-relisted opening count as
    one."""
    fps_by_role: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        metro = metro_code_for(r, firm_row)
        fps_by_role[r.canonical_role].add(
            posting_fingerprint(r.firm_id, r.canonical_role, metro, effective_date(r))
        )
    return max((len(fps) for fps in fps_by_role.values()), default=0)


def _latest_attribute_value(conn, firm_id: str, attr: str, source: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM firm_attribute WHERE firm_id = %s AND attr = %s AND source = %s "
            "ORDER BY observed_at DESC LIMIT 1",
            (firm_id, attr, source),
        )
        row = cur.fetchone()
        return row["value"] if row else None


def _upsert_attribute_if_changed(
    conn, firm_id: str, attr: str, value, source: str, confidence: float, evidence: str
) -> bool:
    """firm_attribute is an append-only observation log (its PK includes
    observed_at), so idempotency has to be judged by content: skip the write
    entirely when the most recent value for this (firm, attr, source) already
    matches -- a pure re-run over unchanged raw_posting rows then adds nothing."""
    if _latest_attribute_value(conn, firm_id, attr, source) == value:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO firm_attribute (firm_id, attr, value, source, confidence, evidence, "
            "observed_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
            (firm_id, attr, Jsonb(value), source, confidence, evidence),
        )
    return True


def write_internal_jobs_fit_claims(conn, resolved_internal: list[tuple[Posting, dict]]) -> int:
    """`resolved_internal` is (posting, firm_row) for every support-role
    internal_jobs posting that resolved to a firm. NEVER writes a signal, NEVER
    sets intent -- context/50-first-party/05-job-history.md, "What it must NOT
    do". Writes the four fit-score claims per firm, each tagged
    source='internal_jobs' so they stay withdrawable."""
    grouped: dict[str, list[Posting]] = defaultdict(list)
    firm_rows: dict[str, dict] = {}
    for p, firm_row in resolved_internal:
        grouped[p.firm_id].append(p)
        firm_rows[p.firm_id] = firm_row

    claims_written = 0
    for firm_id, rows in grouped.items():
        firm_row = firm_rows[firm_id]
        roles = sorted({r.canonical_role for r in rows})
        dates = [r.board_posted_date for r in rows if r.board_posted_date]
        last_attempt = max(dates).isoformat() if dates else None
        repeat_count = _repeat_role_count(rows, firm_row)

        contributing_rungs = {r.resolution_rung for r in rows if r.resolution_rung is not None}
        confidence = min(
            (_RUNG_CONFIDENCE.get(rung, 0.6) for rung in contributing_rungs), default=0.6
        )

        example = max(rows, key=lambda r: r.board_posted_date or r.fetched_at.date())
        example_date = (example.board_posted_date or example.fetched_at.date()).isoformat()
        evidence = (
            f"{len(rows)} support postings in job history, e.g. "
            f"'{example.title}' {example_date}"
        )

        claims_written += sum(
            [
                _upsert_attribute_if_changed(
                    conn, firm_id, "has_hired_support_roles", True,
                    "internal_jobs", confidence, evidence,
                ),
                _upsert_attribute_if_changed(
                    conn, firm_id, "support_roles_posted", roles,
                    "internal_jobs", confidence, evidence,
                ),
                _upsert_attribute_if_changed(
                    conn, firm_id, "last_known_hiring_attempt", last_attempt,
                    "internal_jobs", confidence, evidence,
                ),
                _upsert_attribute_if_changed(
                    conn, firm_id, "repeat_role_count", repeat_count,
                    "internal_jobs", confidence, evidence,
                ),
            ]
        )
    return claims_written
