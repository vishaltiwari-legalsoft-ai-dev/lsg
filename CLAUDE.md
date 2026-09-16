# Brain — the thinking behind the Lead Gen project

No code lives here. Plans, decisions, specs, and the running report of what has been built.

## The rule: write the report at the end of every session

Whenever work is done on the Lead Gen project — in this repo, in the backend, or in the frontend — add it to `REPORT.md` before the session ends.

- One entry per day, newest first, under a `## <day Month year>` heading.
- **One paragraph. Plain words.** What was built or fixed, and why it mattered.
- No bullet lists, no file names, no function names, no jargon, no code.
- Write it for someone who has never seen the code.
- If today's entry already exists, extend that paragraph — never start a second one for the same day.

That is the whole rule. It is a log, not a document: short is correct.

## What is where

| Folder | Holds |
|---|---|
| `REPORT.md` | The day-by-day report above. |
| `PLAN.md` | The project plan: scope, milestones, what is deliberately excluded. |
| `context/` | The knowledge base — 39 chunks: ICP, pipeline, gates, and the decision log in `70-decisions/`. |
| `plan/` | The working plans: API contract, UI plan, design system, the outreach journey and email drafts. |
| `spec/` | The five source PDFs the whole system was built from, and how to re-render them. |
| `archive/` | Superseded drafts. Do not build from these. |

Decisions are numbered `D-001` onward in `context/70-decisions/01-decision-log.md`. A decision that changes behaviour gets written there in the same session it is made.

## The other two repos

- **Backend** — the folder above this one (`..`): the engine, the scrapers, the database, the API.
- **Frontend** — `../frontend`: the screens.
