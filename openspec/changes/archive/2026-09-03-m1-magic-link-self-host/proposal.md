# Proposal: M1 — Magic-link self-host auth

skill_resolution: paths-injected (sdd-propose, web-tdd-philosophy, codegraph-vba-upstream-sync)

## Why this slice

After M0 (PR-M0/641-rdd-m0 archive 2026-09-03), the FastAPI application talks to a local Postgres-backed FastAPI on `http://localhost:8000` (or `http://127.0.0.1:<port>` when spawned by `verify-fallback-ready`), but the only credential channel is Google OAuth through InsForge's hosted proxy. That keeps one foot in the external dependency we are trying to retire.

This slice adds a second credential channel — magic-link — that is **entirely local**:
- A `POST /auth/magic/start` endpoint takes `{email}` and, when the email belongs to an authorized user (already in `authorized_users`), generates a single-use, time-bounded token, persists it to a `magic_link_tokens` table in the local Postgres, and emits a magic-link URL via the configured `MailTransport` seam (default `ConsoleMailTransport` writes JSON to `tests/mailbox.jsonl` so the link is observable end-to-end without SMTP infra; `SMTPMailTransport` activates when `APAP_SMTP_HOST` is set).
- A `GET /auth/magic/verify` (and `POST` fallback for clients without query-string handling) consumes the token, validates it (not expired, not consumed), and issues the same `apap_session` cookie that `/auth/callback` issues today.

## Why not classic password auth (yet)

Classic-password storage + reset paths require a credential-extractor threat model (rate-limit, lockout, password reset email transport) that doesn't shrink the M0 dependency surface — magic-link does. After M1 ships, an authorized user who lost Google access can request a magic link from any browser, receive it on email (dev: console mailbox file), and have the same session as an OAuth login. Classic-password is a future slice (M1.5 or M2) and depends on what we learn from magic-link operation.

## Relationship to M0

- Builds on the local FastAPI backend shipped in M0.
- The `InsForgeClient` URL switch (T1.5) is unchanged — magic-link is opt-in (`APAP_AUTH_ENABLE_MAGIC_LINK=true`) and lives on the SAME process as the rest of the app.
- The `verify-fallback-ready` check continues to gate go-live. M1 adds a new check `check_magic_link_local_round_trip` that exercises the local Postgres path end-to-end.

## Out of scope

- Real SMTP transport production configuration (Mailgun/SES/etc.). The seam is there, the operator fills it.
- Magic-link rate limit / lockout per email (M1.1). M1 ships at-most-1 active token per email; per-IP throttling is M1.1.
- Cancellation flow (user explicitly revokes a magic-link session before its natural 24-hour expiry). Soft-deferred.
- Classic password auth.
- Email rendering templating (JSON envelope is enough for M0/M1; HTML template is M1.2).

## Forecast

Forecast total ≤600 LOC additions plus ≤80 deletions across the slice. Forecast breakdown:

- `app/core/auth_magic/` (new package) — ~280 LOC: ports + adapter + transport seams
- `app/core/migrations/sql/00X_create_magic_link_tokens.sql` — ~30 LOC
- `app/core/auth_flow.py` (extend with two routes) — ~60 LOC additions, 5 deletions
- `app/core/di/auth_dependencies_di.py` (token dependency) — ~10 LOC additions
- `app/core/migration/verify_fallback_ready.py` (add `check_magic_link_local_round_trip`) — ~50 LOC additions
- `tests/integration/test_magic_link.py` — ~150 LOC (8 atoms covering all flows)
- `tests/migration/test_magic_link_local_round_trip.py` — ~50 LOC (1 atom AS10-equivalent)

The forecast exceeds the 400-line hard limit → this is a chain candidate with F1/Magic-foundation (~250 LOC), F2/Magic-rails (~200 LOC), F3/Magic-verify-ready (~150 LOC). Three features, each independently reviewable under RDD.

## Slice structure

The slice ships through three features:

### F1. Magic-foundation — port + adapter + persistence
- `MagicLinkPort` (Protocol) with `request_magic_link(email, ttl_seconds=86400)` and `consume_magic_link(token) -> email | None`
- Postgres-backed adapter with `magic_link_tokens(email, token_hash, requested_at, expires_at, consumed_at)` table
- `MailTransport` Protocol with `ConsoleMailTransport` (default — appends JSON to `tests/mailbox.jsonl`) and `SMTPMailTransport` seam (placeholder when `APAP_SMTP_HOST` is set; not wired in M1.0)
- SQL migration `00X_create_magic_link_tokens.sql`

### F2. Magic-rails — endpoints + cookie + DI + auth_flow wiring
- `POST /auth/magic/start` accepting `{email: str}`. Returns 200 with `{status: "queued"}` regardless of whether the email is authorized (constant-time to prevent enumeration). On authorized email persists a token + emits to the transport.
- `GET /auth/magic/verify?token=...` (and POST fallback) consumes the token, issues `apap_session` cookie identical to the OAuth callback shape.
- DI provider `get_magic_link_port` + `get_mail_transport` using the existing `app.state` pattern.
- Feature-flag gate `APAP_AUTH_ENABLE_MAGIC_LINK` (default OFF in prod, ON in dev).

### F3. Magic-verify-ready — gate + integration atom
- Add `check_magic_link_local_round_trip` to `verify_fallback_ready.py::CI_CHECKS`. The check provisions a magic-link request against a temp user, reads `tests/mailbox.jsonl`, extracts the URL, calls `/auth/magic/verify` against the live process and asserts the session cookie.
- Test `tests/migration/test_magic_link_local_round_trip.py` exercises the same flow against the local backend spawned by `tests/migration/_local_backend_fixture.py`.
- Update `verify-fallback-ready` F1 forecast and tests/migration gate list.

## Risk

- **Email operator side**: without real SMTP, the link is observable in `tests/mailbox.jsonl`. Acceptable for dev/M0/M1; production deployment must set `APAP_SMTP_HOST` and confirm the operator wants email from this service.
- **Token entropy**: `secrets.token_urlsafe(32)` produces 256 bits per RFC 4122 §6; adequate.
- **Concurrent consume race**: two browsers hitting the verify endpoint at the same instant. Postgres `UPDATE ... WHERE consumed_at IS NULL ... RETURNING` provides row-level atomicity. M0 advisory locks (if any) are unrelated.
- **Cookie shape**: the existing `apap_session` cookie is a JWT issued by InsForge in M0. M1 must issue a token (signed locally with `APAP_SESSION_SECRET`) that the existing middleware decodes with the same secret. The session-decoding logic is unchanged; M1 only emits using a self-signed token.

## RDD binding

This slice runs under RDD. Three lineages (one per feature), each opened with `--base-ref=<pre-M1-commit> --workspace-overlay`. Each lineage captures the `review-reliability` lens; F2 and F3 may also pull `review-risk` and `review-resilience` when the change touches auth.
