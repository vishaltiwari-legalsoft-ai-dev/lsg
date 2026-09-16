#!/usr/bin/env bash
# Delete only what a tool regenerates on its own: caches, build output, run logs.
# Never touches the object store, the database, real input data, or .env.
#
#   bash scripts/clean.sh            # show what would go
#   bash scripts/clean.sh --yes      # actually delete it
#
# Stop the frontend dev server first: deleting .next under a running
# "npm run dev" makes it rebuild mid-request.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$(cd "$ROOT_DIR/.." && pwd)/lead-gen-web"
DRY=1
[ "${1:-}" = "--yes" ] && DRY=0

total=0

drop() {
  # drop <path> <why>
  local path="$1" why="$2" kb
  [ -e "$path" ] || return 0
  kb=$(du -sk "$path" 2>/dev/null | cut -f1)
  total=$((total + kb))
  printf '%8s KB  %-52s %s\n' "$kb" "${path#"$(dirname "$ROOT_DIR")"/}" "$why"
  [ "$DRY" = "0" ] && rm -rf "$path"
  return 0
}

echo "--- backend ---"
while IFS= read -r d; do drop "$d" "python bytecode"; done < <(
  find "$ROOT_DIR" -name __pycache__ -type d -not -path "*/.venv/*" 2>/dev/null
)
drop "$ROOT_DIR/.pytest_cache" "pytest cache"
drop "$ROOT_DIR/.ruff_cache" "ruff cache"
while IFS= read -r f; do drop "$f" "finished run log"; done < <(
  find "$ROOT_DIR/.local/logs" -name '*.log' 2>/dev/null
)
drop "$ROOT_DIR/.local/initdb.log" "one-off initdb log"

if [ -d "$WEB_DIR" ]; then
  echo "--- frontend ---"
  drop "$WEB_DIR/.next" "next build cache"
  drop "$WEB_DIR/.next-dev.log" "dev server log"
  drop "$WEB_DIR/tsconfig.tsbuildinfo" "typescript build info"
fi

echo
printf 'total %s KB (~%s MB)\n' "$total" "$((total / 1024))"
if [ "$DRY" = "1" ]; then
  echo "dry run — nothing deleted. run: bash scripts/clean.sh --yes"
else
  echo "deleted."
fi

# Deliberately NOT touched: .local/objects (raw pages — the reason a rule change
# is a re-parse, not a re-crawl), .local/pgdata, .local/pgsql, .local/pg.log
# (the live server's own log), .local/imports (staged uploads the API still
# lists), .venv, data/in, .env.
