"""reconcile() -- context/30-data-model/04-attribute-reconciliation.md, the
canonical algorithm -- plus the `reconcile` component (plane "score") that
runs it set-based over every firm.

`reconcile()` is the ONLY writer of firm's resolved qualification + identity
columns (invariant I7, enforced by sql/001_schema.sql's `trg_firm_writer_check`)
-- every write here goes through `lge.db.writer(conn, 'reconcile')`.

Two entry points share one pure resolver (`resolve_claims`), never duplicated
logic with two chances to drift:

  * `reconcile(conn, firm_id, attr)` -- the spec's function, exactly. One
    firm, one attribute, one SELECT + one write. What the unit tests call.
  * the `reconcile` component -- 37k firms in minutes. Chunks firms (500 at a
    time), reads every attribute's claims for the whole chunk in ONE query
    (never one query per attribute), resolves in Python, and writes each
    chunk with one multi-row UPDATE plus one icp_tier()/fit_score() recompute
    UPDATE -- see `_reconcile_chunk`.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from dateutil import parser as dateutil_parser
from psycopg.types.json import Jsonb

from lge.db import writer
from lge.registry import RunContext, RunResult, component

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "precedence.yml"

_CHUNK_SIZE = 500

# =============================================================================
# Config -- config/precedence.yml
# =============================================================================


def source_family(source: str) -> str:
    """The tag precedence is configured by. An LLM claim's tag carries its
    prompt revision (`llm:p8:v2`) so a prompt bump re-derives cleanly, but
    precedence ranks the TIER (`llm:p8`). Matching exact tags silently dropped
    every v2 claim once prompt_rev moved past the v1 the config named. Every
    other tag is its own family."""
    if source.startswith("llm:"):
        return ":".join(source.split(":")[:2])
    return source


def _revision(source: str) -> int:
    """`llm:p8:v2` -> 2; 0 for any tag without a revision."""
    tail = source.rsplit(":", 1)[-1]
    return int(tail[1:]) if source.startswith("llm:") and tail[1:].isdigit() else 0


@dataclass(frozen=True, slots=True)
class PrecedenceConfig:
    default_freshness_days: int
    tier_determining: frozenset[str]
    exclusive_attrs: frozenset[str]
    unknown_capable: frozenset[str]
    precedence: dict[str, tuple[str, ...]]
    freshness_days: dict[str, int]  # per-attr override; none configured today

    def rank_of(self, attr: str, source: str) -> int:
        order = self.precedence.get(attr, ())
        family = source_family(source)
        if family in order:
            return order.index(family)
        return len(order)  # unlisted sources rank last

    def is_exclusive(self, attr: str) -> bool:
        return attr in self.exclusive_attrs

    def is_unknown_capable(self, attr: str) -> bool:
        return attr in self.unknown_capable

    def is_tier_determining(self, attr: str) -> bool:
        return attr in self.tier_determining

    def freshness_for(self, attr: str) -> int:
        return self.freshness_days.get(attr, self.default_freshness_days)


@functools.lru_cache(maxsize=1)
def load_precedence() -> PrecedenceConfig:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    precedence = {
        attr: tuple(sources) for attr, sources in (raw.get("precedence") or {}).items()
    }
    return PrecedenceConfig(
        default_freshness_days=int(raw["defaults"]["freshness_days"]),
        tier_determining=frozenset(raw.get("tier_determining", ())),
        exclusive_attrs=frozenset(raw.get("exclusive_attrs", ())),
        unknown_capable=frozenset(raw.get("unknown_capable", ())),
        precedence=precedence,
        freshness_days={},
    )


# =============================================================================
# Attribute -> firm column registry
# =============================================================================

# name == firm column name for every scalar attribute.
_SCALAR_COLUMNS: tuple[str, ...] = (
    "entity_kind", "attorney_count", "staff_ratio", "primary_practice",
    "practice_areas", "fee_model", "spanish_intake", "cms_detected",
    "review_count", "paid_ads_active", "has_inhouse_recruiter", "country",
    "first_seen_bar_admission", "has_hired_support_roles",
    "support_roles_posted", "last_known_hiring_attempt", "repeat_role_count",
    "canonical_name", "phone_e164",
)

_ARRAY_COLUMNS = frozenset({"practice_areas", "support_roles_posted"})

# Columns that are never nulled out by an empty/stale reconciliation run --
# `city` because it is dual-owned by `address`'s fan-out and its own attr
# (see config/precedence.yml), `canonical_name` because `firm.canonical_name`
# is NOT NULL (set once by identity resolution before reconcile() ever runs;
# reconcile() may only IMPROVE it from a higher-precedence claim, never blank
# it -- a firm silently losing its name is worse than keeping a stale one).
_COALESCE_COLUMNS = frozenset({"canonical_name", "city"})

# `address` fans out to these; `city` is dual-owned (see module docstring in
# config/precedence.yml under the `address` key) and is COALESCEd against the
# existing value rather than nulled on staleness -- everything else here is
# a direct overwrite, including to NULL, per the literal spec.
_ADDRESS_COLUMNS: tuple[str, ...] = (
    "street_norm", "addr_unit", "addr_hash", "zip5", "state", "city",
)

RECONCILED_ATTRS: tuple[str, ...] = (*_SCALAR_COLUMNS, "address", "city")

# SQL types for every firm column this module writes -- used to cast
# placeholders explicitly (single-firm path) and to declare the VALUES(...)
# column list (bulk path), so a bare Python str/list/None always lands in the
# column Postgres expects regardless of what shape a claim's jsonb value
# happens to be.
_COLUMN_TYPES: dict[str, str] = {
    "entity_kind": "text",
    "attorney_count": "int",
    "staff_ratio": "numeric",
    "primary_practice": "text",
    "practice_areas": "text[]",
    "fee_model": "text",
    "spanish_intake": "bool",
    "cms_detected": "text",
    "review_count": "int",
    "paid_ads_active": "bool",
    "has_inhouse_recruiter": "bool",
    "country": "text",
    "first_seen_bar_admission": "timestamptz",
    "has_hired_support_roles": "bool",
    "support_roles_posted": "text[]",
    "last_known_hiring_attempt": "date",
    "repeat_role_count": "int",
    "canonical_name": "text",
    "phone_e164": "text",
    "street_norm": "text",
    "addr_unit": "text",
    "addr_hash": "text",
    "zip5": "char(5)",
    "state": "char(2)",
    "city": "text",
}


def _address_row(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return dict.fromkeys(_ADDRESS_COLUMNS)
    return {
        "street_norm": value.get("street_norm"),
        "addr_unit": value.get("unit"),
        "addr_hash": value.get("addr_hash"),
        "zip5": value.get("zip5"),
        "state": value.get("state"),
        "city": value.get("city"),
    }


def _coerce_for_column(col: str, value: Any) -> Any:
    """A jsonb claim value for a date/timestamp column arrives as an ISO
    string (JSON has no native date type) -- parse it to the typed Python
    object the codebase's convention expects (context/50-first-party/
    05-job-history.md's loader does the same with dateutil). Everything else
    passes through: ints/floats/bools/strings/lists already round-trip
    correctly through psycopg's adapters."""
    if value is None:
        return None
    if col == "first_seen_bar_admission" and isinstance(value, str):
        return dateutil_parser.parse(value)
    if col == "last_known_hiring_attempt" and isinstance(value, str):
        return dateutil_parser.parse(value).date()
    if col in _ARRAY_COLUMNS:
        items = value if isinstance(value, list) else list(value)
        # P8/P9 write practice_areas in the extraction schema's shape,
        # [{"area": slug, "weight": w}], while rules:practice writes bare slugs.
        # The column holds slugs; heaviest first. A dict reaching psycopg
        # aborted the whole reconcile run the first time AI claims won.
        if any(isinstance(v, dict) for v in items):
            weighted = [v for v in items if isinstance(v, dict) and v.get("area")]
            weighted.sort(key=lambda v: -(v.get("weight") or 0))
            items = [str(v["area"]) for v in weighted]
        return items
    return value


