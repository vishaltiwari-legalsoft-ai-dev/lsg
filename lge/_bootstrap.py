"""Windows runtime bootstrap — must run before anything imports psycopg.

psycopg runs in pure-Python mode on this machine (Windows Application Control
blocks the compiled wheels) and loads libpq.dll from the portable Postgres in
.local/pgsql/bin. Importing the `lge` package runs this; pytest also loads it as a
plugin (`-p lge._bootstrap` in pyproject) so conftest's own `import psycopg` works.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_done = False


def ensure() -> None:
    global _done
    if _done:
        return
    _done = True
    if sys.platform != "win32":
        return
    pg_bin = Path(__file__).resolve().parents[1] / ".local" / "pgsql" / "bin"
    if pg_bin.is_dir():
        os.environ["PATH"] = str(pg_bin) + os.pathsep + os.environ.get("PATH", "")
        os.add_dll_directory(str(pg_bin))
    os.environ.setdefault("PSYCOPG_IMPL", "python")


ensure()
