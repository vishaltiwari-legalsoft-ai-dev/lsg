"""config/schedule.yml loading, config/flows.yml loading, config/alerts.yml
gate thresholds, and scripts/schedule_windows.ps1 -- a generator that
prints but never executes."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from lge.ops.config import load_alerts_config, load_flows, load_schedule
from lge.settings import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "schedule_windows.ps1"


def test_load_schedule_has_the_nightly_flow_entry():
    rows = load_schedule()
    by_id = {r["id"]: r for r in rows}
    nightly = by_id["nightly"]
    assert nightly["kind"] == "flow"
    assert nightly["job"] == "nightly"
    assert nightly["time"] == "02:00"
    assert nightly["cadence"] == "daily"


def test_load_schedule_marks_unbuilt_components_as_placeholders():
    rows = load_schedule()
    by_id = {r["id"]: r for r in rows}
    assert by_id["i3_portal_demand"]["placeholder"] is True
    assert by_id["bench_sync_hourly"].get("placeholder", False) is False


def test_load_flows_has_the_three_required_flows():
    flows = load_flows()
    assert set(flows) >= {"load_first_party", "profile_probe", "nightly"}

    nightly_names = [s.get("component") or s.get("gate") for s in flows["nightly"]]
    assert nightly_names == [
        "ja1_careers", "ja6_normalise", "ja6_closure", "ja7_pain_signals", "score",
        "build_list", "observe_snapshot", "alerts",
    ]


def test_load_flows_has_gates_between_stages():
    flows = load_flows()
    load_first_party_gates = [s["gate"] for s in flows["load_first_party"] if "gate" in s]
    assert load_first_party_gates == ["g1_identity", "g7_coverage"]

    profile_probe_gates = [s["gate"] for s in flows["profile_probe"] if "gate" in s]
    assert profile_probe_gates == ["g3_tier_distribution"]


def test_load_alerts_config_g3_defaults():
    cfg = load_alerts_config()
    assert cfg.gates_g3.shift_threshold == pytest.approx(0.15)
    assert "UNCLASSIFIED" in cfg.gates_g3.exempt_tiers
    assert cfg.gates_g3.min_firms_for_uniformity_check >= 1


def test_alert_thresholds_are_readable():
    cfg = load_alerts_config()
    assert cfg.alert("bounce_rate")["threshold"] == pytest.approx(0.02)
    assert cfg.alert("bench_starvation")["zero_days_threshold"] == 7
    assert cfg.alert("dedupe_drift") == {}  # no tunables -- must not KeyError


@pytest.mark.skipif(shutil.which("powershell") is None, reason="powershell not on PATH")
def test_schedule_windows_ps1_prints_and_executes_nothing():
    result = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(SCRIPT_PATH)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    # The printed lines legitimately START with "schtasks /Create ..." --
    # that IS the generated, copy-pasteable command. What must NOT be true
    # is that the SCRIPT ITSELF ever invokes schtasks as a live command
    # (checked against the .ps1 source below, not this output).
    assert out.count("schtasks /Create") >= 5
    assert "LGE_nightly" in out
    assert "LGE_bench_sync_hourly" in out
    assert "PLACEHOLDER" in out

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    code_lines = [ln for ln in source.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)
    # Every "schtasks" in the CODE (comments excluded -- the header
    # deliberately names what this script must NOT do) is inside a string
    # being built (`return "schtasks ...`), never the first token of a
    # line, which is how the script would call it live rather than print it.
    assert re.search(r"(?m)^\s*schtasks\b", code) is None
    for forbidden in ("Invoke-Expression", "Start-Process schtasks", "& schtasks", "iex "):
        assert forbidden not in code
