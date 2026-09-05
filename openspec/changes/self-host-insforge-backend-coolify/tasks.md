# Tasks: self-host-insforge-backend-coolify

Per the [proposal](proposal.md) and [spec](specs/self-host-insforge-backend-coolify/spec.md), this slice exceeds the 700-line PR threshold if shipped as a single blob. The work is decomposed into **three features**, each ≤400 lines, each independently reviewable under RDD.

| Feature | What it lands | Lines forecast |
|---|---|---|
| F1. **Deploy local-backend as Coolify service** | Dockerfile dedicated to the local-backend factory; Coolify service manifest; service-to-service DNS verification; lifespan applies 27-statement DDL against `apap-pg-test` | ~280 |
| F2. **Flip the prod app to the local backend** | Update Coolify env vars on `apap-web` (`APAP_LOCAL_BACKEND=true`, `APAP_INSFORGE_URL=http://apap-local-backend:8080/api`); smoke-test all 8 dashboard cards return real data; confirm magic-link flow still works | ~100 |
| F3. **Integration tests against the deployed service** | `tests/integration/test_local_backend_deployed.py` covering healthz / rawsql / end-to-end magic-link via sibling container; one-shot curl smoke-test script `scripts/smoke_local_backend.sh` | ~250 |

Total ~630 LOC. Three commits, each ≤400 lines, each merges an independent capability.

The first feature to start is **F1**. F2 starts only after F1's review receipt is burned and gates are green. F3 starts only after F2's gates are green. The user reviews each feature end-to-end before the next feature starts; the SDD status command reports which phase is next.

## F1. Deploy local-backend as Coolify service (no client changes yet)

**Goal**: stand up `app/core/local_backend/app.py::create_app` as a Coolify service called `apap-local-backend`, reachable at `http://apap-local-backend:8080/api` from sibling containers.

### T1.1 Dockerfile dedicated to the local-backend
- [ ] New file `docker/local-backend.Dockerfile` (multi-stage, slim Debian Bookworm) that:
  - [ ] Stage 1 (builder) installs the project wheel via `pip wheel --no-cache-dir --no-deps --wheel-dir /work/dist /work`
  - [ ] Stage 2 (runtime) installs the wheel onto slim Python 3.11, non-root user `app` (uid 1001)
  - [ ] `WORKDIR /app`
  - [ ] `COPY --from=builder /work/dist/*.whl /tmp/wheels/`
  - [ ] `RUN pip install --no-cache-dir /tmp/wheels/*.whl`
  - [ ] `EXPOSE 8080`
  - [ ] `HEALTHCHECK --interval=10s --timeout=3s --start-period=20s CMD wget -qO- http://127.0.0.1:8080/healthz | grep -q db || exit 1`
  - [ ] `CMD ["uvicorn", "app.core.local_backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]` with `create_app(db_dsn="...", oauth_configured=False)` invoked via env-driven kwargs. **Decision**: pass `db_dsn` and `oauth_configured` via env (`APAP_LOCAL_BACKEND_DSN`, `APAP_LOCAL_BACKEND_OAUTH_CONFIGURED`) read inside `create_app` (lazy lookup at lifespan time) so the CMD stays opaque.
- [ ] `.dockerignore` at repo root excludes `.venv/`, `.git/`, `openspec/`, `tests/`, `docs/` to keep the build context small
- [ ] Build locally: `docker build -f docker/local-backend.Dockerfile -t apap-local-backend:dev .` exits 0 and the image is < 250 MB
- [ ] `docker run --rm -e APAP_LOCAL_BACKEND_DSN="..." apap-local-backend:dev` followed by `docker exec ... psql -c "SELECT 1"` against the same DSN to confirm the lifespan applied DDL

