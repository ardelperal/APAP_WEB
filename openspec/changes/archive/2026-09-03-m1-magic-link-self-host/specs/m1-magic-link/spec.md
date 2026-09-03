# Spec: M1 — Magic-link self-host auth

## Intent

Add a passwordless credential channel (magic-link) that lets an authorised user get a session by proving control of their email — without depending on InsForge's hosted OAuth proxy. The magic-link end-to-end lives on the same FastAPI process as the rest of the app and against the local Postgres backend shipped in M0.

In scope:

- `MagicLinkPort` (Protocol) with `request_magic_link` and `consume_magic_link`.
- A Postgres-backed adapter that uses a `magic_link_tokens` table.
- A `MailTransport` seam with a default `ConsoleMailTransport` and a placeholder `SMTPMailTransport`.
- Two HTTP routes: `POST /auth/magic/start` and `GET /auth/magic/verify?token=...` (with `POST` fallback).
- A new gate in `verify-fallback-ready` that exercises the round-trip end-to-end against the local backend.

Out of scope: classic password auth, SMTP production configuration, per-email rate limiting, HTML email templates.

## Requirements

### R1. `MagicLinkPort` is the only access path for magic-link state

The system MUST access magic-link state exclusively through a `MagicLinkPort` Protocol, located at `app/core/ports/magic_link_port.py`. The Protocol MUST expose two methods:

```python
async def request_magic_link(self, email: str, *, ttl_seconds: int = 86400) -> MagicLinkRequest:
    ...

async def consume_magic_link(self, token: str) -> str | None:
    """Returns the authorised email if the token is valid and unused, else None."""
```

`MagicLinkRequest` MUST carry: `email: str`, `token_hash: str` (the SHA-256 of the raw token), `requested_at: datetime`, `expires_at: datetime`, `consumed_at: datetime | None`, `transport_payload: dict`.

`request_magic_link` MUST:
- accept any email string (caller is responsible for authorising first);
- hash the raw token via `hashlib.sha256(token.encode("utf-8")).hexdigest()` BEFORE persisting;
- store the row in `magic_link_tokens`;
- emit the raw token via the injected `MailTransport.send_magic_link(email, raw_token, base_url)`;
- revoke any previous unconsumed token for the same email first (atomic UPDATE `consumed_at = requested_at_of_new_row` of the previous row in the same transaction).

`consume_magic_link` MUST:
- look up by token_hash;
- reject if not found, expired (`expires_at < now()`), or already consumed (`consumed_at IS NOT NULL`);
- atomically UPDATE `consumed_at = now()` AND return the email in the same statement (`UPDATE ... RETURNING email`).

### R2. `MailTransport` is the only access path for email delivery

The system MUST abstract email delivery behind a `MailTransport` Protocol at `app/core/ports/mail_transport_port.py`. The Protocol MUST expose:

```python
async def send_magic_link(self, email: str, raw_token: str, base_url: str) -> None:
    """Build the verification URL `f"{base_url}/auth/magic/verify?token={raw_token}"` and deliver."""
```

The default implementation MUST be `ConsoleMailTransport` at `app/core/auth_magic/mail_transports.py`. On each call it MUST append a single JSON line to `tests/mailbox.jsonl` with keys `{event: "magic_link.sent", email, sent_at, verify_url, raw_token}` so the verify URL is observable end-to-end without SMTP infra.

When `APAP_SMTP_HOST` is set, the system MUST resolve `SMTPMailTransport` instead. M1 ships the seam as a `NotImplementedError`-raising placeholder; M1.1 wires the real SMTP client.

### R3. `magic_link_tokens` table persists the token state

The system MUST create a `magic_link_tokens` table on local-backend startup with:

```sql
CREATE TABLE magic_link_tokens (
    email        TEXT NOT NULL,
    token_hash   TEXT PRIMARY KEY,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    consumed_at  TIMESTAMPTZ
);

CREATE INDEX magic_link_tokens_email_open_idx
    ON magic_link_tokens(email)
    WHERE consumed_at IS NULL;
```

The token row is keyed by `token_hash` (the SHA-256 of the raw token, lowercase hex). The raw token is never persisted; only its hash. The partial index speeds up `request_magic_link` revocation of previous unconsumed tokens for the same email.

