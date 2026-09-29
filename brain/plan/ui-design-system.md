# Design system — "Blue-back"

The visual identity for the Lead Gen Engine platform, redesigned 18 Sep 2026 (D-055). Companion to [ui-plan.md](ui-plan.md). Supersedes "The Record" (11 Sep); its best idea, proof as the hero, is kept.

---

## The idea

Court papers are bound in a **blue back**: a stiff blue cover sheet with the document on white paper inside it. This platform is a binder of them.

- **The desk is the blue back.** The app ground and the rail are a pale legal blue. Every screen is **one white sheet** laid on it, with rounded corners and no shadow.
- **The rail is the binder's index**, and its tabs are the **three steps of the brief** (plan-v3): *1 Raw leads*, *2 Enrichment*, *3 Handover*, with the screens where each step is worked beneath it. The screen you are on is a **white tab joined to the sheet**, with concave corners where it meets the sheet's edge. "You are here" is said by shape, not only by colour.
- **Proof is the one loud colour.** The sentence the engine read on a firm's own site is set in a legal-document serif under a yellow highlighter, with its citation. Nothing else on screen is yellow.
- **A firm's name is a caption.** On its own page a firm's name is set large in Caslon Display, the way a case caption heads a filing. Everywhere else the interface is a crisp grotesque.

---

## What the review threw out

The redesign started from the screens as they were (screenshots of all nine, with sample data) and from a UX audit. What was generic, and what replaced it:

| Before | Why it had to go | After |
|---|---|---|
| Cool grey ground, white cards, cobalt: the stock admin palette | Nothing about it said *law* or *Legal Soft* | The blue-back desk and one white sheet per screen |
| Two navigation models: six screens, plus a separate "pipeline" list of five steps with numbers | People had to learn both | One rail: Home, then the three steps of the brief with their screens and live counts |
| Rubik, rounded | Friendly, but soft for a legal tool; unlike the heavy, condensed Legal Soft wordmark | **Archivo**, whose narrow cut (`type-narrow`) carries the wordmark's voice into titles and live figures |
| A 4,477px home page mixing a manual, a dashboard, an FAQ and a glossary | The state of the work was buried | Home opens on the strongest proof in the system (or, before there is any, the self-building demo), then the three steps with live numbers, then what is waiting; the manual follows under a heavy rule |
| A 3,953px lead page in one 580px column, all nine emails open | Triage meant scrolling past the drafts | Two columns: the reading (proof, people, drafts with touch 1 open) and a pinned working side (next step, decisions, outcome, notes, history, numbers) |
| Eight filter controls, three native dropdowns, an export disguised as a select | Chrome before content | Search, priority, tier, pain, and "More filters" for the rest; a real "Export a list" menu |
| Bordered cards for tables and quotes | The SaaS card kit | Ruled tables across the sheet; quotes unboxed; a bordered frame only for a specimen (the demo case file) or the item under review (the accuracy check) |
| Dot-joined meta strings (`A · B · C`), "WORD — fragment" labels, the stage repeated on every queue row | Template chrome and noise | Counts in words ("11 leads here", "0 ready, 14 one step away, of 17 worked"); the stage is the tab, so a row shows only its next step |

---

## Tokens

### Colour

| Token | Hex | Role |
|---|---|---|
| `desk` | `#DDE5F2` | The blue back: app ground and rail |
| `desk-deep` | `#C7D3E7` | Rules on the desk, the phone top bar's edge |
| `sheet` | `#FFFFFF` | The document every screen is set on |
| `paper` | `#F4F7FC` | A faint tint on the sheet: hover, table heads, the working side of a page |
| `ink` | `#0D1B3A` | Text: the navy of the Legal Soft wordmark, darkened |
| `slate` | `#56637B` | Secondary text, citations, quiet states |
| `rule` | `#E0E6EF` | Rules on the sheet |
| `cobalt` | `#1D4AB5` | **Act.** Primary buttons, links, focus, the step numerals, an active filter |
| `highlighter` | `#FFE14D` | **Proof.** The evidence mark and nothing else |
| `ledger` | `#15744A` | **Confirmed.** Verified address, passed check |
| `redline` | `#C0342C` | **Problem.** An address that failed, do-not-contact, a failed step or check, a firing alert |

