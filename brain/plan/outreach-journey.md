---
purpose: The sequence logic — who enters, what pain drives which angle, what changes by tier
copy: see email-drafts.md for the actual emails
---

# The outreach journey

**Pain → angle → email.** This file is the mapping. The written emails are in
[email-drafts.md](email-drafts.md).

Derived from [context/10-icp/07-decision-makers-and-lead-record.md](../context/10-icp/07-decision-makers-and-lead-record.md)
· [05-tiers-and-wedge-skus.md](../context/10-icp/05-tiers-and-wedge-skus.md)
· [context/20-signals/01-signal-catalog.md](../context/20-signals/01-signal-catalog.md)

---

## The five rules every draft obeys

### 1. The pain sentence is the first line

Not "we place paralegals." **The specific role, the date it was posted, their actual case
system, the partner's real name from the bar record.**

`signal.evidence` empty → **the lead does not go out.** It returns to the pool and waits for a
real signal. A generic email to a perfectly qualified firm wastes the firm, not just the send.

### 2. Capacity, never replacement — from the very first line

> The blocker is frequently the person who opens the mail, and a message that reads as
> "replace your staff" dies in that inbox without ever reaching the owner.

**Banned:** *replace*, *cheaper than hiring*, *cut costs*, *reduce headcount*, *offshore*,
*virtual assistant*, and any comparison of an hourly rate to a US salary.

**Correct:** the work that is not getting done. The backlog. The seat that has been open
eleven weeks.

### 3. Open on a role that touches no client

Intake and case management carry accent concerns, trust concerns and professional-responsibility
anxiety — **a hard first sale into a firm that has never outsourced.**

Open on `demand_writer`, `document_collector`, `lien_negotiator`, `bookkeeper`. Client-facing
expansion becomes the firm's own idea after a quarter of watching it work.

### 4. Speak the fee model's arithmetic, not the product's features

The same role has **opposite economics** depending on how the firm bills. Touch 3 is
fee-model-specific and must never be genericised — it is the entire ICP compressed into three
sentences.

### 5. A proper email, and one ask

**Rewritten 22 Sep 2026 (D-061).** 90–130 words: "Hi {first_name}," then the observation, what
it usually means, what we would do, why we are worth an hour, and one ask. It ends with the
sign-off and signature the renderer appends (`config/sender.yml`), which carries the postal
address and the opt-out line US law requires.

**Subject lines are sentence case and specific** — the role and how long it has been open, the
second posting, the two open seats, the tort. They were lowercase fragments until the owner
said, rightly, that they read as junk.

No attachments, no tracking pixels, no link shorteners — small firms run aggressive filtering,
and a bare link to their own careers page reads better than a redirect anyway.

Never *"I hope this email finds you well."*

---

## Who enters

```
grade          = 'A'                     -- B is a phone list, never an email list
state          ∈ QUALIFIED_A
tier           NOT LIKE 'DQ%'
firm_track     ∉ {'portal', 'displacement'}    -- both are different motions
suppression    no match on domain, email or firm_id
cooldown_until IS NULL OR < now()
signal.evidence IS NOT NULL              -- no pain, no email
```

Routing from [the scoring engine](../context/40-pipeline/04-scoring-engine.md):

| Band | Condition | Journey |
|---|---|---|
| **STRIKE** | fit+intent ≥80 **and contest ≤ MED** | **Human writes it, same day. Not the sequence** |
| **SEQUENCE** | fit+intent ≥60 | All 9 touches |
| **NURTURE** | fit+intent ≥40 | Touches 1, 3, 9 only, at half cadence |
| **HOLD** | below 40 | Not contacted |

STRIKE leaving the sequence is deliberate. High intent + **low contest** is the rarest thing
this system produces — a pain nobody else can see. Spending it on a template wastes the one
advantage that was expensive to find.

---

## Pain → angle

Touch 1 is chosen by **which pain fired**. This table is the whole point of the signal layer.

| Pain signal | The angle | Why it lands |
|---|---|---|
| **Role open >21 days** | *"Still open?"* | They published the need themselves. Just observing it out loud is enough |
| **Role reposted** | *"Second time since March"* | A dated admission that the local market isn't producing the candidate |
| **Two+ roles open** | *"Both still open?"* | Expansion, not backfill. Bigger conversation, more urgency |
| **Mass tort campaign** | *"{tort} — records volume"* | Names the exact operational wall they are about to hit |
| **Reviews: nobody called back** | *"Calls arriving faster than anyone can return them"* | **Never quote the review.** See below |
| **New CMS** | *"You moved to {cms} recently"* | The moment they discover the workflow needed a person, not a feature |
| **Heavy ad spend** | *"Volume outpacing intake"* | Buying cases faster than they can process |
| **No signal — fit only** | NURTURE track, touch 3 first | No pain to name, so lead with the arithmetic instead |

