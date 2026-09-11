"""The flow runner -- ordered lists of already-registered component/gate
names, executed step by step with a hard gate check between stages
(context/40-pipeline/06-orchestration.md). Prefect-on-Cloud-Run is deferred
(see the M10 build report): a flow here is data (config/flows.yml) plus this
walker, and the same component callables can be handed to a real Prefect
flow later without change.

Each step runs in its own transaction, the same path `lge run` uses
(commit_checkpoints=True): call the component, then commit (or roll back in
--dry-run) before moving to the next step. A gate step is read-only and
always rolls back, matching `lge gate`'s own behaviour.

Stopping rules:
  * a gate that fails STOPS the flow immediately -- "the gate that must not
    be advisory" (context/40-pipeline/06-orchestration.md); everything
    downstream is spent per-firm.
  * a component step whose RunResult.failed > 0 STOPS the flow unless the
    step is marked `continue_on_fail: true` in config/flows.yml.
  * a step naming a component or gate that is not registered raises
    FlowError immediately, naming the flow, the step index, and the name --
    never silently skipped.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lge.ops.config import FLOWS_PATH, load_flows
from lge.registry import RunContext, RunResult, discover, registered_components, registered_gates


class FlowError(RuntimeError):
    """A flow definition problem (unknown flow/component/gate, or a
    malformed step) -- never swallowed."""


@dataclass
class StepOutcome:
    index: int
    kind: str  # "component" | "gate"
    name: str
    ok: bool
    detail: str
    result: RunResult | None = None


@dataclass
class FlowOutcome:
    flow: str
    steps: list[StepOutcome] = field(default_factory=list)
    stopped_at: int | None = None  # step index that stopped the flow, else None

    @property
    def ok(self) -> bool:
        return self.stopped_at is None


def _ensure_registered() -> None:
    """Populate lge.registry's component/gate maps. discover() walks the
    contract's fixed package list (lge/registry.py `_DISCOVER_PACKAGES`,
    never modified here) which does NOT include lge.ops -- ops components
    (observe_snapshot, alerts) and the g3_tier_distribution gate register
    themselves as an import side effect instead, the same mechanism
    discover() itself relies on for every other plane."""
    discover()
    import lge.ops  # noqa: F401 -- side effect: registers ops components/gates


def _filtered_opts(fn: Any, opts: dict[str, str]) -> dict[str, str]:
    """Only pass a step the options its component function actually
    accepts. Every real component in this repo takes `**opts`, so this is
    normally a no-op -- but a step must never crash a flow just because a
    global `--opt` was meant for a different step."""
    sig = inspect.signature(fn)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return dict(opts)
    allowed = {
        pname
        for pname, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    allowed.discard("ctx")
    return {k: v for k, v in opts.items() if k in allowed}


def run_flow(
    conn,
    settings,
    name: str,
    *,
    opts: dict[str, str] | None = None,
    from_step: int = 1,
    dry_run: bool = False,
    flows_path: Path = FLOWS_PATH,
) -> FlowOutcome:
    _ensure_registered()
    flows = load_flows(flows_path)
    if name not in flows:
        known = ", ".join(sorted(flows)) or "(none)"
        raise FlowError(f"unknown flow {name!r}. Known flows: {known}")

    steps = flows[name]
    opts = dict(opts or {})
    components = registered_components()
    gates = registered_gates()

    ctx = RunContext(conn, settings, dry_run=dry_run, commit_checkpoints=True)
    outcome = FlowOutcome(flow=name)

    for i, step in enumerate(steps, start=1):
        if i < from_step:
            continue

        if "component" in step:
            cname = step["component"]
            if cname not in components:
                raise FlowError(
                    f"flow {name!r} step {i}: unknown component {cname!r}. "
                    f"Known components: {', '.join(sorted(components))}"
                )
            fn = components[cname].fn
            step_defaults = {k: str(v) for k, v in (step.get("opts") or {}).items()}
            merged = {**step_defaults, **opts}
            call_opts = _filtered_opts(fn, merged)

            result = fn(ctx, **call_opts)
            if not dry_run:
                conn.commit()
            else:
                conn.rollback()

            continue_on_fail = bool(step.get("continue_on_fail", False))
            ok = result.failed == 0 or continue_on_fail
            outcome.steps.append(
                StepOutcome(
                    i, "component", cname, ok,
                    f"processed={result.processed} skipped={result.skipped} failed={result.failed}",
                    result,
                )
            )
            if not ok:
                outcome.stopped_at = i
                return outcome

        elif "gate" in step:
            gname = step["gate"]
            if gname not in gates:
                raise FlowError(
                    f"flow {name!r} step {i}: unknown gate {gname!r}. "
                    f"Known gates: {', '.join(sorted(gates))}"
                )
            passed, report = gates[gname](ctx)
            conn.rollback()
            outcome.steps.append(StepOutcome(i, "gate", gname, passed, report, None))
            if not passed:
                outcome.stopped_at = i
                return outcome

        else:
            raise FlowError(f"flow {name!r} step {i} is neither 'component' nor 'gate': {step!r}")

    return outcome
