# Tasks: M1 — Magic-link self-host auth

Per the [spec](specs/m1-magic-link/spec.md) the slice forecast is ~600 LOC across three features. Each feature is independently reviewable under RDD and ships in the same branch per pre-MVP single-branch workflow.

The first feature to start is **F1. Magic-foundation** (port + adapter + persistence + mail transport seam). It is the dependency for F2 and F3. The user must review F1 end-to-end before F2 starts.

## F1. Magic-foundation — port + adapter + persistence

### T1.1 `MagicLinkPort` Protocol
- [ ] `app/core/ports/magic_link_port.py` — `MagicLinkPort` Protocol + `MagicLinkRequest` dataclass with the two methods (`request_magic_link`, `consume_magic_link`) per spec R1
- [ ] `app/core/ports/mail_transport_port.py` — `MailTransport` Protocol with `send_magic_link(email, raw_token, base_url)`
- [ ] Both Protocols are `runtime_checkable` so tests can `isinstance(...)` cheaply

### T1.2 Postgres-backed adapter
- [ ] `app/core/auth_magic/__init__.py` — empty package init
- [ ] `app/core/auth_magic/postgres_adapter.py` — `PostgresMagicLinkAdapter(MagicLinkPort)` with `__init__(dsn, *, search_path=None)`
- [ ] `request_magic_link` generates `secrets.token_urlsafe(32)`, computes `token_hash = sha256(token).hexdigest()`, calls `MailTransport.send_magic_link`, persists row, revokes previous unconsumed rows for same email in the same transaction
- [ ] `consume_magic_link` runs `UPDATE magic_link_tokens SET consumed_at = now() WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > now() RETURNING email`
- [ ] Lazy table create on first execute — `CREATE TABLE IF NOT EXISTS magic_link_tokens (...)` + the partial index; runs on every `_connect()` (cheap, idempotent)

### T1.3 `MailTransport` implementations
- [ ] `app/core/auth_magic/mail_transports.py`:
  - `ConsoleMailTransport(MailTransport)` writes JSON lines to `tests/mailbox.jsonl` with `{event, email, sent_at, verify_url, raw_token}`
  - `SMTPMailTransport(MailTransport)` is a placeholder raising `NotImplementedError` with a docstring describing the M1.1 wiring contract
- [ ] Resolver `app/core/auth_magic/get_mail_transport.py` — returns SMTPMailTransport when `APAP_SMTP_HOST` set; ConsoleMailTransport otherwise. Cached at module level for the lifetime of the process.

### T1.4 SQL migration for the table (created lazily)
- [ ] `app/core/migrations/sql/00X_create_magic_link_tokens.sql` — DDL matching spec R3, including the partial index
- [ ] The adapter's `_connect` runs this DDL idempotently (psycopg `cursor.execute(sql)` with `CREATE TABLE IF NOT EXISTS`)

### T1.5 Tests (≥5 atoms)
- Unit tests for the Protocol contract: `test_request_magic_link_persists_row_with_correct_hash`, `test_consume_magic_link_returns_email_on_first_use`, `test_consume_magic_link_returns_none_on_reuse`, `test_consume_magic_link_returns_none_after_expiry`
- Integration tests against an ephemeral schema: `test_postgres_adapter_roundtrip_with_ephemeral_schema` — provisions an empty schema, runs request + consume end-to-end, asserts session-bound behaviour

### F1 gate

- [ ] `ruff check app/core/auth_magic/ app/core/ports/magic_link_port.py app/core/ports/mail_transport_port.py` clean
- [ ] `python scripts/check_module_size.py` clean (each new file ≤700 lines)
- [ ] `python scripts/check_mutation_sites.py` clean (no BASELINE entries; new files start from 0 sites and stay <250)
- [ ] `python scripts/check_complexity.py` clean (no function CC>15)
- [ ] `mypy app/core/auth_magic/ app/core/ports/` clean
- [ ] `uv run pytest tests/integration/test_magic_link.py -v` ≥5 atoms green
- [ ] All gates green; one commit; `gentle-ai review start` lineage burned

## F2. Magic-rails — endpoints + cookie + DI + auth_flow wiring

### T2.1 `POST /auth/magic/start`
- [ ] `app/core/auth_magic/routes.py` — `start_magic_link(request: Request, body: MagicLinkStartBody) -> JSONResponse` registered at `POST /auth/magic/start`
- [ ] Validates email (basic regex); HTTP 400 `{"error": "invalid_email"}` on mismatch
- [ ] Reads `APAP_AUTH_ENABLE_MAGIC_LINK` at request time; no-op returns `{"status": "queued"}` when flag off
- [ ] Looks up email in `AuthUsersPort.check_email_taken`; bypasses persistence when not authorised (constant-time)
- [ ] Calls `MagicLinkPort.request_magic_link(email)` and `MailTransport.send_magic_link(email, raw_token, base_url)` for authorised users
- [ ] Uses `app.state` for `magic_link_port` and `mail_transport` (DI lives in lifespan)

