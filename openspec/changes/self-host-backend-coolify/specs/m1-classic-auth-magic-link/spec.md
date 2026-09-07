# Spec: M1 — Login clásico + magic link

This is the M1 milestone of `self-host-backend-coolify`. The deliverable
is an alternative login path (email + password with magic link) that
coexists with the existing Google OAuth flow. Both flows write to the
same `usuarios_autorizados` table; a user can have a password (for
classic) AND/OR be linked to a Google account (for OAuth).

## Requirement: `usuarios_autorizados` supports password auth

### Migration `0050_add_password_hash.sql`

- Adds `password_hash TEXT` (nullable) to `usuarios_autorizados`
- Adds `email_verified_at TIMESTAMPTZ` (nullable) to `usuarios_autorizados`
- Adds `failed_attempts INTEGER NOT NULL DEFAULT 0` to `usuarios_autorizados`
- Idempotent (uses `ADD COLUMN IF NOT EXISTS`)

### Migration `0051_create_magic_link_tokens.sql`

- Creates table `magic_link_tokens`:
  ```sql
  CREATE TABLE IF NOT EXISTS magic_link_tokens (
      token TEXT PRIMARY KEY,
      email TEXT NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL,
      used_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  ```
- Creates index `magic_link_tokens_email_idx ON magic_link_tokens (email)`
- Idempotent

### Backward compatibility

- `password_hash` is nullable. Existing rows from Google OAuth have
  `password_hash = NULL` and continue to work (no password means
  classic login is disabled for that user; they can only use OAuth).
- New users added via `add_authorized_user` can have either or both.

## Requirement: `AuthUsersPort` extends with password methods

The Protocol `app/core/ports/auth_port.py` adds two new methods:

- `verify_password(email: str, password: str) -> AuthorizedUser | None`
- `set_password(email: str, password: str) -> None`

The LocalBackend adapter gains a no-op default (returns None for
`verify_password`, raises for `set_password`) so the migration does
not break the existing OAuth path. The new local adapter implements
both.

### Scenario: `set_password` then `verify_password` round-trip

- GIVEN `password_hash IS NULL` for `ana@test.com`
- WHEN `set_password("ana@test.com", "secret123")` is called
- THEN the row's `password_hash` is set to an argon2id hash of `"secret123"`

- AND `verify_password("ana@test.com", "secret123")` returns the user
- AND `verify_password("ana@test.com", "wrong")` returns `None`
- AND `verify_password("OTHER@test.com", "secret123")` returns `None`
  (user not found)

### Scenario: argon2 parameters

- The hash uses argon2id with `time_cost=3`, `memory_cost=65536` (64MB),
  `parallelism=4`
