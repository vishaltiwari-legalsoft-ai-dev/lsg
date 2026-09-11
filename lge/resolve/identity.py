"""resolve_identity -- the hard gate. Full-set operation over `observation`,
source-agnostic (today: internal_firms; later: places, bar directories,
legal directories, sites).

See context/30-data-model/03-identity-resolution.md (the spec),
context/30-data-model/02-normalization-contracts.md, and
context/40-pipeline/06-orchestration.md ("the gate that must not be
advisory").

Algorithm
---------
1. Load every observation. Build a union-find over observation ids (module
   `lge.resolve.unionfind`).
2. R1 (domain equal) and R2 (phone equal, not shared): group directly and
   union every id in a group with the group's first id -- O(n), never
   O(n^2) pair enumeration. Shared numbers (`norm_phone.shared_numbers`)
   are excluded from R2 entirely before grouping.
3. R3 (addr_hash equal AND name_stem similarity > threshold): a single SQL
   self-join inside the addr_hash block, using pg_trgm's `similarity()`.
   Both conditions are required in the same WHERE clause -- address alone
   would merge every firm in an office tower.
4. R4 (same zip5 AND name_stem similarity > threshold, higher bar than R3):
   another SQL self-join, inside the zip5 block. R4 NEVER unions -- it only
   queues an `identity_review` row, and only for pairs the R1-R3 union-find
   pass has not already connected (checked via `uf.find()` after step 3).
5. Every connected component is inspected for the distinct existing
   `firm_id` values among its member observations:
     - none  -> create one new firm, attach every observation, write
       firm_alias for every other distinct name/domain/phone variant, open
       one DISCOVERED lead.
     - one   -> attach the component's currently-unattached observations to
       that firm. Existing firm ids never change.
     - >= 2  -> do not merge; write one identity_review row per distinct
       pair of firms in the component (rule='cross_firm').
6. Idempotent by construction: a second run with no new observations
   reproduces exactly the same components. Every "one existing firm, no
   unattached observations" component is a true no-op, and both review
   kinds are deduplicated in Python against every currently-open review row
   before insert, so a re-run never grows the queue.

Deviation from the task brief's "one transaction per chunk of components":
this component performs no internal `conn.commit()` -- the surrounding
transaction is owned by the caller (`lge run`, or the `db` test fixture,
which rolls the whole test back). At ~37k observations one transaction with
batched `executemany` calls comfortably meets the 2-minute budget, and an
internal commit would break the test fixture's per-test rollback isolation
by committing rows into the shared test database. Everything is still
batched (`executemany`) and reads only two full-table passes plus two
indexed self-joins -- never O(n^2).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from psycopg.types.json import Jsonb

from lge import db as lge_db
from lge.norm import NORM_VERSION, norm_name
from lge.norm.phone import shared_numbers
from lge.registry import RunContext, RunResult, component, gate
from lge.resolve.unionfind import UnionFind

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "identity.yml"

# R1 outranks R2 outranks R3 when tagging which rule justified a given
# firm_alias variant (see _rule_per_observation).
_RULE_PRIORITY = {"R1": 0, "R2": 1, "R3": 2}


class IdentityConfig(NamedTuple):
    r3_threshold: float
    r4_threshold: float
    shared_phone_min: int
    source_precedence: list[str]
    source_tier: dict[str, str]
    collapse_ratio_min: float
    collapse_ratio_max: float


def load_config(path: Path = _CONFIG_PATH) -> IdentityConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    thresholds = raw["thresholds"]
    gate_cfg = raw.get("gate", {})
    return IdentityConfig(
        r3_threshold=float(thresholds["r3_addr_name_similarity"]),
        r4_threshold=float(thresholds["r4_zip_name_similarity"]),
        shared_phone_min=int(thresholds["shared_phone_min_candidates"]),
        source_precedence=list(raw["source_precedence"]),
        source_tier=dict(raw.get("source_tier", {})),
        collapse_ratio_min=float(gate_cfg.get("collapse_ratio_min", 2.0)),
        collapse_ratio_max=float(gate_cfg.get("collapse_ratio_max", 3.3)),
    )


# =============================================================================
# Pure helpers -- no DB access, easy to reason about and unit test in isolation.
# =============================================================================


def _candidate_key(row: dict[str, Any]) -> str:
    """coalesce(domain, name_stem || '|' || coalesce(zip5, city, '')) --
    the shared_numbers() candidate identity, verbatim from the spec."""
    if row["domain"]:
        return row["domain"]
    return f"{row['name_stem'] or ''}|{row['zip5'] or row['city'] or ''}"


def _pick_mode(rows: list[dict[str, Any]], field: str) -> Any:
    """Most frequent non-null value of `field` across `rows`. Ties broken by
    the lowest observation id carrying that value, for determinism."""
    counts: Counter[Any] = Counter()
    first_id: dict[Any, int] = {}
    for row in rows:
        value = row.get(field)
        if value is None or value == "":
            continue
        counts[value] += 1
        if value not in first_id or row["id"] < first_id[value]:
            first_id[value] = row["id"]
    if not counts:
        return None
    top = max(counts.values())
    tied = [v for v, c in counts.items() if c == top]
    return min(tied, key=lambda v: first_id[v])


def _tier_rank(source: str, cfg: IdentityConfig) -> int:
    tier = cfg.source_tier.get(source, source)
    try:
        return cfg.source_precedence.index(tier)
    except ValueError:
        return len(cfg.source_precedence)  # unranked source -> lowest precedence


def _pick_canonical_name(rows: list[dict[str, Any]], cfg: IdentityConfig) -> str:
    best_rank = min(_tier_rank(r["source"], cfg) for r in rows)
    pool = [r for r in rows if _tier_rank(r["source"], cfg) == best_rank]
    name = _pick_mode(pool, "name_raw")
    if not name:
        name = _pick_mode(rows, "name_raw")
    return name or "Unknown Firm"


def _build_firm(rows: list[dict[str, Any]], cfg: IdentityConfig) -> dict[str, Any]:
    canonical_name = _pick_canonical_name(rows, cfg)
    return {
        "id": str(uuid.uuid4()),
        "canonical_name": canonical_name,
        "name_stem": norm_name(canonical_name),
        "domain": _pick_mode(rows, "domain"),
        "phone_e164": _pick_mode(rows, "phone_e164"),
        "addr_hash": _pick_mode(rows, "addr_hash"),
        "zip5": _pick_mode(rows, "zip5"),
        "city": _pick_mode(rows, "city"),
        "state": _pick_mode(rows, "state"),
        "first_seen": min(r["fetched_at"] for r in rows),
        "norm_versions": dict(NORM_VERSION),
    }


def _rule_per_observation(
    edges: Iterable[tuple[int, int, str]],
) -> dict[int, str]:
    """observation id -> the strongest rule (R1 > R2 > R3) among the union
    edges that touched it. Every non-singleton component member appears in
    at least one edge (union() is only ever called between two literal
    dataset ids), so this covers every id that needs an alias tag."""
    best: dict[int, str] = {}
    for obs_a, obs_b, rule in sorted(edges, key=lambda e: _RULE_PRIORITY[e[2]]):
        for node in (obs_a, obs_b):
            if node not in best:
                best[node] = rule
    return best


def _build_aliases(
    rows: list[dict[str, Any]],
    firm: dict[str, Any],
    obs_rule: dict[int, str],
    now: datetime,
) -> list[dict[str, Any]]:
    """One firm_alias row per OTHER distinct name/domain/phone variant in
    the component -- the canonical value itself is never aliased."""
    aliases: list[dict[str, Any]] = []
    seen: dict[str, set[Any]] = {
        "name": {firm["canonical_name"]},
        "domain": {firm["domain"]} if firm["domain"] else set(),
        "phone": {firm["phone_e164"]} if firm["phone_e164"] else set(),
    }
    for row in rows:
        rule = obs_rule.get(row["id"], "R3")
        for kind, field, col in (
            ("name", "name_raw", "alias_name"),
            ("domain", "domain", "alias_domain"),
            ("phone", "phone_e164", "alias_phone"),
        ):
            value = row[field]
            if not value or value in seen[kind]:
                continue
            seen[kind].add(value)
            aliases.append(
                {
                    "firm_id": firm["id"],
                    "alias_name": None,
                    "alias_domain": None,
                    "alias_phone": None,
                    col: value,
                    "source": row["source"],
                    "merge_rule": rule,
                    "merged_at": now,
                }
            )
    return aliases


# =============================================================================
# resolve_identity
# =============================================================================


@component(
    "resolve_identity",
    "resolve",
    "Cross-source firm identity resolution -- the hard gate before profiling.",
)
def resolve_identity(ctx: RunContext, **_opts: Any) -> RunResult:
    cfg = load_config()
    conn = ctx.conn
    now = datetime.now(UTC)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, source, firm_id, name_raw, name_stem, domain, phone_e164, "
            "addr_hash, zip5, city, state, fetched_at FROM observation"
        )
        rows = cur.fetchall()

    if not rows:
        return RunResult(notes=["no observations to resolve"])

    by_id: dict[int, dict[str, Any]] = {r["id"]: r for r in rows}
    uf = UnionFind(by_id.keys())

    # ---- R1: domain, direct grouping -- never pairwise ---------------------
    by_domain: dict[str, list[int]] = {}
    for r in rows:
        if r["domain"]:
            by_domain.setdefault(r["domain"], []).append(r["id"])
    for ids in by_domain.values():
        for other in ids[1:]:
            uf.union(ids[0], other, "R1")

    # ---- R2: phone, excluding shared numbers, direct grouping -------------
    phone_pairs = [(r["phone_e164"], _candidate_key(r)) for r in rows if r["phone_e164"]]
    shared = shared_numbers(phone_pairs, threshold=cfg.shared_phone_min)

    by_phone: dict[str, list[int]] = {}
    for r in rows:
        if r["phone_e164"] and r["phone_e164"] not in shared:
            by_phone.setdefault(r["phone_e164"], []).append(r["id"])
    for ids in by_phone.values():
        for other in ids[1:]:
            uf.union(ids[0], other, "R2")

    # ---- R3: addr_hash equal AND name_stem similarity > threshold ---------
    # Both conditions in one WHERE clause -- pairwise, but only inside the
    # addr_hash block (a hash self-join, not a scan of all pairs).
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o1.id AS id1, o2.id AS id2
              FROM observation o1
              JOIN observation o2 ON o2.addr_hash = o1.addr_hash AND o2.id > o1.id
             WHERE o1.addr_hash IS NOT NULL
               AND o1.name_stem IS NOT NULL AND o1.name_stem <> ''
               AND o2.name_stem IS NOT NULL AND o2.name_stem <> ''
               AND similarity(o1.name_stem, o2.name_stem) > %s
            """,
            (cfg.r3_threshold,),
        )
        for pair in cur.fetchall():
            uf.union(pair["id1"], pair["id2"], "R3")

    # ---- R4: same zip5 AND name_stem similarity > (higher) threshold ------
    # Never unions. Checked against the post-R1-R3 union-find below.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o1.id AS id1, o2.id AS id2,
                   similarity(o1.name_stem, o2.name_stem) AS sim
              FROM observation o1
              JOIN observation o2 ON o2.zip5 = o1.zip5 AND o2.id > o1.id
             WHERE o1.zip5 IS NOT NULL
               AND o1.name_stem IS NOT NULL AND o1.name_stem <> ''
               AND o2.name_stem IS NOT NULL AND o2.name_stem <> ''
               AND similarity(o1.name_stem, o2.name_stem) > %s
            """,
            (cfg.r4_threshold,),
        )
        r4_candidates = cur.fetchall()

    obs_rule = _rule_per_observation(uf.edges)

    # ---- idempotency: load every currently-open review, once -------------
    with conn.cursor() as cur:
        cur.execute(
            "SELECT left_observation_id, right_observation_id, left_firm_id, "
            "right_firm_id, rule FROM identity_review WHERE status = 'open'"
        )
        existing = cur.fetchall()
    seen_r4_pairs = {
        frozenset({row["left_observation_id"], row["right_observation_id"]})
        for row in existing
        if row["rule"] == "R4"
    }
    seen_cross_firm_pairs = {
        frozenset({row["left_firm_id"], row["right_firm_id"]})
        for row in existing
        if row["rule"] == "cross_firm"
    }

    new_firms: list[dict[str, Any]] = []
    new_aliases: list[dict[str, Any]] = []
    attach_updates: list[tuple[str, int]] = []
    new_leads: list[dict[str, Any]] = []
    cross_firm_reviews: list[dict[str, Any]] = []
    skipped_components = 0

    for member_ids in uf.components().values():
        crows = [by_id[i] for i in member_ids]
        firm_ids = {r["firm_id"] for r in crows if r["firm_id"] is not None}

        if len(firm_ids) >= 2:
            fids = sorted(firm_ids)
            for i in range(len(fids)):
                for j in range(i + 1, len(fids)):
                    pair_key = frozenset({fids[i], fids[j]})
                    if pair_key in seen_cross_firm_pairs:
                        continue
                    seen_cross_firm_pairs.add(pair_key)
                    left_obs = min(
                        (r for r in crows if r["firm_id"] == fids[i]), key=lambda r: r["id"]
                    )
                    right_obs = min(
                        (r for r in crows if r["firm_id"] == fids[j]), key=lambda r: r["id"]
                    )
                    cross_firm_reviews.append(
                        {
                            "rule": "cross_firm",
                            "reason": "cross_firm_component",
                            "left_observation_id": left_obs["id"],
                            "right_observation_id": right_obs["id"],
                            "left_firm_id": fids[i],
                            "right_firm_id": fids[j],
                            "similarity": None,
                            "status": "open",
                            "created_at": now,
                        }
                    )
            continue  # never touch observation.firm_id for a cross-firm component

        if len(firm_ids) == 1:
            (target_firm_id,) = tuple(firm_ids)
            unattached = [r for r in crows if r["firm_id"] is None]
            if not unattached:
                skipped_components += 1
                continue
            attach_updates.extend((target_firm_id, r["id"]) for r in unattached)
            continue

        # No observation in this component has a firm_id -- create one.
        firm = _build_firm(crows, cfg)
        new_firms.append(firm)
        attach_updates.extend((firm["id"], r["id"]) for r in crows)
        new_aliases.extend(_build_aliases(crows, firm, obs_rule, now))
        new_leads.append(
            {
                "id": str(uuid.uuid4()),
                "firm_id": firm["id"],
                "state": "DISCOVERED",
                "created_at": now,
            }
        )

    r4_reviews: list[dict[str, Any]] = []
    for pair in r4_candidates:
        id1, id2, sim = pair["id1"], pair["id2"], pair["sim"]
        if uf.find(id1) == uf.find(id2):
            continue  # already connected by a stronger rule -- "no R1-R3 edge" fails
        pair_key = frozenset({id1, id2})
        if pair_key in seen_r4_pairs:
            continue
        seen_r4_pairs.add(pair_key)
        left, right = by_id[id1], by_id[id2]
        r4_reviews.append(
            {
                "rule": "R4",
                "reason": "name_zip_similarity",
                "left_observation_id": id1,
                "right_observation_id": id2,
                "left_firm_id": left["firm_id"],
                "right_firm_id": right["firm_id"],
                "similarity": sim,
                "status": "open",
                "created_at": now,
            }
        )

    # ---- writes -------------------------------------------------------------
    if new_firms:
        with lge_db.writer(conn, "resolve"), conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO firm (id, canonical_name, name_stem, domain, phone_e164,
                                   addr_hash, zip5, city, state, first_seen, norm_versions)
                VALUES (%(id)s, %(canonical_name)s, %(name_stem)s, %(domain)s, %(phone_e164)s,
                        %(addr_hash)s, %(zip5)s, %(city)s, %(state)s, %(first_seen)s,
                        %(norm_versions)s)
                """,
                [{**f, "norm_versions": Jsonb(f["norm_versions"])} for f in new_firms],
            )

    if attach_updates:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE observation SET firm_id = %s WHERE id = %s", attach_updates
            )

    if new_aliases:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO firm_alias (firm_id, alias_name, alias_domain, alias_phone,
                                         source, merge_rule, merged_at)
                VALUES (%(firm_id)s, %(alias_name)s, %(alias_domain)s, %(alias_phone)s,
                        %(source)s, %(merge_rule)s, %(merged_at)s)
                """,
                new_aliases,
            )

    if new_leads:
        with lge_db.lifecycle(conn, "identity_resolution"), conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO lead (id, firm_id, state, created_at) "
                "VALUES (%(id)s, %(firm_id)s, %(state)s, %(created_at)s)",
                new_leads,
            )

    all_reviews = cross_firm_reviews + r4_reviews
    if all_reviews:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO identity_review (rule, reason, left_observation_id,
                                              right_observation_id, left_firm_id,
                                              right_firm_id, similarity, status, created_at)
                VALUES (%(rule)s, %(reason)s, %(left_observation_id)s, %(right_observation_id)s,
                        %(left_firm_id)s, %(right_firm_id)s, %(similarity)s, %(status)s,
                        %(created_at)s)
                """,
                all_reviews,
            )

    return RunResult(
        processed=len(rows),
        skipped=skipped_components,
        failed=0,
        notes=[
            f"new_firms={len(new_firms)}",
            f"observations_attached={len(attach_updates)}",
            f"aliases_written={len(new_aliases)}",
            f"leads_created={len(new_leads)}",
            f"cross_firm_reviews={len(cross_firm_reviews)}",
            f"r4_reviews={len(r4_reviews)}",
        ],
    )


