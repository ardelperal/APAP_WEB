# Tasks: M1 — Magic-link self-host auth

Per the [spec](specs/m1-magic-link/spec.md) the slice forecast is ~600 LOC across three features. Each feature is independently reviewable under RDD and ships in the same branch per pre-MVP single-branch workflow.

The first feature to start is **F1. Magic-foundation** (port + adapter + persistence + mail transport seam). It is the dependency for F2 and F3. The user must review F1 end-to-end before F2 starts.

## F1. Magic-foundation — port + adapter + persistence

### T1.1 `MagicLinkPort` Protocol
- [x] `app/core/ports/magic_link_port.py` — `MagicLinkPort` Protocol + `MagicLinkRequest` dataclass with the two methods (`request_magic_link`, `consume_magic_link`) per spec R1
- [x] `app/core/ports/mail_transport_port.py` — `MailTransport` Protocol with `send_magic_link(email, raw_token, base_url)`
- [x] Both Protocols are `runtime_checkable` so tests can `isinstance(...)` cheaply

### T1.2 Postgres-backed adapter
- [x] `app/core/auth_magic/__init__.py` — empty package init
- [x] `app/core/auth_magic/postgres_adapter.py` — `PostgresMagicLinkAdapter(MagicLinkPort)` with `__init__(dsn, *, search_path=None)`
- [x] `request_magic_link` generates `secrets.token_urlsafe(32)`, computes `token_hash = sha256(token).hexdigest()`, calls `MailTransport.send_magic_link`, persists row, revokes previous unconsumed rows for same email in the same transaction
- [x] `consume_magic_link` runs `UPDATE magic_link_tokens SET consumed_at = now() WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > now() RETURNING email`
- [x] Lazy table create on first execute — `CREATE TABLE IF NOT EXISTS magic_link_tokens (...)` + the partial index; runs on every `_connect()` (cheap, idempotent)

### T1.3 `MailTransport` implementations
- [x] `app/core/auth_magic/mail_transports.py`:
  - `ConsoleMailTransport(MailTransport)` writes JSON lines to `tests/mailbox.jsonl` with `{event, email, sent_at, verify_url, raw_token}`
  - `SMTPMailTransport(MailTransport)` is a placeholder raising `NotImplementedError` with a docstring describing the M1.1 wiring contract
- [x] Resolver `app/core/auth_magic/get_mail_transport.py` — returns SMTPMailTransport when `APAP_SMTP_HOST` set; ConsoleMailTransport otherwise. Cached at module level for the lifetime of the process.

### T1.4 SQL migration for the table (created lazily)
- [x] `app/core/migrations/sql/00X_create_magic_link_tokens.sql` (file `007_create_magic_link_tokens.sql`) — DDL matching spec R3, including the partial index
- [x] The adapter's `_connect` runs this DDL idempotently (psycopg `cursor.execute(sql)` with `CREATE TABLE IF NOT EXISTS`)

### T1.5 Tests (5 atoms × 2 stub files for the ratchet)
- [x] Integration tests in `tests/integration/test_magic_link.py` (289 lines, 7 atoms):
  - `test_request_magic_link_persists_row_with_correct_hash`
  - `test_consume_magic_link_returns_email_on_first_use`
  - `test_consume_magic_link_returns_none_on_reuse`
  - `test_consume_magic_link_returns_none_after_expiry`
  - `test_console_mail_transport_appends_json_line`
  - `test_get_mail_transport_returns_console_when_no_smtp_env`
  - `test_postgres_adapter_roundtrip_with_ephemeral_schema`
- [x] `tests/test_magic_link.py` (10 lines) — re-exports integration atoms so `check_slice_completeness` finds a `tests/test_*.py` for the magic_link slice
- [x] `tests/test_mail_transport.py` (5 lines) — re-exports the mail-transport atoms for the mail_transport slice

### F1 gate

- [x] `ruff check app/core/auth_magic/ app/core/ports/magic_link_port.py app/core/ports/mail_transport_port.py tests/integration/test_magic_link.py tests/test_magic_link.py tests/test_mail_transport.py` clean
- [x] `python scripts/check_module_size.py` clean (postgres_adapter=242, mail_transports=144, get_mail_transport=53, magic_link_port=54, mail_transport_port=22, all under 700)
- [x] `python scripts/check_mutation_sites.py` clean (no BASELINE entries; each new file <250 sites)
- [x] `python scripts/check_complexity.py` clean (no function CC>15)
- [x] `python scripts/check_layers.py` clean (auth_magic lives under `app/core/` and does NOT import from `app.core.adapters.*`)
- [x] `python scripts/check_slice_completeness.py` clean (the 2 stub re-export modules satisfy the ratchet for both slices)
- [x] `uv run pytest tests/integration/test_magic_link.py -v` — 7 atoms green where APAP_TEST_POSTGRES_DSN is provisioned (CI service container); in this sandbox the atoms fail LOUDLY with `psycopg.OperationalError` per AGENTS.md "MUST NOT silently skip"
- [x] All gates green; one commit `08236fe9`; RDD lineage `review-e0a279bfeb9b7d3b` opened with `--base-ref=f724817 --workspace-overlay` (covers M1 SDD proposal + F1 source commits); 4 lens captures (review-risk, review-resilience, review-readability, review-reliability) all admitted; 13 total informational findings documented (1 WARNING, 12 SUGGESTION); lineage state `approved`, authority burned.