Contrast (WCAG): ink on sheet 17:1; slate on sheet 6.1:1 and on the desk 4.8:1; white on cobalt 7.8:1; ink on highlighter 13:1. Every text pair passes AA. A state never relies on colour alone: every badge carries its word.

### Type

| Face | Use |
|---|---|
| **Archivo** (variable, width 62–125) | The interface. `type-narrow` (width 78) for page titles, the step numerals and every live figure; `type-semi-narrow` (88) where a little of it is wanted |
| **Libre Caslon Display** | A firm's name as the caption of its record (lead page, firm page, the case file beside the queue, the accuracy check, the proof hero) |
| **Libre Caslon Text** 400 / 700 / italic | The record: proof sentences and email copy |

Scale, in px: **12** meta, **13** table, **14** body, **17** section, **22** subtitle, **28** page title, **32** headline, **36** figure, **46** display. Caslon runs a step larger than the sans (quote 15.5, quote title 21, the proof hero 31, captions 27 and 38). Body line height 1.5; quotations 1.55–1.6 and at most 66 characters wide.

### Shape

- Radius encodes hierarchy: **7px** controls and badges, **12px** panels and popovers, **18px** the sheet. Pills only for counts.
- One shadow, for floating layers (menus, the palette, toasts, dialogs). The sheet has none: white on the blue back is its own edge.
- Controls are 36px tall (32px small, 44px large).

---

## Layout

```
 blue-back desk
┌───────────────┬──────────────────────────────────────────────────────┐
│ LEGAL SOFT    │ Work queue   11 leads here      [Export a list] [⌕]  │
│ Lead Gen      ├──────────────────────────────────────────────────────┤
│  Home         │ Needs a decision (11)  Needs a person 2  …  [Closed] │
│ 1 Raw leads   │ [Firm or domain] [Priority] [Tier] [Pain] [More]     │
│    Sheets     │──────────────────────────────────────────────────────│
│ 2 Enrichment  │ Firm           Why now              Decision-  Next  │
│╭─────────────╮│ Harbor Street  ▓We are seeking an▓  maker      step  │
││ Work queue 13  Savannah, GA   ▓experienced…▓       Verified   58    │
│╰─────────────╯│                                                      │
│    Firms      │                                                      │
│    Accuracy 44│                                                      │
│ 3 Handover    │                                                      │
│    Actual leads                                                      │
│ ● Engine      └──────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────────────────────┘
```

- **The frame.** The rail is fixed; the sheet sits beside it, inset 10px from the window, and scrolls with the page (`overflow: clip` keeps its corners round without breaking sticky parts). Below 768px the desk goes: the rail becomes a sticky top bar that scrolls sideways and the sheet is the screen.
- **The head of each sheet** (`TitleBar`): the screen's name set narrow and heavy, what it is showing in words, its actions, and search (Ctrl K). A firm's page sets the firm's name as a Caslon caption instead.
- **Working sides** are tinted `paper`: the lead page's right column (next step, decisions, outcome, notes, history, numbers) and the Sheets upload column. The reading stays on white.
- **Tables** run the width of the sheet between rules; headers are 12px medium slate; figures right-aligned in the narrow cut.

### The screens

