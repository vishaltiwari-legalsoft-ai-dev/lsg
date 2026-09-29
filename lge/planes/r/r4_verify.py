"""r4_verify -- vendor-agnostic email verifier (Plane R,
context/40-pipeline/02-component-register.md; context/60-execution/
04-risk-register.md "Sending-domain death: catch_all and risky are FAILURES,
not passes -- treating them as valid is how a sending domain dies in week
one").

Only `valid` maps to our 'valid' status. Every other provider outcome maps
to 'catch_all', 'risky', or 'invalid' -- never silently upgraded to a pass --
matching `contact_email.status`'s CHECK constraint exactly. This machine
never SMTP-probes an address itself (reputation risk, and residential port
25 is typically blocked outbound regardless): every adapter is an HTTP call
to a provider's documented validation endpoint, nothing lower-level.

Sync `httpx.Client`, deliberately not async like `lge.fetch.client.Fetcher`:
Fetcher's concurrency exists to overlap MANY hosts under a per-host rate
limiter; R4's calls are inherently serialised anyway (the budget check
between calls needs the running total from the previous one), so async
concurrency here would add complexity for no real throughput gain.

Selection is tier-gated and owner/admin-first: only an `unverified` email
belonging to an owner/admin contact, at a firm whose tier is set and is not
`DQ_*`, is a candidate -- "enriching/verifying the whole universe is the
largest avoidable cost in the system" applies to R4 exactly as it does to
R1.

Idempotency is against `verify_attempt` (migration 070), keyed on
(email, provider): once a call to a provider COMPLETES -- any status, not
only 'valid' -- it is never repeated for that (email, provider) pair again,
so a re-run never pays for the same address twice. A transport failure
(timeout, 5xx exhausted) writes NO verify_attempt row -- the provider never
returned a billable answer -- so a retried run tries that email again; that
distinction is deliberate, not an oversight.

`--opt max_usd` stops the run before spending past the cap, checked against
the configured per-email list price in `config/resolvers.yml` (no real
contract exists yet -- this is a budget guard, not a reconciled invoice).
With no provider configured (or a provider selected whose API key
environment variable is unset), the whole component is inert:
`RunResult(skipped=N)` plus the note "inert: no verification provider
configured" -- candidates are still counted so `lge run` output shows what
verification WOULD have covered.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from psycopg.types.json import Jsonb

from lge.registry import RunContext, RunResult, component

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "resolvers.yml"

# Provider name -> the environment variable its API key is read from; the
# environment wins, then lge.settings (which reads .env) for the providers it
# knows (hunter, neverbounce). Which provider runs is the settings' choice
# unless config or --opt name one (D-046).
_ENV_KEYS: dict[str, str] = {
    "zerobounce": "ZEROBOUNCE_API_KEY",
    "neverbounce": "NEVERBOUNCE_API_KEY",
    "hunter": "HUNTER_API_KEY",
}

_ZEROBOUNCE_URL = "https://api.zerobounce.net/v2/validate"
_NEVERBOUNCE_URL = "https://api.neverbounce.com/v4/single/check"
_HUNTER_URL = "https://api.hunter.io/v2/email-verifier"

_VALID_STATUSES = {"valid", "catch_all", "risky", "invalid"}
# A provider's "unknown" is transient by its own definition (a mail server
# that would not answer): it is recorded as an attempt with result 'unknown'
# and no cost, the address stays 'unverified', and it is asked again after
# _UNKNOWN_RETRY_DAYS, at most _UNKNOWN_MAX_TRIES times. Before this it
# became 'risky' for good and the lead sat at "almost" forever (readiness
# audit, 28 Sep 2026, finding 15).
_UNKNOWN = "unknown"
_UNKNOWN_RETRY_DAYS = 7
_UNKNOWN_MAX_TRIES = 2


@dataclass(frozen=True, slots=True)
class VerifyResult:
    status: str  # one of _VALID_STATUSES
    raw: dict[str, Any]


class VerifyError(Exception):
    """A provider call did not complete after every retry (timeout,
    transport error, or a non-2xx the provider never documents as a real
    verification answer). No verify_attempt row is written for this email --
    it was never billed, so a retried run tries it again."""


class VerifyAdapter(Protocol):
    def __call__(
        self, email: str, *, client: httpx.Client, api_key: str, cfg: dict[str, Any]
    ) -> VerifyResult: ...


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["r4_verify"]


def _sleep_backoff(attempt: int, base: float, cap: float) -> None:
    time.sleep(min(cap, base * (2 ** (attempt - 1))))


def _without_query(text: str) -> str:
    """An httpx error message names the URL; a verifier's URL may carry the
    key and a person's address in its query string. Keep the message, drop
    everything after the first '?'."""
    return re.sub(r"\?[^\s'\"]*", "?…", text)


def _get_with_retry(
    client: httpx.Client, url: str, *, params: dict[str, str] | None = None,
    json: dict[str, Any] | None = None, cfg: dict[str, Any],
) -> dict[str, Any]:
    """One provider call with bounded retries: GET with `params`, or POST
    with a JSON `json` body when the provider accepts one (the key then
    never appears in a URL)."""
    max_retries = int(cfg["max_retries"])
    timeout_s = float(cfg["timeout_s"])
    backoff_base = float(cfg["backoff_base_s"])
    backoff_max = float(cfg["backoff_max_s"])

    attempt = 0
    while True:
        attempt += 1
        try:
            if json is not None:
                resp = client.post(url, json=json, timeout=timeout_s)
            else:
                resp = client.get(url, params=params, timeout=timeout_s)
        except httpx.TimeoutException as exc:
            if attempt >= max_retries:
                raise VerifyError(f"timeout after {attempt} attempt(s)") from exc
            _sleep_backoff(attempt, backoff_base, backoff_max)
            continue
        except httpx.HTTPError as exc:
            if attempt >= max_retries:
                raise VerifyError(
                    f"transport error after {attempt} attempt(s): {_without_query(str(exc))}"
                ) from exc
            _sleep_backoff(attempt, backoff_base, backoff_max)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= max_retries:
                raise VerifyError(f"HTTP {resp.status_code} after {attempt} attempt(s)")
            _sleep_backoff(attempt, backoff_base, backoff_max)
            continue
        if resp.status_code >= 400:
            raise VerifyError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()


def verify_none(
    _email: str, *, client: httpx.Client, api_key: str, cfg: dict[str, Any]
) -> VerifyResult:
    raise VerifyError("the 'none' adapter never verifies -- it is only selected when inert")


# ZeroBounce /v2/validate documented `status` values.
_ZEROBOUNCE_STATUS_MAP: dict[str, str] = {
    "valid": "valid",
    "catch-all": "catch_all",
    "unknown": _UNKNOWN,
    "invalid": "invalid",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}


def verify_zerobounce(
    email: str, *, client: httpx.Client, api_key: str, cfg: dict[str, Any]
) -> VerifyResult:
    raw = _get_with_retry(
        client, _ZEROBOUNCE_URL, params={"api_key": api_key, "email": email}, cfg=cfg
    )
    status = _ZEROBOUNCE_STATUS_MAP.get(str(raw.get("status", "")).lower(), "risky")
    return VerifyResult(status, raw)


# NeverBounce /v4/single/check documented `result` values.
_NEVERBOUNCE_RESULT_MAP: dict[str, str] = {
    "valid": "valid",
    "catchall": "catch_all",
    "unknown": _UNKNOWN,
    "invalid": "invalid",
    "disposable": "invalid",
}


def verify_neverbounce(
    email: str, *, client: httpx.Client, api_key: str, cfg: dict[str, Any]
) -> VerifyResult:
    # POST with the key in the body: NeverBounce accepts it, and a URL that
    # gets logged or quoted in an error then carries nothing secret.
    raw = _get_with_retry(
        client, _NEVERBOUNCE_URL, json={"key": api_key, "email": email}, cfg=cfg
    )
    # NeverBounce answers HTTP 200 for every problem too -- `status` is then
    # auth_failure, throttle_triggered, temp_unavail or general_failure and
    # there is no `result`. That is not a verdict on the address: raise, so no
    # attempt row is written and the address is asked again later (readiness
    # audit 28 Sep 2026, finding 2). Before this check an empty `result`
    # became 'risky' for good.
    envelope = str(raw.get("status", "")).lower()
    if envelope != "success":
        raise VerifyError(
            f"neverbounce {envelope or 'no status'}: {str(raw.get('message', ''))[:200]}"
        )
    result = str(raw.get("result", "")).lower()
    if result not in _NEVERBOUNCE_RESULT_MAP:
        raise VerifyError(f"neverbounce: unexpected result {result!r}")
    return VerifyResult(_NEVERBOUNCE_RESULT_MAP[result], raw)


# Hunter /v2/email-verifier documented `status` values. `accept_all` is a
# catch-all domain -- a failure, as everywhere else in this file.
_HUNTER_STATUS_MAP: dict[str, str] = {
    "valid": "valid",
    "accept_all": "catch_all",
    "unknown": "risky",
    "webmail": "risky",
    "invalid": "invalid",
    "disposable": "invalid",
}


def verify_hunter(
    email: str, *, client: httpx.Client, api_key: str, cfg: dict[str, Any]
) -> VerifyResult:
    raw = _get_with_retry(
        client, _HUNTER_URL, params={"api_key": api_key, "email": email}, cfg=cfg
    )
    data = raw.get("data") or {}
    if not data:
        # Hunter answers 222 with no data while a check is still running: not
        # a billable answer, so no attempt row -- the next run asks again.
        raise VerifyError("hunter: no verdict yet (check still running)")
    status = _HUNTER_STATUS_MAP.get(str(data.get("status", "")).lower(), "risky")
    return VerifyResult(status, raw)


_ADAPTERS: dict[str, VerifyAdapter] = {
    "none": verify_none,
    "zerobounce": verify_zerobounce,
    "neverbounce": verify_neverbounce,
    "hunter": verify_hunter,
}


def provider_for(cfg: dict[str, Any], settings: Any, override: Any = None) -> str:
    """`--opt provider=` wins; a config value other than auto/none wins next;
    otherwise the settings' choice (the first verifier with a key, else none)."""
    if override not in (None, ""):
        return str(override)
    configured = str(cfg.get("provider") or "auto")
    if configured not in ("auto", "none"):
        return configured
    return settings.email_verifier_name()


