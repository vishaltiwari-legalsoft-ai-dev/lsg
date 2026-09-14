"""P4 — boilerplate stripper.

trafilatura main-text extraction from stored HTML -> `document_text`. This
never touches the network: it reads raw bytes P2 already stored in the
object store, so it is exempt from the live-network gate and is fully
re-runnable from disk whenever the extractor version bumps
(context/40-pipeline/06-orchestration.md's "backfill" rule -- a
normalizer/extractor version bump is a re-parse, never a re-crawl).

This is an ACCURACY fix, not just a size one: a law-firm footer listing
every practice area the firm ever mentioned must not reach the classifier
that reads `document_text.main_text` downstream (P5+).
"""

from __future__ import annotations

import hashlib
import logging

import psycopg
import trafilatura

from lge.fetch.decode import decode_html
from lge.fetch.selection import select_firm_ids
from lge.registry import RunContext, RunResult, component
from lge.store.objects import ObjectStore, get_store

logger = logging.getLogger("lge.planes.p4")

# "+decode2": charset-aware decoding (lge/fetch/decode.py). Part of the version so a
# decoding change re-extracts stored pages — the probe found "won’t" stored as "won�t".
EXTRACTOR = f"trafilatura:{trafilatura.__version__}+decode2"


def extract_main_text(html: str, url: str | None = None) -> str | None:
    """Thin wrapper so the extraction call site and its settings are in one
    place. favor_precision trims boilerplate harder, at some recall cost --
    the right tradeoff here since a leaked footer corrupts primary_practice
    silently downstream, while losing a paragraph of real text does not."""
    return trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        favor_precision=True,
        include_tables=False,
        include_comments=False,
    )


def _select_eligible_documents(conn: psycopg.Connection, firm_ids: list[str]) -> list[dict]:
    if not firm_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.firm_id, d.url, d.content_hash, d.object_key
            FROM document d
            LEFT JOIN document_text dt ON dt.document_id = d.id
            WHERE d.firm_id = ANY(%s)
              AND d.fetch_ok = true
              AND d.status_code BETWEEN 200 AND 299
              AND d.soft_404 = false
              AND d.object_key IS NOT NULL
              AND (dt.document_id IS NULL OR dt.extractor <> %s)
            ORDER BY d.firm_id, d.id
            """,
            (firm_ids, EXTRACTOR),
        )
        return list(cur.fetchall())


def _input_hash(rows: list[dict]) -> str:
    joined = "|".join(f"{r['id']}:{r['content_hash']}" for r in rows)
    return hashlib.sha256(f"{EXTRACTOR}|{joined}".encode()).hexdigest()


def _extract_and_write(conn: psycopg.Connection, rows: list[dict], store: ObjectStore) -> int:
    written = 0
    with conn.cursor() as cur:
        for row in rows:
            try:
                html_bytes = store.get(row["object_key"])
            except (FileNotFoundError, OSError) as exc:
                logger.warning(
                    "p4_text: object_key %s for document %s missing from the store: %s",
                    row["object_key"],
                    row["id"],
                    exc,
                )
                continue
            html = decode_html(html_bytes)
            main_text = extract_main_text(html, url=row["url"])
            word_count = len(main_text.split()) if main_text else 0
            cur.execute(
                """
                INSERT INTO document_text (document_id, main_text, word_count, extractor,
                                            extracted_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (document_id) DO UPDATE SET
                  main_text    = EXCLUDED.main_text,
                  word_count   = EXCLUDED.word_count,
                  extractor    = EXCLUDED.extractor,
                  extracted_at = EXCLUDED.extracted_at
                """,
                (row["id"], main_text, word_count, EXTRACTOR),
            )
            written += 1
    return written


@component(
    "p4_text", "P", "Boilerplate stripper: trafilatura main-text extraction into document_text"
)
def run(ctx: RunContext, *, store: ObjectStore | None = None, **opts: object) -> RunResult:
    store = store or get_store()
    result = RunResult()
    firm_ids = select_firm_ids(
        ctx.conn,
        firm_ids_file=opts.get("firm_ids_file"),
        limit=opts.get("limit"),
    )
    if not firm_ids:
        result.notes.append("no firms selected")
        return result

    docs = _select_eligible_documents(ctx.conn, firm_ids)
    if not docs:
        result.notes.append(f"no documents pending extraction at {EXTRACTOR}")
        return result

    by_firm: dict[str, list[dict]] = {}
    for row in docs:
        by_firm.setdefault(str(row["firm_id"]), []).append(row)

    for firm_id, rows in by_firm.items():
        input_hash = _input_hash(rows)
        with ctx.once("p4_text", firm_id, input_hash) as should_run:
            if not should_run:
                result.skipped += 1
                continue
            n = _extract_and_write(ctx.conn, rows, store)
            result.processed += 1
            if n < len(rows):
                result.notes.append(f"{firm_id}: extracted {n}/{len(rows)} document(s)")
        ctx.checkpoint()

    return result
