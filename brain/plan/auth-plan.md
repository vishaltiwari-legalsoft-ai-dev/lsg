# Sign-in, accounts and access (D-067, 28 Sep 2026)

**Asked for.** Google sign-in. One primary admin, vishal.tiwari@legalsoft.com, who starts everything. Anyone else from the team who signs in for the first time goes through an onboarding form. The admin has a Users tab and decides, person by person, what each may do.

## How it works

1. **Signing in.** The screens send the browser to Google. Google sends it back to the engine with a one-time code; the engine exchanges the code for the person's identity (Google's own account service says who they are) and opens a session. The session is a row in the engine's database; the browser holds only a random token in a cookie that scripts cannot read. Sessions last thirty days of use.
2. **Who may sign in at all.** Only Google accounts at legalsoft.com (a setting; more domains can be listed). An unverified address, another domain, or a disabled account is sent back with a plain reason.
3. **The admin.** The addresses named in the settings are admins the moment they sign in, skip the form, and cannot be demoted or disabled on the Users screen. That is how the owner never waits for their own approval.
4. **Everyone else.** The first sign-in creates the person with access *pending* and shows the form: name, role at Legal Soft, team, what they will use the engine for, phone. Their answers are kept whole. Then they see "waiting for the admin" until the admin decides.
5. **Access levels.** *Admin*: everything, including Users. *Operator*: works the leads, runs research, records decisions and edits. *Viewer*: reads everything, changes nothing. *Disabled*: turned off, sessions closed. *Pending* is the state before a decision.
6. **The Users screen.** Admin only. Everyone who has signed in, the ones waiting first, with what they said on the form, when they last signed in, and who set their access. One control per person sets the level; every change is written to the person's history with who made it.
7. **The door.** Every ordinary route stands behind one gate: no session is 401; not yet onboarded, waiting or disabled is 403 with that reason; a change by a viewer is 403 read-only; Users without admin is 403. The gate is open until sign-in is configured, so the one local operator today is not locked out.
8. **What is written on records** once sign-in is on: the signed-in address as the actor on decisions, notes and edits, where the record used to say "ui".

## What has to be set up once

A Google Cloud OAuth client (type *Web application*) with `http://127.0.0.1:5000/api/auth/google/callback` as an authorised redirect URI, and its id and secret in `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`. Restart the engine. `LGE_ADMIN_EMAILS` and `LGE_ALLOWED_EMAIL_DOMAINS` are already set. When the screens move off this machine, `LGE_PUBLIC_ORIGIN` becomes their public https address and the redirect URI in Google's console changes with it.

## Where it lives

Backend: migration `sql/104_users.sql` (people, sessions, history); `lge/auth/` (Google, people, sessions, access); `lge/api/gate.py` (the door); routes `lge/api/routes/auth.py` and `users.py`; the settings' sign-in block. Frontend: the sign-in, onboarding and waiting screens shown in place of the app by standing; the Users screen; the signed-in person and sign-out on the rail.

## Deliberately not done

- No passwords, no magic links: Google only, as the UI plan said before any hosting.
- No per-screen permissions beyond the three levels; the brief asked for "what kind of access", and read / work / administer is that.
- No invitation emails; the admin sees who is waiting on the Users screen.
- Export audit (who downloaded which sheet) stays for the handover work.
