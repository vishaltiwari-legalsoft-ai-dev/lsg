---
id: icp.need-model
title: The four need conditions
answers: "Why would a law firm buy remote legal staff at all? What is every filter derived from?"
source: 00 §1
authority: canonical
stability: decided
depends_on: [orientation.project-brief]
feeds: [icp.practice-areas, icp.fee-model, icp.size, icp.tiers, icp.disqualifiers, signals.catalog]
---

# The four need conditions

**This is the root axiom of the whole system.** Start from the buyer, not the product.

A law firm needs outsourced legal staff when four conditions hold **together**. Miss any
one and the firm either does not need it, or needs it but will not buy.

---

### Condition 1 — Delegable volume
The firm generates repetitive, procedural work in quantity: records requests, form
preparation, status calls, document collection.

Bespoke, judgment-heavy work at low volume cannot be handed to anyone, at any price.

→ resolved by [practice area](02-practice-areas.md)

### Condition 2 — Remote-executable
The work needs a phone, a browser and the firm's case system — not a courtroom, a notary
stamp, or a physical file room.

This is a property of the **task**, which is why the wedge is a role, not a practice.

→ resolved by [role selection](05-tiers-and-wedge-skus.md)

### Condition 3 — Cost-centre work
The work is not resold to a client at a markup. Nobody is billed for the hour, so a
cheaper hour is margin rather than lost revenue.

**This is the condition that most targeting misses entirely.**

→ resolved by [fee model](03-fee-model.md)

### Condition 4 — Local hiring blocked
The firm cannot hire the person locally — too slow, too expensive, or no qualified
applicants at all.

Without this, the firm just hires. This condition is also **the most observable from
outside**, which is why the entire signal layer exists to detect it.

→ resolved by [size](04-size-and-need-proxies.md) and [signals](../20-signals/01-signal-catalog.md)

---

## The rule this imposes

> Every filter in the system is derived from one of these four. That is deliberate — a
> targeting rule that cannot be traced back to a reason the firm would buy is a rule that
> will quietly select the wrong firms.

When adding a filter, a score component or a disqualifier, name the condition it serves.
If you cannot, it does not belong. Every entry in
[icp.disqualifiers](06-disqualifiers-and-tracks.md) names the condition it fails, for exactly this
reason.

---

## Why the ordering decides the architecture

**Conditions 1–3 are stable properties of a firm.** They change rarely, so they can be
determined once and stored. This is the **universe** problem, solved by breadth.

**Condition 4 is a transient state.** A firm is blocked on hiring for a few weeks, then it
is not. This is the **in-market** problem, solved by freshness.

Building one system for both is the most common way these projects fail. The plane split
in [pipeline.architecture](../40-pipeline/01-architecture.md) is this distinction made
structural: D and P run once per firm and terminate; W and JA never terminate.