# =============================================================================
# Claims + the pure resolver -- no DB, fully unit-testable
# =============================================================================


@dataclass(frozen=True, slots=True)
class Claim:
    source: str
    value: Any
    confidence: float
    observed_at: datetime
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    attr: str
    value: Any
    confidence: float | None
    source: str | None
    stale: bool
    conflict: bool
    conflict_reason: str | None = None
    # claims actually weighed -- becomes the reconcile_conflict.claims snapshot
    considered: tuple[Claim, ...] = ()


def _is_blank(value: Any) -> bool:
    """A claim carrying no information: JSON null, or the literal string
    'unknown' (a first-class value only fee_model/primary_practice legitimately
    carry -- see config/precedence.yml `unknown_capable`). Never beats a real
    value from any source, no matter that source's own precedence."""
    return value is None or value == "unknown"


def _canon(value: Any) -> Any:
    """Order-independent equality for list-valued claims (practice_areas):
    two sources agreeing on the same set, listed in a different order, still
    count as agreement."""
    if isinstance(value, list):
        try:
            return frozenset(value)
        except TypeError:
            return tuple(sorted(str(v) for v in value))
    if isinstance(value, dict):
        # An address is a dict (street_norm, unit, city, state, zip5, addr_hash):
        # two sources printing the same office agree. Hit once two address
        # sources existed (site:jsonld and site:page, D-031).
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _dedupe_newest_per_source(claims: Sequence[Claim]) -> list[Claim]:
    """When several claims from the same source exist, use the newest."""
    best: dict[str, Claim] = {}
    for c in claims:
        family = source_family(c.source)
        cur = best.get(family)
        # Newest observation wins; at the same observation the newer prompt
        # revision supersedes the older one (a v2 re-run over the same pages).
        if cur is None or (c.observed_at, _revision(c.source)) > (
            cur.observed_at, _revision(cur.source)
        ):
            best[family] = c
    return list(best.values())