def api_key_for(provider: str, settings: Any) -> str:
    env_key = _ENV_KEYS.get(provider)
    if not env_key:
        return ""
    return os.environ.get(env_key, "") or str(getattr(settings, f"{provider}_api_key", "") or "")


def _usable(provider: str, settings: Any) -> bool:
    if provider == "none" or provider not in _ADAPTERS:
        return False
    return not _ENV_KEYS.get(provider) or bool(api_key_for(provider, settings))


def configured_provider(settings: Any) -> str | None:
    """The verifier a run would use with no `--opt provider`, or None when the
    component would be inert -- what the screens' "email verification" light
    reports, so the light and the run cannot disagree."""
    provider = provider_for(_config(), settings)
    return provider if _usable(provider, settings) else None


def _select_candidates(conn, opts: dict[str, Any]) -> list[dict]:
    """(contact_id, email, firm_id) for every unverified email on an
    owner/admin contact at a tier-gated (non-DQ_*, tier assigned) firm."""
    clauses = [
        "ce.status = 'unverified'",
        "c.role IN ('owner', 'admin')",
        "f.tier IS NOT NULL",
        "f.tier NOT LIKE 'DQ%%'",  # same convention as sql/001_schema.sql's firm index
        # A firm the classifier could not place can never pass the readiness
        # checks, so its addresses are not worth a paid call (audit finding 9).
        "f.tier <> 'UNCLASSIFIED'",
    ]
    params: list[Any] = []

    firm_ids_file = opts.get("firm_ids_file")
    if firm_ids_file:
        ids = [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        clauses.append("c.firm_id = ANY(%s)")
        params.append(ids)

    query = (
        "SELECT ce.contact_id, ce.email, c.firm_id FROM contact_email ce "
        "JOIN contact c ON c.id = ce.contact_id JOIN firm f ON f.id = c.firm_id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY c.firm_id, ce.contact_id, ce.email"
    )
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 -- clauses are fixed strings, not user input
        return cur.fetchall()


def _catch_all_domains(conn, provider: str) -> set[str]:
    """Every domain this provider has already called catch-all."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT lower(split_part(email, '@', 2)) AS domain "
            "FROM verify_attempt WHERE provider = %s AND result = 'catch_all'",
            (provider,),
        )
        return {row["domain"] for row in cur.fetchall()}


def _already_attempted(conn, email: str, provider: str) -> bool:
    """Whether this (email, provider) is settled: any real verdict settles
    it; an 'unknown' settles it only for _UNKNOWN_RETRY_DAYS, and for good
    after _UNKNOWN_MAX_TRIES of them."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE result <> %s) AS settled, "
            "count(*) FILTER (WHERE result = %s) AS unknowns, "
            "max(created_at) FILTER (WHERE result = %s) AS last_unknown "
            "FROM verify_attempt WHERE email = %s AND provider = %s",
            (_UNKNOWN, _UNKNOWN, _UNKNOWN, email, provider),
        )
        row = cur.fetchone()
    if row["settled"]:
        return True
    if not row["unknowns"]:
        return False
    if row["unknowns"] >= _UNKNOWN_MAX_TRIES:
        return True
    age = datetime.now(UTC) - row["last_unknown"]
    return age.days < _UNKNOWN_RETRY_DAYS


