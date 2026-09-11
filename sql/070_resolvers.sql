-- 070_resolvers.sql -- Plane R (resolvers) schema additions. Owned by
-- lge/planes/r/*.py (context/40-pipeline/02-component-register.md, Plane R).
--
-- contact gains phone_e164 / phone_line_type / dnc_status (R5 — phone
-- normalizer + DNC scrub adapter interface, inert until a DNC provider is
-- under contract; see lge/planes/r/r5_phone.py).
--
-- verify_attempt is R4's per-(email, provider) audit/cost log. It is also
-- the idempotency primitive R4 checks before spending money on an address a
-- second time -- "never pay twice for the same address" is a query against
-- this table, not a task_run row, because the unit of idempotency is the
-- email+provider pair, not a firm.

ALTER TABLE contact
  ADD COLUMN phone_e164     text,
  ADD COLUMN phone_line_type text,
  ADD COLUMN dnc_status     text NOT NULL DEFAULT 'unknown';

ALTER TABLE contact
  ADD CONSTRAINT contact_dnc_status_check
    CHECK (dnc_status IN ('unknown', 'clear', 'listed'));

CREATE TABLE verify_attempt (
  id         bigserial PRIMARY KEY,
  email      text NOT NULL,
  provider   text NOT NULL,
  result     text NOT NULL,
  raw        jsonb,
  cost_usd   numeric,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- R4's idempotency lookup: "has this email already been paid for at this
-- provider?" -- always filtered on both columns together.
CREATE INDEX verify_attempt_email_provider_idx ON verify_attempt (email, provider);

GRANT SELECT, INSERT, UPDATE, DELETE ON verify_attempt TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