def _pick_by_precedence(cfg: PrecedenceConfig, attr: str, claims: Sequence[Claim]) -> Claim:
    """Highest-precedence source wins; ties broken by higher confidence, then
    by most recently observed."""
    best: Claim | None = None
    best_key: tuple[int, float, float] | None = None
    for c in claims:
        key = (cfg.rank_of(attr, c.source), -c.confidence, -c.observed_at.timestamp())
        if best_key is None or key < best_key:
            best_key, best = key, c
    assert best is not None  # callers only invoke this with a non-empty sequence
    return best


def _conflict(attr: str, claims: Sequence[Claim], reason: str) -> ReconcileOutcome:
    return ReconcileOutcome(
        attr, None, None, None, stale=False, conflict=True,
        conflict_reason=reason, considered=tuple(claims),
    )


def resolve_claims(
    attr: str, claims: Sequence[Claim], *, cfg: PrecedenceConfig | None = None
) -> ReconcileOutcome:
    """The pure algorithm. `claims` must already be within the freshness
    window -- this function does no time-based filtering itself, only
    source-exclusivity filtering, dedup, and precedence resolution."""
    cfg = cfg or load_precedence()

    pool: Sequence[Claim] = claims
    if cfg.is_exclusive(attr):
        allowed = set(cfg.precedence.get(attr, ()))
        pool = [c for c in pool if source_family(c.source) in allowed]

    pool = _dedupe_newest_per_source(pool)

    if not pool:
        return ReconcileOutcome(attr, None, None, None, stale=True, conflict=False)

    real = [c for c in pool if not _is_blank(c.value)]
    blank = [c for c in pool if _is_blank(c.value)]

    if not real:
        winner = _pick_by_precedence(cfg, attr, blank)
        value = "unknown" if cfg.is_unknown_capable(attr) else None
        return ReconcileOutcome(
            attr, value, winner.confidence, winner.source,
            stale=(value is None), conflict=False, considered=tuple(blank),
        )

    sources = {source_family(c.source) for c in real}
    if len(sources) == 1:
        winner = real[0]
        return ReconcileOutcome(
            attr, winner.value, winner.confidence, winner.source,
            stale=False, conflict=False, considered=tuple(real),
        )

    if len({_canon(c.value) for c in real}) == 1:
        winner = _pick_by_precedence(cfg, attr, real)  # attributed source for provenance
        return ReconcileOutcome(
            attr, winner.value, max(c.confidence for c in real), winner.source,
            stale=False, conflict=False, considered=tuple(real),
        )

    # ---- disagreement ----

    if attr == "fee_model":
        regex_claim = next((c for c in real if c.source == "regex:p6"), None)
        llm_claims = [c for c in real if c.source.startswith("llm:")]
        # presence alone breaks the loop -- at any prompt revision
        p9_seen = any(source_family(c.source) == "llm:p9" for c in pool)
        if regex_claim and llm_claims and not p9_seen:
            if any(_canon(c.value) != _canon(regex_claim.value) for c in llm_claims):
                return _conflict(
                    attr, real,
                    "fee_model: regex:p6 and an LLM claim disagree, no llm:p9 claim "
                    "yet -- escalate",
                )

    winner = _pick_by_precedence(cfg, attr, real)
    if cfg.is_tier_determining(attr) and winner.confidence < 0.6:
        return _conflict(
            attr, real,
            f"{attr}: disagreement, precedence winner {winner.source!r} has confidence "
            f"{winner.confidence} < 0.6 on a tier-determining attribute",
        )

    return ReconcileOutcome(
        attr, winner.value, winner.confidence, winner.source,
        stale=False, conflict=False, considered=tuple(real),
    )


