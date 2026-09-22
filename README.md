# Lead Gen Engine — backend

The engine behind the Legal Soft lead generation project: ingest, crawl, normalise, resolve identity, extract, score, and serve it all over an API.

One of three repos. The plans, decisions and the day-by-day report live in **`brain/`**; the screens live in **`frontend/`**.

## Layout

| Folder | Holds |
|---|---|
| `lge/` | The engine. Planes `d` (data in), `p` (pages), `w` (web signals), `r` (research), `i` (identity), `ja` (job ads), plus `score/`, `journey/`, `store/` and the FastAPI app in `lge/api/`. |
| `sql/` | Migrations, in order. The invariants I1–I7 are database triggers, not application code. |
| `config/` | The vocabularies and pattern sets: practice areas, fee patterns, crawl rules, title synonyms, schedule. |
| `journey/copy/` | The outreach email copy the journey builder assembles. |
| `tests/` | pytest. Fixtures under `tests/fixtures/` are tracked on purpose. |
| `scripts/` | Postgres control (`pg.sh`) and housekeeping (`clean.sh`). |
| `data/in`, `data/out` | Real input lists and generated reports. Never committed. |
| `.local/` | Portable Postgres, the raw-page object store, staged imports, logs. Never committed, never deleted — `.local/objects` is what makes a logic change a re-parse instead of a re-crawl. |

## Running it

Windows Application Control blocks the `.venv` launcher stubs, so always go through the module:

```bash
bash scripts/pg.sh start          # portable Postgres on port 54329
.venv/Scripts/python.exe -m lge migrate   # apply sql/ in order
.venv/Scripts/python.exe -m lge serve     # API on 127.0.0.1:8100; the screens run on localhost:5000
.venv/Scripts/python.exe -m pytest       # the suite
```

`uv run` must be called as `uv run --no-sync` while anything is running, or it tries to rewrite a locked environment.

The API binds to `127.0.0.1` only. It serves contact details, which are personal data.

## Rules that are not obvious

- **The store mediates everything.** No component reads another component's output directly.
- **`reconcile()` is the only writer of firm columns.** Everything else writes claims into `firm_attribute` with a source tag.
- **Nothing is re-crawled to fix logic.** Raw HTML is kept; version markers (`norm_version`, the extractor version, the parser version, the claims fingerprint) make a rule change re-derive from what is already stored.
- **Identity is resolved before crawling**, never after.
- **Excluded sources:** no job-board scraping, no professional-network extraction, no defeating bot management. The crawler identifies itself honestly and honours robots.txt.

## At the end of a session

Write one plain-words paragraph about what changed into `brain/REPORT.md`. The rule is in that repo's `CLAUDE.md`.
