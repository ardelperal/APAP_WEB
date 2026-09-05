# Capability Spec — APAP_WEB Phase 2: classic email/password auth (argon2id)

## Intent

Add a third authentication path to APAP_WEB alongside the existing magic-link and Google OAuth flows. Users with a `password_hash` row in `usuarios_autorizados` can authenticate by submitting email + password to `POST /auth/login` and receive the same `apap_session` cookie that magic-link and Google OAuth already issue.

The slice is the Phase 2 follow-up of the self-host umbrella (#641). It depends on Phase 1 (local backend up) and does NOT depend on Phase 3 (Coolify runbook) or Phase 5 (separate migrations step).

Out of scope: real SMTP for forgot-password (the local backend's mail_transport writes to MailDev — operator reads from `http://localhost:8025`); 2FA / TOTP; rate-limiting / lockout; non-Argon2 hashes (bcrypt, pbkdf2, scrypt).

## Requirements

### R1. `usuarios_autorizados` gains a nullable `password_hash` column

The table must gain a `password_hash TEXT` column that is NULL by default (existing rows). The migration MUST be idempotent and MUST NOT break existing magic-link or Google OAuth users (their rows stay NULL).

#### Scenario: AS1.1 — migration adds the column without breaking existing rows
- GIVEN a populated `usuarios_autorizados` table with magic-link or Google OAuth users
- WHEN the migration runs
- THEN the column exists with all existing rows having `password_hash = NULL`
- AND magic-link and Google OAuth continue to work unchanged.

### R2. `POST /auth/login` accepts email + password

The endpoint MUST accept JSON `{"email": str, "password": str}` and return:
- HTTP 200 with `Set-Cookie: apap_session=...; HttpOnly; Secure; SameSite=Strict; Max-Age=604800` on success
- HTTP 401 with `{"error": "invalid_credentials"}` on bad email / bad password / unknown user

The endpoint MUST use `argon2-cffi>=23.1.0` for password hashing. The hash format MUST be `argon2id$...` so the verifier can identify the algorithm.

Constant-time comparison (timing-attack mitigation) MUST be used at the hash-compare site (argon2's verify() does this internally).

#### Scenario: AS2.1 — happy path
- GIVEN `ardelperal@gmail.com` exists with `password_hash = '$argon2id$v=19$m=...$'`
- WHEN `POST /auth/login` with `{"email": "ardelperal@gmail.com", "password": "my-pass"}`
- THEN response is 200 + the `apap_session` cookie is set with Max-Age=604800.

#### Scenario: AS2.2 — wrong password
- GIVEN `ardelperal@gmail.com` exists with a known hash
- WHEN `POST /auth/login` with the wrong password
- THEN response is 401 with `{"error": "invalid_credentials"}` (no cookie set).

#### Scenario: AS2.3 — unknown user
- GIVEN `nobody@example.com` doesn't exist in `usuarios_autorizados`
- WHEN `POST /auth/login` with that email + any password
- THEN response is 401 with `{"error": "invalid_credentials"}` (NOT `user_not_found` — leak no info).

#### Scenario: AS2.4 — user without password (NULL hash)
- GIVEN a user has `password_hash IS NULL`
- WHEN `POST /auth/login` with their email + any password
- THEN response is 401 (NULL hash means no password set; the user must use magic-link or Google OAuth instead).

### R3. `POST /auth/forgot-password` mints a 30-min reset token

The endpoint MUST accept JSON `{"email": str}` and return HTTP 200 with no body detail (don't leak whether the email exists).

If the user has `password_hash IS NOT NULL`, the endpoint MUST mint a single-use reset token, store it with a 30-minute TTL, and emit a `reset_url` of the form `https://apap.romancaba.com/auth/reset-password?token=...`. The slice writes the reset URL to the local backend's `mail_transport` log (operator reads it from MailDev in dev) — NOT to SMTP.

If the user has `password_hash IS NULL` or doesn't exist, the endpoint MUST return 200 with no `reset_url` (always 200 to avoid leaking user existence).

#### Scenario: AS3.1 — user with password requests reset
- GIVEN `ardelperal@gmail.com` has `password_hash` set
- WHEN `POST /auth/forgot-password`
- THEN response is 200 with a `reset_url` containing a single-use token
- AND the token is stored in `password_reset_tokens` with `expires_at = now + 30min`
- AND the local backend's mail_transport log contains a link to the `reset_url`.

### R4. `POST /auth/reset-password` consumes the token and sets the new hash

The endpoint MUST accept JSON `{"token": str, "new_password": str}` and return:
- HTTP 200 + sets the `apap_session` cookie on success (logs the user in immediately)
- HTTP 400 with `{"error": "invalid_token"}` if the token doesn't exist, is expired, or was already used
- HTTP 400 with `{"error": "weak_password"}` if the new password is shorter than 12 characters

The endpoint MUST hash the new password with argon2id (same algorithm as R2) and update the `password_hash` column. The token MUST be marked as consumed (single-use).

#### Scenario: AS4.1 — happy reset path
- GIVEN a valid unexpired reset token for `ardelperal@gmail.com`
- WHEN `POST /auth/reset-password` with `{"token": "...", "new_password": "new-pass-12345"}`
- THEN response is 200 + `apap_session` cookie is set
- AND the `password_hash` column for `ardelperal@gmail.com` is the new argon2id hash
- AND the token is marked as consumed (can't be reused).

#### Scenario: AS4.2 — expired token
- GIVEN a reset token with `expires_at < now()`
- WHEN `POST /auth/reset-password` with it
- THEN response is 400 with `{"error": "invalid_token"}`.

### R5. Login form renders email + password fields

The `/login` page TEMPLATE MUST render both email and password fields. The magic-link form MUST remain available below as a secondary option.

#### Scenario: AS5.1 — login page renders password form
- GIVEN an anonymous user visits `/login`
- WHEN the page renders
- THEN the HTML contains `<input type="email">`, `<input type="password">`, and a `<button>` labeled "Iniciar sesión"
- AND below the password form there is a "Olvidé mi contraseña" link to `/auth/forgot-password`
- AND below that there is a magic-link option (the existing magic-link form).

### R6. CSRF + session parity with existing flows

The login form must include the same CSRF token as the existing magic-link form (per `csrf_token_context_processor`). The session cookie produced by password login must be identical in shape, scope, and lifetime to the one issued by magic-link verify (`apap_session`, HttpOnly, Secure, SameSite=Strict, Max-Age=604800).

#### Scenario: AS6.1 — cookie parity
- WHEN a user logs in via `POST /auth/login` with valid credentials
- THEN the `Set-Cookie` header MUST match the format produced by `auth/magic/verify` exactly (except for the issue time).

## Acceptance scenarios index

| ID | Component | What it proves |
|---|---|---|
| AS1.1 | R1 migration | Column added without breaking existing rows |
| AS2.1 | R2 login happy path | Returns 200 + cookie on valid creds |
| AS2.2 | R2 wrong password | Returns 401, no leak |
| AS2.3 | R2 unknown user | Returns 401, no leak (same as wrong password) |
| AS2.4 | R2 NULL password | Returns 401 (must use other auth flow) |
| AS3.1 | R3 forgot-password | Mints token, writes to local mail_transport |
| AS4.1 | R4 reset happy path | Sets new hash, logs in, marks token consumed |
| AS4.2 | R4 expired token | Returns 400 invalid_token |
| AS5.1 | R5 form | Renders email + password fields |
| AS6.1 | R6 cookie parity | Set-Cookie format identical to magic-link |

10 scenarios across 6 requirements, each pinned as a unit / integration / e2e test before the gate that wraps the slice burns.

## Out-of-scope (explicit)

- Real SMTP for forgot-password (slice writes to local mail_transport — MailDev in dev; Resend wire-up is a separate slice per the umbrella decision).
- 2FA / TOTP, OAuth for additional providers, password rotation policies.
- Migrating the schema migration to a separate `migration/` slice (deferred to #647).
- Coolify-deploy manifest updates (#648).