The table lives in a schema managed by the local backend (created lazily via `_connect` if missing on lifespan startup). It is NOT provisioned in `tests/integration/conftest.py` because that file provisions the integration schema (different scope).

### R4. `POST /auth/magic/start` is the only endpoint that issues magic-link requests

The endpoint MUST accept `Content-Type: application/json` with body `{"email": "<str>"}`. It MUST return HTTP 200 with body `{"status": "queued"}` regardless of whether the email corresponds to an authorised user (constant-time to prevent enumeration).

For non-authorised emails the endpoint MUST NOT call `MailTransport.send_magic_link`. For authorised emails (looked up via `AuthUsersPort.check_email_taken`) the endpoint MUST:

1. call `MagicLinkPort.request_magic_link(email)` to persist the row;
2. build the verify URL as `f"{settings.app_base_url}/auth/magic/verify?token={raw_token}"`;
3. call `MailTransport.send_magic_link(email, raw_token, settings.app_base_url)`.

The endpoint MUST be a no-op (return 200 `{"status": "queued"}`) when the feature flag `APAP_AUTH_ENABLE_MAGIC_LINK` is unset or false.

The endpoint MUST validate `email` is a string matching a basic email regex; HTTP 400 with `{"error": "invalid_email"}` on mismatch.

### R5. `GET /auth/magic/verify?token=...` (and POST fallback) consume the token and issue a session

The endpoint MUST accept query parameter `token=<raw>` (GET) or form body `token=<raw>` (POST). It MUST validate the raw token is a non-empty string ≤4096 chars; HTTP 400 with `{"error": "invalid_request"}` on mismatch.

On any error path the endpoint MUST redirect to `/login` (302) and MUST NOT issue a session cookie. On success it MUST:

