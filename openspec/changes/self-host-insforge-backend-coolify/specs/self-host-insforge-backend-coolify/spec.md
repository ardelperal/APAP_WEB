# Capability Spec — Self-hosted InsForge-compatible backend (Coolify slice)

## Intent

Replace the external `https://c3uc9dk6.eu-central.insforge.app` dependency with a Coolify-resident local backend that exposes the same HTTP contract as InsForge. The deployed `apap-web` app routes its data queries through this new service instead. The application-side `InsForgeClient` does not change — only its base URL.

This makes the production app survivable when the hosted InsForge proxy returns `503: 'No backend services available for app: c3uc9dk6'` (current state since 2026-09-05).

The code is already there: `app/core/local_backend/{db,rawsql,healthz,storage,oauth_google,app}.py` was built and verified in the M0 self-host-backend-rdd slice (`openspec/changes/archive/2026-09-03-m0-self-host-backend-rdd/`). That slice proved the local backend works as a test-time subprocess against 15 acceptance scenarios. This slice stands it up as a long-running Coolify service.

## Scope

This slice covers:
1. **F1.** Deploy the existing `app/core/local_backend/app.py::create_app` as a Coolify service called `apap-local-backend`, reachable over HTTP at `http://apap-local-backend:8080/api` from sibling containers.
2. **F2.** Set Coolify env vars on `apap-web` (`APAP_LOCAL_BACKEND=true`, `APAP_INSFORGE_URL=http://apap-local-backend:8080/api`) so the deployed app routes through the local service.
3. **F3.** Tests against the deployed service: healthz probe, rawsql INSERT/SELECT round-trip, one full magic-link flow that produces an `apap_session` cookie with the local service in the request loop.

## Requirements

### R1. F1 — `apap-local-backend` Coolify service is up and healthy

A new Coolify resource named `apap-local-backend` MUST run `uvicorn app.core.local_backend.app:create_app(...)` on `0.0.0.0:8080`. The service MUST respond to `GET /healthz` with HTTP 200 and the documented envelope `{"db": "up"|"down", "storage": "up", "oauth": "configured"|"missing"}`. No public port (`80/443`) MUST be opened; only service-to-service traffic inside Coolify's docker network is allowed.

#### Scenario: F1.AS1 — Healthz returns 200 and the documented envelope
- GIVEN the `apap-local-backend` Coolify resource is running
- WHEN `curl http://apap-local-backend:8080/healthz` runs from any sibling container (e.g. `apap-web`)
- THEN the response status is `200` and the body parses as JSON with `body["db"] in {"up", "down"}`, `body["storage"] == "up"`, and `body["oauth"] in {"configured", "missing"}`

#### Scenario: F1.AS2 — Healthz reflects Postgres connectivity
- GIVEN the lifespan of `apap-local-backend` opened a Postgres pool against `postgresql://postgres:postgres@apap-pg-test:5432/postgres`
- WHEN the operator pauses the `apap-pg-test` container
- THEN `curl http://apap-local-backend:8080/healthz` returns HTTP 200 with body `{"db": "down", "storage": "up", "oauth": "missing"}`

### R2. F1 — Lifespan applies the 27-statement DDL on startup

