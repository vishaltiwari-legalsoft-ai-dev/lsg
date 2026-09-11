"""suppression_load — the customer-domain suppression list.

Reads a customer-list CSV, auto-detects a domain-shaped column, normalises each
value through norm_domain / norm_email_domain, and writes `suppression`
(scope='domain', reason='customer'). This is what invariant I2
(trg_outreach_touch_suppression, sql/001_schema.sql) checks against at send time --
it is what keeps a paying customer from ever being contacted as a prospect.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import UTC, datetime

from lge.norm import norm_domain, norm_email_domain
from lge.planes.i.i1_firms import _batched_insert, _resolve_path
from lge.registry import RunContext, RunResult, component

# Priority order when more than one header looks like it could hold the domain --
# an explicit "domain"/"website"/"url" column beats falling back to deriving a
# domain from an "email" column.
_COLUMN_PRIORITY = ("domain", "website", "url", "email")


def _detect_column(fieldnames: list[str]) -> str | None:
    lowered = {fn.strip().lower(): fn for fn in fieldnames}
    for key in _COLUMN_PRIORITY:
        if key in lowered:
            return lowered[key]
    for fn in fieldnames:
        low = fn.strip().lower()
        if any(key in low for key in _COLUMN_PRIORITY):
            return fn
    return None


def _normalize(raw: str) -> str | None:
    """Email-shaped values MUST go through norm_email_domain, not norm_domain:
    norm_domain() strips userinfo (the "user@" in a URL's netloc) and would happily
    read "someone@gmail.com" as host "gmail.com" -- successfully, since it has no
    idea about the free-mail blocklist (that check lives only in
    norm_email_domain). Routing every "@"-containing value through
    norm_email_domain first is what keeps a customer's personal Gmail address from
    ever becoming a `gmail.com` suppression entry -- which would suppress every
    firm anyone happens to run Gmail at."""
    value = (raw or "").strip()
    if not value:
        return None
    if "@" in value:
        return norm_email_domain(value)
    return norm_domain(value)


@component(
    "suppression_load",
    "i",
    "Load a customer-domain CSV into suppression (scope=domain, reason=customer).",
)
def suppression_load(ctx: RunContext, **opts: object) -> RunResult:
    raw_path = opts.get("path")
    if not raw_path:
        raise ValueError("suppression_load requires --opt path=<csv file>")
    path = _resolve_path(str(raw_path))
    if not path.is_file():
        raise FileNotFoundError(f"suppression_load: no such file: {path}")

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    column = _detect_column(fieldnames)
    if column is None:
        raise ValueError(
            f"suppression_load: no domain/website/url/email-shaped column found in "
            f"{path} (columns: {fieldnames})"
        )

    now = datetime.now(UTC)
    reject_reasons: Counter[str] = Counter()
    supp_rows: list[tuple] = []

    for row in rows:
        raw = row.get(column) or ""
        domain = _normalize(raw)
        if domain is None:
            reason = "blank" if not raw.strip() else "invalid_or_blocked_host"
            reject_reasons[reason] += 1
            continue
        supp_rows.append(("domain", domain, "customer", now))

    with ctx.conn.cursor() as cur:
        # ON CONFLICT (scope, value) DO NOTHING -- suppression's own PK -- covers
        # both a genuine re-run of this file AND in-file duplicate rows landing on
        # the same normalized domain, in one mechanism.
        inserted = _batched_insert(
            cur,
            "suppression",
            ("scope", "value", "reason", "added_at"),
            ("scope", "value"),
            supp_rows,
        )

    total_rejected = sum(reject_reasons.values())
    notes = [
        f"column used: {column!r}",
        f"rows read: {len(rows)}",
        f"rows loaded (new suppression rows): {inserted}",
        f"rows rejected: {total_rejected}",
        f"rows already suppressed (duplicate domain, this file or a prior load): "
        f"{len(supp_rows) - inserted}",
    ]
    for reason, n in sorted(reject_reasons.items()):
        notes.append(f"  rejected ({reason}): {n}")

    return RunResult(
        processed=len(rows),
        skipped=len(rows) - inserted - total_rejected,
        failed=0,
        notes=notes,
    )
