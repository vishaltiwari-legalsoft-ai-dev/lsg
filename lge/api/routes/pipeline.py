"""GET /api/pipeline/alerts, GET /api/pipeline/gates -- read-only. Every
number comes from `lge.ops.alerts.evaluate_all` (the exact function
`lge alerts` runs) and the registered `@gate` functions in `lge.registry`
(the exact functions `lge gate <name>` runs) -- never re-evaluated here.
"""

from __future__ import annotations

from fastapi import APIRouter

from lge.api.deps import ConnDep
from lge.api.models import AlertItem, AlertsResponse, GateItem, GatesResponse
from lge.ops.alerts import evaluate_all
from lge.registry import RunContext, discover, registered_gates
from lge.settings import get_settings

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_ALERT_LABELS: dict[str, str] = {
    "watcher_silence": "Job-posting watcher",
    "platform_parser_silence": "Bar-board parser",
    "dedupe_drift": "Identity dedupe",
    "extraction_confidence_drop": "Extraction confidence",
    "tier_distribution_shift": "Tier distribution",
    "bounce_rate": "Bounce rate",
    "signal_to_contact_latency": "Signal-to-contact latency",
    "bench_starvation": "Bench starvation",
    "bench_staleness": "Bench freshness",
    "stale_share": "Stale coverage",
    "source_yield_zero": "Source yield",
    "robots_diff": "robots.txt changes",
    "agency_rule3_spike": "Agency spike",
}

# "fast gates only" -- plan/api-contract.md. Slow gates (g2 hand-check is
# its own endpoint; identity's cross-firm review scan and coverage's
# directory diff are read-heavy) are intentionally excluded from a
# request-latency-budget endpoint.
_FAST_GATES = ("invariants", "g1_identity", "g3_tier_distribution", "g7_coverage")

_GATE_LABELS: dict[str, str] = {
    "invariants": "Schema invariants",
    "g1_identity": "Identity dedupe (G1)",
    "g3_tier_distribution": "Tier distribution (G3)",
    "g7_coverage": "Coverage vs. directory (G7)",
}


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts(conn: ConnDep) -> AlertsResponse:
    ctx = RunContext(conn, get_settings())
    outcomes = evaluate_all(ctx)
    items = [
        AlertItem(
            name=o.name, label=_ALERT_LABELS.get(o.name, o.name.replace("_", " ").capitalize()),
            state=o.state, value=o.value, detail=o.detail,
        )
        for o in outcomes
    ]
    return AlertsResponse(items=items)


@router.get("/gates", response_model=GatesResponse)
def get_gates(conn: ConnDep) -> GatesResponse:
    discover()
    gates = registered_gates()
    ctx = RunContext(conn, get_settings())
    items = []
    for name in _FAST_GATES:
        fn = gates.get(name)
        if fn is None:
            continue
        passed, report = fn(ctx)
        items.append(
            GateItem(
                name=name, label=_GATE_LABELS.get(name, name), passed=passed, report=report
            )
        )
    return GatesResponse(items=items)
