# Lead Gen — Brain

The Legal Soft lead generation project is three repositories. This is the first one.

| Repo | Folder | What it is |
|---|---|---|
| **Brain** | `Lead Gen Engine/brain` | Why we are building it and what has been built. Plans, decisions, specs, and `REPORT.md` — the day-by-day report. No code. |
| **Backend** | `Lead Gen Engine` (the folder above) | The engine: scrapers, normalisation, identity resolution, scoring, the lead lifecycle, the database and the API. |
| **Frontend** | `Lead Gen Engine/frontend` | The screens people actually work in. |

Start with `REPORT.md` for where the project stands, `PLAN.md` for where it is going, and `context/70-decisions/01-decision-log.md` for why anything is the way it is.

## What the project does

It finds small US personal-injury law firms that need staff right now, works out whether they fit, finds the person to write to, and drafts the outreach. Two questions kept deliberately apart:

- **Universe** — which firms *could* buy. Slow-changing: practice area, fee model, size, staffing shape.
- **In-market** — which of them needs help *this week*. Short-lived: an unfilled role, a capacity failure in the reviews, a volume spike.

Sending the email is out of scope. The project ends at a drafted, ready-to-send journey.

## Contents

- `REPORT.md` — what was built, day by day, in plain words.
- `PLAN.md` — scope, milestones, and what is deliberately excluded.
- `context/` — the knowledge base, 39 chunks, including the numbered decision log.
- `plan/` — API contract, UI plan, design system, outreach journey and email drafts.
- `spec/` — the five source PDFs, and how to re-render them.
- `archive/` — superseded drafts, kept for history only.