# =============================================================================
# Single-firm DB path -- reconcile(conn, firm_id, attr), the spec's function
# =============================================================================


def _load_claims(conn, firm_id: Any, attr: str, at: datetime, freshness_days: int) -> list[Claim]:
    cutoff = at - timedelta(days=freshness_days)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source, value, confidence, evidence, observed_at FROM firm_attribute "
            "WHERE firm_id = %s AND attr = %s AND observed_at > %s",
            (firm_id, attr, cutoff),
        )
        rows = cur.fetchall()
    return [
        Claim(r["source"], r["value"], float(r["confidence"]), r["observed_at"], r["evidence"])
        for r in rows
    ]


def _claims_json(claims: Sequence[Claim]) -> list[dict]:
    return [
        {
            "source": c.source, "value": c.value, "confidence": c.confidence,
            "observed_at": c.observed_at.isoformat(),
        }
        for c in claims
    ]


def _write_firm_columns_single(conn, firm_id: Any, attr: str, outcome: ReconcileOutcome) -> None:
    if attr == "address":
        row = _address_row(outcome.value)
        set_sql = (
            "street_norm = %s::text, addr_unit = %s::text, addr_hash = %s::text, "
            "zip5 = %s::char(5), state = %s::char(2), city = COALESCE(%s::text, city)"
        )
        params = [
            row["street_norm"], row["addr_unit"], row["addr_hash"],
            row["zip5"], row["state"], row["city"], firm_id,
        ]
    elif attr == "city":
        set_sql = "city = COALESCE(%s::text, city)"
        params = [outcome.value, firm_id]
    elif attr in _COALESCE_COLUMNS:
        coltype = _COLUMN_TYPES[attr]
        set_sql = f"{attr} = COALESCE(%s::{coltype}, {attr})"
        params = [_coerce_for_column(attr, outcome.value), firm_id]
    else:
        coltype = _COLUMN_TYPES[attr]
        set_sql = f"{attr} = %s::{coltype}"
        params = [_coerce_for_column(attr, outcome.value), firm_id]

    with writer(conn, "reconcile"), conn.cursor() as cur:
        cur.execute(f"UPDATE firm SET {set_sql} WHERE id = %s", params)  # noqa: S608


