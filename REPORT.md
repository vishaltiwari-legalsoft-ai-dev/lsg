# Development report

What was built, day by day, in plain words. Newest first.
One paragraph per day — enough that someone who has never seen the code knows what changed and why.

---

## 16 September 2026

The "research this firm" buttons on the screen looked like they were working but nothing ever happened — the job was being handed to a worker before it had been saved, so the worker went looking for it, found nothing, and gave up silently. Jobs are now saved first and then run on their own thread, and anything left hanging from a crashed run is marked failed when the engine starts, so the screen never claims work is in progress when it isn't. We also changed how we look people up: instead of one search per person, we now run one search per firm and match every profile on the results page against the people we already know about, which takes the full list from roughly 250,000 searches down to about 30,000 — the difference between a run that gets us blocked and one that finishes. Finally the project was split into three folders — brain (this one: the plans, the decisions and this report), backend (the engine and the scrapers) and frontend (the screens) — and the loose PDFs, superseded drafts and old run logs were cleared out of the code folder, so it is now obvious where anything lives.

---

*Entries start here. Work before this date is in the decision log (`context/70-decisions/01-decision-log.md`) and the git history of the backend and frontend repos.*
