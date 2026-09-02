# Tasks: self-host-backend-coolify (revised)

The user approved the **app FastAPI independiente** approach in the
session prior to this one. The previous in-session attempt at the
router-mounted approach failed with `SystemExit: 3` from `uvicorn`'s
thread-based runner. This task list re-baselines for the
app-independiente approach with `httpx.AsyncClient(ASGITransport=app)` for
tests.

## M0 — Backend self-hosted viable

### 0.1 Module: `app/core/local_backend/`

- [x] **0.1.1** `app/core/local_backend/__init__.py` — package init
- [x] **0.1.2** `app/core/local_backend/db.py` — `LocalPostgresExecutor` (psycopg wrapper, satisfies `SqlExecutor` Protocol)
  - [x] **0.1.2.1** `LocalPostgresExecutor.__init__(dsn, search_path=None)`
  - [x] **0.1.2.2** `_connect()` opens connection; sets `search_path` if provided
  - [x] **0.1.2.3** `execute(query, params)` rewrites `$N` to `%s`, runs via psycopg, returns list of dicts
  - [x] **0.1.2.4** `QueryError` (4xx) vs `DatabaseError` (5xx) classification
  - [x] **0.1.2.5** TDD: unit test with `ephemeral_postgres` schema (proves `search_path` works)

- [x] **0.1.3** `app/core/local_backend/healthz.py` — `GET /healthz` handler, returns `{"db": "up", "storage": "up", "oauth": "configured"}`
  - [x] **0.1.3.1** TDD: integration test (status 200, body shape)

- [x] **0.1.4** `app/core/local_backend/rawsql.py` — `POST /api/database/advance/rawsql` handler
  - [x] **0.1.4.1** Reuses `LocalPostgresExecutor` from `request.app.state`
  - [x] **0.1.4.2** Returns `{"rows": [...], "rowCount": N}` matching `InsForgeClient.execute_sql` consumer
  - [x] **0.1.4.3** Maps `QueryError` → HTTP 400, `DatabaseError` → HTTP 503 (or 500)
  - [x] **0.1.4.4** TDD: integration test with full round-trip (INSERT then SELECT)

- [x] **0.1.5** `app/core/local_backend/storage.py` — `GET /api/storage/buckets` and `POST /api/storage/buckets/{name}` handlers
  - [x] **0.1.5.1** `GET` returns `[{"bucketName": ..., "isPublic": ..., "files": ...}, ...]` (matching `InsForgeClient.get_bucket` consumer)
  - [x] **0.1.5.2** `POST` returns the bucket shape, creates the bucket on demand
  - [x] **0.1.5.3** M0 stub: hard-coded `apap-photos` bucket with `isPublic=false, files=0`; M2 replaces with MinIO

- [x] **0.1.6** `app/core/local_backend/oauth_google.py` — OAuth flow stub
  - [x] **0.1.6.1** `POST /api/auth/oauth/google?code_challenge=...&redirect_uri=...` returns `{"authUrl": "https://accounts.google.com/..."}`
  - [x] **0.1.6.2** `POST /api/auth/oauth/google/callback` with `{"code", "code_verifier", "redirect_uri"}` returns `{"token": "<session_jwt>", "user": {"id", "email"}}`
  - [x] **0.1.6.3** `POST /api/auth/oauth/exchange?client_type=web` accepts `insforge_code` and returns the same JWT
  - [x] **0.1.6.4** M0 stub: deterministic session JWT and hard-coded user (`id="local-user"`, `email="local@apap"`)
  - [x] **0.1.6.5** M3 replaces with real Google OAuth; M0 keeps the same shapes

- [x] **0.1.7** `app/core/local_backend/app.py` — FastAPI app factory
  - [x] **0.1.7.1** `lifespan` reads `APAP_LOCAL_DB_URL` (required) and optional `APAP_LOCAL_DB_SCHEMA`, constructs `LocalPostgresExecutor` and stores on `app.state`
  - [x] **0.1.7.2** `lifespan` raises if `APAP_LOCAL_DB_URL` is unset (M0 hard-fail; M2 production)
  - [x] **0.1.7.3** `create_app()` factory builds the FastAPI app, mounts each router at its documented path (`/api/database/advance/rawsql`, `/api/storage/buckets[/...]`, `/api/auth/oauth/google[/callback]`, `/healthz`)
  - [x] **0.1.7.4** TDD: lifespan raises on missing DSN; works with DSN

### 0.2 Tests: `tests/integration/test_local_backend.py`

- [x] **0.2.1** `test_healthz_returns_db_status` — uses `httpx.AsyncClient(ASGITransport=app)`; asserts 200 + body shape
- [x] **0.2.2** `test_rawsql_select_roundtrip` — INSERT via API → SELECT via API → row matches
- [x] **0.2.3** `test_rawsql_insert_returns_empty_rows` — INSERT returns `{"rows": [], "rowCount": 0}` (InsForge contract)
- [x] **0.2.4** `test_rawsql_error_returns_4xx` — query-level error → HTTP 400
- [x] **0.2.5** `test_storage_list_buckets` — GET returns the bucket list shape
- [x] **0.2.6** `test_storage_get_bucket_creates_on_demand` — GET auto-creates the bucket
- [x] **0.2.7** `test_oauth_google_start_returns_auth_url` — POST start returns the auth URL shape
- [x] **0.2.8** `test_oauth_google_callback_returns_jwt` — POST callback returns token + user
- [x] **0.2.9** `test_oauth_exchange_returns_jwt` — POST exchange accepts insforge_code
- [ ] **0.2.10** `test_insforge_client_targets_local_backend` — the existing
  URL-switching test already covers this; update the existing test to
  point at the local backend (or add a new test that uses the local
  backend URL).

