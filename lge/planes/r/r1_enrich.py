"""r1_enrich -- the email-finder seam (Plane R; D-046). Multi-vendor contact
enrichment behind one adapter interface (context/40-pipeline/
02-component-register.md: "Runs only on firms that passed the tier gate --
enriching the whole universe is the largest avoidable cost in the system").

Selection is tier-gated and gap-only: a firm qualifies when its tier is set
and is not `DQ_*`, and either it has no owner/admin contact on file, or it
has one who has no email address. R2 (bar join), r_site_contacts and the
free searches run earlier in the pipeline order -- R1 exists to pay for what
the free sources did not find, never to re-fetch what they did.

Which vendor answers is `settings.email_finder_name()` (`hunter` when its
key exists, else `none`); `config/resolvers.yml` or `--opt provider=` can
force one. The Hunter adapter asks two things: the Email Finder for each
decision-maker who lacks an address (domain + first + last -> the address
and Hunter's own verification of it), and, for a firm with no decision-maker
at all, the Domain Search (the people Hunter has for the domain, of whom
only owners and administrators are taken). Every address lands in
`contact_email` with the vendor's verdict mapped onto OUR status vocabulary:
only Hunter's `valid` is 'valid'; `accept_all` is 'catch_all'; an address
Hunter did not verify stays 'unverified' for R4.

Idempotency is `ctx.once()` per firm on a key made of the firm's domain and
the decision-makers still without an address, so a person found later gets
a lookup and a firm already looked up for the same people does not pay
twice. Budget is `--opt max_usd`, checked before every firm.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from lge.classify.roles import classify_role
from lge.registry import RunContext, RunResult, component
from lge.settings import Settings

_COMPONENT_NAME = "r1_enrich"
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "resolvers.yml"

_ENV_KEYS: dict[str, str] = {"hunter": "HUNTER_API_KEY"}
_DECISION_MAKERS = ("owner", "admin")
_SOURCE_HUNTER = "hunter"

HUNTER_FINDER_URL = "https://api.hunter.io/v2/email-finder"
HUNTER_DOMAIN_URL = "https://api.hunter.io/v2/domain-search"

# Hunter's verification statuses onto contact_email.status: only `valid` is a
# pass; an address Hunter has not verified stays unverified for R4.
HUNTER_STATUS_MAP: dict[str, str] = {
    "valid": "valid",
    "accept_all": "catch_all",
    "invalid": "invalid",
    "disposable": "invalid",
    "webmail": "risky",
    "unknown": "risky",
}


@dataclass(frozen=True, slots=True)
class EnrichResult:
    contacts: list[dict[str, Any]]
    cost_usd: float
    raw: dict[str, Any]


class EnrichError(Exception):
    """A vendor call did not complete."""


class EnrichAdapter(Protocol):
    def __call__(
        self, conn: Any, firm_id: Any, *, cfg: dict[str, Any], api_key: str, client: httpx.Client
    ) -> EnrichResult: ...


def enrich_none(
    _conn: Any, _firm_id: Any, *, cfg: dict[str, Any], api_key: str, client: httpx.Client
) -> EnrichResult:
    raise EnrichError("the 'none' adapter never enriches -- it is only selected when inert")


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["r1_enrich"]


def provider_for(cfg: dict[str, Any], settings: Settings, override: Any = None) -> str:
    """`--opt provider=` wins; a config value other than auto/none wins next;
    otherwise the settings' choice (the first vendor with a key, else none)."""
    if override not in (None, ""):
        return str(override)
    configured = str(cfg.get("provider") or "auto")
    if configured not in ("auto", "none"):
        return configured
    return settings.email_finder_name()


def api_key_for(provider: str, settings: Settings) -> str:
    env_key = _ENV_KEYS.get(provider)
    if not env_key:
        return ""
    return os.environ.get(env_key, "") or str(getattr(settings, f"{provider}_api_key", "") or "")


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_HAS_DECISION_MAKER = (
    "EXISTS (SELECT 1 FROM contact c WHERE c.firm_id = f.id AND c.removed_at IS NULL "
    "AND c.role IN ('owner', 'admin'))"
)
_DECISION_MAKER_WITHOUT_EMAIL = (
    "EXISTS (SELECT 1 FROM contact c WHERE c.firm_id = f.id AND c.removed_at IS NULL "
    "AND c.role IN ('owner', 'admin') "
    "AND NOT EXISTS (SELECT 1 FROM contact_email e WHERE e.contact_id = c.id))"
)


