"""The component contract every later agent codes against.

A component is a plain function `(ctx: RunContext, **opts) -> RunResult`
registered with `@component(name, plane, description)`. `discover()` imports
every module under the plane/stage packages so registration decorators run.
`RunContext.once(...)` is the idempotency primitive: a re-run with unchanged
input is a logged no-op, which is what makes every replay free (see
`context/40-pipeline/06-orchestration.md`).

A gate is a cheaper, read-only check — `@gate(name)` registers a function
`(ctx: RunContext) -> (passed: bool, report: str)`.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg

from lge.settings import Settings

logger = logging.getLogger("lge")


@dataclass
class RunResult:
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    plane: str
    description: str
    fn: Callable[..., RunResult]


class RunContext:
    """Everything a component needs to run: the connection, settings, a
    logger, and the dry-run flag. Constructed by the CLI (or by tests)."""

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings,
        *,
        dry_run: bool = False,
        log: logging.Logger | None = None,
        commit_checkpoints: bool = False,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.dry_run = dry_run
        self.log = log or logger
        self.commit_checkpoints = commit_checkpoints

    def checkpoint(self) -> None:
        """Commit completed work mid-run. Long network-bound components (crawls,
        LLM calls) call this after each firm, so a crash at firm 290 of 300 keeps
        the 289 finished documents AND their task_run idempotency markers — the
        re-run then skips them instead of re-fetching everything.

        Only the CLI enables it (commit_checkpoints=True). In tests it is a no-op,
        which preserves the per-test rollback isolation in tests/conftest.py.
        Never called in dry-run.
        """
        if self.commit_checkpoints and not self.dry_run:
            self.conn.commit()

    @contextmanager
    def once(self, component: str, entity_id: str, input_hash: str) -> Iterator[bool]:
        """Idempotency on `task_run(component, entity_id, input_hash)`.

        Yields False (caller should skip) if a row with status='ok' already
        exists for this exact key — logged as a no-op. Otherwise marks the
        row 'running', yields True, then marks 'ok' on success or 'failed'
        (with the error text) on exception, re-raising in the failed case.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM task_run WHERE component = %s AND entity_id = %s "
                "AND input_hash = %s",
                (component, entity_id, input_hash),
            )
            row = cur.fetchone()

        if row is not None and row["status"] == "ok":
            self.log.info(
                "no-op: unchanged input (component=%s entity_id=%s)", component, entity_id
            )
            yield False
            return

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_run (component, entity_id, input_hash, status, started_at)
                VALUES (%s, %s, %s, 'running', now())
                ON CONFLICT (component, entity_id, input_hash)
                DO UPDATE SET status = 'running', started_at = now(),
                              finished_at = NULL, error = NULL
                """,
                (component, entity_id, input_hash),
            )

        # The body runs under a savepoint: a database error inside it aborts
        # the transaction, and without rolling back to the savepoint the
        # 'failed' mark below would itself fail and mask the real error
        # (found on P3: a unique violation surfaced as InFailedSqlTransaction).
        savepoint = not self.conn.autocommit
        if savepoint:
            with self.conn.cursor() as cur:
                cur.execute("SAVEPOINT lge_once")
        try:
            yield True
        except Exception as exc:
            with self.conn.cursor() as cur:
                if savepoint:
                    cur.execute("ROLLBACK TO SAVEPOINT lge_once")
                cur.execute(
                    "UPDATE task_run SET status = 'failed', finished_at = now(), error = %s "
                    "WHERE component = %s AND entity_id = %s AND input_hash = %s",
                    (str(exc), component, entity_id, input_hash),
                )
            raise
        else:
            with self.conn.cursor() as cur:
                if savepoint:
                    cur.execute("RELEASE SAVEPOINT lge_once")
                cur.execute(
                    "UPDATE task_run SET status = 'ok', finished_at = now(), error = NULL "
                    "WHERE component = %s AND entity_id = %s AND input_hash = %s",
                    (component, entity_id, input_hash),
                )


ComponentFn = Callable[..., RunResult]
GateFn = Callable[[RunContext], tuple[bool, str]]

_COMPONENTS: dict[str, ComponentSpec] = {}
_GATES: dict[str, GateFn] = {}

# Packages discover() walks looking for @component / @gate registrations.
_DISCOVER_PACKAGES = (
    "lge.ingest", "lge.planes", "lge.resolve", "lge.score", "lge.journey", "lge.export",
)


def component(name: str, plane: str, description: str) -> Callable[[ComponentFn], ComponentFn]:
    """Register a component. Duplicate names raise at decoration time."""

    def decorator(fn: ComponentFn) -> ComponentFn:
        if name in _COMPONENTS:
            raise ValueError(f"component {name!r} is already registered")
        _COMPONENTS[name] = ComponentSpec(name=name, plane=plane, description=description, fn=fn)
        return fn

    return decorator


def registered_components() -> dict[str, ComponentSpec]:
    return dict(_COMPONENTS)


def gate(name: str) -> Callable[[GateFn], GateFn]:
    """Register a gate: `fn(ctx) -> (passed, report)`. Duplicate names raise."""

    def decorator(fn: GateFn) -> GateFn:
        if name in _GATES:
            raise ValueError(f"gate {name!r} is already registered")
        _GATES[name] = fn
        return fn

    return decorator


def registered_gates() -> dict[str, GateFn]:
    return dict(_GATES)


def discover() -> None:
    """Import every module under the plane/stage packages so registration
    decorators run. Tolerates a package that is missing or has no submodules.
    Import errors must surface loudly — never swallowed."""
    import pkgutil

    for package_name in _DISCOVER_PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except ModuleNotFoundError as exc:
            if exc.name == package_name:
                continue  # the package itself doesn't exist -- tolerated
            raise

        path = getattr(package, "__path__", None)
        if path is None:
            continue  # not a package (no submodules to walk)

        def _onerror(module_name: str) -> None:
            raise ImportError(f"discover(): failed to import {module_name!r}")

        for module_info in pkgutil.walk_packages(
            path, prefix=package_name + ".", onerror=_onerror
        ):
            importlib.import_module(module_info.name)  # raises loudly on failure


# ---------------------------------------------------------------------------
# The `invariants` gate: every trigger/constraint I1-I7 depend on must exist
# in the catalog. This is a catalog check, not a behavioural test -- the
# behavioural proof lives in tests/db/test_invariants.py.
# ---------------------------------------------------------------------------

_REQUIRED_INDEXES = [
    "lead_open_firm_id_uidx",  # I1
]

_REQUIRED_TRIGGERS = [
    ("outreach_touch", "trg_outreach_touch_suppression"),  # I2
    ("outreach_touch", "trg_outreach_touch_grade_b_email"),  # I3
    ("lead", "trg_lead_arming_bench"),  # I4
    ("lead", "trg_lead_transition_whitelist"),
    ("lead", "trg_lead_state_event_insert"),  # I5
    ("lead", "trg_lead_state_event_update"),  # I5
    ("signal", "trg_signal_immutable_update"),  # I6
    ("signal", "trg_signal_no_delete"),  # I6
    ("signal_sighting", "trg_signal_sighting_no_update"),  # I6 history
    ("signal_sighting", "trg_signal_sighting_no_delete"),  # I6 history
    ("firm", "trg_firm_writer_check"),  # I7
]


@gate("invariants")
def _invariants_gate(ctx: RunContext) -> tuple[bool, str]:
    missing: list[str] = []

    with ctx.conn.cursor() as cur:
        for index_name in _REQUIRED_INDEXES:
            cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (index_name,))
            if cur.fetchone() is None:
                missing.append(f"index {index_name!r}")

        for table_name, trigger_name in _REQUIRED_TRIGGERS:
            cur.execute(
                """
                SELECT 1 FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                WHERE c.relname = %s AND t.tgname = %s AND NOT t.tgisinternal
                """,
                (table_name, trigger_name),
            )
            if cur.fetchone() is None:
                missing.append(f"trigger {trigger_name!r} on {table_name!r}")

    if missing:
        return False, "missing: " + "; ".join(missing)
    return True, (
        f"all {len(_REQUIRED_INDEXES)} required indexes and "
        f"{len(_REQUIRED_TRIGGERS)} required triggers are present"
    )
