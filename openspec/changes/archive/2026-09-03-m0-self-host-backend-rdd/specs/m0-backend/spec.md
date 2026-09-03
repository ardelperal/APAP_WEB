# Spec: M0 — Local FastAPI backend (RDD slice)

## Intent

Bring APAP_WEB's data layer under our own control. The current `InsForge` BaaS dependency is gated by an OAuth-interactive provisioning step the agent cannot run unattended, so `verify-fallback-ready --ci-only` fails on `web_to_legacy_check_only` (InsForge deprecation in 2026-Q3). This slice replaces the three InsForge HTTP endpoints the application actually calls with a FastAPI router served by the same process as the app, against a local Postgres. The application-side `InsForgeClient` does not change — when `APAP_LOCAL_BACKEND=true`, it points at `http://localhost:8000/api`.

This is M0 of the larger self-host-backend-coolify change. M1 (classic auth + magic link) and M2 (Coolify docker deploy) follow as separate slices once M0 is green. They are explicitly out of scope here.

The hexagonal architecture (§31) makes this clean: domain and business logic don't notice the swap; only the Port adapter changes its base URL.

## Requirements

### R1. `GET /healthz` returns 200 with the documented envelope

The endpoint MUST return HTTP 200 with body `{"db": "up"|"down", "storage": "up"|"down", "oauth": "configured"|"missing"}`. The body MUST be JSON-serialisable by FastAPI's default response model.

`db` MUST be `up` when the application can open and close a `LocalPostgresExecutor` connection within 500 ms. `db` MUST be `down` otherwise. The check MUST NOT raise; any exception during the connection probe MUST surface as `db: down`.

`storage` MUST always be `up` in M0 (the in-memory bucket stub is always healthy).

`oauth` MUST be `configured` iff `APAP_GOOGLE_CLIENT_ID` is set in the process environment, `missing` otherwise.

### R2. `POST /api/database/advance/rawsql` is a drop-in for `InsForgeClient.execute_sql`

The endpoint MUST accept JSON body `{"query": str, "params": list | None}` and return `{"rows": list[dict], "rowCount": int}`. `query` MUST be validated against the safe-identifier regex (`^[A-Za-z_][A-Za-z0-9_]*$` for each dotted segment) — anything containing a non-safe identifier in the table or column position MUST return HTTP 400 with `{"error": "unsafe_sql_identifier", "detail": "..."}` and MUST NOT execute.

Postgres-native `$N` placeholders MUST be rewritten to psycopg `%s` placeholders inside the handler. `params` MUST be passed as-is to psycopg. The endpoint MUST raise HTTP 400 if `query` is not a string, if `params` is not a list, or if either is missing.

