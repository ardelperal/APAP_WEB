# Proposal: self-host-insforge-backend-coolify

## Context

The `InsForge` hosted proxy at `https://c3uc9dk6.eu-central.insforge.app` has been returning `503: 'No backend services available for app: c3uc9dk6'` since at least 2026-09-05. Every database query the deployed `apap-web` app makes — `/admin`, `/animales`, `/voluntarios`, every dashboard counter — comes back as `HTTP 500` because the upstream `InsForgeError` propagates to the route handlers. The MCP server itself refuses to initialize against this backend (`Failed to fetch backend version: Health check failed with status 503`).

The M0 self-host-backend-rdd slice (archived `2026-09-03-m0-self-host-backend-rdd`) built `app/core/local_backend/` with the full InsForge-compatible surface (rawsql / healthz / storage / oauth stubs) but only as a **test-time subprocess** — never as a persistent Coolify service. This slice stands M0 up as a real Coolify service and re-points the production app at it.

The only thing left for production after this slice is real Google OAuth (M0's stub returns a synthetic `local-user`) and a real SMTP relay (already wired via Resend in commit `26ed6ad`). Both are non-blocking for the operator's primary flow.

## Why a fresh slice

| Reason | |
|---|---|
| **M0 is archived and complete** — no code changes to `app/core/local_backend/*` | keeps the diff to Coolify service config + env-var wiring |
| **Six production failures today are all `503 → InsForgeError`** in the data layer | one fix point (route the data layer to a healthy backend) |
| **The Causal Chain test gate** (`InsForgeClient` URL switch) already exists from M0 | this slice exercises it end-to-end against a real deployed service, not a fixture |
| **Operator wants this NOW** — they've been blocked since 2026-09-05 morning; the slice should ship in a small bounded window | three features, each ≤400 lines, each one merges an independent capability |
| **No new business logic, no new schema, no new auth model** | this is a deployment / wiring slice, not a product slice |

## Causal authority and rollback

- **Invariant**: `app/core/local_backend/app.py::create_app()` produces a `FastAPI` app whose routes implement the same HTTP contract M0 already verifies against 15 acceptance scenarios. The application-side `InsForgeClient` does NOT change — only `APAP_LOCAL_BACKEND=true` + `APAP_INSFORGE_URL=http://apap-local-backend:8080/api` on the Coolify env config.
- **Rollback**: flip the env vars back (`APAP_LOCAL_BACKEND=false` or remove, `APAP_INSFORGE_URL=https://c3uc9dk6...`). Redeploy. The local service can keep running idle (it serves nothing else) or be stopped.
- **Independent invariants**: this slice is independent of M3 (magic-link flow) and M3.1 (e2e test) — both already merged and green. M3 depends on this slice going forward (without it, the /admin and /animales routes 500); M3.1 E2E was running against the working InsForge proxy on `2026-09-04` and is unaffected by the outage.
- **What the slice does NOT touch**: `app/core/local_backend/{db,healthz,oauth_google,rawsql,storage,app}.py` — these already cover the spec. `app/core/insforge.py` (the existing `APAP_LOCAL_BACKEND` URL switch) — already implemented. `app/core/insforge_url.py` — already implemented. The only files this slice touches are the deployment manifests, env var config, and integration tests against the deployed service.

## Slice shape: three features, ≤400 lines each

| Feature | What it lands | Lines forecast |
|---|---|---|
| F1. **Deploy local-backend as Coolify service** | Dockerfile that runs `uvicorn app.core.local_backend.app:create_app(...)` on a port; Coolify resource manifest; service-to-service DNS between `apap-web` and `apap-local-backend` | ~150 |
| F2. **Flip the prod app to the local backend** | Update Coolify env vars on `apap-web`; one-time magic-link token table seed via `APAP_LOCAL_DB_URL`; smoke-test all 8 dashboard cards return real data | ~80 |
| F3. **Integration tests against the deployed service** | `tests/integration/test_local_backend_deployed.py` covering healthz + rawsql + a magic-link flow that hits the live service; one-shot curl smoke-test script in `scripts/smoke_local_backend.sh` | ~200 |

Total ~430 LOC, well under the 700-line single-file budget. Each feature fits the 400-line PR budget.

## Decisions

1. **Three-feature chain, not single PR** — the F1 service deploy and F2 env-var flip are independent capabilities; each one is independently reviewable and revertable; combining them would produce a 400-line PR with three concerns.
2. **Reuse M0's `app/core/local_backend/*` as-is** — it already passes 15 acceptance scenarios against the existing test fixtures (per M0's own gate). Adding Docker/Coolify plumbing without touching the local-backend code is the only safe way to ship this without re-validating 15 test atoms.
3. **Local backend serves a single Coolify service** — no HA, no clustering, no backup. M0's lifespan is in-process, in-memory buckets, and a single Postgres connection pool. Scaling out is out of scope; the operator's `apap-pg-test` Postgres already backs the magic-link token table today, so it just gets one more schema set applied to it.
4. **Bootstrap Postgres schema at local-backend startup** — call `ensure_schema_and_seed(client, settings)` inside `create_app()`'s lifespan so the local service applies the 27-statement DDL on every cold start. Idempotent (`CREATE TABLE IF NOT EXISTS`).
5. **OAuth stays stubbed** — M0 returns synthetic `local-user` and a stub JWT. The current `apap-web` InsForge oauth adapter has been swapped off this path (the deployed app uses magic-link); the stub serves any future test that exercises the OAuth code paths without requiring interactive Google consent.
6. **No M3.1 e2e regression** — the e2e test stays green against `https://apap.romancaba.com/login`. The `E2E_BASE_URL` and `APAP_E2E_STUB_AUTH` env vars don't change. The cookie trust chain still works.
7. **Health-check contract from F1 stays exactly as M0 spec'd** — `{"db": "up"|"down", "storage": "up", "oauth": "configured"|"missing"}`. No new fields. The cooldown `apap-web` already polls `/healthz`; we add a 30-second curl poll in the CI script to fail fast if the service isn't healthy after deploy.

