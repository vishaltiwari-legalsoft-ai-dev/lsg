---
id: signals.dedupe
title: Cross-board dedupe, dates, reposts and closure
answers: "One role on six boards is one signal — how? And when does a signal end?"
source: 03 §5, 03 §7, 03 §8
authority: canonical
stability: decided
depends_on: [signals.filter-resolve, signals.catalog]
feeds: [pipeline.scoring, pipeline.component-register]
---

# Cross-board dedupe, dates, reposts and closure

## One opening, six boards, one signal

One paralegal opening can appear on the firm's careers page, its state bar board, a county
bar board, Indeed, ZipRecruiter and Glassdoor. **That is one signal, not six** — and counted
six times it would push a firm's intent score to the top of the queue for no reason.

```
fingerprint = sha1(
    firm_id                         -- after resolution
  ‖ normalize_title(title)
  ‖ metro_code                      -- CBSA, not raw city string
  ‖ floor_to_week(earliest_posted_date)
)
```

### `normalize_title`

```
lowercase
strip seniority          (sr|jr|senior|junior|lead|i|ii|iii)
strip employment terms   (full[- ]time|part[- ]time|contract|temp)
strip location fragments and firm name
map synonyms → canonical role:
  "legal assistant" | "legal secretary" | "admin assistant, legal"  → legal_assistant
  "paralegal" | "certified paralegal" | "litigation paralegal"      → paralegal
  "intake specialist" | "client intake" | "intake coordinator"      → intake_specialist
  "case manager" | "case coordinator"                               → case_manager
  "records clerk" | "medical records"                               → document_collector
```

### Merge policy on collision

```
keep ONE signal row
first_seen    = MIN across all sources   -- earliest sighting wins
last_seen     = MAX across all sources
sources[]     = append every board it was seen on
canonical_url = prefer the firm's own careers page,
                then the bar board, then a licensed source
```

### `sources[]` is not bookkeeping — it is an intensity measure

A firm that posted **one** paralegal role to **five** different boards is spending effort
and money to fill it. A firm that posted the same role only to its own careers page may be
casually looking.

Same signal kind, materially different urgency — **and it costs nothing to capture**,
because deduplication already touched every copy.

---

## Three date fields, three different meanings

Board-reported dates **cannot be trusted**. Many boards show relative ages that round badly
— "30+ days ago" covers everything from a month to a year. Worse, **employers refresh
listings to keep them near the top**, which resets the displayed date while the underlying
vacancy is unchanged.

```
board_posted_date   what the board claims        -- untrusted, stored
first_seen          when WE first saw this fingerprint  -- THE OPERATIVE ONE
last_seen           most recent sighting         -- drives closure
```

**Our own `first_seen` is what makes "open more than 21 days" computable at all.** It is the
reason the highest-value signal in the system exists.

---

## Repost detection — the strongest variant of signal 01

```
same fingerprint, but board_posted_date has moved forward
while our first_seen stayed put
  → the firm re-listed a vacancy it has not filled
  → an active, dated admission of hiring failure

repost_count >= 1   weight 44   -- above the 40 for "open >21d"
repost_count >= 2   weight 48
```

"Open more than 21 days" is **inferred from absence of an update**. A repost is the firm
**affirmatively spending effort again** on the same unfilled seat. It is a stronger claim,
it is dated, and it is only detectable if we hold our own `first_seen` against the board's
shifting one.

### The line a repost writes

> "Saw the paralegal role at [Firm] go back up on [board] this week — second time since
> [month]."

Specific, verifiable, and **impossible to write without holding the history**. It is the
clearest example of why keeping our own dates matters more than reading theirs.

### Where an ATS gives it to us directly

Greenhouse returns both `first_published` and `updated_at` as separate fields. A listing
whose `updated_at` moves while `first_published` stays fixed is a refreshed vacancy — read
the repost signal **from the source** instead of inferring it.

Our own `first_seen` is still recorded, for every other source and as a cross-check on this
one. See [signals.crawl-policy](05-crawl-policy-and-audit.md).

---

## Closure detection

A signal **must** end when the role is filled, or the pipeline keeps working leads whose
reason for existing has gone. But absence from one board is ambiguous — listings expire on
schedules that have nothing to do with the vacancy.

```
a posting is CLOSED only when it is absent from
EVERY source in sources[] across TWO consecutive sweeps

precedence: the firm's own careers page is authoritative
  gone from Indeed, still on careers page  → still OPEN
  gone from careers page, still on Indeed  → likely CLOSED (board listing is stale)

grace: 2 sweeps, not 1 — one failed fetch must never close a live signal
```

### On close

```
signal.closed_at set → weight drops to 0 → intent recomputes
→ lead may fall out of the armed band

BUT the lead is not discarded. it returns to the pool with fit and
contact intact, and the closed posting stays as FIT HISTORY:
this firm hires paralegals.
```

A closed signal is not a deleted one. It converts from intent evidence into fit evidence —
the same conversion the internal job-history file makes in
[firstparty.job-history](../50-first-party/05-job-history.md).

---

## Do not close on a fetch failure

A site that times out, a board that rate-limits, and a parser that breaks on a redesign all
produce **the same observable as a removed posting: nothing found.**

Distinguish **fetched successfully and absent** from **fetch failed**, and only the first
counts toward closure.

> Without that distinction, one bad night silently closes thousands of live signals.

This is the same class of error as the source-state distinction in
[signals.crawl-policy](05-crawl-policy-and-audit.md): several different causes producing
one indistinguishable observable, collapsed into one flag, with silent and expensive
consequences.