For non-SELECT statements (`INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, etc.), `rows` MUST be `[]` and `rowCount` MUST be the affected-row count returned by psycopg. For SELECT, `rows` MUST be a list of dicts keyed by column name (psycopg default cursor with `dict_row` factory).

The handler MUST NOT accept more than one statement per request (no `;`-chained queries). The handler MUST verify there is at most one statement by counting top-level `;` outside of string literals.

### R3. `GET /api/storage/buckets` and `POST /api/storage/buckets/{name}` match `InsForgeClient.get_bucket` / `ensure_bucket`

`GET /api/storage/buckets` MUST return `list[{"bucketName": str, "isPublic": bool, "files": int}]` containing the in-memory bucket registry. M0 ships with a single registered bucket `apap-photos` with `isPublic=false, files=0` (idempotent — re-registering an existing bucket is a no-op).

`POST /api/storage/buckets/{name}` MUST return the same dict shape for the bucket named in the path. If the bucket does not exist, it MUST be created (in-memory) and returned. The endpoint MUST validate the path parameter against the safe-identifier regex (`^[A-Za-z0-9_-]{1,64}$`).

### R4. OAuth flow stubs (`POST /api/auth/oauth/google`, `POST /api/auth/oauth/google/callback`, `POST /api/auth/oauth/exchange`)

`POST /api/auth/oauth/google?code_challenge=...&redirect_uri=...` MUST return `{"authUrl": "https://accounts.google.com/o/oauth2/v2/auth?..."}`. The URL MUST be a stub (M0 does not integrate with Google — that requires interactive OAuth the agent cannot run).

`POST /api/auth/oauth/google/callback` MUST accept `{"code", "code_verifier", "redirect_uri"}` JSON and return `{"token": "<signed-jwt>", "user": {"id": "local-user", "email": "local@apap"}}`. The JWT MUST be HS256-signed with `APAP_SESSION_SECRET` (or `stub-secret` if unset) and MUST contain claims `{"email": "local@apap", "sub": "local-user", "iat": <now>, "exp": <now + 1h>}`.

`POST /api/auth/oauth/exchange?client_type=web` MUST accept `{"code": "<insforge_code>", "code_verifier": "..."}` JSON and return the same JWT + user envelope. The endpoint MUST validate that `code` matches the `insforge_code` pattern; otherwise HTTP 401.

### R5. `app/core/local_backend/app.py` factory wires the four routers

The factory MUST accept `db_dsn: str` and `oauth_configured: bool` as keyword arguments (both with type hints). It MUST expose `create_app(db_dsn=..., oauth_configured=...)` that returns a `FastAPI` instance with the four routers mounted at:
- `GET /healthz` (root)
- `POST /api/database/advance/rawsql` (under `/api`)
- `GET /api/storage/buckets`, `POST /api/storage/buckets/{name}` (under `/api`)
- `POST /api/auth/oauth/google`, `POST /api/auth/oauth/google/callback`, `POST /api/auth/oauth/exchange` (under `/api`)

The factory MUST raise `RuntimeError` with message `"db_dsn is required for the local backend"` when called without `db_dsn`.

The factory MUST expose the four routers as module-level symbols (`healthz_router`, `rawsql_router`, `storage_router`, `oauth_router`) so integration tests can mount individual routers.

### R6. `apply_legacy_to_web` regression: `verify-fallback-ready --ci-only` is green on the local backend

The existing `migration/verify_fallback_ready.py::check_web_to_legacy_check_only` MUST continue to PASS when the local backend is wired (instead of InsForge). Specifically, the test fixture used by that check MUST:
1. Spawn uvicorn with the local backend factory on a free port
2. Set `APAP_LOCAL_BACKEND=true`, `APAP_INSFORGE_URL=http://127.0.0.1:<port>/api` in the subprocess env
3. The check then runs `migration apply --direction web-to-legacy --check-only` against the local backend instead of InsForge

The spawn MUST complete within 5 s; on timeout the check reports `FAIL` with `detail="local backend did not become healthy on port <port> within 5s"`. On `RuntimeError` from the factory (missing DSN), the check reports `FAIL` with `detail="db_dsn is required for the local backend"`.

### R7. `InsForgeClient` base URL switch is opt-in via env

`InsForgeClient.__init__` MUST read `APAP_LOCAL_BACKEND` and `APAP_INSFORGE_URL`. When `APAP_LOCAL_BACKEND=true` (case-insensitive truthy: `1|true|yes|on`) AND `APAP_INSFORGE_URL` is empty, the client MUST default to `http://localhost:8000`. When `APAP_INSFORGE_URL` is non-empty, the client MUST use that URL regardless of `APAP_LOCAL_BACKEND` (operator override). When both are unset, the client MUST default to the production InsForge URL (`https://c3uc9dk6.eu-central.insforge.app`) for backward compatibility.

## Acceptance scenarios

### AS1. `GET /healthz` smoke test
- GIVEN the local backend factory is built with `db_dsn=postgresql://...`, `oauth_configured=true`
- WHEN `httpx.AsyncClient` GETs `/healthz`
- THEN the response status is 200, the body parses as JSON, and `body["db"] in {"up","down"}`, `body["storage"] == "up"`, `body["oauth"] == "configured"`

### AS2. `GET /healthz` reflects missing OAuth
- GIVEN the local backend factory is built with `db_dsn=...`, `oauth_configured=False`
- WHEN `httpx.AsyncClient` GETs `/healthz`
- THEN `body["oauth"] == "missing"`

### AS3. `POST /api/database/advance/rawsql` SELECT round-trip
- GIVEN the local backend factory is built with `db_dsn=test_dsn`, the test conftest has provisioned an ephemeral schema with a `test_roundtrip(id INT, label TEXT)` table
- WHEN the test POSTs `{"query": "INSERT INTO test_roundtrip (id, label) VALUES ($1, $2)", "params": [1, "alpha"]}` then POSTs `{"query": "SELECT id, label FROM test_roundtrip ORDER BY id", "params": []}`
- THEN the second response is 200, `body["rows"] == [{"id": 1, "label": "alpha"}]`, `body["rowCount"] == 1`

### AS4. `POST /api/database/advance/rawsql` rejects unsafe identifier
- GIVEN any local backend factory
- WHEN the test POSTs `{"query": "DROP TABLE users; --", "params": []}`
- THEN the response is HTTP 400 with `body["error"] == "unsafe_sql_identifier"` and the schema is unchanged

### AS5. `POST /api/database/advance/rawsql` rejects multiple statements
- GIVEN any local backend factory
- WHEN the test POSTs `{"query": "SELECT 1; SELECT 2", "params": []}`
- THEN the response is HTTP 400 (not 200)

### AS6. `GET /api/storage/buckets` returns the seeded bucket
- GIVEN the local backend factory is built
- WHEN `httpx.AsyncClient` GETs `/api/storage/buckets`
- THEN the response is 200 with body `list[{"bucketName": "apap-photos", "isPublic": False, "files": 0}]`

### AS7. `POST /api/storage/buckets/{name}` creates on demand
- GIVEN the local backend factory is built
- WHEN `httpx.AsyncClient` POSTs to `/api/storage/buckets/newbucket`
- THEN the response is 200 with `body["bucketName"] == "newbucket"`, `body["isPublic"] is False`, `body["files"] == 0`

### AS8. OAuth stubs
- GIVEN the local backend factory is built
- WHEN the test POSTs to `/api/auth/oauth/google?code_challenge=abc&redirect_uri=http://x/cb`
- THEN the response is 200 with `body["authUrl"]` starting with `"https://accounts.google.com"`
- WHEN the test POSTs to `/api/auth/oauth/google/callback` with `{"code": "x", "code_verifier": "y", "redirect_uri": "z"}`
- THEN the response is 200 with `body["token"]` having three `.`-separated segments (JWT) and `body["user"] == {"id": "local-user", "email": "local@apap"}`
- WHEN the test POSTs to `/api/auth/oauth/exchange?client_type=web` with `{"code": "ok", "code_verifier": "v"}`
- THEN the response is 200 with the same envelope

### AS9. `InsForgeClient` base URL resolution
- GIVEN `APAP_LOCAL_BACKEND=true` and `APAP_INSFORGE_URL` empty
- WHEN `InsForgeClient(base_url="", service_key="x")` is constructed
- THEN `client._client.base_url == "http://localhost:8000"` (trailing slash stripped)
- GIVEN `APAP_LOCAL_BACKEND=true` and `APAP_INSFORGE_URL=https://custom.example.com`
- WHEN `InsForgeClient(base_url="https://custom.example.com", service_key="x")`
- THEN `client._client.base_url == "https://custom.example.com"`
- GIVEN both unset
- WHEN `InsForgeClient(base_url="", service_key="x")`
- THEN `client._client.base_url == "https://c3uc9dk6.eu-central.insforge.app"`

### AS10. `verify-fallback-ready --ci-only` is green on local backend
- GIVEN a test conftest that spawns uvicorn with the local backend on a free port
- WHEN `python -m migration.cli_verify_fallback_ready --ci-only` runs against that backend
- THEN exit code is 0 and `check_web_to_legacy_check_only` reports `PASS`

## Out of scope (M1/M2 follow-ups)

- M1: classic auth + magic link (separate slice)
- M2: docker-compose / Coolify deploy (separate slice)
- Real Google OAuth integration (requires interactive consent the agent cannot run unattended)
- SMTP for magic-link delivery (the magic-link flow is compatible but the operator-delivery story is M1+)
- InsForge deprecation (this slice only swaps the URL; remote-decommission is a separate epic)

## Forecast

Forecasted additions plus deletions for this slice:

- `app/core/local_backend/__init__.py` — 0 lines (empty package init)
- `app/core/local_backend/app.py` — ~60 lines (factory + lifespan + mount points)
- `app/core/local_backend/db.py` — ~80 lines (LocalPostgresExecutor + rawsql helpers)
- `app/core/local_backend/healthz.py` — ~25 lines (handler + envelope)
- `app/core/local_backend/rawsql.py` — ~120 lines (handler + safe-identifier validation + single-statement check)
- `app/core/local_backend/storage.py` — ~50 lines (bucket list + create-on-demand)
- `app/core/local_backend/oauth_google.py` — ~100 lines (start + callback + exchange + JWT signing)
- `tests/integration/test_local_backend.py` — ~250 lines (10 acceptance scenarios)
- `tests/integration/test_insforge_client_url.py` — ~80 lines (AS9 sub-scenarios)
- `tests/migration/_local_backend_fixture.py` — ~70 lines (conftest helper for AS10)
- `app/core/insforge.py` — ~15 lines added (URL switch)
- `migration/verify_fallback_ready.py` — ~60 lines added (local backend spawn)
- `tests/migration/conftest.py` (or sibling) — ~20 lines (fixture wire-up)

Forecast total: **~930 lines added, ~5 lines modified**. **Above the 400-line hard limit** → this is a chain candidate OR requires a maintainer-approved exception.

Recommended decomposition if a chain is approved:

- **F1. M0-foundation** (~200 lines): `db.py` + `app.py` skeleton + `LocalPostgresExecutor` + tests for AS3 (rawsql round-trip) and AS4 (unsafe identifier). Wired as standalone module; no client-side changes yet.
- **F2. M0-routes** (~350 lines): `healthz.py`, `rawsql.py` handler, `storage.py`, `oauth_google.py` stubs + the rest of AS3–AS8. Tests for AS1, AS2, AS5–AS8. Wired as FastAPI routers.
- **F3. M0-client-switch** (~150 lines): `app/core/insforge.py` URL switch + `migration/verify_fallback_ready.py` spawn wiring + tests for AS9 + AS10. The PR-#643-style end-to-end.

Each feature ≤400 lines, independently reviewable, independently mergeable. Each carries its own spec + tests + RDD lineage.

If a single feature is preferred, this slice requires a maintainer-approved exception to the 400-line budget — at ~930 lines the slice is ~2.3× the budget.

## Gates that must pass before this slice merges

- `ruff check .` clean (no new F-series violations)
- `python scripts/check_module_size.py` clean (the new `app/core/local_backend/*` and `tests/integration/test_local_backend.py` modules must each be ≤700 lines)
- `python scripts/check_mutation_sites.py` clean (each new file ≤250 mutation sites)
- `python scripts/check_complexity.py` clean (no function with CC>15; the safe-identifier validator is the most likely offender — split per-statement-type if CC>15)
- `python scripts/check_ruff_ratchet.py` clean (no new BASELINE entry; no rule count above its current baseline)
- `python scripts/check_rules.py` clean (no AGENTS-rules violations)
- `python scripts/check_layers.py` clean (the new module lives under `app/core/` — must import only from `app.core.domain.*` if it touches domain, not from `app.core.adapters.*`; the OAuth stub does NOT touch domain so it lives at the right layer)
- `python scripts/check_slice_completeness.py` clean (the `local_backend` slice must have at least one `tests/test_local_backend_*.py`)
- `python scripts/check_alantyle.py` clean
- `mypy app/core/local_backend/` clean
- `uv run pytest tests/integration/test_local_backend.py tests/integration/test_insforge_client_url.py tests/migration/` all green

This slice is **not mergeable** unless all gates pass.
