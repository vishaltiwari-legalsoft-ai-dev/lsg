"""M10 CLI commands -- `lge alerts`, `lge flow`, `lge schedule`,
`lge report attribution`. Registers onto the existing Typer `app` from
`lge.cli` (a contract file this build does not modify) rather than defining
a separate entry point.

`lge.cli` does not import this module itself -- see the build report for
the one line the controller adds (`import lge.cli_ops`, after `app =
typer.Typer(...)`) to wire it into the real `lge` command. Importing this
module directly (as tests do) is sufficient on its own: `from lge.cli
import app` below fully imports lge.cli first if it is not already loaded,
so there is no ordering hazard either way.
"""

from __future__ import annotations

import typer

import lge.ops  # noqa: F401 -- side effect: registers observe_snapshot, alerts, g3_tier_distribution
from lge import db
from lge.cli import app
from lge.ops import alerts as ops_alerts
from lge.ops import config as ops_config
from lge.ops import flowrunner
from lge.ops import report as ops_report
from lge.registry import RunContext
from lge.settings import get_settings

report_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(report_app, name="report")


@app.command("alerts")
def alerts_cmd() -> None:
    """Evaluate every observability alert, print a table, record
    alert_event rows, and exit 1 if any alert is firing."""
    settings = get_settings()
    with db.connect(settings.dsn) as conn:
        ctx = RunContext(conn, settings, commit_checkpoints=True)
        outcomes = ops_alerts.evaluate_all(ctx)
        ops_alerts.write_alert_events(ctx, outcomes)
        conn.commit()

    name_width = max((len(o.name) for o in outcomes), default=5)
    typer.echo(f"{'alert':{name_width}}  {'state':7}  {'value':>10}  detail")
    firing = 0
    for o in outcomes:
        if o.state == "firing":
            firing += 1
        value_str = "-" if o.value is None else f"{o.value:.3g}"
        typer.echo(f"{o.name:{name_width}}  {o.state:7}  {value_str:>10}  {o.detail}")

    typer.echo(
        f"{len(outcomes)} alert(s): "
        f"{sum(1 for o in outcomes if o.state == 'ok')} ok, "
        f"{firing} firing, "
        f"{sum(1 for o in outcomes if o.state == 'no_data')} no_data"
    )
    if firing:
        raise typer.Exit(code=1)


_FLOW_OPT_OPTION = typer.Option([], "--opt", help="key=value, repeatable")
_FROM_STEP_OPTION = typer.Option(1, "--from-step", min=1)
_DRY_RUN_OPTION = typer.Option(False, "--dry-run")


@app.command("flow")
def flow_cmd(
    name: str,
    opt: list[str] = _FLOW_OPT_OPTION,
    from_step: int = _FROM_STEP_OPTION,
    dry_run: bool = _DRY_RUN_OPTION,
) -> None:
    """Run a named flow from config/flows.yml, step by step, stopping hard
    at the first failed gate or failed (non continue_on_fail) component."""
    opts: dict[str, str] = {}
    for item in opt:
        if "=" not in item:
            typer.echo(f"--opt must be key=value, got {item!r}")
            raise typer.Exit(code=1)
        key, _, value = item.partition("=")
        opts[key] = value

    settings = get_settings()
    with db.connect(settings.dsn) as conn:
        try:
            outcome = flowrunner.run_flow(
                conn, settings, name, opts=opts, from_step=from_step, dry_run=dry_run
            )
        except flowrunner.FlowError as exc:
            typer.echo(f"flow error: {exc}")
            raise typer.Exit(code=1) from exc

    for step in outcome.steps:
        marker = "ok" if step.ok else "FAIL"
        typer.echo(f"[{step.index}] {step.kind:9} {step.name:24} {marker:4}  {step.detail}")

    if not outcome.ok:
        typer.echo(
            f"flow {name!r} STOPPED at step {outcome.stopped_at} -- downstream steps did not run"
        )
        raise typer.Exit(code=1)
    typer.echo(f"flow {name!r} completed: {len(outcome.steps)} step(s)")


@app.command("schedule")
def schedule_cmd() -> None:
    """Print config/schedule.yml -- the OS-scheduler mirror of
    context/40-pipeline/06-orchestration.md's cron table. Read-only."""
    rows = ops_config.load_schedule()
    if not rows:
        typer.echo("config/schedule.yml has no schedule entries")
        return

    for row in rows:
        when = row.get("time") or row.get("day") or row.get("cadence", "")
        flag = "  [PLACEHOLDER -- not registered yet]" if row.get("placeholder") else ""
        typer.echo(
            f"{when:>8}  {row.get('cadence', ''):10}  {row.get('kind', ''):9}  "
            f"{row.get('job', ''):24}{flag}"
        )
        notes = (row.get("notes") or "").strip()
        if notes:
            for line in notes.splitlines():
                typer.echo(f"           {line.strip()}")


@report_app.command("attribution")
def report_attribution_cmd() -> None:
    """outcome (WON/LOST) x arming-signal kind x tier -- the join that
    turns seeded scoring weights into measured ones. Prints "no outcomes
    yet" when lead has no WON/LOST rows."""
    settings = get_settings()
    with db.connect(settings.dsn) as conn:
        ctx = RunContext(conn, settings)
        rows = ops_report.attribution_report(ctx)
        conn.rollback()

    if not rows:
        typer.echo("no outcomes yet")
        return

    typer.echo(f"{'outcome':8}  {'signal_kind':26}  {'tier':16}  n")
    for r in rows:
        typer.echo(f"{r.outcome:8}  {r.signal_kind:26}  {r.tier:16}  {r.n}")
