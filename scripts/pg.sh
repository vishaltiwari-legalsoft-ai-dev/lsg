#!/usr/bin/env bash
# Portable Postgres control for local dev. Data dir/port/log are fixed so every
# agent and every script in this repo points at the same instance.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="$ROOT_DIR/.local/pgsql/bin"
PGDATA="$ROOT_DIR/.local/pgdata"
PGLOG="$ROOT_DIR/.local/pg.log"
PGPORT=54329
PGHOST=127.0.0.1

export PATH="$PG_BIN:$PATH"

cmd="${1:-status}"

case "$cmd" in
  start)
    if [ ! -d "$PGDATA" ]; then
      echo "no data dir at $PGDATA — run initdb first" >&2
      exit 1
    fi
    # Non-blocking: start detached, then poll pg_isready ourselves.
    pg_ctl -D "$PGDATA" -l "$PGLOG" -o "-p $PGPORT -c listen_addresses=$PGHOST" start
    for _ in $(seq 1 20); do
      if pg_isready -h "$PGHOST" -p "$PGPORT" >/dev/null 2>&1; then
        echo "postgres is ready on $PGHOST:$PGPORT"
        exit 0
      fi
      sleep 1
    done
    echo "postgres did not become ready within 20s — check $PGLOG" >&2
    exit 1
    ;;
  stop)
    pg_ctl -D "$PGDATA" stop -m fast
    ;;
  status)
    pg_ctl -D "$PGDATA" status || true
    pg_isready -h "$PGHOST" -p "$PGPORT" || true
    ;;
  psql)
    shift || true
    psql "postgresql://postgres@${PGHOST}:${PGPORT}/postgres" "$@"
    ;;
  *)
    echo "usage: $0 {start|stop|status|psql}" >&2
    exit 1
    ;;
esac
