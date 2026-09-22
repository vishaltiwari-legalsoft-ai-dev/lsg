"""A `{flow: name}` step is that flow's steps, in place (D-054): a recipe is
written once in config/flows.yml and every flow that runs it asks for it by
name. An include that loops, names no flow, or carries options is refused
loudly at load time. Pure: no connection is ever touched."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lge.ops import flowrunner
from lge.ops.config import FlowError, load_flows
from lge.settings import get_settings


def _write(tmp_path: Path, flows: dict) -> Path:
    path = tmp_path / "flows.yml"
    path.write_text(yaml.safe_dump({"flows": flows}), encoding="utf-8")
    return path


def _names(steps: list[dict]) -> list[str]:
    return [s.get("component") or s.get("gate") for s in steps]


def test_an_include_is_replaced_by_the_flows_steps_in_place(tmp_path):
    path = _write(tmp_path, {
        "inner": {"steps": [{"component": "b"}, {"gate": "g"}, {"component": "c"}]},
        "outer": {"steps": [{"component": "a"}, {"flow": "inner"}, {"component": "d"}]},
    })
    flows = load_flows(path)
    assert _names(flows["outer"]) == ["a", "b", "g", "c", "d"]
    assert _names(flows["inner"]) == ["b", "g", "c"]  # still runs on its own


def test_includes_nest_and_keep_step_options(tmp_path):
    path = _write(tmp_path, {
        "leaf": {"steps": [{"component": "x", "opts": {"limit": 5}, "continue_on_fail": True}]},
        "mid": {"steps": [{"flow": "leaf"}, {"component": "y"}]},
        "top": {"steps": [{"flow": "mid"}, {"flow": "leaf"}]},
    })
    top = load_flows(path)["top"]
    assert _names(top) == ["x", "y", "x"]
    assert top[0] == {"component": "x", "opts": {"limit": 5}, "continue_on_fail": True}


def test_an_include_that_loops_is_refused(tmp_path):
    path = _write(tmp_path, {
        "a": {"steps": [{"flow": "b"}]},
        "b": {"steps": [{"component": "x"}, {"flow": "a"}]},
    })
    with pytest.raises(FlowError, match="includes itself: a -> b -> a"):
        load_flows(path)


def test_an_include_of_an_unknown_flow_is_refused(tmp_path):
    path = _write(tmp_path, {"a": {"steps": [{"flow": "nowhere"}]}})
    with pytest.raises(FlowError, match="unknown flow 'nowhere'"):
        load_flows(path)


def test_an_include_takes_no_options(tmp_path):
    path = _write(tmp_path, {
        "a": {"steps": [{"component": "x"}]},
        "b": {"steps": [{"flow": "a", "opts": {"limit": 1}}]},
    })
    with pytest.raises(FlowError, match="takes no options"):
        load_flows(path)


def test_the_runner_raises_the_same_error_for_a_bad_include(tmp_path):
    path = _write(tmp_path, {"a": {"steps": [{"flow": "nowhere"}]}})
    with pytest.raises(flowrunner.FlowError):
        flowrunner.run_flow(None, get_settings(), "a", flows_path=path)


def test_the_real_recipes_expand_to_what_ran_before():
    flows = load_flows()
    # nightly: the careers-page sweep, then the score and the lists, as always
    assert _names(flows["nightly"]) == [
        "ja1_careers", "ja6_normalise", "ja6_closure", "ja7_pain_signals", "score",
        "build_list", "observe_snapshot", "alerts",
    ]
    research = _names(flows["research"])
    assert research[:3] == ["p1_site_map", "p2_fetch", "p3_render"]
    assert research.count("g3_tier_distribution") == 1
    # ... reconcile, then the AI names what hurts (D-058), then the score
    assert research[-3:] == ["reconcile", "ja8_pain", "score"]
    assert _names(flows["profile_probe"]) == [*research, "build_list"]