1. compute `token_hash = sha256(token).hexdigest()`;
2. call `MagicLinkPort.consume_magic_link(token_hash)` and check the returned email is in `authorized_users` (defence-in-depth: even if someone races a token they shouldn't);
3. create an `apap_session` cookie identical in shape to the one `/auth/callback` issues today. The session payload MUST carry `{user_id, email, rol, is_authorized}` and MUST be signed with `APAP_SESSION_SECRET` (HMAC-SHA256 JWT, claims `{email, sub, rol, iat, exp}` with `exp = iat + 86400`);
4. redirect the browser to `/`.

The endpoint MUST be a no-op (302 to `/login`) when the feature flag is unset.

### R6. `verify-fallback-ready` adds a `check_magic_link_local_round_trip` gate

The system MUST add a new check in `migration/verify_fallback_ready.py::CI_CHECKS` named `check_magic_link_local_round_trip`. The check MUST:

1. Provision a temp user in `authorized_users` (email `magic-link-test@apap.local`).
2. Provision the `magic_link_tokens` table on the local backend if missing.
3. POST `{"email": "magic-link-test@apap.local"}` to `/auth/magic/start`.
4. Read `tests/mailbox.jsonl` and extract the most recent verify URL.
5. Construct an httpx client that points at the local backend base_url.
6. Hit the verify URL via the client; assert the response status is 200 (or 302 following to `/`).
7. Assert the `apap_session` cookie was set.
8. Cleanup: remove the temp user from `authorized_users`.

The check MUST be added to `CI_CHECKS` so it runs in CI.

### R7. Feature gate keeps the channel opt-in

The system MUST read `APAP_AUTH_ENABLE_MAGIC_LINK` env at request time. Endpoints MUST no-op (return the same 200 / redirect shape but skip persistence and transport) when the flag is unset or false.

Defaults:
- dev (`APAP_ENV=dev` or unset): `APAP_AUTH_ENABLE_MAGIC_LINK` defaults to `1` so the magic-link is on out of the box.
- prod: defaults to `0`. Operators flip the flag when ready.

The flag is re-read on every request so it can be flipped without a deploy.

## Acceptance scenarios

### AS1. Magic-link endpoint accepts an authorised email and persists the token
- GIVEN `APAP_AUTH_ENABLE_MAGIC_LINK=1` and a user `a@apap.local` exists in `authorized_users`
- WHEN `POST /auth/magic/start {"email": "a@apap.local"}` returns 200 with `{"status": "queued"}`
- THEN `magic_link_tokens` contains exactly one row with `email="a@apap.local"` and `consumed_at IS NULL`
- AND `tests/mailbox.jsonl` contains one new JSON line with `email="a@apap.local"` and a non-empty `verify_url`

### AS2. Magic-link endpoint no-ops for an unknown email
- GIVEN no user `nope@apap.local` in `authorized_users`
- WHEN `POST /auth/magic/start {"email": "nope@apap.local"}` returns 200 with `{"status": "queued"}`
- THEN `magic_link_tokens` contains zero rows
- AND `tests/mailbox.jsonl` length is unchanged

### AS3. Consuming a valid token issues a session cookie
- GIVEN a fresh token persisted in step AS1
- WHEN `GET /auth/magic/verify?token=<raw>` is hit
- THEN the response includes a `Set-Cookie: apap_session=<jwt>; HttpOnly; SameSite=Strict; Path=/; Secure` header
- AND the JWT decodes with `APAP_SESSION_SECRET` and carries `email="a@apap.local"`, `sub=<user_id>`, `rol=<user_rol>`, `iat=<now>`, `exp=<iat+86400>`
- AND `magic_link_tokens.consumed_at` is no longer null

### AS4. Consuming the same token twice is rejected
- GIVEN the token from AS3 was already consumed
- WHEN the same `GET /auth/magic/verify?token=<raw>` is hit again
- THEN the response is 302 to `/login`
- AND no new session cookie is issued

### AS5. Expired tokens are rejected
- GIVEN a token whose `expires_at < now()`
- WHEN `GET /auth/magic/verify?token=<raw>` is hit
- THEN the response is 302 to `/login`

### AS6. Feature flag off makes the endpoints no-op
- GIVEN `APAP_AUTH_ENABLE_MAGIC_LINK=0`
- WHEN `POST /auth/magic/start {"email": "a@apap.local"}` is hit
- THEN the response is 200 with `{"status": "queued"}`
- AND `magic_link_tokens` is unchanged
- AND `tests/mailbox.jsonl` is unchanged

### AS7. Local-backend round-trip via `verify-fallback-ready`
- GIVEN `verify-fallback-ready --ci-only` runs with the local backend spawned in M0/T3.2
- WHEN the new `check_magic_link_local_round_trip` runs
- THEN it produces `magic_link_round_trip: PASS`
- AND `python -m migration.cli_verify_fallback_ready --ci-only` exits 0

### AS8. Constant-time response on unknown email
- GIVEN no user `nope@apap.local` in `authorized_users`
- WHEN the time for `POST /auth/magic/start {"email": "nope@apap.local"}` and the time for `POST /auth/magic/start {"email": "realuser@apap.local"}` are compared
- THEN the difference is ≤50ms (timing-attack resistance)

## Out of scope

- Classic password auth — separate slice
- SMTP production setup — operator action when `APAP_SMTP_HOST` is configured
- Per-email rate limiting — M1.1
- HTML email templates — M1.2
- Session revocation before natural expiry — M1.3
- Multi-tenant mailbox partitioning — not needed; one mailbox per process

## Forecast

Forecast total ≤600 LOC additions plus ≤80 deletions across the slice. The breakdown is in `proposal.md`.

## Gates

- `ruff check .` clean
- `python scripts/check_module_size.py` clean (each new file ≤700 lines; magic_link_tokens table adapter is fine)
- `python scripts/check_mutation_sites.py` clean (no new BASELINE entries)
- `python scripts/check_complexity.py` clean
- `mypy app/core/auth_magic/ app/core/ports/ app/core/auth_flow.py` clean
- `uv run pytest tests/integration/test_magic_link.py tests/migration/test_magic_link_local_round_trip.py -v` all green (≥8 atoms AS1–AS8)
- `python -m migration.cli_verify_fallback_ready --ci-only` exits 0 with the magic-link check added
- All F1×F2×F3 gates green; one commit per feature; `gentle-ai review start` lineage burned per feature

## Forecast risk

The slice exceeds the 400-line hard limit. Decomposition into F1/F2/F3 keeps each feature ≤350 LOC. Each feature ships independently with its own RDD lineage.
