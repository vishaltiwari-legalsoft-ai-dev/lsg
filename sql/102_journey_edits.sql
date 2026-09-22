-- 102: the email journey as edited on the Email journey screen (D-057).
-- journey/copy/*.md and journey/sequences.yml stay the originals, pinned by
-- tests. A row here replaces one template's wording, or one email's day, for
-- every lead; deleting the row restores the original. Every renderer (a
-- lead's drafts, the work queue's list check, the vendor sheet, build_list's
-- drafts) reads them through lge.export.list.fetch_journey_edits.

CREATE TABLE journey_copy_edit (
    template  text PRIMARY KEY,                  -- path under journey/copy/, e.g. 'touch1/1a.md'
    subject   text,                              -- NULL for a paragraph, which has no subject line
    body      text NOT NULL CHECK (body <> ''),
    edited_at timestamptz NOT NULL DEFAULT now(),
    edited_by text NOT NULL DEFAULT 'ui'
);

CREATE TABLE journey_day_edit (
    step      smallint PRIMARY KEY CHECK (step BETWEEN 2 AND 9),  -- email 1 always goes first
    day       smallint NOT NULL CHECK (day BETWEEN 1 AND 90),     -- days after email 1
    edited_at timestamptz NOT NULL DEFAULT now(),
    edited_by text NOT NULL DEFAULT 'ui'
);
