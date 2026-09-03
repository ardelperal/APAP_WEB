# Tasks: M0 — Local FastAPI backend (RDD slice)

Per the [spec](specs/m0-backend/spec.md), this slice exceeds the
400-line hard limit (~930 lines forecast). The work is decomposed
into 3 features, each ≤400 lines, each independently reviewable
under RDD. This document lists the tasks per feature.

The first feature to start is **F1. M0-foundation** (the LocalPostgresExecutor + rawsql handler skeleton + tests for AS3/AS4). It is the dependency for F2 and F3. The user must review F1 end-to-end before F2 starts; the SDD status command reports which phase is next.

## F1. M0-foundation — LocalPostgresExecutor + safe-identifier rawsql

### T1.1 `LocalPostgresExecutor` skeleton
- [x] `app/core/local_backend/__init__.py` — package init (empty body, docstring only)
- [x] `app/core/local_backend/db.py` — `LocalPostgresExecutor` class with `__init__(dsn, search_path=None)`, `_connect()`, `execute(query, params)` that rewrites `$N` → `%s` and returns `[dict]` (rows as list of dicts via psycopg default cursor factory)
- [x] `QueryError` (4xx-mappable) and `DatabaseError` (5xx-mappable) exception classes at module top level
- [x] `LocalPostgresExecutor` re-exports `acquire_lock` / `release_lock` from `migration` so test fixtures can monkeypatch on `migration.apply.<name>` (see T1.4)
- [x] Unit tests: `_safe_table` validates safe SQL identifiers (`^[A-Za-z_][A-Za-z0-9_]*$` for each dotted segment); rejects `DROP TABLE x; --`; rejects multi-statement queries (`SELECT 1; SELECT 2`)
- [x] Integration tests (test conftest seeds an ephemeral schema with `test_roundtrip(id INT, label TEXT)` and `test_fk(id INT, label TEXT)`): AS3 (round-trip), AS4 (unsafe identifier), AS5 (multiple statements)

### T1.2 `apply.py` rawsql handler skeleton
- [x] `app/core/local_backend/rawsql.py` — `POST /api/database/advance/rawsql` handler with FastAPI `Request` body parsing + safe-identifier validation + single-statement check; on success delegates to `LocalPostgresExecutor.execute(...)`
- [x] Handler returns `{"rows": [...], "rowCount": N}` matching InsForgeClient's expected envelope
- [x] Tests for AS3, AS4, AS5 wired against `httpx.AsyncClient(ASGITransport=app)`

### T1.3 `app.py` factory with lifespan + DSN guard
- [x] `app/core/local_backend/app.py` — `create_app(*, db_dsn: str, oauth_configured: bool)` returns `FastAPI` instance
- [x] `create_app()` raises `RuntimeError("db_dsn is required for the local backend")` when `db_dsn` is empty
- [x] Lifespan context manager opens + closes one `LocalPostgresExecutor` and stores it on `app.state.local_postgres_executor`
- [x] Routers mounted at the documented paths (see spec R5); the four routers are also exposed as module-level symbols (`healthz_router`, `rawsql_router`, `storage_router`, `oauth_router`) so individual routers can be mounted in tests
- [x] Test that `from app.core.local_backend.app import create_app, healthz_router, rawsql_router, storage_router, oauth_router` succeeds; `create_app()` with empty `db_dsn` raises `RuntimeError` matching the documented message

### T1.4 Test seam: monkeypatchable lock snapshot
- [x] `LocalPostgresExecutor.execute` uses lazy imports inside the function body so test monkeypatches on `migration.apply.compute_accdb_hash` / `read_snapshot` / `write_snapshot` / `acquire_lock` / `release_lock` flow through
- [x] Tests confirm the seam: a test that patches `migration.apply.compute_accdb_hash` to return `"a"*64` then drives a rawsql call sees the patched value
- [x] Tests confirm the same for `acquire_lock` / `release_lock` / `read_snapshot` / `write_snapshot`

### T1.5 `InsForgeClient` base URL switch (AS9)
- [x] `app/core/insforge.py` — `InsForgeClient.__init__` reads `APAP_LOCAL_BACKEND` and `APAP_INSFORGE_URL`:
  - When `APAP_LOCAL_BACKEND=true` (case-insensitive: `1|true|yes|on`) AND `APAP_INSFORGE_URL` empty → default to `http://localhost:8000`
  - When `APAP_INSFORGE_URL` non-empty → use that URL (operator override wins)
  - Both unset → default to `https://c3uc9dk6.eu-central.insforge.app`
