"""`lge serve` / `lge openapi` -- registers onto the existing Typer `app`
from `lge.cli`, the same pattern `lge/cli_ops.py` uses (see that module's
docstring for why `lge.cli` does not import this one itself). Importing
this module directly is sufficient on its own: `from lge.cli import app`
below fully imports `lge.cli` first if it is not already loaded.
"""

from __future__ import annotations

import json

import typer

from lge.cli import app
from lge.settings import PROJECT_ROOT

_HOST_OPTION = typer.Option("127.0.0.1", "--host")
_PORT_OPTION = typer.Option(8000, "--port")
_RELOAD_OPTION = typer.Option(False, "--reload")


@app.command("serve")
def serve_cmd(
    host: str = _HOST_OPTION, port: int = _PORT_OPTION, reload: bool = _RELOAD_OPTION
) -> None:
    """Run the FastAPI app with uvicorn. Binds to 127.0.0.1 by default --
    plan/api-contract.md and plan/ui-plan.md's security section: not
    reachable from the network until UI-7 adds auth."""
    import uvicorn

    uvicorn.run("lge.api.app:app", host=host, port=port, reload=reload)


@app.command("openapi")
def openapi_cmd() -> None:
    """Write openapi.json at the repo root from the live FastAPI app --
    the contract the frontend generates its TypeScript types from."""
    from lge.api.app import app as fastapi_app

    schema = fastapi_app.openapi()
    out_path = PROJECT_ROOT / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    typer.echo(f"wrote {out_path}")