def select_firm_ids(conn, opts: dict[str, Any]) -> list[Any]:
    """Firms past the tier gate (tier set, not DQ_*) that have no owner/admin
    contact, or have one with no email address."""
    clauses = [
        "f.tier IS NOT NULL",
        "f.tier NOT LIKE 'DQ%%'",  # same convention as sql/001_schema.sql's firm index
        f"(NOT {_HAS_DECISION_MAKER} OR {_DECISION_MAKER_WITHOUT_EMAIL})",
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

    query = "SELECT f.id FROM firm f WHERE " + " AND ".join(clauses) + " ORDER BY f.id"
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 -- clauses are fixed strings, not user input
        return [r["id"] for r in cur.fetchall()]


def _firm(conn: Any, firm_id: Any) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT canonical_name, domain FROM firm WHERE id = %s", (firm_id,))
        return cur.fetchone()


def _decision_makers_without_email(conn: Any, firm_id: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.full_name, c.role, c.confidence FROM contact c "
            "WHERE c.firm_id = %s AND c.removed_at IS NULL AND c.role IN ('owner', 'admin') "
            "AND NOT EXISTS (SELECT 1 FROM contact_email e WHERE e.contact_id = c.id) "
            "ORDER BY (c.role = 'owner') DESC, c.confidence DESC NULLS LAST, c.full_name",
            (firm_id,),
        )
        return cur.fetchall()


def _has_decision_maker(conn: Any, firm_id: Any) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM contact WHERE firm_id = %s AND removed_at IS NULL "
            "AND role IN ('owner', 'admin') LIMIT 1",
            (firm_id,),
        )
        return cur.fetchone() is not None


def input_key(conn: Any, firm_id: Any, provider: str) -> str:
    """The firm's domain and the decision-makers still without an address:
    the same people again is a no-op; a new person is a new lookup."""
    firm = _firm(conn, firm_id) or {}
    people = _decision_makers_without_email(conn, firm_id)
    has_dm = _has_decision_maker(conn, firm_id)
    text = "|".join([
        provider, str(firm.get("domain") or ""), "dm" if has_dm else "no-dm",
        *sorted(str(p["id"]) for p in people),
    ])
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Writing what a vendor found
# ---------------------------------------------------------------------------


def _split_name(full_name: str) -> tuple[str, str] | None:
    parts = [p for p in full_name.replace(",", " ").split() if p and not p.endswith(".")]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def _status_from(verification: dict[str, Any] | None) -> str:
    status = str((verification or {}).get("status") or "").lower()
    return HUNTER_STATUS_MAP.get(status, "unverified") if status else "unverified"


