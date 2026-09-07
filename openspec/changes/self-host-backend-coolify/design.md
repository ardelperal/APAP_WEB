# Design: self-host-backend-coolify (revised)

The user approved the **app FastAPI independiente** approach in the session
prior to this one. This design revises the earlier draft to match.

## M0 — Self-host backend viable

### 0.1 Architecture: a separate FastAPI app

The local backend is a **separate FastAPI app** — not a router mounted
on `app.main`. The reasons:

- The `app.main` lifespan provisions the schema against LocalBackend (or
  against the local DB when `APAP_LOCAL_BACKEND=true`). The local
  backend app has its own lifespan that constructs the
  `LocalPostgresExecutor` from `APAP_LOCAL_DB_URL`.
- The `LocalBackendClient` already speaks HTTP. It points at the local
  backend via the existing `APAP_INSFORGE_URL` (or the default
  `http://localhost:8000/api` set by `APAP_LOCAL_BACKEND=true`).
- Tests can stand up the local app in-process via
  `httpx.AsyncClient(ASGITransport=app)` which executes the lifespan
  correctly (uvicorn's thread-based runner in tests does not run
  the lifespan reliably — a previous in-session attempt at uvicorn
  threads failed with `SystemExit: 3`).
- M2 (Coolify + production) becomes "deploy this app alongside the
  main app behind coolify-proxy". No mixing of lifespans.

### 0.2 Module layout

```
app/core/local_backend/
├── __init__.py
├── app.py             # FastAPI app factory, lifespan, router mount
├── db.py              # LocalPostgresExecutor (psycopg wrapper, SqlExecutor Protocol)
├── rawsql.py          # POST /api/database/advance/rawsql handler
├── storage.py         # GET/POST /api/storage/buckets[/...] handler
├── healthz.py         # GET /healthz handler
├── oauth_google.py    # POST /api/auth/oauth/google[+callback] handler
└── tests/
    ├── __init__.py
    ├── test_app.py          # ASGITransport tests
    ├── test_rawsql.py
    ├── test_storage.py
    └── test_oauth.py
```

The handlers are split into modules so the file-size budget (AGENTS.md
rule 21) holds. The router in `app.py` mounts each one at its
documented path.

### 0.3 The `LocalPostgresExecutor` (psycopg wrapper)

The `LocalBackendClient` calls `execute_sql(query, params)`. The
Protocol is `app.core.data_access.SqlExecutor`. The local executor
satisfies the same Protocol:

```python
class LocalPostgresExecutor:
    def __init__(self, dsn: str, search_path: str | None = None) -> None:
        self._dsn = dsn
        self._search_path = search_path

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._dsn)
        if self._search_path:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self._search_path}"')
            conn.commit()
        return conn

    def execute(
        self, query: str, params: list | tuple | None = None
    ) -> list[dict[str, Any]]:
        # Rewrite ``$N`` to ``%s`` because psycopg3 ClientCursor counts
        # ``%s`` placeholders, not ``$N`` (the integration conftest does
        # the same).
        if "$" in query:
            import re
            query = re.sub(r"\$(\d+)", r"%s", query)
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                cur.execute(query, params or [])
            except psycopg.Error as exc:
                conn.rollback()
                if getattr(exc, "pgcode", None) is not None:
                    raise QueryError(str(exc)) from exc
                raise DatabaseError(str(exc)) from exc
            try:
                rows = list(cur.fetchall())
            except psycopg.ProgrammingError:
                # INSERT/UPDATE/DELETE return no rows
                rows = []
            conn.commit()
            if rows and not isinstance(rows[0], dict):
                columns = [col[0] for col in cur.description]
                rows = [dict(zip(columns, row)) for row in rows]
            return rows
```

The error model: `QueryError` (4xx, query-level) vs `DatabaseError`
(5xx, connection-level) matches the FastAPI handler's mapping (4xx vs
5xx). The `LocalPostgresExecutor` does **not** know about HTTP — that
is the handler's job.

### 0.4 The FastAPI app and lifespan

