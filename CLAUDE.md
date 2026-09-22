@AGENTS.md

# Lead Gen — frontend

The screens. Three repos: **brain** `../brain` (plans, decisions, report), **backend** the folder above this one (`..`) (engine, scrapers, API), **frontend** here.

## At the end of every session, write the report

Add what you did to `../brain/REPORT.md`: one entry per day, newest first, **one paragraph in plain words** — what was built or fixed and why it mattered. No bullets, no file names, no jargon. If today's entry exists, extend it instead of adding another.

## Running it

- `npm run dev` — http://localhost:5000. `/api/*` is rewritten to the engine on `127.0.0.1:8100`, so the app is same-origin and needs no CORS.
- `npm run dev:fixtures` — sample data only, no engine needed.
- Start the engine first: `.venv/Scripts/python.exe -m lge serve` in the backend repo, with Postgres up (`bash scripts/pg.sh start`).
- Port 3000 belongs to another project on this machine. Never stop or reuse it.

## Rules

- The design system is `../brain/plan/ui-design-system.md`; the API shapes are `../brain/plan/api-contract.md`. Types are generated from the engine's `openapi.json` — regenerate them rather than hand-writing a shape.
- Plain words on screen, never raw codes from the database.
- The highlighter marks quoted proof only — never metadata, never a score.
- Every capability the engine has needs a visible result and a trigger on screen.
- Every screen needs its empty, loading and error state written before it ships.
