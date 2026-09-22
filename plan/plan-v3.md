# Plan v3 — the three-step engine: triage, enrich by batch, hand over

**Proposed and agreed on 18 Sep 2026 (D-053); two decisions are still open. Nothing here is built until its phase starts.** It follows the user's handwritten brief of the same day, cross-checked against the code. It does not replace `plan-v2.md`: the seams, the search engine, the address finding and the verification built there are what this plan wires together. It changes three things v2 left alone — how rows are sorted on the way in, in what order firms are enriched, and what happens to a lead once it is finished.

## The brief, in one paragraph

A sheet must carry five things: firm name, website, location, job post, firm size. Anything more is an add-on. A row with all five goes to **Batch 1**. A row with no firm name is **discarded**. A row with a firm name but any of the other four missing goes to **Batch 2**. Batches are cut into sub-batches of 250. The enrichment engine always works Batch 1 before Batch 2; a Batch 2 firm is first identified by a search (name → website) and then enriched like any other. Enrichment finds the people, their email, phone and LinkedIn profile, the reviews, the Google Business Profile, and reads at most five pages of the site; a missing email is predicted from the name and the domain and verified by NeverBounce; an AI — not a scraper — writes the pain-point analysis and the enrichment report. Finished leads land in **Actual Leads**; the outreach engine drafts each one's email journey and keeps its lifecycle; a handover cycle writes a **Handover Lead Base** document for a vendor and marks those leads as handed over.

## Cross-check — what exists, what does not

### Step 1 · Raw lead data

| The brief asks for | Today | Verdict |
|---|---|---|
| The five fields are recognised on any sheet | All five are in the sheet vocabulary; the AI reads the header and a sample, the rules check it, a person can correct a column | **Have** |
| Extra columns are welcome | Kept with the row as extra data | **Have** |
| Check that the sheet carries the five | The check is two things only: a firm name, and a way to reach the firm (D-043) | **Differs** |
| All five present → Batch 1 | Nothing judges a row. "Batches" today are row ranges of 500 for loading, nothing more | **Missing** |
| No firm name → discard | The row is loaded and becomes a firm called "Unknown Firm" with an open lead | **Wrong today** |
| Name but gaps → Batch 2 | No such grouping | **Missing** |
| The user sees what was discarded | The screen counts rows without a name; it does not say what became of them | **Missing** |
| The sheet's job post and size matter | Both are stored and then read by nothing: the job post never becomes a hiring signal, the size never counts as a size | **Dead data** |

### Step 2 · Batching and the enrichment engine