@component(
    "r4_verify", "R",
    "Vendor-agnostic email verifier: catch_all/risky are failures, only 'valid' passes. "
    "Tier-gated, owner/admin-first, budget-capped, idempotent per (email, provider).",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    cfg = _config()
    provider = provider_for(cfg, ctx.settings, opts.get("provider"))

    candidates = _select_candidates(conn, opts)

    api_key = api_key_for(provider, ctx.settings)

    if not _usable(provider, ctx.settings):
        return RunResult(
            skipped=len(candidates), notes=["inert: no verification provider configured"]
        )

    adapter = _ADAPTERS[provider]
    price = float(cfg.get("price_per_email_usd", {}).get(provider, 0.0))
    raw_max_usd = opts.get("max_usd")
    max_usd = float(raw_max_usd) if raw_max_usd not in (None, "") else None

    result = RunResult()
    spent = 0.0
    current_firm: Any = object()  # sentinel -- never equals a real firm_id
    # A domain that answered catch-all accepts every address: a further call
    # there tells nothing and costs the same. The first catch-all answer marks
    # the rest of that domain's candidates catch-all without paying (the
    # guesser already does this; the 28 Sep 2026 live run paid twice on one
    # domain before this was added). Prior runs' answers count too.
    catch_all_domains: set[str] = _catch_all_domains(conn, provider)

    with httpx.Client() as client:
        for row in candidates:
            if row["firm_id"] != current_firm:
                ctx.checkpoint()
                current_firm = row["firm_id"]

            email = row["email"]

            if _already_attempted(conn, email, provider):
                result.skipped += 1
                continue

            domain = email.rsplit("@", 1)[-1].lower()
            if domain in catch_all_domains:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE contact_email SET status = 'catch_all', verified_at = %s "
                        "WHERE contact_id = %s AND email = %s",
                        (datetime.now(UTC), row["contact_id"], email),
                    )
                result.processed += 1
                result.notes.append(f"{email}: catch-all domain, not paid for")
                continue

            if max_usd is not None and spent + price > max_usd:
                result.skipped += 1
                result.notes.append(f"budget stop: ${max_usd:.2f} cap reached before {email}")
                continue

            try:
                verify_result = adapter(email, client=client, api_key=api_key, cfg=cfg)
            except VerifyError as exc:
                result.failed += 1
                result.notes.append(f"{email}: {exc}")
                continue

            now = datetime.now(UTC)
            if verify_result.status == _UNKNOWN:
                # Not a verdict: the address stays unverified and is asked
                # again later; the provider does not bill an unknown.
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO verify_attempt (email, provider, result, raw, cost_usd) "
                        "VALUES (%s, %s, %s, %s, 0)",
                        (email, provider, _UNKNOWN, Jsonb(verify_result.raw)),
                    )
                result.notes.append(
                    f"{email}: unknown -- asked again in {_UNKNOWN_RETRY_DAYS} days"
                )
                result.processed += 1
                continue
            spent += price
            if verify_result.status == "catch_all":
                catch_all_domains.add(domain)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE contact_email SET status = %s, verified_at = %s "
                    "WHERE contact_id = %s AND email = %s",
                    (verify_result.status, now, row["contact_id"], email),
                )
                cur.execute(
                    "INSERT INTO verify_attempt (email, provider, result, raw, cost_usd) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (email, provider, verify_result.status, Jsonb(verify_result.raw), price),
                )
            result.processed += 1
    ctx.checkpoint()

    return result
