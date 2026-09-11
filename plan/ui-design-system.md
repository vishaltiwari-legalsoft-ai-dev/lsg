# Design system — "The Record"

The visual identity for the Lead Gen Engine platform. Companion to [ui-plan.md](ui-plan.md).

---

## The idea

The product's core act: **it reads a law firm's own website and finds the sentence that proves
the firm needs help.** A paralegal would do the same with a highlighter and a case file.

So the platform is designed as **the record**, and the highlighter is its one bold gesture:

- **Proof is highlighted.** Every evidence sentence the machine read on a firm's own site is set
  as a quotation with a highlighter mark and a pinpoint citation: where it was read, and when *we*
  first saw it. Nothing else on screen is yellow.
- **The record is typeset like a record.** Quotations use a legal-document serif, the way briefs
  and opinions are printed. The interface around them is a quiet, rounded sans from the Legal
  Soft brand kit.
- **Everything else is disciplined.** Cobalt means *act*, green means *confirmed*, red means
  *problem*, and slate is quiet. Tables rather than card grids. Rules rather than shadows.

---

## First pass, and what the review threw out

The first instinct for "premium B2B dashboard" was: white background, blue primary, Inter, a row
of KPI cards (big number, small label) on the home page, rounded cards everywhere with soft
shadows, and a gradient in the header. That is the default for any similar brief, so each part
was revised:

| First pass | Why it's a default | Revised to |
|---|---|---|
| Inter | The typeface of every generated dashboard | **Rubik** (Legal Soft's brand-kit portal font) for the UI, plus **Libre Caslon Text** for the record |
| KPI cards on Today | "Big number, small label" is the stock hero | Today opens on **the strongest piece of proof**: a real, highlighted sentence from a firm that is hurting right now |
| Cards everywhere, one radius, one shadow | The SaaS card kit | **Docket tables and document panels.** Radius encodes hierarchy (6px controls, 10px panels); no shadows except floating layers |
| Blue used everywhere | Undifferentiated | **Cobalt only for action and "you are here".** The only saturated colour on data is the highlighter, and it marks only proof |
| Brand gradient as decoration | Gradient washes are a tell | The Legal Soft gradient stays **inside the logo only** |
| ALL-CAPS section labels, `A · B · C` meta strings, `→` on buttons | Template chrome | Sentence-case labels, fields shown as separate labelled values, verbs on buttons |

Blue stays the brand anchor because it is the client's brand (the Legal Soft wordmark is cobalt),
not because it is safe. The distinctiveness lives in the highlighter and the typeset record.

---

## Tokens

### Colour

| Token | Hex | Role |
|---|---|---|
| `paper` | `#F5F7FA` | App ground: cool, not cream |
| `sheet` | `#FFFFFF` | Document surfaces: tables, panels, the case file |
| `ink` | `#0E1A33` | Text. A navy ink from the Legal Soft blue family |
| `slate` | `#5B6679` | Secondary text, citations, quiet states |
| `rule` | `#DCE2EB` | Borders and dividers |
| `cobalt` | `#1F4FC4` | **Act.** Primary buttons, links, focus, active nav. From the LS wordmark |
| `cobalt-wash` | `#E8EEFB` | Selected row, active nav background |
| `highlighter` | `#FFE066` | **Proof.** The evidence mark, and nothing else |
| `ledger` | `#1C7A4B` | **Confirmed.** Verified email, passed gate, ok alert |
| `redline` | `#C2332B` | **Problem.** Conflicts, rejects, firing alerts, suppression, opt-out |

Contrast: ink on sheet 16.4:1; slate on sheet 5.9:1; white on cobalt 6.8:1; ink on highlighter
14.9:1. All pass AA; the text pairs pass AAA.

**Semantic states never rely on colour alone.** Every status badge carries its word ("Verified",
"Unverified — vendor says verified", "Catch-all — failure", "No data").

- **No data** is a dashed slate outline, distinct from ok (ledger) and firing (redline). The
  spec's point: absence of data is information.
- **Unknown** values are written as *unknown — not guessed*, in slate italic. Never a blank, a
  dash or a zero.

### Type

| Face | Use |
|---|---|
| **Rubik** 400 / 500 | All interface text. From the Legal Soft brand kit's portal-dashboard guide |
| **Libre Caslon Text** 400 / 400 italic | The record only: evidence quotations and quoted email copy |

Scale (minor third, 1.2), in px: **12** citations and meta · **13** table body · **14** body ·
**16** section titles · **20** page titles · **28** the Today proof. Line height 1.45 for body,
1.25 for titles, 1.6 for Caslon quotations. Caslon runs 1px larger than the sans at every step,
so the two faces read at the same size. Quotations cap at 68 characters per line. Numeric table
columns are right-aligned with `tabular-nums`.

Magistral, the brand kit's heading face, is not used: it is a commercial font whose web
embedding licence is unknown. Rubik 500 carries headings instead — one family, per the brand
kit's own pairing.

### Shape and space

- 4px base grid. Table rows 40px (comfortable) or 32px (compact toggle).
- Radius: **6px** for controls, badges and inputs; **10px** for panels; nothing fully rounded
  except avatars. Radius encodes hierarchy.
- Elevation: none on the page. A single shadow for floating layers only (popovers, the command
  palette, toasts).
- Content is left-aligned throughout. Numbers are right-aligned.

---

## Layout

```
┌──────────┬──────────────────────────────────────────────────────────────────┐
│ LEGAL    │ Leads                                        [⌘K Search firms]   │
│ SOFT     ├───────────────────────────────────┬──────────────────────────────┤
│          │ Strike 12  Sequence 184  Nurture  │ Atlanta Personal Injury      │
│ Today    │ ──────────────────────────────────│ Law Group                    │
│ Leads    │ Atlanta Personal Injury…    1A    │ Tier 1A, personal injury,    │
│ Firms    │ ▓Paralegal role open 26 days▓     │ Atlanta                      │
│ Review 7 │ Jordan Gore, owner                │                              │
│ Journey  │───────────────────────────────────│ The proof                    │
│ Pipeline │ Aleem Law Firm              1A    │ ▓“The attorneys at Atlanta   │
│          │ ▓Case manager role, reposted▓     │ Personal Injury Law Group    │
│          │ …                                 │ work on a contingency fee”▓  │
│ Settings │                                   │ Careers page, first seen 14… │
└──────────┴───────────────────────────────────┴──────────────────────────────┘
```

- **App shell:** a fixed left rail with the Legal Soft wordmark, the nav, and review counts. Each
  page gets a title bar with the ⌘K command palette.
- **Leads is master–detail:** the docket on the left, the case file for the selected lead on the
  right. `j`/`k` move, `Enter` opens full screen, and number keys record outcomes. Triage never
  leaves the page.
- **The case file** stacks: the proof → people → drafts (touches 1–9, a real sequence, so they
  are numbered) → the record (lifecycle timeline, also a sequence) → score, labelled seeded.
- **Firm pages** read as a record: a definition list of attribute, value and citation. Expanding a
  row shows the competing claims, like a record showing the losing arguments.
- **Review queues** are a side-by-side comparison with the decision keys visible at all times.

### Today

Not a dashboard of numbers. It opens on **the single strongest piece of proof in the system**:
the highlighted sentence, the firm, how long ago we first saw it, who to write to, and the first
draft ready to copy. Below it sit the other STRIKE leads, then "needs attention": firing alerts,
no-data alerts, review counts and bench status.

---

## Motion — one moment

When proof appears (opening a lead, or loading Today), **the highlighter draws across the
sentence** once, in about 450ms, left to right. That is the only motion nobody asked for. Every
other movement answers a person's action: a drawer opening, a row confirming an outcome, a toast.
`prefers-reduced-motion` shows the highlight statically.

---

## Principles

1. **Proof is the hero.** The highlighter marks only what the machine read on a firm's own site.
2. **Typeset the record like a record.** Every quotation carries its citation: where, and when we
   first saw it.
3. **Write the unknowns.** "Unknown — not guessed" and "No data" are states, not blanks.
4. **Colour is semantic.** Cobalt acts, green confirms, red warns, slate is quiet.
5. **Fast is premium.** Keyboard first, instant filters, optimistic outcome buttons, skeletons
   instead of spinners.
6. **Density with calm.** Tables over cards, rules over shadows, radius as hierarchy.

---

## Copy

- Sentence case everywhere. Plain verbs on buttons, and the same name through the flow:
  **Mark as replied** gives the toast **Marked as replied**.
- Name things by what people do, not how the system works: *Customer list*, not *suppression
  scope=domain*. The technical term appears once, in the details, for the people who need it.
- Empty states direct: "No STRIKE leads today. The next careers sweep runs at 02:00."
- Errors say what happened and how to fix it, and never apologise: "Couldn't reach the engine.
  Start it with scripts/pg.sh start, then reload."
- Seeded numbers say so: *Scores use seeded weights until outcomes are recorded.*

---

## Components

`AppShell` (rail, title bar, ⌘K palette) · `DocketTable` · `CaseFile` · `ProofQuote` (highlight,
Caslon quotation, citation) · `SourceCite` · `TierMark` · `BandTabs` · `StatusBadge` (verified,
unverified, failure, no data) · `ScoreBreakdown` · `DraftSequence` (touches 1–9) ·
`RecordTimeline` · `AttributeRow` (value, source, competing claims) · `CompareSplit` · `Kbd` ·
`EmptyState` · `Toast`.

Built on shadcn/ui (Radix) primitives, restyled to these tokens: the default shadcn look is
itself a template tell.