### T2.2 `GET /auth/magic/verify?token=...` (and POST fallback)
- [ ] `verify_magic_link(request: Request, token: str = Query(...)) -> Response` registered at both `GET` and `POST /auth/magic/verify`
- [ ] Validates token (non-empty, ≤4096 chars); HTTP 400 on mismatch
- [ ] Reads `APAP_AUTH_ENABLE_MAGIC_LINK` at request time; redirects to `/login` when flag off
- [ ] Calls `MagicLinkPort.consume_magic_link(token_hash)`; redirects to `/login` when returns None
- [ ] On success: builds JWT (`PyJWT` already in the project? `app/core/auth_dependencies_session_di.py` shows session shape — verify with `codegraph_node`) with HMAC-SHA256, sets `apap_session` cookie identical to the OAuth callback shape; redirects to `/`
- [ ] Lifespan owns the DI: opens the Postgres adapter at startup, attaches to `app.state`

### T2.3 Wire into `app/core/auth_flow.py` and router registration
- [ ] `register_auth_flow_routes` adds the two new routes alongside the existing OAuth routes
- [ ] `app/core/auth_flow.py`'s session cookie shape (or wherever the JWT issuance lives) is reused; do NOT fork a different cookie name

### T2.4 Tests (≥7 atoms covering AS1–AS6 + AS8)
- AS1: `test_as1_authorized_email_persists_row_and_emails_transport`
- AS2: `test_as2_unknown_email_returns_200_without_persisting`
- AS3: `test_as3_consume_valid_token_issues_session_cookie`
- AS4: `test_as4_consume_same_token_twice_returns_302_to_login`
- AS5: `test_as5_consume_expired_token_returns_302_to_login`
- AS6: `test_as6_feature_flag_off_makes_endpoints_noop`
- AS8: `test_as8_unknown_email_response_time_within_50ms_of_known`

### T2.5 Session cookie compatibility
- [ ] The JWT issued here must be acceptable to the existing session middleware (verify by reading `app/core/session.py` and `app/core/auth_dependencies_di.py`)
- [ ] Decoded payload MUST carry `{user_id, email, rol, is_authorized}` identical to the OAuth path

### F2 gate

- [ ] All F1 gates still green
- [ ] `tests/integration/test_magic_link.py` covers AS1–AS6 + AS8 (7 atoms green)
- [ ] `python scripts/check_module_size.py` clean for F2 files (routes.py + lifespan wiring)
- [ ] `python scripts/check_rules.py app/core/auth_magic/ app/core/auth_flow.py` clean (no new layer violations — auth_magic lives under `app/core/` but does NOT import from `app.core.adapters.*`)
- [ ] All gates green; one commit; `gentle-ai review start` lineage burned

## F3. Magic-verify-ready — gate + integration atom

### T3.1 `check_magic_link_local_round_trip`
- [ ] `migration/verify_fallback_ready.py` adds `check_magic_link_local_round_trip()` to `CI_CHECKS` (after the existing three)
- [ ] The check reuses the local backend spawn helper from M0/T3.2 if available; otherwise spawns its own ephemeral backend
- [ ] Provisions a temp user in `authorized_users`, POSTs to `/auth/magic/start`, reads `tests/mailbox.jsonl` (cleared at start), extracts the verify URL, GETs it, asserts 200/302 with `apap_session` cookie

### T3.2 Test conftest extension
- [ ] `tests/migration/_local_backend_fixture.py` extends the existing fixture with an env var override `APAP_AUTH_ENABLE_MAGIC_LINK=1` and `APAP_SMTP_HOST` unset (so the local backend resolves `ConsoleMailTransport`)
- [ ] The teardown also clears `tests/mailbox.jsonl` between tests

### T3.3 Test atom AS7
- [ ] `tests/migration/test_magic_link_local_round_trip.py::test_magic_link_local_round_trip_against_spawned_backend`
- [ ] Uses the extended fixture from T3.2
- [ ] Asserts the migration subprocess `verify-fallback-ready --ci-only` returns exit 0 with `magic_link_round_trip: PASS` in stdout

### F3 gate

- [ ] All F1/F2 gates still green
- [ ] `migration/verify_fallback_ready.py` adds the new check, total file ≤700 lines
- [ ] `tests/migration/test_magic_link_local_round_trip.py` covers AS7 (1 atom)
- [ ] `python scripts/check_layers.py` clean (the new check lives in `migration/` and does NOT import from `app.core.auth_magic.*` without proper layering — keeps deps narrow)
- [ ] `uv run pytest tests/migration/` all green
- [ ] All gates green; one commit; `gentle-ai review start` lineage burned

## Final slice gate (after F3 merge)

- [ ] `tests/integration/test_magic_link.py` ≥7 atoms, all green
- [ ] `tests/migration/test_magic_link_local_round_trip.py` 1 atom, all green
- [ ] `python -m migration.cli_verify_fallback_ready --ci-only` exits 0 on the local backend with the magic-link check added
- [ ] `app/main.py` is unchanged for OAuth path (M1 is additive; existing Google OAuth flow continues to work)
- [ ] `app/main.py` IS modified to register the new routes via `register_auth_flow_routes` or equivalent
- [ ] `openspec/changes/m1-magic-link-self-host/` has the proposal, tasks, spec, and an apply-progress.md
- [ ] When `APAP_AUTH_ENABLE_MAGIC_LINK=0`, the production OAuth flow is unaffected

After F3 merge, M1 is green. M2 (Coolify production deploy) is the next slice with its own spec at the parent `self-host-backend-coolify` change.

## RDD binding

Each F1, F2, F3 ships under RDD. The parent orchestrator opens lineage with `--base-ref=<pre-F1-commit> --workspace-overlay` so the entire branch range is covered by the lineage scope. This avoids the F1/F2/F3 lineage-scoping loop encountered in M0.
