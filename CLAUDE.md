@AGENTS.md

# Lead Gen — frontend

The screens. Three repos: **brain** `../lead-gen-brain` (plans, decisions, report), **backend** `../Lead Gen Engine` (engine, scrapers, API), **frontend** here.

## At the end of every session, write the report

Add what you did to `../lead-gen-brain/REPORT.md`: one entry per day, newest first, **one paragraph in plain words** — what was built or fixed and why it mattered. No bullets, no file names, no jargon. If today's entry exists, extend it instead of adding another.

## Running it

- `npm run dev` — http://localhost:3100. `/api/*` is rewritten to the engine on `127.0.0.1:8000`, so the app is same-origin and needs no CORS.
- `npm run dev:fixtures` — sample data only, no engine needed.
- Start the engine first: `python -m lge serve` in the backend repo, with Postgres up (`bash scripts/pg.sh start`).

## Rules

- The design system is `../lead-gen-brain/plan/ui-design-system.md`; the API shapes are `../lead-gen-brain/plan/api-contract.md`. Types are generated from the engine's `openapi.json` — regenerate them rather than hand-writing a shape.
- Plain words on screen, never raw codes from the database.
- The highlighter marks quoted proof only — never metadata, never a score.
- Every capability the engine has needs a visible result and a trigger on screen.
- Every screen needs its empty, loading and error state written before it ships.
