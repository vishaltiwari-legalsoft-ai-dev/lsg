"""Loaders for config/alerts.yml, config/flows.yml and config/schedule.yml.

Same pattern as lge/resolve/identity.py:load_config -- every tunable number
lives in YAML, read here, never hardcoded in lge/ops/alerts.py,
lge/ops/gates.py or lge/ops/flowrunner.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lge.settings import PROJECT_ROOT

ALERTS_PATH = PROJECT_ROOT / "config" / "alerts.yml"
FLOWS_PATH = PROJECT_ROOT / "config" / "flows.yml"
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yml"


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass(frozen=True)
class G3Config:
    shift_threshold: float
    exempt_tiers: frozenset[str]
    min_firms_for_uniformity_check: int


@dataclass(frozen=True)
class AlertsConfig:
    raw: dict[str, Any] = field(repr=False)
    gates_g3: G3Config = field(repr=False)

    def alert(self, name: str) -> dict[str, Any]:
        """Raw config dict for one alert. `{}` (not KeyError) for an alert
        with no tunables (e.g. dedupe_drift) -- a missing SECTION is a
        config bug worth surfacing, but every alert() caller below already
        supplies its own defaults, so an absent key never crashes evaluation."""
        return dict(self.raw.get("alerts", {}).get(name) or {})


def load_alerts_config(path: Path = ALERTS_PATH) -> AlertsConfig:
    raw = _read_yaml(path)
    g3_raw = raw.get("gates", {}).get("g3_tier_distribution", {})
    g3 = G3Config(
        shift_threshold=float(g3_raw.get("shift_threshold", 0.15)),
        exempt_tiers=frozenset(g3_raw.get("exempt_tiers", ["UNCLASSIFIED"])),
        min_firms_for_uniformity_check=int(g3_raw.get("min_firms_for_uniformity_check", 2)),
    )
    return AlertsConfig(raw=raw, gates_g3=g3)


def load_flows(path: Path = FLOWS_PATH) -> dict[str, list[dict[str, Any]]]:
    """{flow_name: [step, ...]} -- each step is {"component": name, ...}
    or {"gate": name}. Raises FileNotFoundError / yaml.YAMLError loudly;
    never swallowed, per the same rule discover() follows for a bad import."""
    raw = _read_yaml(path)
    flows = raw.get("flows", {})
    return {name: list((spec or {}).get("steps", [])) for name, spec in flows.items()}


def load_schedule(path: Path = SCHEDULE_PATH) -> list[dict[str, Any]]:
    raw = _read_yaml(path)
    return list(raw.get("schedule", []))
