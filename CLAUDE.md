# Lead Gen Engine — backend

The engine: scrapers, database, scoring, API. Three repos: **brain** `brain/` (plans, decisions, report), **backend** here, **frontend** `frontend/`.

## At the end of every session, write the report

Add what you did to `brain/REPORT.md`: one entry per day, newest first, **one paragraph in plain words** — what was built or fixed and why it mattered. No bullets, no file names, no jargon. If today's entry exists, extend it instead of adding another.

A decision that changes behaviour also gets a numbered entry in `brain/context/70-decisions/01-decision-log.md` in the same session.

## Where the docs are

Docstrings in `lge/` cite `plan/api-contract.md` and `context/...`. Those paths are now relative to `brain/`.

## Running things here

- `bash scripts/pg.sh start` — portable Postgres, port 54329, database `lge`.
- `.venv/Scripts/python.exe -m lge <cmd>` and `... -m pytest` — go through the interpreter. Application Control blocks the `.venv` launcher stubs, so never call `lge.exe` or `pytest.exe`, and the system `python` has none of the dependencies.
- `uv run --no-sync` while any process is running; a plain `uv run` tries to rewrite a locked environment.
- Stop a server **by exact PID only**, verified against the port and its command line. Never by name or pattern — that has killed an unrelated service before.
- `.local/objects` is the raw-page store and `.local/pgdata` is the database. Never delete either.

## Rules

- The store mediates everything; no component reads another's output.
- `reconcile()` is the only writer of firm columns; everything else writes claims into `firm_attribute` with a source tag.
- A logic change re-derives from stored HTML. Never re-crawl to fix a rule.
- No job-board scraping, no professional-network extraction, no defeating bot management. Honour robots.txt; the crawler identifies itself honestly.
- A bot check (a 202 from search) means back off and stop — never work around it.
- The API binds to `127.0.0.1` only. Contacts are personal data. Never log or print keys.
