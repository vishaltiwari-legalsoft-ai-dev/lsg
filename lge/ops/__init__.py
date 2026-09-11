"""Ops plane (M10): observability (context/40-pipeline/07-observability.md)
and orchestration (context/40-pipeline/06-orchestration.md) -- daily
metrics snapshots, the alert suite, the g3_tier_distribution gate, the flow
runner, and the attribution report.

`lge/registry.py`'s `discover()` walks a fixed package list
(`_DISCOVER_PACKAGES`) that does NOT include `lge.ops` -- that list is part
of a contract file this build does not modify. Importing this package is
therefore what registers observe_snapshot, the alerts component and
g3_tier_distribution (the same way discover() registers everything else,
just triggered by import rather than by package-walk): every module here
that carries an `@component`/`@gate` decorator is imported below as a side
effect, so `import lge.ops` (directly, or transitively via lge.cli_ops) is
enough to make them visible to `registered_components()`/`registered_gates()`.
"""

from __future__ import annotations

from lge.ops import alerts as _alerts  # noqa: F401
from lge.ops import gates as _gates  # noqa: F401
from lge.ops import snapshot as _snapshot  # noqa: F401
