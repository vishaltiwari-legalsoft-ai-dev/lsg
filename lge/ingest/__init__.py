"""Ingest -- any sheet a person hands us becomes one canonical row shape.

The purchased list was the only input for the first build, and its column
names leaked into every step that read `observation.payload`. Real inputs are
whatever the team has: a vendor export, a conference list, last quarter's
outreach sheet, a partner's referrals -- different headers, different
languages for the same thing, different completeness.

    reader     -- CSV (any encoding, any delimiter) and XLSX -> headers + rows
    vocab      -- the fixed field vocabulary every downstream step reads,
                  and which fields are mandatory
    sniff      -- header synonyms + value shapes -> a column map with
                  confidence, and what mandatory data the sheet lacks
    normalize  -- one raw row + column map -> the canonical row
    batches    -- rows -> numbered batches, processed one at a time
    health     -- a batch's canonical rows -> a data-health report
"""
