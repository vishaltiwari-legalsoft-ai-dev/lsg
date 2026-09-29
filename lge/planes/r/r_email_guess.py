"""r_email_guess -- a decision-maker's address from their name and the firm's
domain, confirmed by the verifier (Plane R; D-051).

When a firm has no known address at all, r3_email_pattern has nothing to
learn a pattern from and the decision-maker stays without an address. This
component builds the candidates the eleven schemes give for the person's
name -- john.smith@, john@, jsmith@, johnsmith@ ... -- most common first,
and asks the verifier about each one until one comes back valid. The hit is
written as the person's address (status 'valid', the scheme recorded);
r3 then learns the firm's pattern from it on its next run and mints the
rest of the firm's people.

A catch-all domain answers "deliverable" to anything, so the first catch-all
answer ends the search for that firm: the most common scheme is kept for
each decision-maker with status 'catch_all' -- on file, never sent to -- and
no more money is spent on that domain.

Cost: about a cent a candidate; two or three candidates on average.
`--opt max_usd` caps a run, `max_candidates` caps a person, and every
attempt is logged in verify_attempt, so an address is never paid for twice.
Selection is tier-gated like R1 and R4. Inert without a verifier key.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from lge.norm import FREEMAIL_BLOCKLIST
from lge.planes.r.r3_email_pattern import _name_parts, _render
from lge.planes.r.r4_verify import (
    _ADAPTERS,
    _ENV_KEYS,
    VerifyError,
    _already_attempted,
    _config,
    api_key_for,
    provider_for,
)
from lge.registry import RunContext, RunResult, component

_COMPONENT_NAME = "r_email_guess"
_DEFAULT_MAX_CANDIDATES = 6
_MAX_CONSECUTIVE_FAILURES = 5

# The schemes in the order they are seen on US law-firm domains (D-035's
# probe): the first three cover most firms.
CANDIDATE_ORDER = (
    "first.last", "first", "flast", "firstlast", "first_last", "firstl",
    "f.last", "last", "lastf", "last.first", "lastfirst",
)


def candidates(full_name: str | None, domain: str) -> list[tuple[str, str]]:
    """(scheme, address) for a person at a domain, most common scheme first,
    duplicates dropped (a one-token surname can make two schemes collide)."""
    parts = _name_parts(full_name)
    if parts is None:
        return []
    first, last = parts
    if not first or not last:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for scheme in CANDIDATE_ORDER:
        address = f"{_render(first, last, scheme)}@{domain}".lower()
        if address in seen:
            continue
        seen.add(address)
        out.append((scheme, address))
    return out


def _price(cfg: dict[str, Any], provider: str) -> float:
    return float(cfg.get("price_per_email_usd", {}).get(provider, 0.0))


def _select(conn: Any, opts: dict[str, Any]) -> list[dict]:
    """Decision-makers without an address at tiered firms where nobody has an
    on-domain address yet (otherwise r3's pattern already covers them)."""
    clauses = [
        "c.removed_at IS NULL",
        "c.role IN ('owner', 'admin')",
        "f.domain IS NOT NULL",
        "f.tier IS NOT NULL",
        "f.tier NOT LIKE 'DQ%%'",
        "f.tier <> 'UNCLASSIFIED'",  # never pay for a firm that cannot become ready
        "NOT EXISTS (SELECT 1 FROM contact_email e WHERE e.contact_id = c.id)",
        "NOT EXISTS (SELECT 1 FROM contact_email e JOIN contact c2 ON c2.id = e.contact_id "
        "WHERE c2.firm_id = f.id AND e.email LIKE '%%@' || f.domain)",
    ]
    params: list[Any] = []
    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        ids = [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        clauses.append("f.id = ANY(%s)")
        params.append(ids)
    query = (
        "SELECT c.id AS contact_id, c.full_name, c.role, f.id AS firm_id, f.domain "
        "FROM contact c JOIN firm f ON f.id = c.firm_id WHERE " + " AND ".join(clauses)
        + " ORDER BY f.id, (c.role = 'owner') DESC, c.confidence DESC NULLS LAST, c.id"
    )
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 -- clauses are fixed strings, not user input
        return cur.fetchall()


def _prior_result(conn: Any, email: str, provider: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT result FROM verify_attempt WHERE email = %s AND provider = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (email, provider),
        )
        row = cur.fetchone()
        return row["result"] if row else None


def _attach(conn: Any, contact_id: Any, email: str, status: str, scheme: str) -> None:
    now = datetime.now(UTC) if status != "unverified" else None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_email (contact_id, email, status, pattern, verified_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (contact_id, email) DO NOTHING",
            (contact_id, email, status, scheme, now),
        )


def _record_attempt(
    conn: Any, email: str, provider: str, result: str, raw: Any, price: float
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO verify_attempt (email, provider, result, raw, cost_usd) "
            "VALUES (%s, %s, %s, %s, %s)",
            (email, provider, result, Jsonb(raw), price),
        )


@component(
    _COMPONENT_NAME, "R",
    "A decision-maker's address from their name and the firm's domain: the candidate "
    "schemes, most common first, each confirmed by the verifier until one is real. "
    "Tier-gated, budget-capped, never pays for an address twice.",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    cfg = _config()
    provider = provider_for(cfg, ctx.settings, opts.get("provider"))
    api_key = api_key_for(provider, ctx.settings)
    people = _select(conn, opts)

    env_key = _ENV_KEYS.get(provider)
    if provider == "none" or provider not in _ADAPTERS or (env_key and not api_key):
        return RunResult(skipped=len(people), notes=["inert: no verification provider configured"])

    adapter = _ADAPTERS[provider]
    price = _price(cfg, provider)
    max_candidates = int(opts.get("max_candidates") or _DEFAULT_MAX_CANDIDATES)
    raw_max_usd = opts.get("max_usd")
    max_usd = float(raw_max_usd) if raw_max_usd not in (None, "") else None

    result = RunResult()
    spent = 0.0
    found = catch_all = 0
    consecutive_failures = 0
    catch_all_domains: set[str] = set()

    with httpx.Client() as client:
        for person in people:
            domain = str(person["domain"]).lower()
            if domain in FREEMAIL_BLOCKLIST:
                result.skipped += 1
                continue
            options = candidates(person["full_name"], domain)[:max_candidates]
            if not options:
                result.skipped += 1
                continue
            if domain in catch_all_domains:
                # the domain accepts anything: a call tells nothing, so the most
                # common scheme goes on file as catch-all without paying
                scheme, address = options[0]
                _attach(conn, person["contact_id"], address, "catch_all", scheme)
                catch_all += 1
                result.processed += 1
                continue
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                result.skipped += 1
                continue

            outcome = "not_found"
            for scheme, address in options:
                prior = (
                    _prior_result(conn, address, provider)
                    if _already_attempted(conn, address, provider) else None
                )
                if prior is None:
                    if max_usd is not None and spent + price > max_usd:
                        result.notes.append(
                            f"budget stop: ${max_usd:.2f} cap reached before {address}"
                        )
                        outcome = "budget"
                        break
                    try:
                        verdict = adapter(address, client=client, api_key=api_key, cfg=cfg)
                    except VerifyError as exc:
                        consecutive_failures += 1
                        result.notes.append(f"{address}: {exc}")
                        outcome = "failed"
                        break
                    consecutive_failures = 0
                    # An "unknown" is not billed by the provider and not a
                    # verdict: recorded at no cost, and the next scheme is tried.
                    charged = 0.0 if verdict.status == "unknown" else price
                    spent += charged
                    _record_attempt(conn, address, provider, verdict.status, verdict.raw, charged)
                    prior = verdict.status
                if prior == "valid":
                    _attach(conn, person["contact_id"], address, "valid", scheme)
                    found += 1
                    outcome = "found"
                    break
                if prior == "catch_all":
                    catch_all_domains.add(domain)
                    _attach(conn, person["contact_id"], address, "catch_all", scheme)
                    catch_all += 1
                    outcome = "catch_all"
                    break
                # invalid or risky: the next scheme
            if outcome == "budget":
                result.skipped += 1
                break
            if outcome == "failed":
                result.failed += 1
                continue
            result.processed += 1
            ctx.checkpoint()

    result.notes.insert(
        0,
        f"{provider}: addresses confirmed {found}, catch-all domains {len(catch_all_domains)} "
        f"({catch_all} people), spent ${spent:.2f}",
    )
    return result
