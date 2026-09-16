---
id: datamodel.invariants
title: The seven invariants
answers: "What must be true always, and what enforces it?"
source: 01 §10
authority: canonical
stability: decided
depends_on: [datamodel.schema]
feeds: [execution.gates, pipeline.lifecycle]
---

# The seven invariants

> Each of these is enforced by **a constraint or a trigger, not by convention**. Anything
> enforced only in application code will eventually be bypassed by a backfill script.

| # | Invariant | Enforced by |
|---|---|---|
| **I1** | At most one open lead per firm | `UNIQUE INDEX ON lead (firm_id) WHERE closed_at IS NULL` |
| **I2** | No `outreach_touch` may be written for a lead whose firm domain is in `suppression` | `BEFORE INSERT` trigger — **re-checked at send, not at arm** |
| **I3** | Grade B leads may never be emailed | `CHECK (grade='A' OR channel <> 'email')` |
| **I4** | A lead cannot enter `ARMED` without bench inventory for its wedge SKU | Arming query **joins** `bench_inventory`; no join, no row |
| **I5** | Every state change writes exactly one `lead_state_event` | `AFTER UPDATE` trigger on `lead.state` |
| **I6** | `signal` is append-only; correction is a new row with a later `last_seen` | `REVOKE UPDATE, DELETE` |
| **I7** | Every `firm` value traces to at least one `firm_attribute` row | `reconcile()` is the **only writer** of those columns |

Target file: `sql/001_schema.sql`, alongside the tables. **Not yet written** — the build
order calls for these as constraints and triggers in step 1, at the same time as the schema.

---

## Why each one exists

**I1** — a firm with two open leads gets two sequences. The unique partial index makes that
impossible rather than unlikely.

**I2** — the gap between arming and sending is real. A lead can sit `ARMED` for hours; a
suppression can land in between. Checking at arm time and trusting it at send time is the
bug this invariant names. **The trigger is the enforcement; the sequencer is not trusted.**

**I3** — Grade B is a phone-and-research product. Emailing a guessed address damages the
ability to email anyone. This is a `CHECK` constraint rather than sequencer logic precisely
because someone will eventually write a "just this once" backfill.

**I4** — the product promises a start in under three days. Arming against an empty bench
manufactures a promise the delivery side cannot keep, and **the failure lands on the
strongest part of the pitch**. Expressing it as a join rather than a check means the absence
of inventory produces *no row*, which cannot be overridden by a flag.

**I5** — `lead_state_event` **is the audit log. Nothing else needs to be.** An `AFTER UPDATE`
trigger means it cannot be skipped by whoever writes the state change.

**I6** — a signal is evidence about a moment. Mutating it destroys the history that
`first_seen`-versus-`board_posted_date` repost detection depends on. Revoking the grants is
stronger than a code review.

**I7** — provenance. Without it, "why is this firm tier 3?" has no answer six weeks later,
and every debugging session becomes archaeology.

---

## The pattern

Six of the seven prevent a **silent** failure — one that produces plausible data, no error,
and a consequence weeks later. That is the failure mode this system is designed against
throughout:

- a broken dedupe that presents as better coverage
- a confident wrong `fee_model` with no error anywhere
- a name-only merge writing a false hiring history
- a stale bench that arms leads against placed inventory
- a watcher returning zero results, which does not error

Wherever a rule guards against something invisible, it is enforced in the database.
