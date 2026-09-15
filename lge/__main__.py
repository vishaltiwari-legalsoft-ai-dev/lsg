"""`python -m lge` -- the same command line as the `lge` console script.

The console script is an unsigned launcher stub that Windows Smart App
Control may refuse to run; the interpreter itself is allowed, so this is
the launch path that always works: `uv run --no-sync python -m lge ...`.
"""

from lge.cli import app

app(prog_name="lge")