### The review signal needs care

Uncontested evidence, delicate framing. **Never quote the review. Never reference a specific
complaint.**

Reading a customer's public criticism back to a firm is hostile, and it converts a capacity
conversation into a defensive one. You lose the reply and you deserve to.

**The signal decides who we contact. It does not have to appear in the copy.** Name the
*pattern* — calls arriving faster than anyone returns them — not their review.

---

## The nine touches

~28 days.

| # | Day | Angle | Driven by |
|---|---|---|---|
| 1 | 0 | **The pain.** One observation, one question | `signal.kind` |
| 2 | 3 | **The specific work.** Name the task, not the job title | tier |
| 3 | 7 | **The arithmetic.** Fee-model-specific | `firm.fee_model` |
| 4 | 10 | **A comparable firm.** Same tier, same size, named shape | tier |
| 5 | 14 | **Pre-empt the blocker.** Confidentiality and supervision, unprompted | `firm.cms_detected` |
| 6 | 18 | **The second SKU.** A different seat, in case the first was wrong | `wedge_sku_2` |
| 7 | 21 | **The other person.** Administrator if we opened on the owner | `contact.role` |
| 8 | 25 | **Still open?** Only fires if the pain is still live | `signal.closed_at IS NULL` |
| 9 | 28 | **Close the loop.** No pressure, door open | — |

**Any inbound reply halts the sequence immediately** — regardless of sentiment
(`ENGAGED → RESPONDED`). A sequence that keeps sending after a human replied is the most
visible failure a prospect can see.

**Touch 5 is load-bearing.** The blocker — senior in-house paralegal, or the partner's own risk
instinct — often reads the owner's inbox. Answering the confidentiality question before it is
asked is what gets the email forwarded instead of deleted.

---

## What changes by tier

| Tier | Segment | Opens on | Touch 6 | Never lead with |
|---|---|---|---|---|
| **1A** | PI & mass tort · contingency | `demand_writer` | `document_collector` | Intake |
| **1B** | Immigration · flat fee | `legal_assistant_es` | `document_collector` | — *(bilingual is the hook)* |
| **2** | Fee-shifting litigation | `case_manager` | `legal_assistant` | — |
| **3** | Flat-fee volume | `legal_assistant` | `bookkeeper` | — |
| **4** | Hourly · **holdout** | `bookkeeper` | `marketing_specialist` | **Paralegal. Ever.** |

**Tier 2 deserves more volume than its number suggests.** Identical overhead economics to
contingency, heavy third-party records work, and **far less crowded — almost every competitor
targets PI first.**

**Tier 4 is the falsification test.** Hourly firms are the weakest fit under the fee-model
axis, which is the axis this entire ICP rests on. If they convert anywhere near tier 1A on a
non-billable role, the primary assumption is wrong — and that is worth knowing. The copy must
never pitch them a paralegal.

---

## Personalization tokens → columns

**A token that cannot resolve means the lead does not go out.** `Hi {first_name}` reaching a
managing partner costs more than the lead is worth.

| Token | Source | Required |
|---|---|---|
| `{first_name}` | `contact.full_name` | **Yes** |
| `{firm_name}` | `firm.canonical_name` | **Yes** |
| `{role}` | `signal.evidence → normalize_title()` | **Yes** for job signals |
| `{posted_date}` | `signal.first_seen` — **ours, not the board's** | **Yes** for job signals |
| `{practice}` | `firm.primary_practice` | **Yes** |
| `{cms}` | `firm.cms_detected` | No — every draft has a no-CMS variant |
| `{city}` | `firm.city` | No |
| `{tort}` | `signal.evidence` | Mass tort only |
| `{repost_month}` | first repost date | Repost variant only |

`{posted_date}` comes from **our** `first_seen`, never the board's. Boards show "30+ days ago"
covering anything from a month to a year, and employers refresh listings to stay near the top —
which resets the displayed date while the vacancy is unchanged.

---

## After the sequence

| Outcome | Next |
|---|---|
| **Positive reply** | `HANDOFF` — a human owns it |
| **"Not now"** | Cooldown **from the date they named**, not a default +90d |
| **Opt-out** | `SUPPRESSED` at **domain scope**. Sticky — only a human clears it |
| **Exhausted, no reply** | **Re-pooled.** Cooldown +90d, intent reset, **contact retained** |

**Re-pooling is the product.**

> A firm that did not respond is not spent. It returns to the pool with its verified contact
> intact and waits for the next signal. Most firms are not in market today; the point of
> holding a current record is being ready on the day they are.

The quiet lead still bought us a verified partner name, a working phone and a known case
system — the expensive part. The next pain signal costs nothing to act on.
