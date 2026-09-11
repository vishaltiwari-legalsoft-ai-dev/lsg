"""Write openapi.json at the repo root from the live FastAPI app -- the
same thing `lge openapi` does, as a plain script for CI or a pre-commit
hook that would rather not go through the Typer CLI.

Run with `uv run --no-sync python scripts/export_openapi.py`.
"""

from __future__ import annotations

import json

from lge.api.app import app
from lge.settings import PROJECT_ROOT


def main() -> None:
    schema = app.openapi()
    out_path = PROJECT_ROOT / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