| The brief asks for | Today | Verdict |
|---|---|---|
| Sub-batches of 250 | None. The import screen offers 250 as a loading size; it is not an enrichment batch | **Missing** |
| Batch 1 always before Batch 2 | No queue, no priority. Bulk runs take firms in id order; the screen starts one thread per lead, up to 100 at once, with no limit on how many run together | **Missing** |
| Enrichment starts on its own | Loading stops after duplicates are merged. A person must select leads and press Research, 100 at a time | **Missing** |
| Batch 2: search, identify the firm | The website finder exists and is careful (searches name + city, opens the candidate's home page, adopts it only when the page names the firm). It can only be run from the command line: no flow, no screen, no job runs it. It never fills a missing location, and it checks the name only, not the place | **Built, unwired** |
| Find contacts | People are read off the site and the AI's reading, with roles (owner, administrator, attorney) | **Have** |
| Find the email | Off the site, from search results, from the firm's address pattern | **Have** |
| Email predictor: first + last @ domain, patterns, learn from scraped addresses, NeverBounce verifies | Built exactly so: eleven patterns, most common first, the firm's pattern learned from addresses already found. **Switched off: there is no verification key**, so it skips every person. Only the first six patterns are tried unless told otherwise | **Built, inert** |
| Find the phone | The firm's main line only. No step finds a person's direct number, and the step that puts a phone on a contact is in no flow | **Partial** |
| Find the LinkedIn profile | Per firm and per person, from search results; LinkedIn is never opened | **Have** |
| Find reviews | Google rating, review count and up to eight result snippets; the site's testimonials are stored and never analysed; no review text from anywhere | **Partial** |
| Google Business Profile analysis | With a Serper key the listing is read — and only its link, rating and count are kept; phone, address, website and category are thrown away. No analysis of any kind. Without the key it falls back to guessing from snippets. The screen's "Places" light reads a setting that does not exist | **Partial** |
| At most 5 pages: landing, careers, about, testimonials, staff | Twelve pages over seven kinds (adds contact; three attorney pages, two team, two careers, two testimonials) | **Differs** |
| Pain Point Analyzer is an AI | Pain is three fixed rules and a word pattern. The AI is asked ten facts about the firm from its pages and never sees reviews, profiles, openings or gaps | **Missing** |
| Enrichment report | No per-lead report exists in any form | **Missing** |

One fault found on the way: the Research button runs a shorter list of steps than the full flow — the two lists are kept in two places and have drifted. It leaves out the AI's reading of the site (one of the three sources of decision-makers), the check of any address found on the site or in search (only a predicted address gets verified, because the predictor checks its own guesses), and the step that moves a lead through its states. A lead researched from the screen therefore stays at "Researching" in the work queue for good, however much was found — while the Qualified panel, which does not look at the state, may call the same lead ready.

### Step 3 · Handoff and outreach

| The brief asks for | Today | Verdict |
|---|---|---|
| Actual Leads: where finished leads land | The Qualified leads panel works it out afresh on every visit (seven checks). Nothing is stored. A second, different definition of "ready" lives in the list builder | **Partial** |
| The outreach engine drafts the journey | Nine touches from written templates, rendered on the fly, shown on the lead. Not stored; no AI; nothing sends (sending is out of scope by standing decision) | **Partial** |
| …and manages the lifecycle | Nineteen states with a whitelist and a full event log; outcome buttons (sent, replied, meeting, won, lost, not now, opt out). The touch table exists and nothing writes to it; most leads cannot legally reach "in outreach" | **Partial** |
| Handover cycle, Handover Lead Base document | Nothing. No vendor, no handover record, no note of who received which lead when. The export is a plain download that leaves no trace | **Missing** |
| Handed-over leads show it | "Handed off" means "with sales", with no vendor behind it | **Missing** |

One fault found on the way: the ready-leads sheet skips the hygiene rules the other export applies. A paying customer's firm, or a firm in its cooling-off period, can appear on the sheet meant for the vendor.

## What stands in the way before any building

Only the OpenRouter key is in place. Two parts of the brief cannot run without a key each:

- **NeverBounce** (or ZeroBounce) — the email predictor and every "verified" check. Without it no lead can ever be ready.
- **Serper** — the Batch 2 search and the Google Business Profile. Without it the search is DuckDuckGo, which stops us after a few hundred queries, and the standing rule is to back off and stop, never to work around it.

## The work, in order

Basics first. Each phase ends with something visible on the screen and a number measured on the user's first real sheet (the store is empty; the old probe is gone).

### Phase 0 — mend what is already there

One list of enrichment steps, asked by the flow, the batch runner and the Research button alike, so they cannot drift again. The ready-leads sheet applies the same hygiene as every other export. The Places light reads the real setting. Small, and everything after depends on it.

**Status — done 18 Sep 2026 (D-054).** The recipe is written once in the flow file and the button reads it: the AI reading, the address check and the step that moves a lead forward are back in every Research click. On the way, the second AI reading had to learn that a firm list narrows its trigger rather than replacing it — otherwise every click would have gone to the expensive model. The vendor sheet and the Qualified panel now apply the same list rules as every other list, and say how many leads the rules held back. A lead whose decision-maker had no address at all was vanishing from the panel instead of showing as one step away; fixed. The lights now say what the engine will actually do. Phase 2's batch runner will ask the same flow file.

### Phase 1 — triage on the way in

- Every row is judged as it is normalised: **complete** (all five usable), **partial** (a name, something missing), **discard** (no name). "Usable" means a value that works: a website that yields no domain counts as missing.
- A discarded row never enters the store. It is written to a rejects list with its row number and the reason, so the screen can show it and the user can download it. Nothing disappears silently.
- A firm that appears on several rows is judged on all of them together, after duplicates merge.
- The import screen shows three numbers before loading — Batch 1, Batch 2, discarded — and warns when a whole column is absent. A sheet missing one of the five columns still loads, every row in Batch 2; a sheet with no firm-name column at all is refused, because every row would be discarded. The "a way to reach the firm" requirement of D-043 stops blocking the load: a row with a name and nothing else is Batch 2, and the identify step searches for it.
- The sheet's job post becomes evidence of an opening on the firm; the sheet's size becomes the lowest-ranked source of firm size. Today both are dead, which would make "complete" mean nothing downstream.

**Measured:** rows in each class against a hand count on the first sheet; zero "Unknown Firm" records.

### Phase 2 — the enrichment queue

- After loading, firms are cut into sub-batches of 250 (firms, not rows — rows collapse when duplicates merge), each marked Batch 1 or Batch 2.
- One runner takes the next sub-batch: any waiting Batch 1 sub-batch, from any sheet, before any Batch 2. The rule is applied between sub-batches, so a new Batch 1 waits at most one sub-batch. It runs the components over the whole sub-batch at once, which is how they were built to run, instead of a thread per lead.
- It starts by itself when a sheet finishes loading. The screen shows each sub-batch — waiting, running, step by step, done, failed — with pause, resume and retry.
- Batch 2's recipe opens with **identify**: the website finder, now wired in, then location, size and openings filled from the site and the business listing. It also checks the place, not only the name, when the sheet gave one. A firm with a name and no place is adopted only when the answer is unambiguous — one candidate whose page names the firm and no second one that does — because "Smith & Associates" alone names hundreds of firms (the same reason a name-only match is never merged). A firm that cannot be identified is parked as "could not identify" with the reason shown — never enriched blind, never dropped quietly.
- A bot check pauses Batch 2 with a visible reason. It is never worked around.

**Measured:** a sheet goes from upload to enriched with no clicks; a Batch 1 sheet uploaded mid-run is taken next; share of Batch 2 firms identified.

### Phase 3 — enrichment to the letter of the brief

- **Five pages**, one config change, re-derived from pages already stored: landing, about, careers, testimonials, one staff page. What is lost by dropping the contact page is measured, and the business listing's phone and address cover most of it.
- **Google Business Profile kept whole**: phone, address, website, category as well as rating and count — then read for what it says (few reviews, a low rating, a listing that disagrees with the site).
- **Reviews**: review text through the search provider's licensed endpoint where it has one (to be confirmed when built), alongside the site's testimonials. No review site is scraped.
- **Phone** wired in: the listing's and the site's main line on the firm; a person's direct line only where the site prints it.
- **Email predictor live** once the key is in; all eleven patterns available.

**Measured:** per sheet, share of firms with a named person, an address, a verified address, a phone, a profile, a business listing.

### Phase 4 — the Pain Point Analyzer and the enrichment report

- A new step that is not a scraper: it reads everything the store holds on a firm — site facts and gaps, openings, size, reviews and testimonials, the business listing, the tools detected, profile headcount — and the AI writes the pains, each with the sentence that proves it and where that sentence came from. A pain with no evidence in the store is thrown out; the grounding check that guards the AI's other answers is reused.
- The fixed rules stay as cheap inputs to it, not as the analysis.
- The result is stored, keyed to what it read, so a re-run costs nothing and a change of prompt re-derives without re-crawling.
- The **enrichment report** is the lead's page and a download: the firm, the people and how to reach them, reviews and listing, what the site shows, the pain analysis.
- Prompt and model go through the AI-engineering review before they are changed, as the project's rules require.

**Measured:** on fifty leads checked by hand — share of pains whose evidence is real and relevant.

**Started 22 Sep 2026 (D-058): the Pain Point Analyzer is built and running.** `ja8_pain` reads the whole record for a firm and names what hurts, each pain quoting one line of that record; what cannot be quoted is thrown away and the throw-away is recorded. It sits in the research flow, costs about a cent a firm, and shows as "What hurts" on the lead and the firm. Still to come in this phase: the enrichment report (the lead's page as a document and a download), and the fixed rules folded in as inputs rather than a parallel path.

### Phase 5 — Actual Leads, the journey on record, the handover

- **Actual Leads** becomes a stored pool with one definition of ready, shared by the panel and every export, hygiene always applied. Every lead that finishes enrichment lands there with its checklist; only the ready ones can be handed over.
- The journey is **saved** when a lead lands, so what a vendor was given is on record; the pain analysis feeds the first touch. Sending stays outside the engine.
- **Handover**: choose a vendor, choose ready leads, and the engine writes the Handover Lead Base document — lead, person, contact details, pain, the drafted touches — and records the handover: which vendor, which leads, when, by whom. In Actual Leads each of those leads reads "Handed to ‹vendor› on ‹date›" and cannot be handed to a second vendor by accident. What the vendor reports back is recorded through the existing outcomes.
- The document carries personal data: generated on request, downloaded from the local machine, every creation logged.

**Measured:** a handover of fifty leads produces the document, marks all fifty, and a second attempt on the same leads is refused.

**Started 19 Sep 2026, ahead of phases 1–4 while the keys are awaited (D-057): the Email journey screen.** The journey a vendor will be handed can be read day by day, for an example firm or for any lead, and its wording and its days changed for every lead, with the engine's rules enforced and the originals always one click away. Still to come in this phase: the stored Actual Leads pool, the journey saved per lead when it lands (which also fixes a Day-26 email that counts the days a post has been open as of the day it was drafted), vendors, and the handover document.

## Decisions

Settled by the user on 18 Sep 2026 (D-053), each the recommended option:

1. **A sheet missing one of the five columns altogether** loads, with a warning on screen, and every row goes to Batch 2. Not refused; not judged on the columns it happens to have.
2. **Sub-batches are 250 for both batches**, not 1000 for Batch 2.
3. **Five pages.** The contact page is dropped; phone and address come from the business listing; the loss in addresses found is measured on the first sheet, and contact goes back (one config line) if it hurts.
4. **Everything that finishes enrichment lands in Actual Leads**, with its checklist; only a lead passing every check can be handed over.

Still open:

5. **The sheet's firm size as a source of size** — reverses part of D-016 and D-044, which kept a purchased list's employee range out on purpose. Recommended: yes, as the lowest-ranked source, outranked by anything the site or the AI says. Needed before phase 1 finishes.
6. **The two keys** — NeverBounce (or ZeroBounce) and Serper, in `.env`. Phases 0 and 1 do not need them; phase 2's Batch 2 and phase 3 do.