The `apap-local-backend` lifespan MUST call `ensure_schema_and_seed(client, settings)` (the same call `apap-web`'s production lifespan makes today) so the local Postgres ends up with all 27 domain tables (`animales`, `voluntarios`, `entradas`, `adopciones`, etc.) plus the bootstrap admin row.

The bootstrap MUST be idempotent — repeated startups MUST NOT fail with "table already exists". The pre-existing `magic_link_tokens` table (created by the migration system) MUST coexist; the local backend MUST NOT delete it.

#### Scenario: F2.AS1 — Cold start applies schema
- GIVEN `apap-pg-test` has an empty `public` schema
- AND the `apap-local-backend` Coolify resource is set to start
- WHEN the container starts up
- THEN within 30 seconds `docker exec apap-pg-test psql -c "\dt"` lists 28 tables (`magic_link_tokens` + 27 from the DDL)
- AND a row exists in `usuarios_autorizados` with `rol='developer'` (seeded admin from `APAP_INITIAL_ADMIN_EMAIL`)

#### Scenario: F2.AS2 — Repeat start is idempotent
- GIVEN the `apap-local-backend` Coolify resource was previously started
- AND the schema is fully applied
- WHEN the operator restarts the container
- THEN the lifespan completes in < 5 seconds with no errors
- AND `\dt` still lists the same 28 tables (no duplicates, no losses)

### R3. F1 — Rawsql endpoint accepts INSERT/SELECT and rejects unsafe inputs

The `apap-local-backend` MUST keep all the M0 guarantees: safe-identifier regex per dotted segment, single-statement enforcement, INSERT/UPDATE returning `{"rows": [], "rowCount": N}`, SELECT returning rows as `[dict]`.

The endpoint MUST be reachable from sibling containers at `http://apap-local-backend:8080/api/database/advance/rawsql`.

#### Scenario: F3.AS1 — INSERT then SELECT round-trip
- GIVEN the local backend is up and `animales` table is empty
- WHEN the operator runs `curl -X POST http://apap-local-backend:8080/api/database/advance/rawsql -H 'Content-Type: application/json' -d '{"query":"INSERT INTO animales (nombre) VALUES ($1)", "params":["Firulais"]}'`
- THEN the response is `{"rows": [], "rowCount": 1}`
- AND `curl ... '{"query":"SELECT nombre FROM animales LIMIT 1"}'` returns `{"rows": [{"nombre": "Firulais"}], "rowCount": 1}`

#### Scenario: F3.AS2 — Unsafe identifier is rejected
- WHEN the operator runs the negative control `curl -X POST .../rawsql -d '{"query":"DROP TABLE usuarios_autorizados; --"}'`
- THEN the response is HTTP 400 with `{"error": "unsafe_sql_identifier"}`
- AND `usuarios_autorizados` STILL EXISTS in Postgres

### R4. F2 — `apap-web` Coolify env vars flip to the local backend

The `apap-web` Coolify resource MUST have `APAP_LOCAL_BACKEND=true` and `APAP_INSFORGE_URL=http://apap-local-backend:8080/api` set. The `InsForgeClient` reads these at construction time (M0's `app/core/insforge_url.py:resolve_insforge_url`) and routes every `execute_sql` to the local service.

The flip MUST NOT change the application's external surface: `https://apap.romancaba.com/login` is still served by the same nginx / Cloudflare / Coolify edge to the same `apap-web` Coolify resource.

#### Scenario: F4.AS1 — Magic-link start hits the local backend
- GIVEN the env vars above are set on `apap-web`
- AND the operator is not logged in
- WHEN the operator submits the magic-link form at `https://apap.romancaba.com/login`
- THEN the `apap-web` lifespan's `_capture_state()` factory is called
- AND inside `factory()` it calls the local backend's `POST /api/database/advance/rawsql` (via `InsForgeClient.execute_sql`) to look up the user
- AND the local backend returns the seeded admin row
- AND the email is sent via Resend SMTP (no change to the SMTP flow)

#### Scenario: F4.AS2 — `/admin` no longer 500s
- GIVEN the operator is logged in via the magic-link cookie
- WHEN they navigate to `https://apap.romancaba.com/admin`
- THEN `/admin` returns HTTP 200 with the user-management table populated from `usuarios_autorizados` rows in the local Postgres
- (was HTTP 500 with `InsForgeError: 503` before this slice)

#### Scenario: F4.AS3 — `/animales` and `/voluntarios` work
- GIVEN the operator is logged in
- WHEN they navigate to `/animales` and `/voluntarios`
- THEN both return HTTP 200 (no 503 from InsForge)
- AND the dashboard counter cards (`Animales`, `Voluntarios`) populate from the local Postgres queries

### R5. F2 — `usuarios_autorizados` is seeded from `APAP_INITIAL_ADMIN_EMAIL`

The `apap-local-backend` lifespan MUST read `APAP_INITIAL_ADMIN_EMAIL` from the environment and seed `usuarios_autorizados(email, rol='developer', activo=true)` if no `developer` row already exists. This is the same `ensure_schema_and_seed(client, settings)` call that `apap-web`'s production lifespan makes today.

#### Scenario: F5.AS1 — Cold start seeds the operator's admin
- GIVEN `APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com` is set on `apap-local-backend`
- AND no admin row exists yet
- WHEN the container starts
- THEN `SELECT email, rol FROM usuarios_autorizados WHERE rol='developer'` returns one row with `email='ardelperal@gmail.com'`

### R6. F3 — Integration tests against the deployed service

`tests/integration/test_local_backend_deployed.py` MUST cover the wired service in production:

- `F6.AS1` — `GET http://apap-local-backend:8080/healthz` from a sibling container returns HTTP 200 with `body["db"] == "up"`.
- `F6.AS2` — `POST .../rawsql` with `INSERT` returns `{"rowCount": 1}`; a follow-up `SELECT` returns the row.
- `F6.AS3` — End-to-end magic link: `apap-web` POST `/auth/magic/start` → email in MailDev (or Resend) → `GET /auth/magic/verify?token=...` → 302 to `/` with `apap_session` cookie set.
- `F6.AS4` — Negative control: `rawsql` with `DROP TABLE` returns HTTP 400.

These tests MUST pass in CI (the `ci-e2e-deployed` job, separate from the in-process `tests/integration/test_local_backend.py` which uses fixtures).

### R7. F3 — One-shot curl smoke-test script

`scripts/smoke_local_backend.sh` MUST be callable as `bash scripts/smoke_local_backend.sh` and exit `0` only when all of the following succeed against the locally-running Coolify resources:

- `GET http://apap-local-backend:8080/healthz` returns `db=up`
- `POST .../rawsql` with `SELECT 1` returns 200 with `rowCount=1`
- `POST .../auth/magic/start` (against `apap-web`) returns `200 {"status": "queued"}` for `ardelperal@gmail.com`

The script MUST be callable from the VPS without extra setup (it reads `APAP_INSFORGE_URL` from the env if set, defaulting to `http://apap-local-backend:8080/api`).

## Out-of-scope (explicit)

- **Real Google OAuth**. M0 returns a synthetic JWT. The deployed app uses magic links exclusively; no production flow exercises the OAuth endpoint. Refining this is a separate slice (M6 or later).
- **Real MinIO / S3 storage**. M0 returns an in-memory bucket. The 1-bucket use case (`apap-photos`) is fine.
- **Real SMTP / Resend wiring**. Already complete in commit `26ed6ad`.
- **Postgres HA / read replicas / backup**. Out of SDD scope.
- **External-facing DNS / HTTPS for the local backend**. Internal-only. Operators can reach `/healthz` via `docker exec` if they need to debug.
- **Migrations as a separate deployment step**. The lifespan bootstrap is idempotent and adequate for day-1. A future M5 slice will add Alembic-style migrations if the operator wants it.
- **Reverting `apap-web` to the hosted InsForge proxy**. Trivial (toggle `APAP_LOCAL_BACKEND=false`); not a slice.

## Acceptance scenarios index

| ID | Component | What it proves |
|---|---|---|
| F1.AS1 | F1 | Healthz returns 200 + envelope |
| F1.AS2 | F1 | Healthz reflects Postgres connectivity |
| F2.AS1 | F1 | Cold start applies schema |
| F2.AS2 | F1 | Repeat start is idempotent |
| F3.AS1 | F1 | INSERT/SELECT round-trip works |
| F3.AS2 | F1 | DROP TABLE is rejected |
| F4.AS1 | F2 | Magic-link start hits the local backend |
| F4.AS2 | F2 | `/admin` no longer 500s |
| F4.AS3 | F2 | `/animales` and `/voluntarios` work |
| F5.AS1 | F2 | Admin seed from `APAP_INITIAL_ADMIN_EMAIL` |
| F6.AS1 | F3 | Healthz from a sibling container |
| F6.AS2 | F3 | INSERT/SELECT via the deployed service |
| F6.AS3 | F3 | End-to-end magic link works end-to-end |
| F6.AS4 | F3 | Negative control: unsafe SQL rejected |

13 scenarios across 3 features, each pinned as a unit / integration / e2e test before the gate that wraps the feature burns.

## Causal chain

```
env: APAP_LOCAL_BACKEND=true
env: APAP_INSFORGE_URL=http://apap-local-backend:8080/api
  → app/core/insforge_url.py:resolve_insforge_url() returns the local URL
    → InsForgeClient initialized against the local URL
      → postgres_adapter.execute_sql() calls InsForgeClient.execute_sql(...)
        → HTTP POST to /api/database/advance/rawsql on apap-local-backend
          → LocalPostgresExecutor.execute()
            → psycopg against postgresql://postgres:postgres@apap-pg-test:5432/postgres
              → row returned
                → app JSON-returned to InsForgeClient
                  → JSON-returned to apap-web route
                    → template rendered
```

This is the data path that breaks today. This slice makes the chain reach a `200 OK` end-to-end against a backend the operator controls.
