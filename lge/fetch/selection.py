"""Firm selection -- the one contract every P/JA component in this file set
shares: `--opt firm_ids_file=<path>` (one UUID per line, no filtering -- this
is how a firm with no domain reaches P1's NO_WEB path deliberately) or
`--opt limit=N` (firms with an open lead and a non-null domain, ordered by
id, so a run is reproducible and resumable).
"""

from __future__ import annotations

from pathlib import Path

import psycopg


def select_firm_ids(
    conn: psycopg.Connection,
    *,
    firm_ids_file: str | None = None,
    limit: int | str | None = None,
) -> list[str]:
    if firm_ids_file:
        path = Path(firm_ids_file)
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    n = int(limit) if limit is not None else None
    with conn.cursor() as cur:
        query = """
            SELECT DISTINCT f.id
            FROM firm f
            JOIN lead l ON l.firm_id = f.id AND l.closed_at IS NULL
            WHERE f.domain IS NOT NULL
            ORDER BY f.id
        """
        if n is not None:
            cur.execute(query + " LIMIT %s", (n,))
        else:
            cur.execute(query)
        return [str(row["id"]) for row in cur.fetchall()]


def already_done(
    conn: psycopg.Connection, component: str, input_hashes: dict[str, str]
) -> set[str]:
    """Which entity_ids in `input_hashes` already have a status='ok'
    task_run row for their given input_hash.

    Used to filter live network work OUT of the async fetch phase before it
    happens -- `ctx.once` alone only protects the DB write that follows,
    which is too late to save the request itself from being made twice.
    """
    done: set[str] = set()
    if not input_hashes:
        return done
    with conn.cursor() as cur:
        for entity_id, input_hash in input_hashes.items():
            cur.execute(
                "SELECT 1 FROM task_run WHERE component = %s AND entity_id = %s "
                "AND input_hash = %s AND status = 'ok'",
                (component, entity_id, input_hash),
            )
            if cur.fetchone() is not None:
                done.add(entity_id)
    return done