```python
# app/core/local_backend/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.local_backend.rawsql import router as rawsql_router
from app.core.local_backend.storage import router as storage_router
from app.core.local_backend.healthz import router as healthz_router
from app.core.local_backend.oauth_google import router as oauth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.environ.get("APAP_LOCAL_DB_URL")
    if not dsn:
        # M0: the local backend requires a DSN. M2 (production) will
        # refuse to start with a missing DSN at the Coolify-proxy
        # level.
        raise RuntimeError("APAP_LOCAL_DB_URL is not set")
    search_path = os.environ.get("APAP_LOCAL_DB_SCHEMA")  # optional
    app.state.local_postgres_executor = LocalPostgresExecutor(
        dsn, search_path=search_path
    )
    try:
        yield
    finally:
        # The current implementation builds a fresh connection per
        # execute() call (no pool in M0). The hook is here for M2 when
        # a real connection pool arrives.
        pass


def create_app() -> FastAPI:
    """App factory for the local backend.

    A factory (not a module-level instance) keeps the tests hermetic
    and lets the lifespan be properly initialised by the test
    client (ASGITransport). Module-level instances skip the lifespan
    in some test setups; factories do not.
    """
    app = FastAPI(
        title="APAP_WEB local backend (M0)",
        lifespan=lifespan,
    )
    app.include_router(rawsql_router, prefix="/api")
    app.include_router(storage_router, prefix="/api")
    app.include_router(healthz_router)
    app.include_router(oauth_router, prefix="/api")
    return app
```

### 0.5 Endpoint shapes (pinned to what `LocalBackendClient` consumes)

The `LocalBackendClient` has been audited for the exact shapes it
consumes. Each handler matches.

#### 0.5.1 `GET /healthz`

`app/core/local_backend.py` does not call `/healthz` directly; the
integration test setup calls it to confirm the app is alive.

Returns:
```json
{"db": "up", "storage": "up", "oauth": "configured"}
```

#### 0.5.2 `POST /api/database/advance/rawsql`

Consumed by `LocalBackendClient.execute_sql`. Body:
```json
{"query": "SELECT ...", "params": ["a", 1]}
```

Returns:
```json
{"rows": [{"col_a": ..., "col_b": ...}, ...], "rowCount": N}
```

The `rows` is the list of dicts (or `[]` for INSERT/UPDATE/DELETE
without RETURNING). The `rowCount` is the number of rows returned
(or affected for non-SELECT). HTTP status:

- 200 OK on success
- 400 Bad Request on query-level error (syntax, FK violation)
- 500 Internal Server Error on connection-level error
  (DSN bad, connection refused)

#### 0.5.3 `GET /api/storage/buckets`

Consumed by `LocalBackendClient.get_bucket` (which iterates the list
and picks the one matching `name`). Returns:
```json
[{"bucketName": "apap-photos", "isPublic": false, "files": 0}, ...]
```

The list shape matches LocalBackend's actual API. M0 returns a
hard-coded `apap-photos` bucket with `isPublic=false, files=0`; M2
will use MinIO's `list_buckets` instead.

#### 0.5.4 `POST /api/storage/buckets/{name}`

`ensure_bucket(name, is_public=False)` calls this. Body:
```json
{"isPublic": false}
```

Returns the bucket shape:
```json
{"bucketName": "apap-photos", "isPublic": false, "files": 0}
```

For M0: always creates the bucket and returns its shape. (LocalBackend
treats 200 and 201 as success; M0 always returns 200 for
simplicity — `ensure_bucket` does not depend on the status code.)

#### 0.5.5 OAuth flow

Two endpoints:

- `POST /api/auth/oauth/google?code_challenge=...&redirect_uri=...`
  → `{"authUrl": "https://accounts.google.com/..."}`

- `POST /api/auth/oauth/google/callback` with `{"code": "...",
  "code_verifier": "...", "redirect_uri": "..."}`
  → `{"token": "<session_jwt>", "user": {"id": "...", "email": "..."}}`

For M0 the OAuth flow is a **stub**: it returns a deterministic
session JWT and a hard-coded user (e.g. `id="local-user", email="local@apap"`).
The real Google OAuth provider is not contacted — that would be M3.
The stub lets the rest of the app (Google login flow in
`app/core/auth_flow.py`) exercise the path end-to-end.

A `POST /api/auth/oauth/exchange?client_type=web` endpoint is also
required by the LocalBackendClient's `exchange_local_backend_oauth_code` flow.
The stub accepts an `oauth_code` (returned by the stub
`/callback`) and returns the same JWT.

### 0.6 Test strategy

The integration test uses `httpx.AsyncClient(ASGITransport=app)`:

