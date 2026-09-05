# Proposal: Phase 2 — login clásico email/password (argon2id)

## Context

The current APAP_WEB auth surface (after M0 + M3.1) is **passwordless**:

| Auth flow | How | Required infra |
|---|---|---|
| Magic link | Email a token; user clicks; cookie issued | SMTP (Resend) |
| Google OAuth | Google's hosted consent screen | `APAP_GOOGLE_CLIENT_ID/SECRET` |
| Stub OAuth (M0) | Local backend returns synthetic JWT | None — dev only |

This works, but the operator (small animal-shelter admin) needs a **password** flow for cases where email delivery is slow or unreachable. The original umbrella slice #641 Phase 2 captured this as a deferred follow-up:
> Añadir columna `password_hash TEXT` (nullable para mantener compatibilidad con el OAuth actual que no setea hash). Hash con **argon2id** (no bcrypt — más moderno, mejor resistencia a GPU/ASIC).

This slice implements that.

## Why now

1. **The cookie trust chain works** (Phase 1 fail-open for InsForge 503, commit `f9e4259`) — the existing magic-link path is solid in production; the password path is additive.
2. **The local backend is up** (Phase 1 `apap-local-backend`) — the password hash function runs in-process, no extra infra.
3. **The schema is in our control** — adding a column is a one-liner DDL.

The slice is bounded: one migration, one auth adapter, three new routes, one form. ~250 LOC. Easily fits the 400-line PR budget.

## Causal authority and rollback

- **Invariant**: `ClassicPasswordAuthPort.verify_password(email, password)` returns True iff the bcrypt-style hash stored on the `password_hash` column matches the supplied password. Migration only adds a nullable column (existing OAuth/magic-link users unaffected). Magic-link and Google OAuth continue to work unchanged.
- **Rollback**: drop the new column. The slice doesn't touch existing flows.
- **Independent invariants**: depends on Phase 1 (local backend up); does NOT depend on Phase 3 (runbook) or Phase 5 (migrations).

## Slice shape: one feature (Phase 2 is small enough that one commit is sufficient)

| Forecast | Files | Notes |
|---|---|---|
| ~250 LOC | 4 modified + 4 new | 1 migration SQL, 1 auth port, 3 routes, 1 form template, 4 unit tests |

## Decisions

1. **argon2id (not bcrypt or pbkdf2)** — the original proposal says argon2id because it has the best GPU/ASIC resistance and a smaller config footprint than bcrypt. Use `argon2-cffi>=23.1.0` (already in dependencies per the Phase 1 wheel).
2. **Nullable `password_hash` column** — keeps existing magic-link and Google-OAuth users (no password) unaffected. Migration adds the column, doesn't backfill.
3. **`POST /auth/forgot-password` uses magic-link, not SMTP** — the operator's deferred-to-MVP "SMTP real" isn't required for this slice. The forgot-password endpoint mints a short-lived (30min) reset token and renders the reset link in the response (for testing); sending via email is a separate slice (M3.x SMTP integration).
4. **`POST /auth/login` returns 200 with `apap_session` cookie on success, 401 on bad creds** — same shape as the existing magic-link verify endpoint, so the existing `csrf_token_context_processor` keeps working unchanged.
5. **`POST /auth/logout` already exists** (in `app/core/auth_flow.py`) — reuse it; don't add a second logout route.

## What this slice does NOT do

- **Real SMTP** for forgot-password — use the local backend's `mail_transport` (console / MailDev), the same one the magic-link route uses. Operator can read the link from the MailDev UI for testing.
- **2FA / TOTP** — out of scope; defer to a later slice.
- **Apple / Facebook / GitHub OAuth** — the `AuthUsersPort` Protocol is already backend-agnostic; adding providers is a future slice.
- **Multi-tenant / row-level isolation** — the auth is single-tenant (one APAP_WEB instance = one protectora); that's a much later slice.
- **Password rotation policy** (force-change-on-first-login, expiry, reuse-history) — the slice ships a plain `verify_password` adapter; policy can layer on later.

## Acceptance (operator flow)

- **O1.** Operator runs `python -m migration apply` → `password_hash TEXT` column added to `usuarios_autorizados`. Existing rows have NULL (no password, they use magic-link / OAuth).
- **O2.** Operator opens `https://apap.romancaba.com/login` → sees email + password fields (the magic-link-only field becomes a secondary option below).
- **O3.** Operator enters `ardelperal@gmail.com` + `my-new-password` → POST /auth/login → 200 + `apap_session` cookie + redirect to `/`.
- **O4.** Operator enters wrong password → 401 + login form re-renders with error message.
- **O5.** Operator clicks "Forgot password?" → POST /auth/forgot-password → 200 + (in test) a magic-link-like reset URL is in the response body. Clicking it → POST /auth/reset-password → updates `password_hash` for the user.
- **O6.** Magic-link login still works (unchanged). Google OAuth still works (unchanged). Existing users with NULL `password_hash` can only use the non-password flows.

## Open questions for the user

1. **Where does the password reset link get sent?** — For tests/dev, the local backend's `mail_transport` writes it to MailDev (operator reads from `http://localhost:8025`). For production, we have two choices: (a) reuse the existing Resend SMTP wiring (commit `26ed6ad`), or (b) store in DB and surface in an admin UI. Recommend (a) for Phase 2; (b) for Phase 4.
2. **Rate-limiting / lockout** — does the slice add account-lockout-after-N-failures? Recommend defer to Phase 6 (security hardening) — the password reset flow covers the brute-force loss-of-access case.
3. **Password complexity rules** — min length, char-classes, etc.? Recommend Phase 2 ships with min-length 12 + bcrypt's defaults; explicit complexity rules (NIST-style) deferred to Phase 6.
4. **Session handling for `password_hash=NULL` users** — does the login form show "set up a password" for users with NULL hash? Recommend yes (call-to-action in the login form for first-time password setup). Track in this slice or Phase 6.

Captured: 4 (4 of 5 answered). Deferred to operator answers before TDD starts.
