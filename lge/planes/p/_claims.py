"""Shared helpers for the profile plane's deterministic components (P5, P6, P7,
px_site_rules): firm selection, document/document_text access, the claims writer,
and the idempotency-hash builder every one of them uses identically.

Nothing here is a component itself -- no `@component` registration in this module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lge.fetch.decode import decode_html
from lge.store.objects import ObjectStore

# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def write_claim(
    conn: psycopg.Connection,
    firm_id: Any,
    attr: str,
    value: Any,
    source: str,
    confidence: float,
    evidence: str | None,
    observed_at: Any,
) -> bool:
    """Insert one `firm_attribute` claim. `value` is stored as jsonb -- pass a
    plain JSON-able Python value (str, bool, list, dict, ...), not a pre-serialized
    string.

    PK is (firm_id, attr, source, observed_at); a re-run over the same documents
    computes the same observed_at (the source document's fetched_at). These are
    DETERMINISTIC claims re-derived from stored HTML, so when a corrected rule
    produces a different value for the same observation the claim is updated in
    place — the raw HTML, not the claim, is the audit trail. Unchanged re-runs
    write nothing (the WHERE guard). LLM claims instead version their source tag
    (llm:p8:v1 -> v2), per the extraction contract. Returns True iff a row was
    inserted or changed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO firm_attribute
                (firm_id, attr, value, source, confidence, evidence, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (firm_id, attr, source, observed_at) DO UPDATE
               SET value = EXCLUDED.value, confidence = EXCLUDED.confidence,
                   evidence = EXCLUDED.evidence
             WHERE (firm_attribute.value, firm_attribute.confidence, firm_attribute.evidence)
                   IS DISTINCT FROM (EXCLUDED.value, EXCLUDED.confidence, EXCLUDED.evidence)
            """,
            (firm_id, attr, Jsonb(value), source, confidence, evidence, observed_at),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def compute_input_hash(content_hashes: Iterable[str | None], version: str) -> str:
    """`ctx.once` input hash: sorted content hashes of every document considered,
    plus a version string that captures the classifier/config in play. Bumping
    `version` (a code-logic bump, or a config file's own fingerprint changing)
    forces a re-parse of unchanged stored HTML without touching the crawl."""
    h = hashlib.sha256()
    for chash in sorted(str(c) for c in content_hashes if c):
        h.update(chash.encode("utf-8"))
        h.update(b"\x00")
    h.update(b"\x01")
    h.update(version.encode("utf-8"))
    return h.hexdigest()


def config_fingerprint(*paths: Path) -> str:
    """sha256 over the given config files' bytes, in the order given. Folded into
    a component's version string so an edit to its yaml config (not just a code
    change) also forces a re-parse."""
    h = hashlib.sha256()
    for path in paths:
        h.update(Path(path).read_bytes())
        h.update(b"\x00")
    # The TEXT these components read depends on the HTML decoder and P4's extractor,
    # not only on the raw HTML hash. Found after the probe: a decoding fix re-extracted
    # document_text, yet P5-P7 skipped every firm as "unchanged input". Folding the
    # text pipeline's own versions in makes a text-level change invalidate them too.
    h.update(_TEXT_PIPELINE_VERSION.encode())
    return h.hexdigest()


def _text_pipeline_version() -> str:
    from lge.planes.p.p4_text import EXTRACTOR  # local import: p4 imports this module

    return f"decode2|{EXTRACTOR}"


_TEXT_PIPELINE_VERSION = _text_pipeline_version()


# ---------------------------------------------------------------------------
# Firm selection
# ---------------------------------------------------------------------------


def select_firm_ids(
    conn: psycopg.Connection,
    *,
    firm_ids_file: str | None = None,
    limit: str | int | None = None,
) -> list[Any]:
    """`--opt firm_ids_file=<path>` (one id per line) takes precedence; otherwise
    firms that have at least one `document` row, optionally capped by `limit`
    (accepts the string CLI passes through `--opt limit=N` or the int the CLI's
    own `--limit` flag sets)."""
    if firm_ids_file:
        path = Path(firm_ids_file)
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    lim = int(limit) if limit not in (None, "") else None
    query = "SELECT DISTINCT firm_id FROM document WHERE firm_id IS NOT NULL ORDER BY firm_id"
    params: list[Any] = []
    if lim is not None:
        query += " LIMIT %s"
        params.append(lim)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [row["firm_id"] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Document access
# ---------------------------------------------------------------------------


def fetch_documents(
    conn: psycopg.Connection,
    firm_id: Any,
    *,
    page_kinds: Sequence[str] | None = None,
    fetch_ok_only: bool = True,
    status_200_only: bool = False,
) -> list[dict]:
    """Raw `document` rows for one firm, oldest-fetched first (a stable,
    deterministic order every re-run reproduces)."""
    clauses = ["firm_id = %s", "soft_404 = false"]
    params: list[Any] = [firm_id]
    if fetch_ok_only:
        clauses.append("fetch_ok = true")
    if status_200_only:
        clauses.append("status_code = 200")
    if page_kinds:
        clauses.append("page_kind = ANY(%s)")
        params.append(list(page_kinds))

    query = (
        "SELECT id, page_kind, url, object_key, content_hash, word_count, "
        "status_code, fetch_ok, fetched_at FROM document WHERE "
        + " AND ".join(clauses)
        + " ORDER BY fetched_at ASC, id ASC"
    )
    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 (clauses are fixed strings, not user input)
        return cur.fetchall()


def fetch_documents_with_text(
    conn: psycopg.Connection,
    firm_id: Any,
    *,
    page_kinds: Sequence[str] | None = None,
    fetch_ok_only: bool = True,
) -> list[dict]:
    """`document` LEFT JOIN `document_text` for one firm -- `main_text`/`word_count`
    come back None for a page P4 hasn't stripped yet, tolerated by callers."""
    clauses = ["d.firm_id = %s", "d.soft_404 = false"]
    params: list[Any] = [firm_id]
    if fetch_ok_only:
        clauses.append("d.fetch_ok = true")
    if page_kinds:
        clauses.append("d.page_kind = ANY(%s)")
        params.append(list(page_kinds))

    query = (
        "SELECT d.id AS document_id, d.page_kind, d.url, d.object_key, d.content_hash, "
        "d.fetched_at, dt.main_text, dt.word_count "
        "FROM document d LEFT JOIN document_text dt ON dt.document_id = d.id "
        "WHERE " + " AND ".join(clauses) + " ORDER BY d.fetched_at ASC, d.id ASC"
    )
    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 (clauses are fixed strings, not user input)
        return cur.fetchall()


def read_html(store: ObjectStore, object_key: str | None) -> str:
    """Raw HTML for one document's object_key, or "" when there is nothing to
    read (no key, or the object is missing from this store) -- callers treat
    that the same as a page with no signal rather than raising."""
    if not object_key:
        return ""
    try:
        return decode_html(store.get(object_key))
    except FileNotFoundError:
        return ""