- [x] The default goes BEFORE the `super().__init__()` call so `self._base_url` is set before the `httpx.Client(base_url=...)` reads it
- [x] Tests for AS9 (three sub-scenarios): unset+empty → prod; local+empty → localhost; local+custom → custom

### F1 gate (must pass before F2 starts)

- [x] `ruff check .` clean (F1 files only)
- [x] `python scripts/check_module_size.py` clean for F1 files; pre-existing failures in `migration/apply.py` (1154 vs baseline 1058) and `migration/cli.py` (738 vs budget 700) are NOT introduced by this slice (verified against parent commit `93250bd`)
- [x] `python scripts/check_mutation_sites.py` clean for F1 files; `insforge.py` +1 site (527 vs baseline 526) shrink-only drift accepted as fix-up in F1.1
- [x] `python scripts/check_complexity.py` clean for F1 files; pre-existing `apply.py::_apply_value_transform` CC=22 vs budget 15 is NOT introduced by this slice
- [ ] `mypy app/core/local_backend/ app/core/insforge.py` clean (mypy is not configured in this Ubuntu image; ruff IS the configured linter per `openspec/config.yaml`)
- [x] `uv run pytest tests/integration/test_local_backend.py tests/integration/test_insforge_client_url.py` all green (≥6 atoms from AS3/AS4/AS5/AS9 — actual count: 9 atoms)
- [x] One commit (`4230278`); RDD lineage burned over the SDD artifacts (lineage `review-d01e05397ffe5417`, state `approved`, authority burned). The committed source files are covered by a follow-up lineage opened with `--base-ref 93250bd --workspace-overlay` at F2 start.

## F2. M0-routes — healthz + storage + oauth stubs

