"""Every step the flows and the research jobs name is a registered component
whose function takes the run context -- the registry path the CLI, the flow
runner and the API actually call, which the per-component tests bypass by
calling `module.run` directly. A decorator that lands on the wrong function
(a helper slid in above `run`) is caught here, not in production."""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from lge.api.routes.actions import CONTACT_STEPS, FULL_STEPS
from lge.registry import discover, registered_components, registered_gates

_FLOWS = Path(__file__).resolve().parents[1] / "config" / "flows.yml"


def _flow_steps() -> list[tuple[str, str, str]]:
    with _FLOWS.open("r", encoding="utf-8") as fh:
        flows = yaml.safe_load(fh)["flows"]
    out = []
    for flow, spec in flows.items():
        for step in spec["steps"]:
            if "component" in step:
                out.append((flow, "component", step["component"]))
            elif "gate" in step:
                out.append((flow, "gate", step["gate"]))
    return out


def _takes_ctx(fn) -> bool:
    params = list(inspect.signature(fn).parameters.values())
    return bool(params) and params[0].name == "ctx"


def test_every_research_step_is_a_registered_component_taking_ctx():
    discover()
    components = registered_components()
    for name in {*FULL_STEPS, *CONTACT_STEPS}:
        assert name in components, f"{name} is not a registered component"
        fn = components[name].fn
        assert _takes_ctx(fn), f"{name} is registered as {fn.__name__}{inspect.signature(fn)}"


def test_every_flow_step_is_registered_and_takes_ctx():
    discover()
    components = registered_components()
    gates = registered_gates()
    for flow, kind, name in _flow_steps():
        if kind == "component":
            assert name in components, f"flow {flow}: component {name} is not registered"
            fn = components[name].fn
        else:
            assert name in gates, f"flow {flow}: gate {name} is not registered"
            fn = gates[name]
        assert _takes_ctx(fn), f"flow {flow}: {name} is registered as {fn.__name__}"
