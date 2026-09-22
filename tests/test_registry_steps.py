"""Every step the flows and the research jobs name is a registered component
whose function takes the run context -- the registry path the CLI, the flow
runner and the API actually call, which the per-component tests bypass by
calling `module.run` directly. A decorator that lands on the wrong function
(a helper slid in above `run`) is caught here, not in production.

And the research button runs the recipe the full run runs (D-054): its steps
are read from config/flows.yml, never kept beside it, because a list kept
beside it drifted -- the button left out the AI reading, the address check
and classify, and a lead researched from the screen never left PROFILING."""

from __future__ import annotations

import inspect

from lge.api.labels import has_step_label
from lge.api.routes.actions import RESEARCH_FLOWS, research_steps
from lge.ops.config import load_flows
from lge.registry import discover, registered_components, registered_gates


def _takes_ctx(fn) -> bool:
    params = list(inspect.signature(fn).parameters.values())
    return bool(params) and params[0].name == "ctx"


def _components(flow: str) -> list[str]:
    return [s["component"] for s in load_flows()[flow] if "component" in s]


def test_every_research_step_is_a_registered_component_taking_ctx():
    discover()
    components = registered_components()
    for scope in RESEARCH_FLOWS:
        for name in research_steps(scope):
            assert name in components, f"{scope}: {name} is not a registered component"
            fn = components[name].fn
            assert _takes_ctx(fn), f"{name} is registered as {fn.__name__}{inspect.signature(fn)}"


def test_every_flow_step_is_registered_and_takes_ctx():
    discover()
    import lge.ops  # noqa: F401 -- registers observe_snapshot, alerts and the g3 gate

    components = registered_components()
    gates = registered_gates()
    for flow, steps in load_flows().items():  # includes already expanded
        for step in steps:
            if "component" in step:
                name = step["component"]
                assert name in components, f"flow {flow}: component {name} is not registered"
                fn = components[name].fn
            else:
                name = step["gate"]
                assert name in gates, f"flow {flow}: gate {name} is not registered"
                fn = gates[name]
            assert _takes_ctx(fn), f"flow {flow}: {name} is registered as {fn.__name__}"


def test_the_button_runs_what_the_full_run_runs():
    # profile_probe is the whole-list build: the research recipe, then the lists.
    assert _components("profile_probe") == [*research_steps("full"), "build_list"]
    full = research_steps("full")
    # the four the button's own list once left out
    for name in ("p8_llm", "p9_escalate", "r4_verify", "classify"):
        assert name in full, f"the research recipe lost {name}"
    # the address check and classify come after the people are found
    assert full.index("r4_verify") > full.index("r_email_guess")
    assert full.index("classify") > full.index("r4_verify")
    contacts = research_steps("contacts")
    assert "r4_verify" in contacts and "classify" in contacts
    assert contacts.index("reconcile") < contacts.index("classify")


def test_a_research_job_leaves_the_gates_out():
    assert "g3_tier_distribution" in [s.get("gate") for s in load_flows()["research"]]
    assert "g3_tier_distribution" not in research_steps("full")


def test_research_steps_carry_no_options_a_job_would_not_pass():
    # A job passes its firm list and live=1, nothing else. An `opts:` on a
    # research step would reach `lge flow` and not the button -- the drift
    # this module guards against. Decide how jobs take it before adding one.
    for flow in RESEARCH_FLOWS.values():
        for step in load_flows()[flow]:
            assert not step.get("opts"), f"flow {flow}: {step} carries options"


def test_every_research_step_has_a_plain_label():
    for scope in RESEARCH_FLOWS:
        for name in research_steps(scope):
            assert has_step_label(name), f"{name} would show as its bare name on the job"