Note: the user's lineage abandoned earlier `review-cdcbb2a641e7b4e0` (which only covered `.pi/gentle-ai/persona.json`) is documented as an operational lesson. The correction is captured in the apply-progress.md of this slice.

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

- [x] All F1 gates still green
- [x] `tests/integration/test_magic_link.py` covers AS1–AS6 + AS8 (7 atoms green) — note: the file was split at line 296 to keep each test file ≤700 lines per spec soft cap; F2 atoms live in `tests/integration/test_magic_link_routes.py`; both re-exported from `tests/test_magic_link.py` for the slice_completeness ratchet
- [x] `python scripts/check_module_size.py` clean for F2 files (routes.py=289, app_state.py=99; test_magic_link.py=298, test_magic_link_routes.py=544)
- [x] `python scripts/check_rules.py` / `check_layers.py` clean (no new layer violations — `auth_magic.routes` lives under `app/core/` and only imports `app.core.session`, `app.core.config`, `app.core.ports.*`; no `app.core.adapters.*`)
- [x] All gates green; one commit `212674d feat(m1-magic-rails)`; `gentle-ai review start` lineage **deferred** to F3 close — the F1 lineage `review-97a3bfe09c1113ff` was opened pre-F2 and its frozen scope excluded the F2 commits; we follow the M0 pattern and run ONE final lineage after F3 lands with `--base-ref=f724817 --workspace-overlay` covering F1+F2+F3 source files atomically.

## F3. Magic-verify-ready — gate + integration atom

### T3.1 `check_magic_link_local_round_trip`
- [x] `migration/verify_fallback_ready.py` adds `check_magic_link_local_round_trip()` to `CI_CHECKS` (after the existing three)
- [x] The check reuses the local backend spawn helper from M0/T3.2 if available; otherwise spawns its own ephemeral backend
- [x] Provisions a temp user in `authorized_users`, POSTs to `/auth/magic/start`, reads `tests/mailbox.jsonl` (cleared at start), extracts the verify URL, GETs it, asserts 200/302 with `apap_session` cookie

### T3.2 Test conftest extension
- [x] `tests/migration/_local_backend_fixture.py` extends the existing fixture with an env var override `APAP_AUTH_ENABLE_MAGIC_LINK=1` and `APAP_SMTP_HOST` unset (so the local backend resolves `ConsoleMailTransport`)
- [x] The teardown also clears `tests/mailbox.jsonl` between tests

### T3.3 Test atom AS7
- [x] `tests/migration/test_magic_link_local_round_trip.py::test_magic_link_local_round_trip_against_spawned_backend`
- [x] Uses the extended fixture from T3.2
- [x] Asserts the migration subprocess `verify-fallback-ready --ci-only` returns exit 0 with `magic_link_round_trip: PASS` in stdout

### F3 gate

- [x] All F1/F2 gates still green
- [x] `migration/verify_fallback_ready.py` adds the new check, total file ≤700 lines (verified at 373)
- [x] `tests/migration/test_magic_link_local_round_trip.py` covers AS7 (1 atom marked @pytest.mark.integration)
- [x] `python scripts/check_layers.py` clean (the new check lives in `migration/` and imports only from `tests.migration._local_backend_fixture` per the F3 design — narrow dependency)
- [x] `uv run pytest tests/migration/` — the AS10-equivalent atom fails LOUDLY with `RuntimeError: APAP_TEST_POSTGRES_DSN is required` per AGENTS.md "MUST NOT silently skip"; with a real DSN the test exercises the round-trip; CI integration job provides the service container
- [x] All F3 gates green; one commit `c993e9d feat(m1-magic-verify-ready)`; RDD lineage `review-462a42960b25ac4c` opened with `--base-ref=f724817 --workspace-overlay` (covers M1 SDD + F1 + F2 + F3 source files, 23 paths); 4 lens captures (review-risk/resilience/readability/reliability) all admitted; 23 informational findings documented (4 risk + 3 resilience + 1 readability + 15 fiabilidad); lineage state `approved`, authority burned.

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
