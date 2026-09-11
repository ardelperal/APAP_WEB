# Spec: M0 — Self-host backend viable

This is the M0 milestone of `self-host-backend-coolify`. The deliverable
is a backend running in the project repo (Postgres + FastAPI local
backend + MinIO via Docker) that the `LocalBackendClient` can talk to via
`APAP_LOCAL_BACKEND=true`. The apply path is unchanged: only the URL
base changes when the operator flips the flag.

## Requirement: `LocalBackendClient` is backend-agnostic

The `LocalBackendClient` constructor already accepts a `base_url` parameter
(the URL of the LocalBackend REST API). When `APAP_LOCAL_BACKEND=true` is
set and the existing `APAP_INSFORGE_URL` env var is empty, the
constructor MUST default `base_url` to the local backend URL
(`http://localhost:8000/api`).

#### Scenario: local backend selected

- GIVEN `APAP_LOCAL_BACKEND=true` is set
- AND `APAP_INSFORGE_URL` is empty
- WHEN `LocalBackendClient(base_url="", service_key="...")` is constructed
- THEN `self._client.base_url` equals `http://localhost:8000/api`

#### Scenario: remote LocalBackend still works

- GIVEN `APAP_LOCAL_BACKEND` is unset or false
- AND `APAP_INSFORGE_URL=https://c3uc9dk6.eu-central.local_backend.app` is set
- WHEN the same construction runs
- THEN `self._client.base_url` equals the configured LocalBackend URL

## Requirement: Local backend exposes the three LocalBackend endpoints

The local backend MUST expose the same three HTTP endpoints that
`LocalBackendClient` consumes, with byte-compatible response shapes.

### `/api/database/advance/rawsql` (POST)

- Accepts JSON body `{"query": str, "params": list} | {"query": str}`
- Executes against Postgres via `psycopg2`
- Returns `{"rows": [...], "rowCount": int}` on success
- On Postgres error, returns `{"error": "...", "pgcode": "...", "pgerror": "..."}`
  with the corresponding HTTP status (400 for syntax, 500 for runtime)
- The endpoint MUST be synchronous and use a connection pool

#### Scenario: SELECT round-trip

- GIVEN the `animales` table has 3 rows
- WHEN `POST /api/database/advance/rawsql` with body
  `{"query": "SELECT id, nombreanimal FROM animales WHERE activo = true"}`
- THEN the response is `{"rows": [...], "rowCount": 3}`
- AND each row is a dict with keys `id` and `nombreanimal`

#### Scenario: INSERT with RETURNING

- GIVEN the `animales` table exists
- WHEN `POST /api/database/advance/rawsql` with body
  `{"query": "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) VALUES ($1, $2, $3, $4, $5) RETURNING id", "params": ["CHIP-FIX-001", "Test", "CANINA", "H", "2020-01-01"]}`
- THEN the response is `{"rows": [{"id": "..."}], "rowCount": 1}`

#### Scenario: ERROR raises HTTP 500

- GIVEN a query that violates a CHECK constraint
- WHEN the request is made
- THEN the response is HTTP 500 with body
  `{"error": "...", "pgcode": "23514", "pgerror": "..."}`

### `/api/storage/buckets` (GET, POST) and `/api/storage/buckets/{name}` (GET)

- `GET /api/storage/buckets` returns `[{name, isPublic, files}, ...]`
- `GET /api/storage/buckets/{name}` returns the bucket dict or 404
- `POST /api/storage/buckets/{name}` with body `{"isPublic": false}`
  creates the bucket and returns the dict
- The `isPublic` parameter is ignored for the private bucket policy
  (the bucket is always private — privacy default-deny, regla §6)

#### Scenario: list buckets

- GIVEN the `apap-photos` bucket exists
- WHEN `GET /api/storage/buckets`
- THEN the response includes `apap-photos` with `isPublic: false`

#### Scenario: create bucket

- GIVEN the `apap-photos` bucket does not exist
- WHEN `POST /api/storage/buckets/apap-photos` with body `{"isPublic": true}`
- THEN the response is `{"name": "apap-photos", "isPublic": false, "files": 0}`
  (the `isPublic: true` is overridden to `false`)

### `/healthz` (GET)

- Returns `{"db": "up"|"down", "storage": "up"|"down", "oauth": "configured"|"unconfigured"}`
- Returns HTTP 200 even if a dependency is down (for debugging)
- The check is non-blocking and uses a 1-second timeout per check

## Requirement: Postgres schema is provisioned idempotently

The schema migration MUST run on every cold start and be idempotent
(same pattern as `apply_sql_migrations` for LocalBackend).

### Scenario: fresh DB

- GIVEN a fresh Postgres with no schema
- WHEN the app starts
- THEN all 13 tables (8 domain + 5 catalogos + users + shadow) are created
- AND the bootstrap admin is seeded if `APAP_INITIAL_ADMIN_EMAIL` is set

### Scenario: existing DB

- GIVEN the schema already exists
- WHEN the app starts
- THEN the migration is a no-op (all `CREATE TABLE IF NOT EXISTS`)
- AND no errors are raised

## Requirement: MinIO bucket is created on bootstrap

- On app startup, the bucket MUST be created via the MinIO client if it
  does not exist
- The bucket is always created with block-listing enabled (privacy
  default-deny); never public
- Creation is idempotent — if the bucket exists, no error is raised
- The storage layer returns a fail-closed placeholder (1×1 PNG) when
  `APAP_S3_BUCKET` is not set or MinIO is unreachable

## Requirement: docker-compose runs the full stack locally

- `docker-compose up` starts app + db + minio
- The app connects to the local DB via `LocalPostgresExecutor` and to
  MinIO via the `Minio` Python client
- The verify-fallback-ready gate is green when running against this
  stack (3/3 CI checks pass)

### Scenario: full stack boot

- GIVEN the operator runs:
  ```
  cp env.example .env
  # fill in APAP_SESSION_SECRET, APAP_INITIAL_ADMIN_EMAIL, APAP_DB_PASSWORD
  # fill in APAP_S3_ACCESS_KEY, APAP_S3_SECRET_KEY, APAP_S3_BUCKET
  docker compose up --build
  ```
- WHEN all three services are healthy
- THEN `curl http://localhost:8001/healthz` returns
  `{"db": "up", "storage": "up", "oauth": "configured"}`
- AND `curl http://localhost:8001/api/storage/buckets` returns the bucket list

## Out of scope (M0)

- Login email/password (M1)
- Magic link generation (M1)
- Password reset (M1)
- Coolify provisioning (M2)
- Migrating real legacy data (separate epic, post-M2)
- Document storage (Feature 04, Fase 7)

## Acceptance

- [x] `Dockerfile` builds and produces a ~250MB image
- [x] `docker-compose up` boots app+db+minio
- [ ] `LocalBackendClient(base_url="", service_key=...)` with
      `APAP_LOCAL_BACKEND=true` defaults to `http://localhost:8000/api`
- [ ] `POST /api/database/advance/rawsql` with `SELECT 1` returns
      `{"rows": [{"?column?": 1}], "rowCount": 1}`
- [x] `GET /api/storage/buckets` returns the real bucket list from MinIO
- [x] `GET /healthz` returns `{"db": "up", "storage": "up", "oauth": "configured"}`
- [ ] The schema migration is idempotent (re-running on a populated DB
      is a no-op)
- [x] `verify-fallback-ready --ci-only` returns exit 0 when the local
      stack is running (2/3 CI checks pass; msaccess preflight is PENDING)