# =============================================================================
# g1_identity -- hard, never advisory
# =============================================================================


@gate("g1_identity")
def g1_identity(ctx: RunContext) -> tuple[bool, str]:
    cfg = load_config()
    conn = ctx.conn
    lines: list[str] = []
    passed = True

    with conn.cursor() as cur:
        cur.execute(
            "SELECT domain, count(*) AS n FROM firm WHERE domain IS NOT NULL "
            "GROUP BY domain HAVING count(*) > 1 ORDER BY n DESC, domain"
        )
        domain_offenders = cur.fetchall()
        cur.execute(
            "SELECT phone_e164, count(*) AS n FROM firm WHERE phone_e164 IS NOT NULL "
            "GROUP BY phone_e164 HAVING count(*) > 1 ORDER BY n DESC, phone_e164"
        )
        phone_offenders = cur.fetchall()

    if domain_offenders:
        passed = False
        lines.append(f"FAIL: {len(domain_offenders)} domain(s) shared by more than one firm:")
        lines.extend(
            f"  domain={row['domain']!r} firms={row['n']}" for row in domain_offenders[:20]
        )
    else:
        lines.append("OK: no domain is shared by more than one firm")

    if phone_offenders:
        passed = False
        lines.append(
            f"FAIL: {len(phone_offenders)} phone number(s) shared by more than one firm:"
        )
        lines.extend(
            f"  phone_e164={row['phone_e164']!r} firms={row['n']}" for row in phone_offenders[:20]
        )
    else:
        lines.append("OK: no phone_e164 is shared by more than one firm")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM observation WHERE firm_id IS NOT NULL")
        resolved_obs = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM firm")
        firm_count = cur.fetchone()["n"]
        cur.execute("SELECT count(DISTINCT source) AS n FROM observation WHERE firm_id IS NOT NULL")
        distinct_sources = cur.fetchone()["n"]

    if firm_count == 0:
        lines.append("collapse ratio: n/a (no firms)")
    else:
        ratio = resolved_obs / firm_count
        if distinct_sources >= 2:
            lines.append(
                f"collapse ratio = {ratio:.2f}x ({resolved_obs} resolved observations / "
                f"{firm_count} firms), expected {cfg.collapse_ratio_min}-"
                f"{cfg.collapse_ratio_max}x ({distinct_sources} discovery sources)"
            )
            if ratio > cfg.collapse_ratio_max:
                passed = False
                lines.append("FAIL: over-merging -- check R3/R4 thresholds")
            elif ratio < cfg.collapse_ratio_min:
                passed = False
                lines.append("FAIL: under-merging -- check the NORMALIZERS, not the thresholds")
        else:
            lines.append(
                f"collapse ratio = {ratio:.2f}x ({resolved_obs} resolved observations / "
                f"{firm_count} firms) -- informational only: the "
                f"{cfg.collapse_ratio_min}-{cfg.collapse_ratio_max}x band is calibrated for "
                f"three-way discovery (Places + bar + directory), and only {distinct_sources} "
                "discovery source is resolved here, so the band does not apply to a single "
                "contact-level file"
            )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM identity_review WHERE status = 'open'")
        queue_size = cur.fetchone()["n"]
    lines.append(f"identity_review open queue: {queue_size}")

    return passed, "\n".join(lines)
