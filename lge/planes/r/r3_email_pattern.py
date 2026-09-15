"""r3_email_pattern -- learn each firm's local-part email pattern from
existing `contact_email` rows on the firm's domain, then apply it to
contacts at that firm with no email at all (Plane R,
context/40-pipeline/02-component-register.md; context/60-execution/
04-risk-register.md: "Guessed email addresses ... Every inferred address
from R3 still goes through R4").

Learning
--------
Only `contact_email` rows whose email domain equals `firm.domain` count as
evidence -- a purchased vendor row on some unrelated domain says nothing
about how THIS firm assigns local parts. A vendor row's own `vendor_status`
claim (e.g. "verified") is NOT filtered on: it is acceptable evidence of the
PATTERN even though, per the risk register, it is never treated as proof the
address itself is deliverable -- that is what `status`/R4 are for, and
learning a pattern is explicitly not verifying an address.

Config (`config/resolvers.yml`, `r3_email_pattern`): a pattern is accepted
when either >= `min_support_multi` emails agree on it, or the firm has
exactly one known email in total and that one email matches a pattern
(`min_support_single`). A firm whose known emails disagree (no pattern
reaches the multi-support bar, and there is more than one email) gets no
claim and nothing is inferred -- guessing from a split vote is exactly the
"Guessed email addresses" risk this component exists to avoid.

Application
-----------
The learned pattern is applied only to contacts at the SAME firm with zero
`contact_email` rows (typically the site-derived owners/admins R3 exists to
serve) -- never to a freemail or non-US-firm domain. The inserted row's
`status` is always 'unverified': R3 never marks anything verified, and R4
selects on exactly that status.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from psycopg.types.json import Jsonb

from lge.norm import FREEMAIL_BLOCKLIST, norm_email_domain
from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "r3_email_pattern"
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "resolvers.yml"

# Order matters only as a tie-break. The last six were added when search
# results started supplying real addresses (D-035): jsmith@ and john.smith@
# are the common law-firm schemes, but johnsmith@, john_smith@, smithj@,
# j.smith@, smith.john@ and smithjohn@ are all seen on the probe.
_PATTERN_CHOICES = (
    "first.last", "flast", "first", "firstl", "last",
    "firstlast", "first_last", "lastf", "f.last", "last.first", "lastfirst",
)
_NAME_TOKEN_RE = re.compile(r"[^A-Za-z]")


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["r3_email_pattern"]


def _name_parts(full_name: str | None) -> tuple[str, str] | None:
    if not full_name:
        return None
    tokens = [_NAME_TOKEN_RE.sub("", t) for t in full_name.strip().split()]
    tokens = [t for t in tokens if t]
    if len(tokens) < 2:
        return None
    return tokens[0].lower(), tokens[-1].lower()


def infer_pattern(full_name: str | None, email: str) -> str:
    """One of _PATTERN_CHOICES, or 'other' when the local part matches none
    of them (including when `full_name` has no usable first+last pair)."""
    parts = _name_parts(full_name)
    if parts is None:
        return "other"
    first, last = parts
    if not first or not last:
        return "other"
    local = email.split("@", 1)[0].lower()
    for pattern in _PATTERN_CHOICES:
        if local == _render(first, last, pattern):
            return pattern
    return "other"


def _render(first: str, last: str, pattern: str) -> str:
    return {
        "first.last": f"{first}.{last}",
        "flast": f"{first[0]}{last}",
        "first": first,
        "firstl": f"{first}{last[0]}",
        "last": last,
        "firstlast": f"{first}{last}",
        "first_last": f"{first}_{last}",
        "lastf": f"{last}{first[0]}",
        "f.last": f"{first[0]}.{last}",
        "last.first": f"{last}.{first}",
        "lastfirst": f"{last}{first}",
    }[pattern]


def render_pattern(full_name: str, pattern: str) -> str | None:
    """The inverse of infer_pattern: local part for `full_name` under
    `pattern`, or None if `full_name` has no usable first+last pair."""
    parts = _name_parts(full_name)
    if parts is None:
        return None
    first, last = parts
    if not first or not last:
        return None
    return _render(first, last, pattern)


def _learn_pattern(rows: list[dict]) -> tuple[str, int, float] | None:
    """rows: [{full_name, email}] for contact_email evidence on the firm's
    domain. Returns (pattern, support, confidence) or None if no pattern
    clears the configured support bar."""
    cfg = _config()
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        pattern = infer_pattern(row["full_name"], row["email"])
        total += 1
        if pattern in _PATTERN_CHOICES:
            counts[pattern] = counts.get(pattern, 0) + 1

    if not counts:
        return None

    # Highest count wins; a tie prefers whichever pattern sorts first in
    # _PATTERN_CHOICES, purely for a deterministic result.
    best_pattern = min(counts, key=lambda p: (-counts[p], _PATTERN_CHOICES.index(p)))
    best_support = counts[best_pattern]

    if total == 1 and best_support == 1:
        return best_pattern, 1, float(cfg["confidence_single"])
    if best_support >= int(cfg["min_support_multi"]):
        return best_pattern, best_support, float(cfg["confidence_multi"])
    return None


def _select_firm_ids(conn, opts: dict[str, Any]) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    query = (
        "SELECT DISTINCT f.id FROM firm f "
        "JOIN contact c ON c.firm_id = f.id "
        "WHERE f.domain IS NOT NULL ORDER BY f.id"
    )
    params: list[Any] = []
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["id"] for r in cur.fetchall()]


def _firm_row(conn, firm_id: Any) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, domain, country FROM firm WHERE id = %s", (firm_id,))
        return cur.fetchone()


def _domain_evidence(conn, firm_id: Any, domain: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.full_name, ce.email FROM contact_email ce "
            "JOIN contact c ON c.id = ce.contact_id "
            "WHERE c.firm_id = %s",
            (firm_id,),
        )
        rows = cur.fetchall()
    return [r for r in rows if norm_email_domain(r["email"]) == domain]


def _contacts_missing_email(conn, firm_id: Any) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.full_name FROM contact c "
            "LEFT JOIN contact_email ce ON ce.contact_id = c.id "
            "WHERE c.firm_id = %s AND ce.contact_id IS NULL",
            (firm_id,),
        )
        return cur.fetchall()


def _write_pattern_claim(
    conn, firm_id: Any, pattern: str, support: int, confidence: float, now: Any
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO firm_attribute
                (firm_id, attr, value, source, confidence, evidence, observed_at)
            VALUES (%s, 'email_pattern', %s, 'rules:r3', %s, NULL, %s)
            ON CONFLICT (firm_id, attr, source, observed_at) DO UPDATE
               SET value = EXCLUDED.value, confidence = EXCLUDED.confidence
             WHERE (firm_attribute.value, firm_attribute.confidence)
                   IS DISTINCT FROM (EXCLUDED.value, EXCLUDED.confidence)
            """,
            (firm_id, Jsonb({"pattern": pattern, "support": support}), confidence, now),
        )