```python
# tests/integration/test_local_backend.py
import httpx
import pytest
from app.core.local_backend.app import create_app


@pytest.fixture
def local_backend_url() -> str:
    os.environ["APAP_LOCAL_DB_URL"] = "postgresql://..."
    # The factory initialises the lifespan (which builds the executor).
    app = create_app()
    with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_rawsql_select_roundtrip(local_backend_url):
    # Insert a row through the local API, query it back.
    r = await local_backend_url.post(
        "/api/database/advance/rawsql",
        json={
            "query": "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
                     "VALUES ($1, $2, 'CANINA', 'H', '2020-01-01')",
            "params": ["CHIP-LB-001", "Test"],
        },
    )
    assert r.status_code == 200
    r = await local_backend_url.post(
        "/api/database/advance/rawsql",
        json={
            "query": "SELECT nchip, nombreanimal FROM animales WHERE nchip = $1",
            "params": ["CHIP-LB-001"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rowCount"] == 1
    assert body["rows"][0]["nchip"] == "CHIP-LB-001"
    assert body["rows"][0]["nombreanimal"] == "Test"
```

`ASGITransport` runs the lifespan correctly (unlike uvicorn's thread
runner). The schema is the integration conftest's ephemeral
schema (via `APAP_LOCAL_DB_URL` configured with the right
`?options=-c search_path=...` — but the simpler approach for M0
is to use the conftest's ephemeral schema directly).

Actually, the simpler approach: **use the integration conftest's
`self_host_schema` fixture directly** in the test, pass the schema
name to the executor via `APAP_LOCAL_DB_SCHEMA`. The executor sets
`search_path` after each connect. This is what the previous
`LocalPostgresExecutor` design supports.

```python
@pytest.fixture
def local_backend_url(self_host_schema):
    os.environ["APAP_LOCAL_DB_URL"] = os.environ["APAP_TEST_POSTGRES_DSN"]
    os.environ["APAP_LOCAL_DB_SCHEMA"] = self_host_schema.schema
    app = create_app()
    with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
```

### 0.7 Decision matrix (why these choices)

| Choice | Picked | Why |
|---|---|---|
| App FastAPI independent | YES (per user) | Clean separation; uvicorn in tests is brittle; lifespan runs correctly in `ASGITransport` |
| `httpx.ASGITransport` for tests | YES | `uvicorn.Server` thread does not run lifespan reliably; `ASGITransport` does |
| `LocalPostgresExecutor` class | YES | Matches `SqlExecutor` Protocol; the existing `LocalBackendClient` can target it via the same `execute_sql` interface |
| `LocalPostgresExecutor` lives in `app/core/local_backend/` | YES | The local backend is its own module; the executor is a private detail of that module |
| Schema routing via `search_path` env var | YES | The integration conftest already provisions schemas by name; reusing the env var means the test can use the conftest's schema without a re-provision |
| File split (`rawsql.py`, `storage.py`, etc.) | YES | AGENTS.md rule 21 (700-line budget) |
| OAuth as a stub for M0 | YES | M0 is "self-host viable", not "self-host production OAuth". M3 is real OAuth. |
| Storage as hard-coded `apap-photos` | YES for M0 | M2 replaces with MinIO; the shape stays the same. |
| Real `psycopg2` or `psycopg` | `psycopg` (v3) | The project already uses `psycopg[binary]`. The local executor is a thin wrapper, no migration needed. |

### 0.8 Files added (M0)

```
app/core/local_backend/__init__.py
app/core/local_backend/app.py
app/core/local_backend/db.py
app/core/local_backend/healthz.py
app/core/local_backend/rawsql.py
app/core/local_backend/storage.py
app/core/local_backend/oauth_google.py
tests/integration/test_local_backend.py
```

### 0.9 Files NOT touched (M0)

- `app/main.py` — no change (the LocalBackendClient modification from the
  previous session is already in; no further modification needed because
  the local backend runs as a separate app)
- `app/core/local_backend.py` — no change
- `app/core/data_access.py` — no change (the Protocol is unchanged;
  `LocalPostgresExecutor` is an implementation of it)
- `migration/cli_verify_fallback_ready.py` — no change (the gate
  already works against the existing tests)

### 0.10 Migration to M2 (Coolify + production)

M0 is local dev + tests. M2 adds:
- `Dockerfile` + `docker-compose.yml` for the local backend
- `coolify.yaml` metadata
- A real MinIO deployment (replacing the hard-coded `apap-photos` stub)
- A real Google OAuth provider (replacing the OAuth stub)
- DNS + reverse proxy for production routing

That is M2. It is not in the M0 scope.
