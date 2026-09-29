-- 104: who may use the screens (D-067). Sign-in is Google's; the engine
-- keeps one row per person, their access level, when they signed in, the
-- onboarding answers they gave the first time, and who set their access.
-- Sessions are server-side rows keyed on the hash of a random token; the
-- browser holds only the token, in an HttpOnly cookie.

CREATE TABLE app_user (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email           text NOT NULL UNIQUE,
  google_sub      text UNIQUE,
  name            text,
  picture_url     text,
  -- admin: everything, including the Users screen. operator: works the
  -- leads. viewer: reads. pending: signed in and onboarded, waiting for the
  -- admin. disabled: turned off by the admin.
  access          text NOT NULL DEFAULT 'pending'
                  CHECK (access IN ('admin', 'operator', 'viewer', 'pending', 'disabled')),
  onboarded_at    timestamptz,
  onboarding      jsonb,
  access_set_by   text,
  access_set_at   timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_sign_in_at timestamptz
);

CREATE TABLE app_session (
  token_hash   text PRIMARY KEY,
  user_id      uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX app_session_user_idx ON app_session (user_id);

-- Every change to a person's standing, on record: signed up, onboarded,
-- access set (by whom, from what, to what), signed out everywhere.
CREATE TABLE app_user_event (
  id      bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  kind    text NOT NULL,
  detail  jsonb,
  actor   text NOT NULL,
  at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX app_user_event_user_idx ON app_user_event (user_id, at);

GRANT SELECT, INSERT, UPDATE, DELETE ON app_user, app_session, app_user_event TO lge_app;
GRANT USAGE, SELECT ON SEQUENCE app_user_event_id_seq TO lge_app;