def attach_email(
    conn: Any, contact_id: Any, email: str, status: str, vendor_status: str | None
) -> bool:
    """An address onto a contact. A row already there is upgraded only from
    'unverified' -- OUR verification is never overwritten by a vendor's."""
    now = datetime.now(UTC) if status != "unverified" else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO contact_email (contact_id, email, status, vendor_status, verified_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (contact_id, email) DO UPDATE SET
              status = CASE WHEN contact_email.status = 'unverified'
                            THEN EXCLUDED.status ELSE contact_email.status END,
              vendor_status = COALESCE(EXCLUDED.vendor_status, contact_email.vendor_status),
              verified_at = CASE WHEN contact_email.status = 'unverified'
                                 THEN EXCLUDED.verified_at ELSE contact_email.verified_at END
            """,
            (contact_id, email.lower(), status, vendor_status, now),
        )
        return cur.rowcount > 0


def _existing_contact(conn: Any, firm_id: Any, full_name: str) -> Any | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM contact WHERE firm_id = %s AND removed_at IS NULL "
            "AND lower(full_name) = lower(%s) LIMIT 1",
            (firm_id, full_name),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def add_contact(
    conn: Any, firm_id: Any, *, full_name: str, title: str | None, role: str,
    linkedin_url: str | None, confidence: float,
) -> Any:
    existing = _existing_contact(conn, firm_id, full_name)
    if existing is not None:
        return existing
    contact_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO contact (id, firm_id, full_name, title, role, linkedin_url, source, "
            "confidence, enriched_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (contact_id, firm_id, full_name, title, role, linkedin_url, _SOURCE_HUNTER,
             confidence, datetime.now(UTC)),
        )
    return contact_id


# ---------------------------------------------------------------------------
# Hunter
# ---------------------------------------------------------------------------


def _hunter_get(
    client: httpx.Client, url: str, params: dict[str, Any], cfg: dict[str, Any]
) -> dict:
    try:
        resp = client.get(url, params=params, timeout=float(cfg.get("timeout_s", 15.0)))
    except httpx.HTTPError as exc:
        raise EnrichError(f"hunter: transport error: {exc}") from exc
    if resp.status_code == 404:
        return {"data": {}}  # Hunter's "nothing for this domain / person"
    if resp.status_code in (401, 403):
        raise EnrichError(f"hunter refused the key ({resp.status_code})")
    if resp.status_code == 429:
        raise EnrichError("hunter: rate limit (429)")
    if resp.status_code >= 400:
        raise EnrichError(f"hunter answered {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if "data" not in body:
        raise EnrichError(f"hunter: no data in the answer: {str(body)[:200]}")
    return body


def enrich_hunter(
    conn: Any, firm_id: Any, *, cfg: dict[str, Any], api_key: str, client: httpx.Client
) -> EnrichResult:
    firm = _firm(conn, firm_id)
    if not firm or not firm.get("domain"):
        return EnrichResult(contacts=[], cost_usd=0.0, raw={"skipped": "no domain"})
    domain = str(firm["domain"]).lower()
    price = float(cfg.get("price_per_request_usd", {}).get("hunter", 0.0))
    max_people = int(cfg.get("max_people", 4))
    requests = 0
    found: list[dict[str, Any]] = []
    raw: dict[str, Any] = {"finder": [], "domain_search": None}

    # 1. the decision-makers we know by name but have no address for
    for person in _decision_makers_without_email(conn, firm_id)[:max_people]:
        names = _split_name(person["full_name"])
        if names is None:
            continue
        first, last = names
        body = _hunter_get(
            client, HUNTER_FINDER_URL,
            {"domain": domain, "first_name": first, "last_name": last, "api_key": api_key}, cfg,
        )
        requests += 1
        data = body.get("data") or {}
        email = data.get("email")
        raw["finder"].append({"person": person["full_name"], "email": email,
                              "score": data.get("score")})
        if not email:
            continue
        status = _status_from(data.get("verification"))
        vendor = f"hunter:{data.get('score')}" if data.get("score") is not None else "hunter"
        attach_email(conn, person["id"], email, status, vendor)
        found.append({"contact_id": person["id"], "email": email, "status": status})

    # 2. a firm with no decision-maker at all: the people Hunter has for the domain
    if not _has_decision_maker(conn, firm_id):
        body = _hunter_get(
            client, HUNTER_DOMAIN_URL,
            {"domain": domain, "api_key": api_key, "limit": 10, "type": "personal"}, cfg,
        )
        requests += 1
        data = body.get("data") or {}
        raw["domain_search"] = {"organization": data.get("organization"),
                                "emails": len(data.get("emails") or [])}
        taken = 0
        for entry in data.get("emails") or []:
            first, last = entry.get("first_name"), entry.get("last_name")
            if not first or not last or not entry.get("value"):
                continue
            position = entry.get("position")
            role = classify_role(position).role if position else "unknown"
            if role not in _DECISION_MAKERS and str(entry.get("seniority") or "") == "executive":
                role = "owner"
            if role not in _DECISION_MAKERS:
                continue
            confidence = float(entry.get("confidence") or 0) / 100.0
            contact_id = add_contact(
                conn, firm_id, full_name=f"{first} {last}", title=position, role=role,
                linkedin_url=entry.get("linkedin"), confidence=round(confidence, 2),
            )
            status = _status_from(entry.get("verification"))
            attach_email(
                conn, contact_id, entry["value"], status, f"hunter:{entry.get('confidence')}"
            )
            found.append({"contact_id": contact_id, "email": entry["value"], "status": status})
            taken += 1
            if taken >= max_people:
                break

    return EnrichResult(contacts=found, cost_usd=requests * price, raw=raw)


_ADAPTERS: dict[str, EnrichAdapter] = {"none": enrich_none, "hunter": enrich_hunter}


@component(
    "r1_enrich", "R",
    "Email finder behind one adapter interface (Hunter). Tier-gated; only firms with no "
    "decision-maker or a decision-maker without an address. Inert without a key.",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    cfg = _config()
    provider = provider_for(cfg, ctx.settings, opts.get("provider"))
    api_key = api_key_for(provider, ctx.settings)

    firm_ids = select_firm_ids(conn, opts)

    if provider == "none" or provider not in _ADAPTERS or (provider in _ENV_KEYS and not api_key):
        return RunResult(
            skipped=len(firm_ids), notes=["inert: no enrichment provider configured"]
        )

    adapter = _ADAPTERS[provider]
    raw_max_usd = opts.get("max_usd")
    max_usd = float(raw_max_usd) if raw_max_usd not in (None, "") else None

    result = RunResult()
    spent = 0.0
    found_total = 0

    with httpx.Client() as client:
        for firm_id in firm_ids:
            if max_usd is not None and spent >= max_usd:
                result.skipped += 1
                result.notes.append(
                    f"budget stop: ${max_usd:.2f} cap reached before firm {firm_id}"
                )
                ctx.checkpoint()
                continue
            try:
                key = input_key(conn, firm_id, provider)
                with ctx.once(_COMPONENT_NAME, str(firm_id), key) as should_run:
                    if not should_run:
                        result.skipped += 1
                    else:
                        outcome = adapter(conn, firm_id, cfg=cfg, api_key=api_key, client=client)
                        spent += outcome.cost_usd
                        found_total += len(outcome.contacts)
                        result.processed += 1
            except EnrichError as exc:
                result.failed += 1
                result.notes.append(f"{firm_id}: {exc}")
            ctx.checkpoint()

    result.notes.insert(0, f"{provider}: addresses attached {found_total}, spent ${spent:.2f}")
    return result