## What this slice does NOT do

- Real Google OAuth consent (requires interactive flow; M0's stub covers integration tests)
- Real SMTP / Resend wiring (already wired in commit `26ed6ad`)
- Real MinIO / S3 storage (M0's in-memory bucket registry covers our 1-bucket use case)
- Postgres HA / read replicas / backup (operator's `apap-pg-test` is a single-instance dev DB; production-grade HA is a separate ops slice, out of SDD scope)
- Production-grade metrics / tracing / alerting (Coolify's built-in container logs are enough for now)
- Migrations during deploy (the local backend applies schema on startup; we do not run a separate migration step in Coolify)
- DNS subdomains or HTTPS for `apap-local-backend` (Coolify service-to-service networking is HTTP, internal; external calls hit `apap.romancaba.com` only)
- Switching away from `apap.romancaba.com` magic link entirely — that wire stays; only the data backend changes

## Operator flow this slice proves

- **O1.** Operator opens Coolify, sees a new `apap-local-backend` service alongside the existing `apap-web`, `apap-pg-test`, `apap-smtp-dev` services.
- **O2.** Operator visits `https://apap.romancaba.com/admin` while logged in via the magic-link cookie: the user-management table renders (was 500 before this slice).
- **O3.** Operator visits `https://apap.romancaba.com/animales`: the animals list renders; counters (Pendientes de entrada, etc.) populate from the local Postgres.
- **O4.** `curl http://apap-local-backend:8080/healthz` returns `{"db": "up", "storage": "up", "oauth": "missing"}`. Local backend is reachable from app.
- **O5.** `curl -X POST http://apap-local-backend:8080/api/database/advance/rawsql -d '{"query": "SELECT 1"}' -H "Content-Type: application/json"` returns `{"rows": [{"?column?": 1}], "rowCount": 1}`.
- **O6.** Negative control — `curl -X POST http://apap-local-backend:8080/api/database/advance/rawsql -d '{"query": "DROP TABLE usuarios_autorizados; --"}'` returns HTTP 400 with `unsafe_sql_identifier`.

## Resolved operator decisions (this slice)

The five open questions have been resolved by the operator:

1. **Container name**: `apap-local-backend` (M0 vocabulary preserved).
2. **Port**: `8080` (matches `app/core/local_backend/app.py::create_app`). Internal only; no `80/443` exposure.
3. **Postgres backend**: reuse existing `apap-pg-test` — single DB, single schema source of truth, single backup window. The 27-table DDL coexists with the existing `magic_link_tokens` table.
4. **Schema bootstrap strategy**: lifespan reapplies the 27-statement DDL on each startup (idempotent, ~10 ms). A separate "migrations-as-deployment-step" is deferred to a future M5 slice. For day-1 we ship the lifespan bootstrap as the only deployment entry-point.
5. **Service-to-service URL**: `APAP_INSFORGE_URL=http://apap-local-backend:8080/api` is set via env var on `apap-web`. The same env var lets the operator switch back to the hosted InsForge proxy if needed (`APAP_INSFORGE_URL=https://c3uc9dk6...`).
