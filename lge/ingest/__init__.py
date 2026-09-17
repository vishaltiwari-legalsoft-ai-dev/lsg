"""Ingest -- any sheet a person hands us becomes one canonical row shape.

The purchased list was the only input for the first build, and its column
names leaked into every step that read `observation.payload`. Real inputs are
whatever the team has: a vendor export, a conference list, last quarter's
outreach sheet, a partner's referrals -- different headers, different
languages for the same thing, different completeness.

    reader     -- CSV (any encoding, any delimiter) and XLSX -> headers + rows,
                  streamed: the loader never holds the whole sheet
    vocab      -- the fixed field vocabulary every downstream step reads; the
                  two mandatory things (a firm name, a way to reach the firm)
                  and where research fills everything else
    columns    -- the ColumnReader seam: the AI reads the sheet (checked
                  against the values) or the rules do; one ColumnMap either way
    sniff      -- the rule reader: header synonyms + value shapes
    normalize  -- one raw row + column map -> the canonical row
    batches    -- rows -> numbered batches, processed one at a time
    health     -- a batch's canonical rows -> a data-health report
"""