@component(
    "r3_email_pattern", "R",
    "Learns a firm's email local-part pattern from known addresses, applies it to "
    "contacts with no email. Every inferred address still goes through R4.",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    now = datetime.now(UTC)

    for firm_id in _select_firm_ids(conn, opts):
        try:
            firm = _firm_row(conn, firm_id)
            if firm is None or not firm["domain"]:
                result.skipped += 1
                continue
            if firm["domain"] in FREEMAIL_BLOCKLIST:
                result.skipped += 1
                continue
            if firm["country"] not in (None, "US"):
                result.skipped += 1
                continue

            evidence = _domain_evidence(conn, firm_id, firm["domain"])
            missing = _contacts_missing_email(conn, firm_id)

            if not evidence or not missing:
                result.skipped += 1
                continue

            learned = _learn_pattern(evidence)
            if learned is None:
                result.skipped += 1
                continue
            pattern, support, confidence = learned

            input_hash = hashlib.sha256(
                json.dumps(
                    {
                        "evidence": sorted((e["full_name"], e["email"]) for e in evidence),
                        "missing": sorted(str(m["id"]) for m in missing),
                        "pattern": pattern,
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()

            with ctx.once(_COMPONENT_NAME, str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                _write_pattern_claim(conn, firm_id, pattern, support, confidence, now)

                applied = 0
                with conn.cursor() as cur:
                    for contact in missing:
                        local = render_pattern(contact["full_name"], pattern)
                        if not local:
                            continue
                        candidate = f"{local}@{firm['domain']}"
                        if norm_email_domain(candidate) != firm["domain"]:
                            continue  # belt and braces: never write off-domain
                        cur.execute(
                            """
                            INSERT INTO contact_email (contact_id, email, status, pattern)
                            VALUES (%s, %s, 'unverified', %s)
                            ON CONFLICT (contact_id, email) DO NOTHING
                            """,
                            (contact["id"], candidate, pattern),
                        )
                        applied += cur.rowcount

                result.notes.append(
                    f"{firm_id}: pattern={pattern} support={support} applied={applied}"
                )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"r3_email_pattern firm={firm_id}: {exc}")
        ctx.checkpoint()

    return result
