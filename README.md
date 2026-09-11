# Lead Gen Engine — web

The web UI for Legal Soft's Lead Gen Engine. Next.js 16 (App Router, Turbopack),
React 19, Tailwind v4, TanStack Query and Table, shadcn/ui (Radix) restyled to
the design system in `../Lead Gen Engine/plan/ui-design-system.md` ("The Record").

## Commands

| Command | What it does |
|---|---|
| `npm run dev:fixtures` | Dev server on fixture data (`src/fixtures/*.json`) — no engine needed |
| `npm run dev` | Dev server against the live engine at `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`) |
| `npm run api:types` | Regenerate `src/lib/api/schema.d.ts` from `../Lead Gen Engine/openapi.json` |
| `npm run typecheck` | Route types plus `tsc --noEmit` |
| `npm run lint` | ESLint |
| `npm run test` | Vitest (jsdom) |
| `LGE_LIVE_API=http://127.0.0.1:8000 npm run test` | Also checks the running engine against the contract |
| `npm run build` | Production build (api mode) |

Start the engine with `uv run lge serve` in the backend folder. Its CORS allows
`http://localhost:3000` and `http://127.0.0.1:3000` only, so run the live UI on
port 3000.

## Where things live

- `src/lib/api/` — typed client (`client.ts`), transport, TanStack Query hooks,
  and `types.ts`, which aliases the generated OpenAPI schema. `fixture-server.ts`
  is a dev-only stand-in for the engine; api-mode builds don't include it.
- `src/components/record/` — the record's vocabulary: `ProofQuote` (the
  highlighter), `SourceCite`, `TierMark`, `StatusBadge`, unknown values.
- `src/components/ui/` — shadcn primitives, each restyled to the tokens.
- `src/app/globals.css` — the tokens. Tailwind's default palette is reset:
  extend the token layer rather than reaching for a one-off colour.
- `src/test/contract-schemas.ts` — strict schemas pinned to the contract types,
  used to hold fixtures (and optionally the live engine) to the contract.