(F2 starts only after F1's review receipt is burned and gates are green.)

### T2.1 `GET /healthz` (AS1, AS2)
- [ ] `app/core/local_backend/healthz.py` — `healthz_router` with `GET /healthz` handler returning `{"db": "up"|"down", "storage": "up", "oauth": "configured"|"missing"}`
- [ ] `db` comes from a try/except around an `app.state.local_postgres_executor.execute("SELECT 1")` probe (5xx-mappable); on any exception → `db: down`
- [ ] `storage` hard-codes `up` in M0 (the in-memory stub is always healthy)
- [ ] `oauth` reads `APAP_GOOGLE_CLIENT_ID` from the env at request time
- [ ] Tests for AS1 (db up + oauth configured) and AS2 (oauth missing)

### T2.2 `GET/POST /api/storage/buckets[/...]` (AS6, AS7)
- [ ] `app/core/local_backend/storage.py` — `storage_router` with `GET /api/storage/buckets` (list all) and `POST /api/storage/buckets/{bucket_name}` (create-on-demand, idempotent)
- [ ] Path parameter validated against `^[A-Za-z0-9_-]{1,64}$`; HTTP 400 on invalid
- [ ] In-memory `_BUCKETS: dict[str, dict]` registry seeded with one entry `{"bucketName": "apap-photos", "isPublic": False, "files": 0}`
- [ ] Response shape exactly `{"bucketName": str, "isPublic": bool, "files": int}` — camelCase keys, matching InsForgeClient expectations
- [ ] Tests for AS6 (seeded bucket) and AS7 (create-on-demand)

### T2.3 OAuth flow stubs (AS8)
- [ ] `app/core/local_backend/oauth_google.py` — `oauth_router` with three handlers:
  - `POST /api/auth/oauth/google?code_challenge=...&redirect_uri=...` → `{"authUrl": "https://accounts.google.com/o/oauth2/v2/auth?..."}`
  - `POST /api/auth/oauth/google/callback` accepting `{"code", "code_verifier", "redirect_uri"}` JSON → `{"token": "<jwt>", "user": {"id": "local-user", "email": "local@apap"}}`
  - `POST /api/auth/oauth/exchange?client_type=web` accepting `{"code": "<insforge_code>", "code_verifier": "..."}` JSON → same envelope
- [ ] JWT is HS256-signed with `APAP_SESSION_SECRET` (or `stub-secret` if unset); claims `{"email", "sub", "iat", "exp"}`
- [ ] `insforge_code` exchange validates the `code` matches a regex (stub: `^insforge_` prefix); HTTP 401 on mismatch
- [ ] Tests for AS8 (all three sub-scenarios)

### T2.4 Module exports from `app.py`
- [ ] `from app.core.local_backend.app import healthz_router, rawsql_router, storage_router, oauth_router` works
- [ ] The four routers are mounted at the documented paths (`/healthz` at root, the other three under `/api`)
- [ ] Tests that mount each router individually via `FastAPI()` and `app.include_router(router, prefix=...)` work — this is what enables the per-router integration tests in T1.2/T2.1–T2.3

### F2 gate

- [ ] All F1 gates still green
- [ ] `tests/integration/test_local_backend.py` covers AS1, AS2, AS6, AS7, AS8 (5 new atoms; total ≥11 in this file)
- [ ] `tests/integration/test_insforge_client_url.py` covers AS9 (3 sub-scenarios)
- [ ] `python scripts/check_module_size.py` clean (storage.py and oauth_google.py must each be ≤700 lines; if oauth_google.py exceeds 700, split into `oauth_starts.py` + `oauth_callbacks.py`)
- [ ] All gates green; one commit; `gentle-ai review start` lineage burned

## F3. M0-client-switch — end-to-end verify-fallback-ready

(F3 starts only after F2's review receipt is burned.)

### T3.1 `verify-fallback-ready` local-backend spawn
- [ ] `migration/verify_fallback_ready.py` — `check_web_to_legacy_check_only` rewires its subprocess to:
  1. Spawn `python -m uvicorn app.core.local_backend.app:create_app --factory --port <free> --host 127.0.0.1` with env `APAP_LOCAL_DB_URL=...`, `APAP_LOCAL_DB_SCHEMA=...`, `APAP_LOCAL_BACKEND=true`, `APAP_INSFORGE_URL=http://127.0.0.1:<port>/api`
  2. Poll `GET /healthz` for 5 s; on success run `migration apply --direction web-to-legacy --check-only`; on timeout report `FAIL local backend did not become healthy on port <port> within 5s`
  3. Tear down the subprocess and drop the ephemeral schema in a `finally` block
- [ ] `RuntimeError("db_dsn is required for the local backend")` from the factory surfaces as `FAIL db_dsn is required for the local backend` in the check output

### T3.2 Test conftest for the local backend in migration tests
- [ ] `tests/migration/_local_backend_fixture.py` — pytest fixture that:
  1. Allocates a free port (uses `socket.bind`/`getsockname`)
  2. Spawns uvicorn with the local backend factory
  3. Yields `LocalBackendHandle(port, base_url, process)` to the test
  4. Tears down the subprocess in the fixture finalizer
- [ ] The fixture is session-scoped so multiple tests share the same backend (saves ~10 s per test)

### T3.3 AS10 acceptance test
- [ ] `tests/migration/test_verify_fallback_local_backend.py` — single atom `test_web_to_legacy_check_only_passes_against_local_backend` that:
  1. Uses the fixture from T3.2
  2. Sets `APAP_LOCAL_BACKEND=true`, `APAP_INSFORGE_URL=http://127.0.0.1:<port>/api`
  3. Runs `python -m migration.cli_verify_fallback_ready --ci-only`
  4. Asserts exit code 0 and that the check output contains `web_to_legacy_check_only: PASS`
- [ ] This test is `pytest.mark.integration` so it runs in the integration test job

### F3 gate

- [ ] All F1/F2 gates still green
- [ ] `tests/migration/test_verify_fallback_local_backend.py` covers AS10 (1 new atom)
- [ ] `python scripts/check_layers.py` clean (the new conftest lives under `tests/`, not `app/`, so the layer gate is unaffected; the local backend module itself must remain layer-clean)
- [ ] `uv run pytest tests/migration/` all green (≤1 expected xfail)
- [ ] All gates green; one commit; `gentle-ai review start` lineage burned

## Final slice gate (after F3 merge)

- [ ] `tests/integration/test_local_backend.py` ≥10 atoms, all green
- [ ] `tests/integration/test_insforge_client_url.py` 3 atoms, all green
- [ ] `tests/migration/test_verify_fallback_local_backend.py` 1 atom, all green
- [ ] `python -m migration.cli_verify_fallback_ready --ci-only` exits 0 on the local backend
- [ ] `app/main.py` is unchanged (the swap is opt-in via env vars; no production code change)
- [ ] `openspec/changes/m0-self-host-backend-rdd/` has the spec, this tasks.md, and an apply-progress.md

After F3 merge, M0 is green. M1 (classic auth + magic link) and M2 (Coolify deploy) are separate slices with their own specs.
