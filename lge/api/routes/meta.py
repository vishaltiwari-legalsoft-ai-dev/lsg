"""GET /api/meta/providers -- booleans only, never key values.
GET /api/meta/capabilities -- what is built and what it needs (D-059).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

from lge.api.deps import ConnDep, providers_status
from lge.api.models import (
    CapabilitiesResponse,
    CapabilityPart,
    CapabilityStep,
    OutsideService,
    ProvidersResponse,
)
from lge.settings import PROJECT_ROOT

router = APIRouter(prefix="/api/meta", tags=["meta"])

_CAPABILITIES = PROJECT_ROOT / "config" / "capabilities.yml"
_STATE_DISPLAY = {"built": "Built", "partial": "Partly built", "planned": "Not built yet"}


@functools.lru_cache(maxsize=1)
def load_capabilities(path: Path = _CAPABILITIES) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _ai_spend(conn) -> str | None:
    """What the AI has cost on this machine, from its own call log."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS calls, coalesce(sum(cost_usd), 0) AS usd FROM llm_call")
        row = cur.fetchone()
    if not row or not row["calls"]:
        return None
    return f"${float(row['usd']):.2f} so far, over {row['calls']:,} readings"


@router.get("/providers", response_model=ProvidersResponse)
def get_providers() -> ProvidersResponse:
    return ProvidersResponse(**providers_status())


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(conn: ConnDep) -> CapabilitiesResponse:
    """The three steps, what is built in each, and the outside services the
    rest waits on. The states come from config/capabilities.yml; whether a
    service is switched on is asked of the engine's own seams, so a key
    arriving changes this page without anyone editing anything."""
    cfg = load_capabilities()
    status = providers_status()

    services = []
    for item in cfg["outside"]:
        on = bool(status.get(item["provider"]))
        services.append(
            OutsideService(
                id=item["id"], label=item["label"], key=item["key"],
                what=" ".join(item["what"].split()), cost=item["cost"], on=on,
                spent_display=_ai_spend(conn) if item["id"] == "ai" and on else None,
            )
        )
    off = {s.id: s.label for s in services if not s.on}

    steps, counts, waiting = [], {"built": 0, "partial": 0, "planned": 0}, 0
    for step in cfg["steps"]:
        parts = []
        for part in step["parts"]:
            counts[part["state"]] += 1
            # A built part whose service is off is built, and idle: say which.
            waits = off.get(part.get("needs")) if part["state"] != "planned" else None
            if waits:
                waiting += 1
            parts.append(
                CapabilityPart(
                    label=part["label"],
                    what=" ".join(part["what"].split()) if part.get("what") else None,
                    state=part["state"], state_display=_STATE_DISPLAY[part["state"]],
                    waiting_on=waits,
                )
            )
        steps.append(
            CapabilityStep(step=step["step"], label=step["label"], note=step["note"], parts=parts)
        )

    total = sum(counts.values())
    summary = (
        f"{counts['built']} of {total} parts are built, "
        f"{counts['partial']} are partly there and {counts['planned']} are still to come."
    )
    if waiting:
        summary += f" {waiting} built parts are idle until a key is set."
    return CapabilitiesResponse(
        steps=steps, outside=services, built=counts["built"], partial=counts["partial"],
        planned=counts["planned"], waiting=waiting, summary=summary,
    )
