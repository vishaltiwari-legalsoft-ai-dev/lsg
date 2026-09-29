---
purpose: The actual copy. Ready to send.
logic: see outreach-journey.md for who gets which
---

> **Rewritten 22 Sep 2026 (D-060).** The words below are the first draft, kept
> for the reasoning under each one -- why that sentence, why that order, why no
> numbers in touch 4. **`journey/copy/*.md` is now the copy itself**, rewritten
> for Legal Soft's actual offer: pre-vetted people, free to interview, working
> in under three days, HIPAA-trained. Every email also carries a signature and
> an opt-out line, appended by the renderer from `config/sender.yml`. The five
> rules in outreach-journey.md did not change, and neither did which email goes
> to whom.

# Email drafts

Written for **Tier 1A** (PI & mass tort, contingency, 2–25 attorneys) — the beachhead, and
what phases 0 and 1 collect. Swap tables for the other tiers at the bottom.

**Conventions:** lowercase subject lines. 50–90 words. No links, attachments or images in
touches 1–3. `{tokens}` resolve from the database —
[mapping here](outreach-journey.md#personalization-tokens--columns).

---

# Touch 1 — the pain

Choose by which signal fired. **This is the highest-leverage sentence in the programme.**

---

### 1A · Role open more than 21 days

> The strongest evidence available — and the one every rival sees the same morning. We do not
> win it on speed. We win it on `{cms}` and `{posted_date}`, which they do not have.

```
Subject: your {role} opening

{first_name} — the {role} role on your careers page has been up since
{posted_date}. Still looking?

We place dedicated remote legal staff with PI firms. One person, your
cases, working inside {cms} — not a pooled service desk.

Worth a short call, or should I put it in writing first?
```

**No-CMS variant** — replace the middle paragraph:
```
We place dedicated remote legal staff with PI firms. One person, assigned
to your cases, working in your systems — not a pooled service desk.
```

---

### 1B · Role reposted

> Almost nobody can write this. It requires holding our own `first_seen` against the board's
> shifting date.

```
Subject: the {role} role, second time

{first_name} — saw the {role} posting go back up this week. Second time
since {repost_month}, if I'm reading it right.

That usually means the local market isn't producing the candidate, not
that the need went away.

We staff that seat remotely — dedicated, not shared. Want the details?
```

---

### 1C · Two or more roles open

```
Subject: both roles still open?

{first_name} — you have {role} and {role_2} both posted. Still open?

Two seats at once usually means case volume moved before payroll could.
That gap is what we fill — dedicated remote staff, working your matters
inside {cms}.

Which of the two is hurting more?
```

Ending on a **question they can answer in four words** is deliberate. It is the lowest-friction
reply in the sequence.

---

### 1D · Mass tort campaign

```
Subject: {tort} — records volume

{first_name} — noticed you're running {tort} intake.

Four to six provider requests per claimant, thousands of claimants, all
against a filing deadline. None of it billable, and it's usually the part
that breaks first.

We staff exactly that work. Worth a conversation before the volume lands?
```

**"Before the volume lands"** is the whole message. Mass tort pain is *predictable* — reaching
them ahead of it is a different conversation from reaching them during it.

---

### 1E · Reviews — nobody called back

> **Never quote the review. Never reference a specific complaint.** Reading a customer's public
> criticism back to a firm is hostile and turns a capacity conversation defensive.

```
Subject: intake coverage

{first_name} — firms doing {practice} at your volume usually hit the same
wall: calls arriving faster than anyone can return them, and the signed
case going to whoever picked up first.

Is that a live problem for you right now, or have you got it covered?
```

*"Or have you got it covered"* gives them a graceful exit. Counter-intuitively that raises the
reply rate — it reads as a question rather than a pitch.

---

### 1F · New case management system

```
Subject: you moved to {cms}

{first_name} — looks like you moved onto {cms} recently.

The thing most firms find about a month in is that the workflow needed a
person, not a feature. Someone to actually run the records requests the
system is now tracking.

We place people who already work inside {cms}. Useful, or too early?
```

---

# Touches 2–9 · Tier 1A

---

### Touch 2 — day 3 — the specific work

```
Subject: re: your {role} opening

{first_name} — following up on the above.

The part most PI firms hand over first isn't the paralegal seat itself.
It's the records chase — provider requests, follow-ups, calling the same
clinic a fourth time.

That's the work sitting between a case and the demand going out. Want to
see what it looks like as a dedicated person?
```

**Narrows from a job title to a task.** A job title is a hiring decision; a task is a problem.
The second is much easier to say yes to.

---

### Touch 2 — pain-specific variants (added during the build)

The touch 2 above follows up on "your {role} opening". A lead armed by a mass-tort, review or
new-CMS signal has no opening, so the renderer used to skip touch 2 for them. These close that
gap. **Tier 4 (hourly) never receives any of them**: in an hourly shop records and document work
is billable, and pitching it asks the firm to convert revenue into cost.

**Mass tort:**
```
Subject: re: {tort} — records volume

{first_name} — following up on the above.

On a {tort} docket the bottleneck is rarely claimant intake. It's the
provider requests behind every claimant — the fourth call to the same
records department, the follow-up nobody has time to send before the
filing date.

That's the work we'd take first. Want to see what it looks like as a
dedicated person?
```

**Reviews — nobody called back.** The pain is intake, but rule 3 still holds: offer the
back-office half that frees their people to pick up, not an intake person. Practice-neutral,
because the review signal also runs for tier 1B.
```
Subject: re: intake coverage

{first_name} — following up.

When calls go unreturned it's rarely because nobody cares. It's because
the same people answering the phone are also chasing documents and
assembling case files.

We take the back-office half — records, follow-ups, document collection —
so your team is free to pick up. Want to see what that looks like?
```

**New case system:**
```
Subject: re: {cms}

{first_name} — following up.

A new case system usually surfaces the same thing: the tasks it tracks
still need someone to do them. Records requests queued, follow-ups due,
documents waiting to be chased.

Our people already work inside {cms}, so there's no ramp on the tooling.
Want to see what a dedicated person would take off your list?
```

---

### Touch 3 — day 7 — the arithmetic · **contingency**

> Never genericise this. The whole ICP turns on it.

```
Subject: the unbilled hours

{first_name} —

On contingency, every hour your team spends chasing records is unbilled,
and it sits between you and the fee.

A demand writer isn't a cost saving. It shortens the gap to settlement —
which is a different thing entirely, and the reason PI firms are usually
the easiest version of this conversation.

Happy to walk through the numbers on a call.
```

---

### Touch 4 — day 10 — a comparable firm

```
Subject: a firm about your size

{first_name} —

A six-attorney PI firm we work with had the same shape of problem: ad
spend bringing in cases faster than two paralegals could process them.

They started with one demand writer. Their paralegals stopped doing
records entirely and went back to actual case work.

Not saying that's you — but the pattern is common enough to mention.
```

**No numbers, no percentages, no logo.** A specific claim invites a specific challenge. The
shape of the story is the persuasive part.

---

### Touch 5 — day 14 — pre-empt the blocker

> The blocker often reads the owner's inbox. This email is written for **them**, not the owner.

```
Subject: the part people ask about

{first_name} —

The question I usually get around now is about client information.

Straight answer: your person works inside {cms} under permissions you set,
same as an in-house hire. NDA and confidentiality agreement signed before
day one. You supervise the work the way you'd supervise anyone's.

Happy to send the agreement over to read before we ever speak.
```

**"Before we ever speak"** removes the last excuse. It offers something of value with no
meeting attached.

---

### Touch 6 — day 18 — the second SKU

```
Subject: maybe the wrong end

{first_name} —

It's possible I've been aiming at the wrong end of this.

If the bottleneck isn't the demand side but the front — requests going
out, chasing providers, the clinic that never responds — that's a
document collector, and it's a smaller thing to start with.

Which end hurts more?
```

**Admitting we may have guessed wrong is disarming**, and it re-opens a thread that has gone
quiet for eighteen days without adding pressure.

---

### Touch 7 — day 21 — the other person

```
Subject: right person?

{first_name} — I may be writing to the wrong person entirely.

If someone else handles hiring and case workflow — office manager, firm
administrator — I'm happy to talk to them instead and leave you out of it.

Otherwise I'll assume the timing isn't right.
```

The administrator *is the person who posted the job nobody applied to*. Where one exists they
are the **best first contact in the firm**. This touch exists to find them.

---

### Touch 8 — day 25 — still open

**Only fires if `signal.closed_at IS NULL`.** If they filled the role, this email is actively
damaging.

```
Subject: still open?

{first_name} — the {role} posting is still up as of this week.

If you've filled it, congratulations, ignore me. If it's still open
{days_open} days on, that's usually the market telling you the candidate
isn't there locally.

That's the specific gap we fill.
```

---

### Touch 9 — day 28 — close the loop

```
Subject: closing the loop

{first_name} —

I'll stop here.

If the records backlog becomes a bigger problem later, we're easy to
find. No hard feelings either way.

Good luck with the hire.
```

**Genuinely close it.** No "just circling back," no fake deadline. This lead re-pools with its
contact intact and comes back when the next signal fires — which works far better if the last
email was gracious.

---

# Tier swaps

Touches 4, 7, 8 and 9 carry across unchanged. These are the ones that change.

---

## Tier 1B — Immigration · flat fee · bilingual

**Touch 1** — replace the middle paragraph:
```
We place bilingual legal assistants with immigration firms — form prep,
evidence collection, status checks. Spanish first language, working
inside {cms}.
```

**Touch 2** — the specific work:
```
The part most immigration firms hand over first isn't the whole assistant
role. It's form prep at volume — I-130s, adjustment packets, the evidence
chase — plus the Spanish-language calls that eat an afternoon.
```

**Touch 3** — the arithmetic · **flat fee**:
```
Subject: margin, per matter

{first_name} —

On a flat fee, the price is fixed the day you're retained. Every extra
hour on that matter comes straight out of the margin on that specific
matter.

Which makes this unusually easy to measure — you'll see the effect on the
next twenty cases, not next year.
```

**Touch 6** — second SKU is `document_collector`, framed as evidence collection.

---

## Tier 2 — Fee-shifting · employment, lemon law, workers' comp, SSDI, consumer

> Identical economics to contingency, **far less crowded.** Almost every competitor targets PI
> first, so these firms are hearing this for the first time.

**Touch 1** — middle paragraph:
```
We place dedicated remote case managers with {practice} firms — records,
agency forms, status chasing. One person, your matters, inside {cms}.
```

**Touch 3** — the arithmetic · **fee-shifting**:
```
Subject: who actually pays for the hours

{first_name} —

The defendant pays the fees. But your own labour getting there is still
an unbilled input — records, employer files, agency forms — and nobody
reimburses the time it took to chase them.

Same arithmetic as contingency, and noticeably fewer people are having
this conversation with you.
```

That last line is **true and worth saying**. It signals we understand their segment rather
than treating them as spillover PI.

---

## Tier 3 — Flat-fee volume · bankruptcy, criminal, estate, family

**Touch 1** — middle paragraph:
```
We place dedicated legal assistants with {practice} firms — document
assembly, client document collection, scheduling. One person, your
matters.
```

**Touch 3** — same flat-fee arithmetic as 1B, with the volume angle:
```
Thin margins per matter and a lot of matters means the support hours are
the whole game. Shift those and the economics move immediately.
```

**Expect this tier to buy one role readily and expand slowly.** Do not oversell the second SKU
at touch 6.

---

## Tier 4 — Hourly · **the holdout**

> **Never pitch a paralegal.** Their paralegals are billable inventory. Asking them to replace
> billable hours with cheaper unbillable ones asks them to convert revenue into cost.
>
> This tier exists to **test whether the fee-model axis is real.** Copy that violates the rule
> invalidates the test.

**Touch 1:**
```
Subject: the unbillable hours

{first_name} — a narrower note than usual.

I'm not going to suggest a paralegal — yours are billable and that would
be a bad trade for you.

But the bookkeeping, the intake calls, the marketing admin? Nobody bills
for those. That's the part we'd take.

Worth ten minutes?
```

**Touch 3:**
```
Subject: only the part nobody bills

{first_name} —

Everything your team does that appears on an invoice should stay exactly
where it is.

It's the rest — reconciliation, intake, chasing your own paperwork —
that's pure overhead in an hourly shop, and the only part worth moving.
```

**Naming the objection before they do** is the entire tier-4 strategy. It converts "you don't
understand my business" into "this person actually does."

---

# Before any of this sends

| Check | Why |
|---|---|
| `signal.evidence` present | No pain, no email. A generic email wastes the firm, not just the send |
| Every token resolves | `Hi {first_name}` costs more than the lead is worth |
| Grade A only | Grade B is a phone list |
| Not suppressed | Domain scope — one partner opting out silences the firm |
| Not `firm_track='portal'` | They already raised their hand |
| Touch 8 only if signal live | Asking about a filled role reads as careless |
| Fee model matches touch 3 | **The one that silently wrecks the tier-4 test** |
