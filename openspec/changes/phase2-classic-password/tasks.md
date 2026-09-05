# Tasks: Phase 2 — classic email/password auth (argon2id)

Per the [proposal](proposal.md) and [spec](specs/phase2-classic-password/spec.md), this slice fits in a single feature (~250 LOC, under the 400-line PR budget). One feature, one commit.

The first (and only) feature is **F2.1 — classic password auth**.

## F2.1. Classic password auth (argon2id)

**Goal**: users with `password_hash` set in `usuarios_autorizados` can authenticate by submitting email + password to `POST /auth/login` and receive the same `apap_session` cookie that magic-link and Google OAuth already issue. Forgot-password → reset-password flow included.

### T2.1.1 Schema migration: add `password_hash` column

- [ ] `app/core/migrations/sql/008_add_password_hash.sql` (NEW):
  - [ ] `ALTER TABLE usuarios_autorizados ADD COLUMN IF NOT EXISTS password_hash TEXT;`
  - [ ] `ALTER TABLE usuarios_autorizados ADD COLUMN IF NOT EXISTS password_reset_token TEXT;`
  - [ ] `ALTER TABLE usuarios_autorizados ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP;`
  - [ ] Comments documenting that NULL means "no password set" (magic-link / OAuth users).
- [ ] `migration/__init__.py` (or whatever file registers SQL files) includes the new file in the list of migrations to apply.
- [ ] Tests:
  - [ ] `tests/migration/test_password_column.py::test_migration_is_idempotent` — running the migration twice doesn't fail
  - [ ] `tests/migration/test_password_column.py::test_existing_rows_unchanged` — existing magic-link users still have NULL password_hash after the migration
  - [ ] `tests/migration/test_password_column.py::test_new_column_is_nullable` — column accepts NULL inserts

### T2.1.2 `ClassicPasswordAuthPort` adapter

