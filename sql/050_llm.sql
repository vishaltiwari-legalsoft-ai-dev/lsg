-- 050_llm.sql — P8 (LLM extractor) / P9 (LLM escalator) call log.
--
-- One row per OpenRouter request, win or lose — this is the observability
-- floor for context/40-pipeline/03-extraction-contract.md: "every extraction
-- emits component · model · prompt rev · input tokens · per-field
-- confidence", and the median fee_model.confidence week-over-week alert
-- reads this table. firm_id is nullable so a call that fails before the
-- firm is even resolvable (should not happen in practice, but the schema
-- should not make the observability row depend on the thing it is meant to
-- diagnose) never blocks the log write.
--
-- status:
--   ok         -- validated, grounded, claims written
--   ungrounded -- validated, but a tier-determining field's evidence did not
--                 occur in the source text and was nulled; claims for the
--                 (now-unknown) fields are still written -- unknown is a
--                 first-class answer, never a silent guess
--   invalid    -- structured-output response failed pydantic validation
--                 twice (one retry); no claims written -- never a partial
--                 write
--   failed     -- transport/HTTP failure surviving the retry policy; no
--                 claims written
CREATE TABLE llm_call (
  id                bigserial PRIMARY KEY,
  firm_id           uuid REFERENCES firm,
  component         text NOT NULL,
  model             text NOT NULL,
  prompt_rev        text NOT NULL,
  input_chars       int,
  input_tokens      int,
  output_tokens     int,
  cost_usd          numeric,
  status            text NOT NULL CHECK (status IN ('ok', 'failed', 'invalid', 'ungrounded')),
  ungrounded_fields text[],
  response          jsonb,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX llm_call_firm_idx ON llm_call (firm_id, created_at DESC);
CREATE INDEX llm_call_component_idx ON llm_call (component, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON llm_call TO lge_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lge_app;
