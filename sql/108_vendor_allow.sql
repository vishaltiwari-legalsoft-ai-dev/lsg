-- 108: two kinds of person at the door (D-068). Legal Soft staff sign in
-- with a legalsoft.com account and walk in; a person from an email vendor's
-- team signs in with any Google account, but only when that address, or
-- its whole domain, is on the vendor allow list the admin keeps.

ALTER TABLE app_user
  ADD COLUMN kind text NOT NULL DEFAULT 'staff' CHECK (kind IN ('staff', 'vendor')),
  ADD COLUMN vendor_name text;

CREATE TABLE vendor_allow (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- a whole address ("dana@sendco.com") or a whole domain ("@sendco.com"), lower-case
  pattern     text NOT NULL UNIQUE,
  vendor_name text NOT NULL,
  note        text,
  added_by    text NOT NULL,
  added_at    timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON vendor_allow TO lge_app;