- [ ] `app/core/adapters/auth/classic_password_auth_port.py` (NEW):
  - [ ] `class ClassicPasswordAuthPort` implementing `AuthUsersPort`
  - [ ] `verify_password(email, password) -> bool` — fetches user by email, returns False if `password_hash IS NULL`, otherwise calls `argon2.PasswordHasher().verify(password_hash, password)` (which is constant-time)
  - [ ] `set_password(email, new_password) -> None` — generates an argon2id hash and updates the user's row
  - [ ] `request_password_reset(email) -> str | None` — generates a 32-byte URL-safe token, stores it with `expires_at = now + 30min`, returns the token (None if user doesn't exist or has no password set)
  - [ ] `consume_password_reset(token, new_password) -> AuthorizedUser | None` — validates token (exists, not expired, not consumed), hashes the new password, updates the row, marks the token consumed, returns the user
  - [ ] All methods catch `argon2.exceptions.VerifyMismatchError` and return False/None instead (no exception leak)
- [ ] Tests:
  - [ ] `tests/unit/test_classic_password_auth.py::test_verify_password_success`
  - [ ] `tests/unit/test_classic_password_auth.py::test_verify_password_wrong_password_returns_false`
  - [ ] `tests/unit/test_classic_password_auth.py::test_verify_password_null_hash_returns_false`
  - [ ] `tests/unit/test_classic_password_auth.py::test_verify_password_unknown_user_returns_false`
  - [ ] `tests/unit/test_classic_password_auth.py::test_set_password_then_verify_round_trip`
  - [ ] `tests/unit/test_classic_password_auth.py::test_set_password_hash_uses_argon2id`
  - [ ] `tests/unit/test_classic_password_auth.py::test_password_reset_token_expires`
  - [ ] `tests/unit/test_classic_password_auth.py::test_password_reset_token_single_use`

### T2.1.3 HTTP routes: login + logout + forgot-password + reset-password

- [ ] `app/core/routes/password_routes.py` (NEW):
  - [ ] `POST /auth/login` (JSON body: `{"email", "password"}`) → 200 + `Set-Cookie: apap_session=...; HttpOnly; Secure; SameSite=Strict; Max-Age=604800` on success, 401 on bad creds
  - [ ] `POST /auth/forgot-password` (JSON body: `{"email"}`) → 200 always; if user has password_hash, write the reset URL to `mail_transport` log
  - [ ] `POST /auth/reset-password` (JSON body: `{"token", "new_password"}`) → 200 + login cookie on success, 400 on bad token
  - [ ] Each route uses the existing `csrf_token_context_processor` so CSRF token validation keeps working
  - [ ] Each route uses the existing `_BaseUrlAwareConsoleTransport` for the email (writes to MailDev log)
- [ ] Register the routes in `app/main.py` (or `app/routes_registry.py`) alongside the existing magic-link routes
- [ ] Tests:
  - [ ] `tests/integration/test_password_routes.py::test_login_returns_200_and_cookie_on_valid_creds`
  - [ ] `tests/integration/test_password_routes.py::test_login_returns_401_on_bad_password`
  - [ ] `tests/integration/test_password_routes.py::test_login_returns_401_on_unknown_email`
  - [ ] `tests/integration/test_password_routes.py::test_login_returns_401_for_null_password_hash_user`
  - [ ] `tests/integration/test_password_routes.py::test_login_emits_apap_session_cookie_with_max_age_604800`
  - [ ] `tests/integration/test_password_routes.py::test_forgot_password_writes_reset_url_to_mail_log_for_known_user`
  - [ ] `tests/integration/test_password_routes.py::test_forgot_password_returns_200_for_unknown_email_no_leak`
  - [ ] `tests/integration/test_password_routes.py::test_reset_password_consumes_token_and_logs_user_in`
  - [ ] `tests/integration/test_password_routes.py::test_reset_password_with_expired_token_returns_400`

### T2.1.4 Login form template: email + password

- [ ] `app/templates/login.html` (MODIFY):
  - [ ] Add `<input type="email" name="email">` + `<input type="password" name="password">` + `<button type="submit">Iniciar sesión</button>`
  - [ ] Below: `<a href="/auth/forgot-password">Olvidé mi contraseña</a>`
  - [ ] Below the password form: keep the existing magic-link form (so users can choose between password and magic-link)
  - [ ] JS to handle form submission via fetch (JSON), matching the pattern already in place for the magic-link form
- [ ] Tests (Playwright):
  - [ ] `tests/e2e/test_password_login.py::test_login_form_renders_email_and_password_fields`
  - [ ] `tests/e2e/test_password_login.py::test_login_form_submits_via_json_fetch`
  - [ ] `tests/e2e/test_password_login.py::test_login_form_redirects_to_dashboard_on_success`
  - [ ] `tests/e2e/test_password_login.py::test_login_form_shows_error_message_on_401`
  - [ ] `tests/e2e/test_password_login.py::test_forgot_password_link_present`

### T2.1.5 Wire up the dependency graph

- [ ] `app/main.py` (MODIFY): the lifespan mounts `ClassicPasswordAuthPort` on `app.state.password_auth` (alongside the existing magic-link and InsForge ports)
- [ ] The login route looks up `app.state.password_auth` at request time
- [ ] Existing magic-link flow unchanged

### F2.1 gate (must pass before RDD burn)

- [ ] `ruff check app/core/adapters/auth/classic_password_auth_port.py app/core/routes/password_routes.py app/templates/login.py tests/` — clean
- [ ] `python scripts/check_module_size.py` — clean (the new files are all under 200 lines)
- [ ] `python scripts/check_mutation_sites.py` — clean
- [ ] `python scripts/check_layers.py` — clean (auth adapter stays in `app.core.adapters.auth.*`)
- [ ] `uv run pytest tests/unit/test_classic_password_auth.py tests/integration/test_password_routes.py tests/migration/test_password_column.py tests/e2e/test_password_login.py` — all green
- [ ] `uv run pytest tests/e2e/test_mobile_burger.py tests/e2e/test_nav_layout.py` — still green (no regression)
- [ ] `bash scripts/smoke_local_backend.sh` — exits 0 (the slice doesn't break the local backend health probes)
- [ ] One commit on the existing `feat/641-rdd-m0` branch (~250 LOC, under the 400-line PR budget per AGENTS.md §15)
- [ ] RDD lineage opened BEFORE the commit (per `gentle-ai review start --cwd <repo> --base-ref <ref>`); the user burns the receipt after the gate passes

## Files this slice touches

| Path | Type | Why |
|---|---|---|
| `app/core/migrations/sql/008_add_password_hash.sql` | NEW | Adds the `password_hash` column + reset-token columns |
| `app/core/adapters/auth/classic_password_auth_port.py` | NEW | `ClassicPasswordAuthPort` adapter (argon2id) |
| `app/core/routes/password_routes.py` | NEW | `POST /auth/login`, `/auth/forgot-password`, `/auth/reset-password` |
| `app/main.py` | EDIT | Mount `ClassicPasswordAuthPort` on `app.state.password_auth`; register the new routes |
| `app/templates/login.html` | EDIT | Email + password + forgot-password link; keep magic-link as secondary |
| `tests/unit/test_classic_password_auth.py` | NEW | Argon2id round-trip, NULL-hash, unknown-user, expired-token, single-use-token |
| `tests/integration/test_password_routes.py` | NEW | Real HTTP round-trips for all 3 routes |
| `tests/migration/test_password_column.py` | NEW | Migration is idempotent + nullable + doesn't break existing rows |
| `tests/e2e/test_password_login.py` | NEW | Playwright login + reset flows |

`app/core/auth_flow.py` (existing Google OAuth flow) is **not touched** — classic password is additive.

## Rollback

| Step | Action |
|---|---|
| Migration failed | The migration is `IF NOT EXISTS` so re-running is safe. |
| Slice misbehaves | Revert the commit; `password_hash` column stays but unused. Magic-link / Google OAuth unchanged. |
| User locked out | Operator runs `UPDATE usuarios_autorizados SET password_hash = NULL WHERE email = '<user>';` to force-reset that user's password. |

## RDD binding (per `documentation-alan-style` §17)

This slice opens a single RDD lineage BEFORE the commit:

```bash
gentle-ai review start \
    --cwd /home/ubuntu/apap-rdd-m0 \
    --base-ref origin/main \
    --focus reliability
```

After the gate passes (all unit / integration / e2e tests green, ruff + ratchet scripts clean), the user burns the receipt by capturing the appropriate lens:

```bash
gentle-ai review capture-result \
    --lineage <id-from-status> \
    --target <id-from-status> \
    --lens reliability \
    --order 1 \
    --input <review.json>
```

The burning closes the lineage and unblocks merging.
