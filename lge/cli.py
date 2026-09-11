"""The `lge` command-line entry point."""

from __future__ import annotations

import logging

import typer

from lge import db
from lge.registry import RunContext, discover, registered_components, registered_gates
from lge.settings import get_settings

app = typer.Typer(add_completion=False, no_args_is_help=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_STATUS_TABLES = [
    "firm",
    "observation",
    "contact",
    "signal",
    "lead",
    "lead_state_event",
    "outreach_touch",
    "suppression",
    "document",
]


@app.command()
def migrate() -> None:
    """Apply every sql/*.sql migration that hasn't run yet."""
    settings = get_settings()
    applied = db.migrate(settings.dsn)
    if applied:
        typer.echo(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        typer.echo("no pending migrations")


_LIMIT_OPTION = typer.Option(None, "--limit")
_DRY_RUN_OPTION = typer.Option(False, "--dry-run")
_OPT_OPTION = typer.Option([], "--opt", help="key=value, repeatable")


@app.command()
def run(
    component: str,
    limit: int = _LIMIT_OPTION,
    dry_run: bool = _DRY_RUN_OPTION,
    opt: list[str] = _OPT_OPTION,
) -> None:
    """Run one registered component."""
    discover()
    components = registered_components()
    if component not in components:
        typer.echo(f"unknown component {component!r}. Known: {', '.join(sorted(components))}")
        raise typer.Exit(code=1)

    opts: dict[str, str] = {}
    for item in opt:
        if "=" not in item:
            typer.echo(f"--opt must be key=value, got {item!r}")
            raise typer.Exit(code=1)
        key, _, value = item.partition("=")
        opts[key] = value
    if limit is not None:
        opts["limit"] = limit

    settings = get_settings()
    with db.connect(settings.dsn) as conn:
        ctx = RunContext(conn, settings, dry_run=dry_run, commit_checkpoints=True)
        result = components[component].fn(ctx, **opts)
        if not dry_run:
            conn.commit()
        else:
            conn.rollback()

    typer.echo(
        f"processed={result.processed} skipped={result.skipped} failed={result.failed}"
    )
    for note in result.notes:
        typer.echo(f"  - {note}")

    if result.failed > 0:
        raise typer.Exit(code=1)


@app.command()
def components() -> None:
    """List every registered component."""
    discover()
    for spec in sorted(registered_components().values(), key=lambda s: (s.plane, s.name)):
        typer.echo(f"{spec.plane:10} {spec.name:20} {spec.description}")


@app.command()
def status() -> None:
    """Row counts for the main tables."""
    settings = get_settings()
    with db.connect(settings.dsn) as conn:
        with conn.cursor() as cur:
            for table in _STATUS_TABLES:
                cur.execute(f"SELECT count(*) AS n FROM {table}")  # noqa: S608 (fixed allowlist)
                row = cur.fetchone()
                typer.echo(f"{table:20} {row['n']}")


@app.command()
def gate(name: str) -> None:
    """Run one registered gate."""
    discover()
    gates = registered_gates()
    if name not in gates:
        typer.echo(f"unknown gate {name!r}. Known: {', '.join(sorted(gates))}")
        raise typer.Exit(code=1)

    settings = get_settings()
    with db.connect(settings.dsn) as conn:
        ctx = RunContext(conn, settings)
        passed, report = gates[name](ctx)
        conn.rollback()

    typer.echo(report)
    if not passed:
        raise typer.Exit(code=1)


import lge.cli_ops  # noqa: F401,E402 -- registers `alerts`/`flow`/`schedule`/`report` commands

if __name__ == "__main__":
    app()