- A typical hash takes ~100ms on modern hardware
- Verification takes ~100ms regardless of the password's strength
  (argon2id is designed to be slow on the defender's side too)

## Requirement: Magic link tokens

### Token generation

- `MagicLinkPort.create_token(email, *, purpose="login", ttl_minutes=30)`
- Generates `raw_token = secrets.token_hex(32)` (64 chars hex)
- Stores `hash = sha256(raw_token)` in the DB (so a DB leak doesn't
  expose live tokens)
- Returns the `raw_token` to the caller (caller logs it for the operator)
- The `email` is normalised to lower-case before storage

### Token consumption

- `MagicLinkPort.consume_token(raw_token)` returns the email if:
  - The token exists in the DB
  - The token is not used (`used_at IS NULL`)
  - The token is not expired (`expires_at > now()`)
- On success, marks `used_at = now()` (one-time use)
- Returns `None` for any failure (invalid, used, expired)

#### Scenario: valid token consumed

- GIVEN a token was created for `ana@test.com` 5 minutes ago
- WHEN `consume_token(token)` is called
- THEN the email `"ana@test.com"` is returned
- AND the token's `used_at` is set to `now()`

#### Scenario: token used twice

- GIVEN a token was consumed at time T
- WHEN `consume_token(token)` is called again at T+1
- THEN `None` is returned (one-time use)

#### Scenario: expired token

- GIVEN a token was created 31 minutes ago
- WHEN `consume_token(token)` is called
- THEN `None` is returned (TTL expired)

### Token listing (admin panel)

- `MagicLinkPort.list_active()` returns all unexpired, unused tokens
  for the admin to view
- Returns: `[{email, expires_at, created_at}, ...]` ordered by
  `created_at DESC`
- Only `APAP_ADMIN_EMAILS` can call this via the admin endpoint

## Requirement: New API endpoints

The local backend exposes these endpoints in addition to the M0 ones:

### `POST /api/auth/login`

- Body: `{"email": str, "password": str}`
- On success: HTTP 200 `{"ok": true}` + `Set-Cookie: session=...`
- On failure: HTTP 401 `{"error": "invalid credentials"}`
- Generic error message (no email enumeration: "invalid credentials"
  whether the email doesn't exist OR the password is wrong)
- Increments `failed_attempts` on failure (for future rate-limiting,
  out of scope for this milestone)
- Resets `failed_attempts` to 0 on success

#### Scenario: successful login

- GIVEN `ana@test.com` has a password set
- WHEN `POST /api/auth/login` with `{"email": "ana@test.com", "password": "secret123"}`
- THEN HTTP 200 with `Set-Cookie: session=...` and body `{"ok": true}`

#### Scenario: wrong password

- GIVEN `ana@test.com` has a password set
- WHEN `POST /api/auth/login` with `{"email": "ana@test.com", "password": "wrong"}`
- THEN HTTP 401 with body `{"error": "invalid credentials"}`

#### Scenario: no password set (OAuth-only user)

- GIVEN `ana@test.com` has `password_hash IS NULL` (OAuth-only)
- WHEN `POST /api/auth/login` with `{"email": "ana@test.com", "password": "anything"}`
- THEN HTTP 401 with body `{"error": "invalid credentials"}`

### `POST /api/auth/logout`

- No body
- On success: HTTP 200 `{"ok": true}` + `Set-Cookie: session=; Max-Age=0`
- Idempotent: returns the same response even if no session is active

### `POST /api/auth/forgot-password`

- Body: `{"email": str}`
- On success: HTTP 200 `{"ok": true}` (always — no email enumeration)
- Generates a magic link with `purpose="password_reset"` and TTL 30min
- Logs the token to the magic link log (operator retrieves it)
- The log entry includes `email`, `token`, `expires_at`

#### Scenario: request password reset

- GIVEN the user `ana@test.com` exists
- WHEN `POST /api/auth/forgot-password` with `{"email": "ana@test.com"}`
- THEN HTTP 200 `{"ok": true}`
- AND a new row appears in `magic_link_tokens` with `purpose="password_reset"`

#### Scenario: request for non-existent email

- GIVEN `ghost@test.com` does not exist
- WHEN `POST /api/auth/forgot-password` with `{"email": "ghost@test.com"}`
- THEN HTTP 200 `{"ok": true}` (no enumeration)

### `GET /api/auth/magic?token=...`

- Query param: `token` (the raw token from the email / log)
- On success: HTTP 302 redirect to `/` with `Set-Cookie: session=...`
- On failure: HTTP 401 `{"error": "invalid or expired token"}`
- The token is consumed atomically (marked `used_at = now()`)

#### Scenario: consume valid token

- GIVEN a token was created for `ana@test.com`
- WHEN `GET /api/auth/magic?token=<raw_token>` is called
- THEN the user is logged in and redirected to `/`
- AND the token's `used_at` is set to `now()`

### `POST /api/auth/reset-password`

- Body: `{"token": str, "new_password": str}`
- On success: HTTP 200 `{"ok": true}`
- On failure: HTTP 401
- The token MUST be a `password_reset` purpose token (not `login`)
- The `new_password` is hashed with argon2id and stored

#### Scenario: reset password with valid token

- GIVEN a `password_reset` token exists for `ana@test.com`
- WHEN `POST /api/auth/reset-password` with `{"token": ..., "new_password": "newpass456"}`
- THEN HTTP 200 `{"ok": true}`
- AND `ana@test.com`'s `password_hash` is updated to the argon2id hash of `"newpass456"`

### `GET /admin/magic-links` (admin only)

- Lists active magic link tokens (admin-only via session check)
- Response: `[{email, expires_at, created_at}]`
- Only `APAP_ADMIN_EMAILS` can access

#### Scenario: admin lists active tokens

- GIVEN I am logged in as `admin@apap.local` (in `APAP_ADMIN_EMAILS`)
- AND a magic link was created 5 minutes ago for `ana@test.com`
- WHEN `GET /admin/magic-links`
- THEN the response includes the `ana@test.com` token with `expires_at`
  ~25 minutes from now

## Requirement: Local auth adapter

A new adapter `app/core/adapters/auth_local/classic_password_auth_port.py`
implements `AuthUsersPort` with the password methods, plus a new
`MagicLinkPort` adapter `app/core/adapters/auth_local/magic_link_port.py`.

### Scenario: local adapter is wired in DI

- GIVEN `APAP_LOCAL_BACKEND=true`
- WHEN the app starts
- THEN `AuthUsersPort` is bound to `ClassicPasswordAuthPort` (with the
  LocalBackend adapter as fallback for the OAuth-only methods)
- AND `MagicLinkPort` is bound to the local Postgres-backed implementation
- AND the operator can call the new endpoints without re-deploying

## Out of scope (M1)

- Email verification enforcement (the `email_verified_at` column is
  added but not enforced — that's a future epic)
- 2FA / one-time-password
- Rate limiting on login (the `failed_attempts` column is added but
  not used; that's a future epic)
- Audit log of login attempts
- SMTP real (magic link operator-delivery is the MVP)
- Password reset via email link (operator delivers magic link in person)

## Acceptance

- [ ] `ClassicPasswordAuthPort.verify_password` returns the user when
      password matches, None otherwise
- [ ] `ClassicPasswordAuthPort.set_password` stores an argon2id hash
- [ ] `MagicLinkPort.create_token` stores a SHA-256 hash of the token,
      returns the raw token to the caller
- [ ] `MagicLinkPort.consume_token` is one-time-use, expires after 30 min
- [ ] `MagicLinkPort.list_active` returns active tokens for the admin panel
- [ ] `POST /api/auth/login` works with the correct password (HTTP 200
      with session cookie)
- [ ] `POST /api/auth/login` returns 401 with the wrong password
      (generic error, no enumeration)
- [ ] `POST /api/auth/login` returns 401 when the user has no password
- [ ] `POST /api/auth/forgot-password` always returns 200
- [ ] `GET /api/auth/magic?token=...` consumes a valid token and logs in
- [ ] `GET /api/auth/magic?token=...` rejects an invalid/expired/used token
- [ ] `POST /api/auth/reset-password` updates the password hash
- [ ] `GET /admin/magic-links` is admin-only
- [ ] Google OAuth still works (no breaking changes to `oauth_local_backend_adapter`)
- [ ] Tests: `test_classic_password_auth.py` (login, wrong password,
      hash timing), `test_magic_link.py` (create/consume, expiry, one-time-use)
- [ ] `docs/runbooks/self-host-backend.md` has a "reset password" section
- [ ] Migrations 0050 and 0051 are idempotent