### T1.2 Wire the `_capture_state()` / lifespan to read DSN from env
- [ ] `app/core/local_backend/app.py::create_app(db_dsn: str, oauth_configured: bool)` — no changes to the signature, but add a thin `create_app_from_env()` helper that:
  - [ ] Reads `APAP_LOCAL_BACKEND_DSN` (required) from `os.environ`
  - [ ] Reads `APAP_LOCAL_BACKEND_OAUTH_CONFIGURED` (default `False`)
  - [ ] Calls `ensure_schema_and_seed(client, settings)` inside the lifespan **before** the four routers mount (or use the `_state`-keyed POST-decorator approach used by `apap-web`)
  - [ ] Raises `RuntimeError("APAP_LOCAL_BACKEND_DSN is required for the local backend")` when env is missing
- [ ] Unit tests for `create_app_from_env()`:
  - [ ] `test_create_app_from_env_raises_runtimeerror_when_dsn_missing` — without `APAP_LOCAL_BACKEND_DSN`, the function raises with the documented message
  - [ ] `test_create_app_from_env_returns_fastapi_when_dsn_set` — happy path returns a `FastAPI()` instance

### T1.3 Coolify service manifest
- [ ] New file `coolify/apap-local-backend.json` documenting the resource spec:
  - [ ] `name`: `apap-local-backend`
  - [ ] `project_uuid`: `mjgxwv4srqlsuww4pfpyo0t7` (the APAP project)
  - [ ] `environment_uuid`: `c7wgl2dmapown2x84f1gbgl9` (production)
  - [ ] `image`: `ghcr.io/ardelperal/apap_web/local-backend:1.0.0` (first build)
  - [ ] `ports_exposes`: `8080`
  - [ ] `ports_mappings`: none (internal only)
  - [ ] `health_check_path`: `/healthz`
  - [ ] `health_check_port`: `8080`
  - [ ] `health_check_interval_seconds`: `5`
  - [ ] `health_check_retries`: `10`
  - [ ] `health_check_timeout_seconds`: `3`
  - [ ] `env`:
    - [ ] `APAP_LOCAL_BACKEND_DSN=postgresql://postgres:postgres@apap-pg-test:5432/postgres`
    - [ ] `APAP_LOCAL_BACKEND_OAUTH_CONFIGURED=false`
    - [ ] `APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com`
  - [ ] `custom_docker_run_options`: `--network=coolify` (force the container onto Coolify's user-defined network so `apap-web` can reach it by service name)
  - [ ] `restart_policy`: `unless-stopped`
- [ ] Bootstrap script `scripts/coolify_deploy_local_backend.sh` that:
  - [ ] Reads `COOLIFY_API`, `COOLIFY_ACCESS_TOKEN` from the operator's env
  - [ ] Reads `APP_UUID` (the apap-web uuid, used as the project's parent for service-side env injection)
  - [ ] Builds + pushes the image via `docker build` (or calls Coolify's `POST /applications/{uuid}/deploy` if GHCR mirror is configured)
  - [ ] Creates the Coolify application resource via `POST /v1/applications/private` (Coolify v4 endpoint) with the manifest above
  - [ ] Injects the env vars via `POST /v1/applications/{uuid}/envs` (Coolify v4 accepts POST and the existing endpoint already works)
  - [ ] Triggers `POST /v1/deploy` with `{"uuid": "...", "force": false}` and prints the `deployment_uuid`
  - [ ] Watches `GET /v1/deployments/{deployment_uuid}` until status is `finished` / `failed` / `error` (max 120 s, poll 4 s)

### T1.4 Service-to-service DNS verification
- [ ] After `apap-local-backend` is up, run from a sibling container:
  - [ ] `docker exec apap-web curl -sf http://apap-local-backend:8080/healthz` returns HTTP 200 with the documented envelope (`db` is `"up"` if Postgres is reachable, `"down"` otherwise; `storage` is `"up"`; `oauth` is `"missing"` because `APAP_GOOGLE_CLIENT_ID` is not set)
  - [ ] `docker exec apap-local-backend psql "postgresql://postgres:postgres@apap-pg-test:5432/postgres" -c "\dt"` lists the 27 domain tables plus `magic_link_tokens` (28 total). Negative control: drop a session-wide table, restart `apap-local-backend`, confirm it's reapplied (`CREATE TABLE IF NOT EXISTS`)
- [ ] `scripts/smoke_local_backend_standalone.sh` (one-shot curl):
  - [ ] `curl -sf http://127.0.0.1:8080/healthz` from the host (or via `docker exec`) returns the documented envelope
  - [ ] `curl -sSf -X POST http://127.0.0.1:8080/api/database/advance/rawsql -H 'Content-Type: application/json' -d '{"query": "SELECT 1"}'` returns `{"rows": [{"?column?": 1}], "rowCount": 1}`
  - [ ] `curl -sSf -X POST http://127.0.0.1:8080/api/database/advance/rawsql -H 'Content-Type: application/json' -d '{"query": "DROP TABLE usuarios_autorizados; --"}'` returns HTTP 400 (or expected error code) and does NOT drop the table
  - [ ] The script exits `0` only when all three return success; otherwise prints the failing call and exits non-zero

### F1 gate (must pass before F2 starts)
- [ ] `ruff check docker/local-backend.Dockerfile` exits 0 (Dockerfile has no Python but ruff skips unsupported types)
- [ ] `python scripts/check_module_size.py` clean (no new module > 700 lines; the Dockerfile is text-only and not in `SCAN_DIRS`)
- [ ] `python scripts/check_mutation_sites.py` clean (no new mutation sites introduced by F1)
- [ ] `python scripts/check_layers.py` clean — the local backend modules stay in `app/core/local_backend/`
- [ ] `uv run pytest tests/integration/test_local_backend.py tests/integration/test_create_app_from_env.py` all green (15 existing M0 atoms + 2 new atoms for the env-driven factory)
- [ ] Live `curl http://apap-local-backend:8080/healthz` from a sibling container returns 200 with `db=up`
- [ ] `psql -c "\dt"` against `apap-pg-test` lists 28 tables after the cold start
- [ ] One commit; RDD lineage burned over the SDD artifacts

## F2. Flip the prod app to the local backend (data goes through it)

**Goal**: `apap-web`'s Coolify env vars flip from the hosted InsForge proxy to `apap-local-backend`. The `InsForgeClient` URL switch (already implemented in M0's `app/core/insforge_url.py`) makes the routing change transparent to the application code.

### T2.1 Set Coolify env vars on `apap-web`
- [ ] Update Coolify env vars on `apap-web` (`cxm5x2f489eos8nr8e1qv1c6`):
  - [ ] `APAP_LOCAL_BACKEND=true`
  - [ ] `APAP_INSFORGE_URL=http://apap-local-backend:8080/api`
  - [ ] `APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com` (already set, no change)
- [ ] `scripts/setup_local_backend_envvars.sh` that:
  - [ ] Reads `COOLIFY_API`, `COOLIFY_ACCESS_TOKEN`, `APP_UUID`
  - [ ] DELETEs the existing `APAP_INSFORGE_URL` entry (delete existing then POST new, per the same pattern as `scripts/setup_resend_smtp.sh`)
  - [ ] POSTs `APAP_LOCAL_BACKEND=true`
  - [ ] POSTs `APAP_INSFORGE_URL=http://apap-local-backend:8080/api`
  - [ ] Triggers `POST /v1/deploy` and watches `GET /v1/deployments/{deployment_uuid}` until status is `finished` (max 120 s)

### T2.2 Verify the data layer goes through the local service
- [ ] Log in via magic link at `https://apap.romancaba.com/login` (cookie trust chain still works — verify `/healthz` on `apap-web` first)
- [ ] Visit `https://apap.romancaba.com/admin` — the user-management table renders (was HTTP 500 with `InsForgeError: 503` before this slice)
- [ ] Visit `https://apap.romancaba.com/animales` — the animals list renders (or shows an empty state for an empty database)
- [ ] Visit `https://apap.romancaba.com/voluntarios` — the volunteers table renders
- [ ] All 8 dashboard cards (`Tareas`, `Animales incoherentes`, `Pendientes de entrada`, etc.) populate from the local Postgres (counters should match `SELECT COUNT(*)` against the respective tables)
- [ ] `docker exec apap-local-backend cat /proc/<pid>/status | grep -E VmRSS` after a single request to confirm the local backend is the one that handled the query

### F2 gate
- [ ] All F1 gates still green
- [ ] `ruff check scripts/setup_local_backend_envvars.sh` exits 0 (no Python lint, but bash sanity)
- [ ] Live smoke against `https://apap.romancaba.com/{admin,animales,voluntarios}` returns 200 from a logged-in browser (Playwright or curl with the magic-link cookie)
- [ ] No HTTP 500 in `apap-web` container logs after flipping the env vars
- [ ] One commit; RDD lineage burned

## F3. Integration tests against the deployed service

**Goal**: tests that fail fast if the service-to-service wiring breaks (replaces the M0 fixture-based tests with real-network tests).

### T3.1 `tests/integration/test_local_backend_deployed.py`
- [ ] New file `tests/integration/test_local_backend_deployed.py` covering:
  - [ ] `test_healthz_returns_envelope_from_sibling` — `docker exec`-style probe against `http://apap-local-backend:8080/healthz` returns 200 with `db in {up, down}`, `storage == up`, `oauth in {configured, missing}`
  - [ ] `test_rawsql_insert_select_roundtrip` — POST `/api/database/advance/rawsql` with `INSERT INTO animales (nombre) VALUES ($1)` then `SELECT nombre FROM animales LIMIT 1`; row count + row data round-trip correctly
  - [ ] `test_rawsql_rejects_drop_table` — negative control: `DROP TABLE usuarios_autorizados; --` returns HTTP 400 and the table still exists
  - [ ] `test_magic_link_end_to_end_hits_local_backend` — `httpx.AsyncClient` POST against `https://apap.romancaba.com/auth/magic/start` with JSON `{email: "ardelperal@gmail.com"}` returns 200; an `apap_session` cookie is set after the verify; the local backend's logs (via `docker logs apap-local-backend --since 30s`) record the `POST /api/database/advance/rawsql` call (verifying the request actually went through the local backend, not the InsForge proxy)
  - [ ] `test_unauthorized_html_on_dashboard_routes` — sanity: `/admin`, `/animales`, `/voluntarios` all return HTTP 200 when authenticated via the magic-link cookie (catches regressions where someone reverts the env vars back to the hosted InsForge proxy)
- [ ] Tests marked `@pytest.mark.e2e_deployed` so they can be excluded via `-m "not e2e_deployed"` for fast in-process runs
- [ ] Document in the file header that this suite depends on:
  - [ ] `apap-local-backend` running in Coolify
  - [ ] `apap-web` reachable at `https://apap.romancaba.com`
  - [ ] `APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com` set on both services
  - [ ] `MAILDEV_URL=http://localhost:8025` (or the equivalent Resend setup) so the magic-link `GET /auth/magic/verify?token=...` step has a token to consume

### T3.2 `scripts/smoke_local_backend.sh`
- [ ] New file `scripts/smoke_local_backend.sh` (~40 lines) that:
  - [ ] Reads `APAP_INSFORGE_URL` (default `http://apap-local-backend:8080/api`) and `APAP_PUBLIC_BASE_URL` (default `https://apap.romancaba.com`) from env
  - [ ] Runs `curl -sf $APAP_INSFORGE_URL/healthz` → checks `db=up`
  - [ ] Runs `curl -sf -X POST .../rawsql -d '{"query":"SELECT 1"}'` → checks HTTP 200
  - [ ] Runs `curl -sf -X POST $APAP_PUBLIC_BASE_URL/auth/magic/start -d '{"email":"ardelperal@gmail.com"}' -H 'Content-Type: application/json'` → checks HTTP 200 with `{"status": "queued"}`
  - [ ] Exits `0` only when all three succeed; non-zero with diagnostics on failure
- [ ] Documented in script header how to invoke (operator runs `bash scripts/smoke_local_backend.sh` from the VPS)

### T3.3 CI wiring (deferred)
- [ ] Document in `.github/workflows/` (or wherever CI is wired) that the `e2e_deployed` marker gates a separate job. **Out of scope to implement** for this slice — the tests run manually against the deployed service for now. A future ops slice will wire CI.

### F3 gate
- [ ] All F1 + F2 gates still green
- [ ] `uv run pytest tests/integration/test_local_backend.py tests/integration/test_local_backend_deployed.py -m "not e2e_deployed"` exits 0
- [ ] `uv run pytest tests/integration/test_local_backend_deployed.py -m e2e_deployed` exits 0 (against the real deployed service)
- [ ] `bash scripts/smoke_local_backend.sh` exits 0
- [ ] `python scripts/check_module_size.py` clean (`tests/integration/test_local_backend_deployed.py` < 700 lines, `scripts/smoke_local_backend.sh` < 200 lines)
- [ ] `python scripts/check_mutation_sites.py` clean (no new mutation sites)
- [ ] One commit; RDD lineage burned

## Files this slice touches

| Path | Type | Why |
|---|---|---|
| `docker/local-backend.Dockerfile` | NEW | Multi-stage build for the local-backend factory |
| `app/core/local_backend/app.py` | EDIT | Adds `create_app_from_env()` helper |
| `tests/integration/test_local_backend.py` | EDIT | Adds 2 atoms for the env-driven factory |
| `coolify/apap-local-backend.json` | NEW | Coolify service manifest (reference for the deploy script) |
| `scripts/coolify_deploy_local_backend.sh` | NEW | Coolify API bootstrap (idempotent) |
| `scripts/smoke_local_backend_standalone.sh` | NEW | F1 curl smoke test |
| `.dockerignore` | NEW | Trim the build context |
| `scripts/setup_local_backend_envvars.sh` | NEW | F2 env-var flip |
| `tests/integration/test_local_backend_deployed.py` | NEW | F3 service tests |
| `scripts/smoke_local_backend.sh` | NEW | F3 end-to-end smoke |

`app/core/local_backend/{db,rawsql,healthz,storage,oauth_google}.py` are **not touched** — M0 already shipped and tested them.

## Rollback

| Step | Action |
|---|---|
| F1 only (Coolify service misbehaves) | `DELETE /v1/applications/{apap-local-backend-uuid}` — Coolify stops + removes the container |
| F2 fails (env-var flip breaks `/admin` etc.) | `DELETE env APAP_LOCAL_BACKEND` + `PATCH env APAP_INSFORGE_URL=https://c3uc9dk6.eu-central.insforge.app`, redeploy `apap-web`. The data path returns to the hosted InsForge proxy. |
| F3 fails (tests are flaky) | Delete `tests/integration/test_local_backend_deployed.py`; downstream operators get M0's in-process tests until the next slice retriggers |

## RDD binding (per `documentation-alan-style` §17)

This slice is F1 → F2 → F3 chained, three burned RDD lineages. The first lineage opens AFTER the SDD artifacts land on `main` (so the SDD is in scope) and BEFORE the F1 Dockerfile is committed (so the F1 commit is in scope). Each subsequent lineage opens AFTER the previous feature gates are green and BEFORE the next feature's commit. The killing of the receipt capture by the user closes each lineage and unblocks the next feature. The slice ends with F3's lineage burned and the new feature in place.
