"""ingest_renormalize -- rows loaded before the canonical payload existed.

The first 36,814 observations carry the vendor's own column names as their
payload. Downstream steps now read canonical keys only, so each legacy row is
re-read through the same sniff + normalize path a fresh upload takes: the map
is sniffed once from the legacy keys, every payload becomes the canonical row
with the original kept under `_raw`, and the observation's own columns
(phone, address hash, ZIP, city, state) are filled where the sheet had them.

Identity keys (name_stem, domain) are recomputed by the same rule that first
computed them; on a resolved row a changed key is reported, never written --
that would silently desync the row from its firm.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from lge.ingest.load import DOMAIN_RULE_VERSION
from lge.ingest.normalize import NORMALIZE_VERSION, normalize_row
from lge.ingest.sniff import sniff_columns
from lge.norm import NORM_VERSION, norm_addr
from lge.registry import RunContext, RunResult, component

_CHUNK = 2000


def is_legacy(payload: dict[str, Any]) -> bool:
    return "firm_name" not in payload and "_raw" not in payload


@component(
    "ingest_renormalize", "I",
    "Rewrite pre-canonical observation payloads into the canonical row shape.",
)
def ingest_renormalize(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    source = str(opts.get("source_tag", "internal_firms"))
    result = RunResult()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, payload, firm_id, name_stem, domain FROM observation "
            "WHERE source = %s ORDER BY id",
            (source,),
        )
        rows = [r for r in cur.fetchall() if is_legacy(r["payload"])]
    if not rows:
        return RunResult(notes=[f"no legacy payloads under source {source}"])

    headers = sorted({k for r in rows[:500] for k in r["payload"]})
    colmap = sniff_columns(headers, [r["payload"] for r in rows[:500]])
    result.notes.append(
        "column map: " + ", ".join(f"{f}<-{c}" for f, c in sorted(colmap.mapping.items()))
    )
    if colmap.missing:
        result.notes.append(f"mandatory groups the legacy sheet lacks: {colmap.missing}")

    updates: list[tuple] = []
    key_changed = 0
    for r in rows:
        raw = {k: ("" if v is None else str(v)) for k, v in r["payload"].items()}
        norm = normalize_row(raw, colmap)
        if r["firm_id"] is not None and (norm["name_stem"], norm["domain"]) != (
            r["name_stem"], r["domain"]
        ):
            key_changed += 1
            # keep the row's identity as resolved; still canonicalise the payload
            norm["name_stem"], norm["domain"] = r["name_stem"], r["domain"]
        payload = dict(norm)
        payload["_raw"] = r["payload"]
        payload["_legacy"] = True
        addr = norm_addr(norm.get("address"), norm.get("city"), norm.get("state"), norm.get("zip"))
        versions = {
            "norm_domain": NORM_VERSION["norm_domain"],
            "norm_name": NORM_VERSION["norm_name"],
            "i1_domain_rule": DOMAIN_RULE_VERSION,
            "normalize": NORMALIZE_VERSION,
        }
        updates.append(
            (
                Jsonb(payload), norm.get("firm_name"), norm["name_stem"], norm["domain"],
                norm.get("phone_e164"), addr.addr_hash, addr.zip5 or norm.get("zip"),
                norm.get("city"), norm.get("state"), Jsonb(versions), r["id"],
            )
        )

    for start in range(0, len(updates), _CHUNK):
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE observation SET payload = %s, name_raw = %s, name_stem = %s, domain = %s, "
                "phone_e164 = COALESCE(%s, phone_e164), addr_hash = COALESCE(%s, addr_hash), "
                "zip5 = COALESCE(%s, zip5), city = COALESCE(%s, city), "
                "state = COALESCE(%s, state), norm_versions = norm_versions || %s "
                "WHERE id = %s",
                updates[start : start + _CHUNK],
            )
        result.processed += min(_CHUNK, len(updates) - start)
        ctx.checkpoint()

    result.notes.append(f"rewritten: {len(updates)} legacy payload(s)")
    if key_changed:
        result.notes.append(
            f"{key_changed} resolved row(s) would change identity key under the current rule "
            "-- kept as resolved; review before re-keying"
        )
    return result