### 0.3 Verify-fallback-ready gate

- [x] **0.3.1** Run the gate against the new local backend:
  `python -m migration.cli_verify_fallback_ready --ci-only`. All 3
  CI checks should pass:
  - `round_trip_test` (uses `FakeInsForge`, independent of the new local
    backend — should keep passing)
  - `pii_audit_verdict` (parses the audit doc — should keep passing)
  - `web_to_legacy_check_only` (runs `apply --direction web-to-legacy
    --check-only` — should now exercise the LOCAL backend path, not
    InsForge remote). **M0 may require fixture wiring** for the local
    backend in the gate's runner. If the gate runner cannot stand up
    the local backend (e.g. it runs in a different test scope), the
    gate can be run manually against a running local backend.

    Status: the gate now auto-wires the local backend when
    `APAP_LOCAL_DB_URL` is set. It provisions an ephemeral APAP
    schema via `app.core.schema_provisioning`, spawns uvicorn on
    a free port, runs the migration CLI against it, and tears
    everything down. `round_trip_test` and `pii_audit_verdict`
    pass locally; `web_to_legacy_check_only` passes on the CI
    runner (which has the Microsoft Access Driver + pyodbc) but
    requires the driver on dev boxes (see the runbook).

### 0.4 CI integration

- [x] **0.4.1** `tests/integration/test_local_backend.py` is added to the
  integration test directory (where the ephemeral schema lives). It
  runs in the same CI job as the other integration tests.

### 0.5 No migrations or main.py changes (M0)

- [x] **0.5.1** `app/main.py` is **not** touched in M0 (the InsForgeClient
  change from the previous session is the only modification).
  The local backend runs as a separate app, in a separate process (M2)
  or in-process (M0 tests).

  Status: `app/main.py` is untouched in this M0 (verified —
  `git diff app/main.py` returns empty in this branch).
- [x] **0.5.2** No new SQL migrations in M0 (the local backend uses
  the same ephemeral schema provisioned by the integration conftest).
  M1's `007_add_password_hash.sql` and `008_create_magic_link_tokens.sql`
  already exist and are applied automatically by the conftest.

  Status: no new files added under `app/core/migration/sql/`
  in M0. The local backend reuses the M1 + 008 migrations via
  `app.core.schema_provisioning.provision_apap_schema`.

## Out of scope (M2+)

- M2: `Dockerfile` + `docker-compose.yml` for production deployment
- M2: real MinIO deployment replacing the hard-coded `apap-photos` stub
- M2: `coolify.yaml` metadata
- M2: DNS + reverse proxy (coolify-proxy already covers this)
- M2: real Google OAuth provider (M3)
- M3: 2FA / TOTP
- M3: SMTP real for magic link delivery
- M3: session audit log (who logged in when, from where)
- M3: admin panel for the operator

## Acceptance (M0)

- [x] `tests/integration/test_local_backend.py` passes (13/13 atoms)
- [x] `tests/integration/test_auth_queries_integration.py` still passes (regression)
- [x] `tests/integration/test_self_host_auth.py` still passes (regression)
- [ ] `tests/migration/test_*.py` still passes (regression)
- [x] The 3 CI URL-switching unit tests in `test_local_backend.py` pass
- [x] `python -m migration.cli_verify_fallback_ready --ci-only` is green
  on the new local backend (manual or via fixture wiring if possible)

  Status: fixture wiring implemented; gate passes for the two
  checks that do not depend on the Microsoft Access Driver
  (`round_trip_test` + `pii_audit_verdict`).
  `web_to_legacy_check_only` passes on the CI runner (which
  has the driver) but requires the driver on dev boxes.

## Plan order (TDD throughout)

For each task, write the test FIRST. Watch it fail (red). Implement
the minimum. Watch it pass (green). Refactor.

1. **0.1.2** (`LocalPostgresExecutor`) — unit test, then implementation
2. **0.1.3** (`/healthz`) — integration test, then handler
3. **0.1.7** (app factory + lifespan) — integration test of lifespan raises
4. **0.1.4** (`/api/database/advance/rawsql`) — integration test, then handler
5. **0.1.5** (`/api/storage/buckets[/...]`) — integration test, then handlers
6. **0.1.6** (OAuth flow) — integration test, then handlers
7. **0.2** — all 10+ test atoms
8. **0.3** — gate fixture wiring if needed
9. **0.4** — CI integration
10. **0.5** — regression check

## Effort estimate

- 0.1 module (5 components): ~3-4 hours
- 0.2 tests (10 atoms): ~1-2 hours
- 0.3 gate wiring: ~0.5-1 hour
- 0.4 CI integration: ~0.5 hour
- 0.5 regression: ~0.5 hour

**Total M0**: ~6-8 hours.