def _write_firm_attr_state(
    conn, firm_id: Any, attr: str, outcome: ReconcileOutcome, at: datetime
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO firm_attr_state (firm_id, attr, stale, reconciled_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (firm_id, attr) DO UPDATE
              SET stale = EXCLUDED.stale, reconciled_at = EXCLUDED.reconciled_at
            """,
            (firm_id, attr, outcome.stale, at),
        )


def _write_conflict_single(conn, firm_id: Any, attr: str, outcome: ReconcileOutcome) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM reconcile_conflict WHERE firm_id = %s AND attr = %s "
            "AND resolved_at IS NULL",
            (firm_id, attr),
        )
        open_row = cur.fetchone()

    if outcome.conflict:
        if open_row is None:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO reconcile_conflict (firm_id, attr, claims, reason) "
                    "VALUES (%s, %s, %s, %s)",
                    (
                        firm_id, attr,
                        Jsonb(_claims_json(outcome.considered)), outcome.conflict_reason,
                    ),
                )
    elif open_row is not None:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE reconcile_conflict SET resolved_at = now() WHERE id = %s",
                (open_row["id"],),
            )


def reconcile(conn, firm_id: Any, attr: str, *, at: datetime | None = None) -> ReconcileOutcome:
    """context/30-data-model/04-attribute-reconciliation.md's FUNCTION
    reconcile(firm_id, attr), exactly. Resolves one firm's one attribute from
    its current firm_attribute claims and writes the result: the firm
    column(s), `firm_attr_state` (staleness), and `reconcile_conflict` (opened
    on a fresh conflict, resolved_at set when a later run resolves one that
    was open). The only writer of firm's resolved columns (I7)."""
    if attr not in RECONCILED_ATTRS:
        raise ValueError(f"reconcile(): unknown attribute {attr!r}")
    at = at or datetime.now(UTC)
    cfg = load_precedence()
    claims = _load_claims(conn, firm_id, attr, at, cfg.freshness_for(attr))
    outcome = resolve_claims(attr, claims, cfg=cfg)
    _write_firm_columns_single(conn, firm_id, attr, outcome)
    _write_firm_attr_state(conn, firm_id, attr, outcome, at)
    _write_conflict_single(conn, firm_id, attr, outcome)
    return outcome


# =============================================================================
# Bulk path -- the `reconcile` component. Chunked, set-based: one claims
# query and one write per chunk of firms, never one query per attribute.
# =============================================================================


def combine_firm_columns(outcomes: dict[str, ReconcileOutcome]) -> dict[str, Any]:
    """Flatten one firm's per-attribute outcomes into firm column values.
    `city` is the one dual-owned column (the `address` fan-out and the
    standalone `city` attribute both target it): the standalone attribute's
    fresh value wins, the fan-out's is the fallback, and when NEITHER
    produced a value this run the result is None -- callers must write that
    through `COALESCE(v.city, f.city)`, never a bare overwrite, or a stale
    run on one attribute would erase a value the other legitimately set."""
    cols: dict[str, Any] = {}
    for attr, outcome in outcomes.items():
        if attr in ("address", "city"):
            continue
        cols[attr] = outcome.value

    address_row = (
        _address_row(outcomes["address"].value)
        if "address" in outcomes
        else dict.fromkeys(_ADDRESS_COLUMNS)
    )
    for col in _ADDRESS_COLUMNS:
        if col != "city":
            cols[col] = address_row.get(col)

    city_val = outcomes["city"].value if "city" in outcomes else None
    cols["city"] = city_val if city_val is not None else address_row.get("city")
    return cols


def _select_firm_ids(conn, opts: dict[str, Any]) -> list[str]:
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        path = Path(str(firm_ids_file))
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    limit = opts.get("limit")
    query = "SELECT id FROM firm ORDER BY id"
    params: list[Any] = []
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [str(r["id"]) for r in cur.fetchall()]


def _bulk_write_firm_columns(
    conn, outcomes_by_firm: dict[str, dict[str, ReconcileOutcome]]
) -> None:
    # Postgres' `(VALUES ...) AS v(name, ...)` alias takes column NAMES only
    # -- it cannot declare types the way a table definition can. Every
    # placeholder is cast explicitly instead, so the VALUES list's column
    # type is unambiguous regardless of row order or which rows are NULL.
    columns = list(_COLUMN_TYPES.keys())
    row_casts = ["%s::uuid", *(f"%s::{_COLUMN_TYPES[c]}" for c in columns)]
    values_cols_decl = ", ".join(["id", *columns])

    rows_sql: list[str] = []
    params: list[Any] = []
    for firm_id, outcomes in outcomes_by_firm.items():
        combined = combine_firm_columns(outcomes)
        rows_sql.append("(" + ", ".join(row_casts) + ")")
        params.append(firm_id)
        params.extend(_coerce_for_column(c, combined.get(c)) for c in columns)

    set_clause = ", ".join(
        (f"{c} = COALESCE(v.{c}, f.{c})" if c in _COALESCE_COLUMNS else f"{c} = v.{c}")
        for c in columns
    )
    sql = (
        f"UPDATE firm f SET {set_clause} "  # noqa: S608 -- fixed column list, values parameterized
        f"FROM (VALUES {', '.join(rows_sql)}) AS v({values_cols_decl}) "
        f"WHERE f.id = v.id"
    )
    with writer(conn, "reconcile"), conn.cursor() as cur:
        cur.execute(sql, params)


def _bulk_write_conflicts(conn, outcomes_by_firm: dict[str, dict[str, ReconcileOutcome]]) -> None:
    firm_ids = list(outcomes_by_firm.keys())
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, firm_id, attr FROM reconcile_conflict "
            "WHERE resolved_at IS NULL AND firm_id = ANY(%s)",
            (firm_ids,),
        )
        open_by_key = {(str(r["firm_id"]), r["attr"]): r["id"] for r in cur.fetchall()}

    to_insert: list[tuple] = []
    to_resolve: list[int] = []
    for firm_id, outcomes in outcomes_by_firm.items():
        for attr, outcome in outcomes.items():
            key = (firm_id, attr)
            if outcome.conflict:
                if key not in open_by_key:
                    to_insert.append((
                        firm_id, attr,
                        Jsonb(_claims_json(outcome.considered)), outcome.conflict_reason,
                    ))
            elif key in open_by_key:
                to_resolve.append(open_by_key[key])

    with conn.cursor() as cur:
        if to_insert:
            placeholders = ", ".join(["(%s, %s, %s, %s)"] * len(to_insert))
            flat = [v for row in to_insert for v in row]
            cur.execute(
                "INSERT INTO reconcile_conflict (firm_id, attr, claims, reason) "  # noqa: S608
                f"VALUES {placeholders}",
                flat,
            )
        if to_resolve:
            cur.execute(
                "UPDATE reconcile_conflict SET resolved_at = now() WHERE id = ANY(%s)",
                (to_resolve,),
            )


def _recompute_tier_fit(conn, firm_ids: list[str]) -> int:
    """Set-based icp_tier()/fit_score() recompute for the whole chunk, inside
    the SAME transaction as `_bulk_write_firm_columns` -- the `before` CTE
    reads the pre-statement snapshot, so this correctly counts firms whose
    tier changed as a result of the attribute writes just made."""
    with writer(conn, "reconcile"), conn.cursor() as cur:
        cur.execute(
            """
            WITH before AS (
              SELECT id, tier FROM firm WHERE id = ANY(%(ids)s)
            ), updated AS (
              UPDATE firm f SET tier = icp_tier(f), fit_score = fit_score(f)
              WHERE f.id = ANY(%(ids)s)
              RETURNING f.id, f.tier
            )
            SELECT count(*) AS n FROM updated u
            JOIN before b ON b.id = u.id
            WHERE u.tier IS DISTINCT FROM b.tier
            """,
            {"ids": firm_ids},
        )
        return cur.fetchone()["n"]


def _reconcile_chunk(conn, firm_ids: list[Any], at: datetime, cfg: PrecedenceConfig) -> int:
    # Normalize to str once -- callers may pass UUID objects (e.g. straight
    # from a `RETURNING id`) or strings (the component's own _select_firm_ids
    # already stringifies). Every lookup below keys on str(firm_id); mixing
    # UUID and str objects in the same dict would silently miss every claim.
    firm_ids = [str(f) for f in firm_ids]

    # One query per chunk covers every attribute's claims -- never one query
    # per attribute. The SQL cutoff uses the loosest (largest) freshness
    # window configured; each attribute's own, possibly tighter, window is
    # then applied in Python while grouping.
    max_freshness = max([cfg.default_freshness_days, *cfg.freshness_days.values()])
    sql_cutoff = at - timedelta(days=max_freshness)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT firm_id, attr, source, value, confidence, evidence, observed_at "
            "FROM firm_attribute WHERE firm_id = ANY(%s) AND observed_at > %s",
            (firm_ids, sql_cutoff),
        )
        rows = cur.fetchall()

    reconciled = set(RECONCILED_ATTRS)
    by_firm_attr: dict[tuple[str, str], list[Claim]] = {}
    for r in rows:
        attr = r["attr"]
        if attr not in reconciled:
            continue  # informational-only claims (vendor_headcount_range, languages, ...)
        attr_cutoff = at - timedelta(days=cfg.freshness_for(attr))
        if r["observed_at"] <= attr_cutoff:
            continue
        key = (str(r["firm_id"]), attr)
        by_firm_attr.setdefault(key, []).append(
            Claim(r["source"], r["value"], float(r["confidence"]), r["observed_at"], r["evidence"])
        )

    outcomes_by_firm: dict[str, dict[str, ReconcileOutcome]] = {}
    for firm_id in firm_ids:
        outcomes_by_firm[firm_id] = {
            attr: resolve_claims(attr, by_firm_attr.get((firm_id, attr), []), cfg=cfg)
            for attr in RECONCILED_ATTRS
        }

    _bulk_write_firm_columns(conn, outcomes_by_firm)
    _bulk_write_conflicts(conn, outcomes_by_firm)
    return _recompute_tier_fit(conn, firm_ids)


@component(
    "reconcile", "score",
    "Reconcile firm_attribute claims into firm columns; recompute tier/fit_score.",
)
def reconcile_component(ctx: RunContext, **opts: Any) -> RunResult:
    at = datetime.now(UTC)
    cfg = load_precedence()
    firm_ids = _select_firm_ids(ctx.conn, opts)

    result = RunResult()
    tier_changed_total = 0

    for i in range(0, len(firm_ids), _CHUNK_SIZE):
        chunk = firm_ids[i : i + _CHUNK_SIZE]
        if not chunk:
            continue
        tier_changed_total += _reconcile_chunk(ctx.conn, chunk, at, cfg)
        result.processed += len(chunk)
        ctx.checkpoint()

    result.notes.append(f"firms reconciled: {result.processed}")
    result.notes.append(f"tier changed: {tier_changed_total}")
    return result