| Step | Screen | What it is |
|---|---|---|
| | **Home** | (D-059: and then what is built, what is half built and what waits on a key, from the engine's own `config/capabilities.yml`) The strongest proof right now, with who to write to and the first email; the three steps with live numbers and the screens of each; what is waiting and what the engine is doing; then the manual: how to use it (stepper and demo), questions, the words on the screens |
| 1 | **Sheets** | Upload by drop or choice; the sheets; the chosen sheet's reading, health and loading batches. Empty, it explains the three things that happen to a sheet |
| 2 | **Work queue** | Every lead by stage (tabs), filtered; the case file opens beside the list |
| 2 | **Firms** / a firm | Every firm; a firm's record: the tier sentence, at a glance, why now, people, what the site says, every claim, pages read |
| 2 | **Accuracy check** | The engine's reading of 50 firms, checked by hand before the list widens |
| 3 | **Actual leads** | Every worked lead with its seven checks; "Ready to hand over" and "One step away"; a setup notice when address checking is off; what the list rules held back; "Download for the vendor" |
| 3 | **Email journey** | What a lead is sent, day by day (D-057): the day line (each email a square on its day, numbered, dashed when this firm would not get it), then every email in the record serif, written by the engine for an example firm (tier, pain, case system, Sequence or Nurture, all in the URL) or for one lead (`?lead=`). Each email says which version it is and opens "Change the wording"; the other versions sit under it. The working side: the schedule with "Change the days", who gets which emails, when the firm answers, the rules every email keeps |
| | a lead | The case file on its own page, in two columns |

Future screens of the brief (batches of a sheet, handovers to vendors) join their step's group in the rail when they are built; nothing links to an unbuilt screen.

---

## Motion — one moment

When proof appears, the highlighter draws across the sentence once, in about half a second, left to right. The home page's demo case file plays once on load. Nothing else moves unless a person asked it to; `prefers-reduced-motion` shows both finished.

---

## Principles

1. **The three steps are the spine.** The rail, the home page and the words follow the user's own drawing: raw leads, enrichment, handover.
2. **Proof is the hero, and the only loud colour.**
3. **One sheet per screen.** Sections, rules and a faint tint, never a grid of cards.
4. **A firm's name is a caption; data is set in the grotesque.**
5. **Write the unknowns.** "Unknown, not guessed" and "No data" are states, not blanks.
6. **Say counts in words.** No dot-joined strings; a row never repeats what its tab says.
7. **Fast is premium.** Keyboard first (J, K, Enter, 1–7, Ctrl K), filters in the URL, skeletons instead of spinners.

---

## Copy

Sentence case everywhere; plain verbs on buttons, one name through the flow (**Copy first email** gives **Copied first email**). Name things by what people do: *Sheets*, *Actual leads*, *Before the list widens*, never *Gate G2* or *universe*. Empty states direct ("Start with a sheet of law firms"), errors say how to fix it and never apologise, and the engine's start command is the one that works on this machine (`.venv\Scripts\python.exe -m lge serve`).

---

## Components

`Rail` (binder tabs, three steps, live counts) · `TitleBar` (with `caption`) · `DocketTable` · `CaseFile` (panel or two-column page) · `ProofQuote` / `Quotation` / `SourceCite` · `TierMark` · `StageTabs` · `FilterBar` (with More filters) · `StatusBadge` / `EmailStatusBadge` (one address badge everywhere) · `SetupNotice` (a switched-off provider and what it stops) · `ScoreBreakdown` · `DraftSequence` (links to the lead's journey) · the journey's day line, `TemplateEditor` (fill-ins insert at the cursor; the engine's own checks as you type) and `ScheduleSection` · `RecordSection` · `AttributeTable` · `Kbd` · `EmptyState` · `ErrorState` · `Select` (items may carry a hint) · `Popover` · toasts.

**Days are counted from Day 1.** The engine counts days after the first email; every screen shows `Day {day + 1}`, so the first email goes on Day 1, never "Day 0". The sequence's pieces are *emails*, not *touches*.

**Words that must not collide:** the work queue's stage is *Ready to reach* (a person with an address); the Actual leads tab is *Ready to hand over* (all seven checks). The blue button on a lead is the lead's own next step, never a fixed action. A count appears only next to something a person can act on.

Built on shadcn/ui (Radix) primitives, restyled to these tokens: the default shadcn look is itself a template tell.
