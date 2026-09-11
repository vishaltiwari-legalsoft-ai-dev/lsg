"""r5_phone -- phone normalizer + DNC scrub adapter (Plane R,
context/40-pipeline/02-component-register.md: "Business lines sit outside
most DNC scope, but solos routinely list a mobile as the firm number. Scrub
anyway [once a provider exists]").

Normalisation
-------------
For every contact with no `phone_e164` yet, `norm_phone()` is applied to
`contact.phone_direct` first and to `firm.phone_e164` (the firm's main line,
already normalized by whichever component set it) as a fallback -- a solo
who lists no direct line commonly IS reachable at the firm's own number.
Neither source being a usable number leaves the contact untouched (never a
guess).

`phone_line_type` comes from `phonenumbers.number_type()`, recorded
honestly rather than guessed: for a US number the library very often
returns FIXED_LINE_OR_MOBILE (US carriers don't publish the fixed/mobile
split the way some countries do) -- that is recorded as 'fixed_or_mobile',
not forced into 'fixed_line' or 'mobile'.

DNC scrub
---------
`dnc_status` defaults to 'unknown' (migration 070) and this component's DNC
adapter interface has exactly one implementation today, `none`, which
leaves it there -- a registry scrub needs a subscription this project does
not have yet. The adapter is still exercised on every row (not skipped
outright) so wiring a real provider later is a one-line swap of
`_DNC_ADAPTERS['<name>']`, not a new code path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import phonenumbers
import yaml

from lge.norm import norm_phone
from lge.registry import RunContext, RunResult, component

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "resolvers.yml"

_LINE_TYPE_MAP: dict[int, str] = {
    phonenumbers.PhoneNumberType.FIXED_LINE: "fixed_line",
    phonenumbers.PhoneNumberType.MOBILE: "mobile",
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
    phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
    phonenumbers.PhoneNumberType.VOIP: "voip",
}


class DncAdapter(Protocol):
    def __call__(self, e164: str) -> str: ...  # 'unknown' | 'clear' | 'listed'


def _dnc_none(_e164: str) -> str:
    return "unknown"


_DNC_ADAPTERS: dict[str, DncAdapter] = {"none": _dnc_none}


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["r5_phone"]


def line_type(e164: str) -> str:
    try:
        parsed = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException:
        return "unknown"
    return _LINE_TYPE_MAP.get(phonenumbers.number_type(parsed), "unknown")


def _select_contacts(conn, opts: dict[str, Any]) -> list[dict]:
    firm_ids_file = opts.get("firm_ids_file")
    clauses = ["c.phone_e164 IS NULL", "(c.phone_direct IS NOT NULL OR f.phone_e164 IS NOT NULL)"]
    params: list[Any] = []
    if firm_ids_file:
        ids = [
            line.strip()
            for line in Path(str(firm_ids_file)).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        clauses.append("c.firm_id = ANY(%s)")
        params.append(ids)

    query = (
        "SELECT c.id, c.firm_id, c.phone_direct, f.phone_e164 AS firm_phone "
        "FROM contact c JOIN firm f ON f.id = c.firm_id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY c.firm_id, c.id"
    )
    limit = opts.get("limit")
    if limit not in (None, ""):
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)  # noqa: S608 -- clauses are fixed strings, not user input
        return cur.fetchall()


@component(
    "r5_phone", "R",
    "Normalises contact/firm phone numbers into contact.phone_e164 + an honest "
    "phone_line_type; DNC scrub is an inert adapter until a provider is under contract.",
)
def run(ctx: RunContext, **opts: Any) -> RunResult:
    conn = ctx.conn
    cfg = _config()
    provider = str(opts.get("dnc_provider", cfg.get("dnc_provider", "none")))
    dnc_fn = _DNC_ADAPTERS.get(provider, _dnc_none)

    result = RunResult()
    rows = _select_contacts(conn, opts)

    current_firm: Any = object()  # sentinel -- never equals a real firm_id
    for row in rows:
        if row["firm_id"] != current_firm:
            ctx.checkpoint()
            current_firm = row["firm_id"]
        try:
            raw = row["phone_direct"] or row["firm_phone"]
            e164 = norm_phone(raw) if raw else None
            if not e164:
                result.skipped += 1
                continue
            dnc_status = dnc_fn(e164)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE contact SET phone_e164 = %s, phone_line_type = %s, "
                    "dnc_status = %s WHERE id = %s",
                    (e164, line_type(e164), dnc_status, row["id"]),
                )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001 -- one bad row must not sink the run
            result.failed += 1
            result.notes.append(f"r5_phone contact={row['id']}: {exc}")
    ctx.checkpoint()

    if provider not in _DNC_ADAPTERS or provider == "none":
        result.notes.append("inert: no DNC provider configured")

    return result
