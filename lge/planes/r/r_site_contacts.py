"""r_site_contacts -- turns team-page findings into people (Plane R,
context/40-pipeline/02-component-register.md).

Reads two `firm_attribute` claim kinds and creates/updates `contact` rows:

  * `decision_makers` (source LIKE 'llm:%', e.g. 'llm:p8:v2' / 'llm:p9:v2')
    -- P8/P9's list of {name, title, role, evidence}. Every entry here
    already passed `grounding.ground()` before it reached `firm_attribute`
    (lge/llm/grounding.py: "A decision maker whose name does not appear in
    the text is dropped") -- this component adds no further invention. It
    writes exactly the people the claim names, nothing more.
  * `jsonld_people` (source 'site:jsonld') -- P5's deterministic
    {name, jobTitle} list, informational until now. `classify_role()`
    supplies the role P5 itself never assigns.
  * `site_people` (source 'site:page') -- px_site_facts' {name, title, url,
    confidence} list read off the team and attorneys pages (D-031). Role
    from the printed title via `classify_role()`; a person named without a
    title is kept at the extractor's own (lower) confidence so a printed
    email can still be attached to them.

Only the MOST RECENT claim of each kind per firm is used (a prompt-rev bump
or a P9 escalation supersedes an older pass rather than stacking on top of
it) -- the same "latest wins" reading `p9_escalate.py` uses for its own
trigger query.

Dedupe is against existing `contact` rows for the firm, matched by a name
normalised for case/punctuation/middle-initial (`_norm_person_name` below --
deliberately NOT `lge.norm.norm_name`, which is tuned for FIRM names, e.g.
stripping "Group"/"LLC"; applying it to a person's name risks collapsing two
different people who happen to share a corporate-sounding surname). A
matched contact is upgraded in place (title/role/confidence/source
overwritten) only when the new read is at least as strong as what is on
file already -- role rank first (owner > admin > attorney > unknown), then
confidence as the tiebreaker -- so a confident site read never gets quietly
overwritten by a weaker one processed later in the same run, and a known
owner is never downgraded to unknown because a page's phrasing was
ambiguous. The firm's own site outranking a purchased vendor row is exactly
this rule in practice, not a separate special case.

Idempotency: `ctx.once()` keyed on the firm id and a hash of the exact claim
rows under consideration, so a re-run with no new/changed claims is a no-op.
This component is neither network-bound nor paid -- `ctx.checkpoint()` per
firm is cheap insurance for a full-universe CLI run, not a resilience
requirement the way it is for R4.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lge.classify.people import person_name
from lge.classify.roles import classify_role
from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "r_site_contacts"

# Role strength ordering for the "upgrade only if at least as strong" rule --
# higher beats lower. An unrecognised/missing role sorts as weakest.
_ROLE_RANK = {"owner": 3, "admin": 2, "attorney": 1, "unknown": 0}

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _role_rank(role: str | None) -> int:
    return _ROLE_RANK.get(role or "unknown", 0)




def _norm_person_name(name: str | None) -> str:
    """Case/punctuation/middle-initial-insensitive key for matching one
    PERSON's name across sources. "John Q. Smith", "John Q Smith", and
    "john smith" all collapse to "john smith" -- a lone single-letter token
    (a middle initial) is dropped, but a full middle NAME is kept, since
    dropping it risks colliding two different people."""
    if not name:
        return ""
    text = _PUNCT_RE.sub(" ", name.casefold())
    tokens = [t for t in _WS_RE.split(text) if t and len(t) > 1]
    return " ".join(tokens)


def _select_firm_ids(conn, opts: dict[str, Any]) -> list[Any]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        return [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    query = (
        "SELECT DISTINCT firm_id FROM firm_attribute "
        "WHERE attr IN ('decision_makers', 'jsonld_people', 'site_people') ORDER BY firm_id"
    )
    params: list[Any] = []
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [r["firm_id"] for r in cur.fetchall()]


def _latest_claim(conn, firm_id: Any, attr: str, source_pattern: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value, source, confidence, observed_at FROM firm_attribute "
            "WHERE firm_id = %s AND attr = %s AND source LIKE %s "
            "ORDER BY observed_at DESC LIMIT 1",
            (firm_id, attr, source_pattern),
        )
        return cur.fetchone()


def _existing_contacts_by_key(conn, firm_id: Any) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, full_name, title, role, confidence FROM contact WHERE firm_id = %s",
            (firm_id,),
        )
        rows = cur.fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        key = _norm_person_name(row["full_name"])
        if key:
            out[key] = row
    return out


def _upsert_person(
    conn,
    firm_id: Any,
    existing: dict | None,
    *,
    name: str,
    title: str | None,
    role: str,
    confidence: float,
    source: str,
    now: datetime,
) -> tuple[str, dict]:
    """Insert a new contact, or upgrade `existing` in place, per the
    role-rank-then-confidence rule described in the module docstring.
    Returns (outcome, snapshot) where outcome is 'inserted' | 'upgraded' |
    'skipped' and snapshot is the row now on file for this key (used or
    unused for the next entry that matches the same normalised name)."""
    if existing is None:
        new_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contact
                    (id, firm_id, full_name, title, role, source, confidence, enriched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (new_id, firm_id, name, title, role, source, confidence, now),
            )
        return "inserted", {
            "id": new_id, "full_name": name, "title": title,
            "role": role, "confidence": confidence,
        }

    existing_rank = _role_rank(existing["role"])
    new_rank = _role_rank(role)
    existing_confidence = (
        float(existing["confidence"]) if existing["confidence"] is not None else 0.0
    )
    not_stronger = new_rank == existing_rank and confidence <= existing_confidence
    if new_rank < existing_rank or not_stronger:
        return "skipped", existing

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE contact SET title = %s, role = %s, confidence = %s, "
            "source = %s, enriched_at = %s WHERE id = %s",
            (title, role, confidence, source, now, existing["id"]),
        )
    snapshot = dict(existing)
    snapshot.update(title=title, role=role, confidence=confidence)
    return "upgraded", snapshot


def _apply_claim_entries(
    conn,
    firm_id: Any,
    existing_by_key: dict[str, dict],
    entries: list[dict],
    *,
    classify: Any,  # entry (dict) -> (title, role, confidence)
    source: str,
    now: datetime,
    counts: dict[str, int],
) -> None:
    for entry in entries:
        name = person_name(entry.get("name"))
        if not name:
            counts["not_a_person"] = counts.get("not_a_person", 0) + 1
            continue
        key = _norm_person_name(name)
        if not key:
            continue
        title, role, confidence = classify(entry)
        outcome, snapshot = _upsert_person(
            conn, firm_id, existing_by_key.get(key),
            name=name, title=title, role=role, confidence=confidence,
            source=source, now=now,
        )
        counts[outcome] += 1
        existing_by_key[key] = snapshot


@component(
    "r_site_contacts", "R",
    "Turns team-page findings (LLM decision_makers, P5 jsonld_people, site_people) into contacts",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    result = RunResult()
    now = datetime.now(UTC)

    for firm_id in _select_firm_ids(conn, opts):
        try:
            dm_claim = _latest_claim(conn, firm_id, "decision_makers", "llm:%")
            people_claim = _latest_claim(conn, firm_id, "jsonld_people", "site:jsonld")
            site_claim = _latest_claim(conn, firm_id, "site_people", "site:page")

            if dm_claim is None and people_claim is None and site_claim is None:
                result.skipped += 1
                continue

            hash_payload = {
                "dm": [dm_claim["value"], dm_claim["source"], str(dm_claim["observed_at"])]
                if dm_claim else None,
                "people": [
                    people_claim["value"], people_claim["source"], str(people_claim["observed_at"])
                ] if people_claim else None,
                "site": [site_claim["value"], str(site_claim["observed_at"])]
                if site_claim else None,
            }
            input_hash = hashlib.sha256(
                json.dumps(hash_payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()

            with ctx.once(_COMPONENT_NAME, str(firm_id), input_hash) as should_run:
                if not should_run:
                    result.skipped += 1
                    continue

                existing_by_key = _existing_contacts_by_key(conn, firm_id)
                counts = {"inserted": 0, "upgraded": 0, "skipped": 0}

                if dm_claim:
                    dm_confidence = float(dm_claim["confidence"])

                    def _classify_dm(
                        entry: dict[str, Any], _conf: float = dm_confidence
                    ) -> tuple[str | None, str, float]:
                        return entry.get("title"), entry.get("role") or "unknown", _conf

                    _apply_claim_entries(
                        conn, firm_id, existing_by_key, dm_claim["value"],
                        classify=_classify_dm, source="site:llm", now=now, counts=counts,
                    )

                if people_claim:
                    def _classify_jsonld(entry: dict[str, Any]) -> tuple[str | None, str, float]:
                        title = entry.get("title")
                        role_result = classify_role(title)
                        return title, role_result.role, role_result.confidence

                    _apply_claim_entries(
                        conn, firm_id, existing_by_key, people_claim["value"],
                        classify=_classify_jsonld, source="site:jsonld", now=now, counts=counts,
                    )

                if site_claim:
                    def _classify_site(entry: dict[str, Any]) -> tuple[str | None, str, float]:
                        title = entry.get("title")
                        if not title:
                            return None, "unknown", float(entry.get("confidence") or 0.5)
                        role_result = classify_role(title)
                        return title, role_result.role, role_result.confidence

                    _apply_claim_entries(
                        conn, firm_id, existing_by_key, site_claim["value"],
                        classify=_classify_site, source="site:page", now=now, counts=counts,
                    )

                result.notes.append(
                    f"{firm_id}: inserted={counts['inserted']} "
                    f"upgraded={counts['upgraded']} skipped={counts['skipped']}"
                )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- per-firm isolation, never global
            result.failed += 1
            result.notes.append(f"r_site_contacts firm={firm_id}: {exc}")
        ctx.checkpoint()

    return result
