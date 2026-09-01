# Design: self-host-backend-coolify

Decisiones técnicas detalladas para reemplazar InsForge con un backend self-hosted en Coolify.

## M0 — Backend self-hosted

### 0.1 Imagen Docker (`Dockerfile`)

Multi-stage build:

```dockerfile
# ---- Builder ----
FROM python:3.11-slim AS builder

# System dependencies for pyodbc, argon2-cffi, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager, ya en pyproject.toml)
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy only what's needed for dependency resolution (cache-friendly)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy source and install
COPY app/ ./app/
COPY migration/ ./migration/
RUN uv sync --frozen --no-dev

# ---- Runtime ----
FROM python:3.11-slim

# Runtime system dependencies (smaller set)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    unixodbc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python env from builder
COPY --from=builder /app /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Non-root user
RUN useradd -m -u 1000 apap
USER apap

EXPOSE 8000

# Healthcheck para Coolify
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers"]
```

**Decisiones**:
- `python:3.11-slim` (la imagen base de Coolify ya corre 3.11).
- `uv` para instalar dependencias (más rápido que pip, ya en el proyecto).
- `--workers 4` — para 50-100 voluntarios, 4 workers son suficientes. Ajustable vía env var.
- `--proxy-headers` — Coolify-proxy agrega X-Forwarded-* headers; la app los respeta.
- Multi-stage: imagen final ~250MB (vs ~800MB si install todo en runtime).

### 0.2 docker-compose.yml (dev local)

```yaml
version: "3.9"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      APAP_LOCAL_BACKEND: "true"
      APAP_LOCAL_DB_URL: "postgresql://apap:apap@db:5432/apap"
      APAP_S3_ENDPOINT_URL: "http://minio:9000"
      APAP_S3_ACCESS_KEY: "minioadmin"
      APAP_S3_SECRET_KEY: "minioadmin"
      APAP_S3_BUCKET: "apap-photos"
      APAP_S3_REGION: "us-east-1"  # MinIO ignores this but boto3 requires it
      APAP_SESSION_SECRET: "${APAP_SESSION_SECRET:-change-me-in-prod-this-is-a-development-only-fallback-32-chars}"
      APAP_GOOGLE_CLIENT_ID: "${APAP_GOOGLE_CLIENT_ID:-}"
      APAP_GOOGLE_CLIENT_SECRET: "${APAP_GOOGLE_CLIENT_SECRET:-}"
      APAP_INSFORGE_URL: ""  # empty when local backend
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: apap
      POSTGRES_PASSWORD: apap
      POSTGRES_DB: apap
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U apap"]
      interval: 5s
      retries: 5

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - miniodata:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      retries: 5

volumes:
  pgdata:
  miniodata:
```

**Decisiones**:
- MinIO `console-address :9001` expone la consola de administración en otro puerto.
- `depends_on: condition: service_healthy` — la app espera a que Postgres y MinIO estén listos.
- Volúmenes nombrados para que los datos persistan entre `docker-compose up`.
- `APAP_INSFORGE_URL=""` cuando local — el cliente InsForge se salta si la URL está vacía.

### 0.3 Módulo `app/core/local_backend/`

```
app/core/local_backend/
├── __init__.py
├── api.py            # FastAPI router con los 3 endpoints InsForge-equivalentes
├── db.py             # psycopg2 wrapper que satisface SqlExecutor
├── storage.py        # boto3 client para MinIO
├── auth_classic.py   # login email/password con magic link
├── magic_link.py     # generación + verificación de tokens
└── health.py         # /healthz endpoint
```

#### 0.3.1 `db.py` — psycopg2 wrapper

Implementa el Protocol `SqlExecutor` (`app/core/data_access.py`):

```python
class Psycopg2Executor:
    """psycopg2 wrapper that satisfies the SqlExecutor Protocol.
    
    The connection pool is shared via SQLAlchemy's QueuePool for
    concurrent requests. The same connection string format Django
    uses is accepted (postgresql://user:pass@host:port/dbname).
    """
    
    def __init__(self, db_url: str) -> None:
        from sqlalchemy import create_engine
        self._engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
        )
    
    def execute_sql(self, query, params=None):
        from psycopg2.extras import RealDictCursor
        with self._engine.connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params or [])
                if cur.description is None:
                    return []
                return [dict(r) for r in cur.fetchall()]
```

`RealDictCursor` retorna filas como `dict` con nombres de columna, igual que `InsForgeClient`. **La app no se entera del swap.**

#### 0.3.2 `storage.py` — boto3 MinIO

```python
class S3StorageAdapter:
    """boto3 client adapter for S3-compatible storage (MinIO in dev)."""
    
    def __init__(self, endpoint_url, access_key, secret_key, bucket, region="us-east-1"):
        import boto3
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
    
    def get_bucket(self, name):
        try:
            self._client.head_bucket(Bucket=name)
            return {"name": name, "isPublic": False, "files": 0}  # simplified
        except ClientError:
            return None
    
    def ensure_bucket(self, name, *, is_public=False):
        try:
            self._client.head_bucket(Bucket=name)
        except ClientError:
            self._client.create_bucket(Bucket=name)
        # Set private ACL regardless of is_public (privacy default-deny)
        return {"name": name, "isPublic": False, "files": 0}
    
    def get_download_strategy(self, bucket, key):
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=300
        )
    
    def get_upload_strategy(self, bucket, key):
        return self._client.generate_presigned_post(
            Bucket=bucket, Key=key, ExpiresIn=300
        )
    
    def delete_object(self, bucket, key):
        self._client.delete_object(Bucket=bucket, Key=key)
```

El shape de retorno (`get_bucket`, `ensure_bucket`) matchea exactamente el de `InsForgeClient` para que la app no note el swap.

#### 0.3.3 `api.py` — FastAPI router

Tres endpoints que replican los de InsForge:

```python
from fastapi import APIRouter, HTTPException, Request, Response
from app.core.local_backend.db import Psycopg2Executor
from app.core.local_backend.storage import S3StorageAdapter
from app.core.local_backend.auth_classic import ClassicAuthAdapter
from app.core.local_backend.magic_link import MagicLinkAdapter

router = APIRouter()

# Inicialización lazy (los adapters se construyen con lifespan)
@router.on_event("startup")
async def startup_event():
    from app.core.config import get_settings
    settings = get_settings()
    global db, storage, classic_auth, magic_link
    db = Psycopg2Executor(settings.apap_local_db_url)
    storage = S3StorageAdapter(...)
    classic_auth = ClassicAuthAdapter(db)
    magic_link = MagicLinkAdapter(db)

# Healthcheck
@router.get("/healthz")
async def healthz():
    db_ok = await db.ping() if hasattr(db, "ping") else True
    storage_ok = storage.get_bucket(settings.apap_s3_bucket) is not None
    return {"db": "up" if db_ok else "down", "storage": "up" if storage_ok else "down"}

# /api/database/advance/rawsql — replica del InsForge
@router.post("/api/database/advance/rawsql")
async def execute_sql(request: Request):
    body = await request.json()
    query = body.get("query", "")
    params = body.get("params", [])
    if not query:
        raise HTTPException(400, "query is required")
    try:
        rows = db.execute_sql(query, params)
    except psycopg2.Error as e:
        raise HTTPException(500, f"database error: {e.pgcode} {e.pgerror}")
    return {"rows": rows, "rowCount": len(rows)}

# /api/storage/buckets (GET, POST) — replica del InsForge
@router.get("/api/storage/buckets")
async def list_buckets():
    return [b for b in storage.list_buckets()]

@router.get("/api/storage/buckets/{bucket_name}")
async def get_bucket(bucket_name):
    bucket = storage.get_bucket(bucket_name)
    if bucket is None:
        raise HTTPException(404, "bucket not found")
    return bucket

@router.post("/api/storage/buckets/{bucket_name}")
async def ensure_bucket(bucket_name, is_public: bool = False):
    return storage.ensure_bucket(bucket_name, is_public=is_public)

# /api/auth/oauth/google, /callback — sigue funcionando idéntico
@router.post("/api/auth/oauth/google")
async def start_google_oauth(request: Request):
    body = await request.json()
    # ... reuse oauth_insforge_adapter logic, just with local DB for session
    
@router.post("/api/auth/oauth/google/callback")
async def exchange_google_oauth_code(request: Request):
    # ...
    
# /api/auth/login (nuevo, classic password)
@router.post("/api/auth/login")
async def login(request: Request, response: Response):
    body = await request.json()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    user = classic_auth.verify_password(email, password)
    if user is None:
        raise HTTPException(401, "invalid credentials")
    set_session_cookie(response, user)
    return {"ok": True}

# /api/auth/forgot-password, /api/auth/magic, /api/auth/reset-password
@router.post("/api/auth/forgot-password")
async def forgot_password(request: Request):
    body = await request.json()
    email = body.get("email", "").strip().lower()
    token = magic_link.create_token(email, ttl_minutes=30)
    log_safe("magic_link_generated", email=email, token=token, expires_at=...)
    return {"ok": True}  # always ok to prevent email enumeration

@router.get("/api/auth/magic")
async def magic_login(token: str, response: Response):
    user = magic_link.consume_token(token)
    if user is None:
        raise HTTPException(401, "invalid or expired token")
    set_session_cookie(response, user)
    return {"ok": True}

@router.post("/api/auth/reset-password")
async def reset_password(request: Request):
    body = await request.json()
    token = body.get("token", "")
    new_password = body.get("password", "")
    if not magic_link.is_valid_for_reset(token):
        raise HTTPException(401, "invalid or expired token")
    classic_auth.set_password(email_from_token(token), new_password)
    return {"ok": True}
```

### 0.4 `app/main.py` integración

```python
# Existing
if settings.apap_local_backend:
    # Mount the local backend router at the same /api/* prefix
    from app.core.local_backend.api import router as local_backend_router
    app.include_router(local_backend_router)
```

Y en `InsForgeClient.__init__`:

```python
def __init__(self, base_url, service_key, ...):
    if not base_url and settings.apap_local_backend:
        # Use the local API by default
        base_url = "http://localhost:8000/api"
    self._client = httpx.Client(base_url=base_url, ...)
```

## M1 — Login clásico con magic link

### 1.1 Schema migration

```sql
-- 0050_add_password_hash.sql
ALTER TABLE usuarios_autorizados
    ADD COLUMN password_hash TEXT;

ALTER TABLE usuarios_autorizados
    ADD COLUMN email_verified_at TIMESTAMPTZ;

ALTER TABLE usuarios_autorizados
    ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;

-- 0051_create_magic_link_tokens.sql
CREATE TABLE IF NOT EXISTS magic_link_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS magic_link_tokens_email_idx
    ON magic_link_tokens (email);
```

### 1.2 Adapter `classic_password_auth_port.py`

```python
import argon2

class ClassicPasswordAuthPort:
    """Classic email/password authentication with argon2id hashing."""
    
    def __init__(self, db: Psycopg2Executor):
        self._db = db
        self._hasher = argon2.PasswordHasher(
            time_cost=3,        # ~100ms per hash on modern hardware
            memory_cost=65536,  # 64MB
            parallelism=4,
        )
    
    def verify_password(self, email: str, password: str) -> Optional[AuthorizedUser]:
        row = self._db.execute_sql(
            "SELECT id, email, password_hash, rol, activo FROM usuarios_autorizados WHERE email = %s",
            [email]
        )
        if not row:
            return None
        user = row[0]
        if not user["password_hash"] or not user["activo"]:
            return None
        try:
            self._hasher.verify(user["password_hash"], password)
        except argon2.exceptions.VerifyMismatchError:
            return None
        return AuthorizedUser.from_row(user)
    
    def set_password(self, email: str, password: str) -> None:
        password_hash = self._hasher.hash(password)
        self._db.execute_sql(
            "UPDATE usuarios_autorizados SET password_hash = %s WHERE email = %s",
            [password_hash, email]
        )
```

### 1.3 Adapter `magic_link_port.py`

```python
import secrets
import hashlib
from datetime import datetime, timedelta, UTC

class MagicLinkPort:
    """One-time tokens for passwordless login / password reset."""
    
    def __init__(self, db: Psycopg2Executor, ttl_minutes: int = 30):
        self._db = db
        self._ttl = timedelta(minutes=ttl_minutes)
    
    def create_token(self, email: str, *, purpose: str = "login") -> str:
        # Token = 32 random bytes hex-encoded. We store a SHA-256 hash
        # in the DB so a DB leak doesn't expose live tokens.
        raw_token = secrets.token_hex(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + self._ttl
        self._db.execute_sql(
            "INSERT INTO magic_link_tokens (token, email, expires_at) VALUES (%s, %s, %s)",
            [token_hash, email, expires_at]
        )
        return raw_token
    
    def consume_token(self, raw_token: str) -> Optional[str]:
        """Return the email if the token is valid; mark as used."""
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        rows = self._db.execute_sql(
            "SELECT email, expires_at, used_at FROM magic_link_tokens WHERE token = %s",
            [token_hash]
        )
        if not rows:
            return None
        row = rows[0]
        if row["used_at"]:
            return None  # already used
        if row["expires_at"] < datetime.now(UTC):
            return None  # expired
        self._db.execute_sql(
            "UPDATE magic_link_tokens SET used_at = %s WHERE token = %s",
            [datetime.now(UTC), token_hash]
        )
        return row["email"]
    
    def list_active(self) -> list[dict]:
        """For admin panel: list active (not used, not expired) tokens."""
        return self._db.execute_sql(
            "SELECT email, expires_at, created_at FROM magic_link_tokens "
            "WHERE used_at IS NULL AND expires_at > %s ORDER BY created_at DESC",
            [datetime.now(UTC)]
        )
```

### 1.4 Test del login clásico

```python
# tests/test_classic_password_auth.py
def test_verify_password_returns_user_when_correct():
    auth = ClassicPasswordAuthPort(...)
    auth.set_password("ana@test.com", "secret123")
    user = auth.verify_password("ana@test.com", "secret123")
    assert user is not None
    assert user.email == "ana@test.com"

def test_verify_password_returns_none_when_wrong():
    auth = ClassicPasswordAuthPort(...)
    auth.set_password("ana@test.com", "secret123")
    user = auth.verify_password("ana@test.com", "wrong")
    assert user is None
```

## M2 — Coolify + producción

### 2.1 `coolify.yaml`

```yaml
# Coolify application metadata — consumed by coolify-cli provision
name: apap-web
description: APAP_WEB — animal shelter management self-hosted backend
type: python
version: "1.0.0"

build:
  dockerfile: Dockerfile
  context: .
  args:
    - APAP_LOCAL_BACKEND=true

env:
  APAP_LOCAL_BACKEND: "true"
  APAP_LOCAL_DB_URL: "postgresql://apap:${APAP_DB_PASSWORD}@coolify-db:5432/apap"
  APAP_S3_ENDPOINT_URL: "http://coolify-minio:9000"
  APAP_S3_ACCESS_KEY: "${APAP_S3_ACCESS_KEY}"
  APAP_S3_SECRET_KEY: "${APAP_S3_SECRET_KEY}"
  APAP_S3_BUCKET: "apap-photos"
  APAP_S3_REGION: "us-east-1"
  APAP_SESSION_SECRET: "${APAP_SESSION_SECRET}"
  APAP_GOOGLE_CLIENT_ID: "${APAP_GOOGLE_CLIENT_ID}"
  APAP_GOOGLE_CLIENT_SECRET: "${APAP_GOOGLE_CLIENT_SECRET}"

healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s

ports:
  - "8000:8000"

depends_on:
  - coolify-db    # already deployed
  - coolify-minio  # to be deployed
```

### 2.2 Runbook: deploy

```markdown
# Deploy APAP_WEB self-hosted backend

## Prerequisites
- Coolify VPS con `coolify-db` (Postgres 16) provisionado
- MinIO provisionado via Coolify como `coolify-minio` (image: `minio/minio:latest`)
- DNS wildcard `*.apap.local` apuntando a coolify-proxy

## Steps

1. **Provision MinIO** (one-time):
   ```bash
   coolify deploy --name coolify-minio --image minio/minio:latest \
       --env MINIO_ROOT_USER=apap MINIO_ROOT_PASSWORD=$(openssl rand -hex 32) \
       --port 9000:9000
   ```

2. **Generate secrets**:
   ```bash
   openssl rand -hex 32 > /tmp/session_secret
   openssl rand -hex 32 > /tmp/s3_secret
   ```

3. **Deploy the app**:
   ```bash
   coolify deploy --name apap-web --dockerfile Dockerfile \
       --env-file .env.production \
       --depends-on coolify-db coolify-minio
   ```

4. **Bootstrap the schema** (one-time per fresh DB):
   ```bash
   coolify exec apap-web python -c "
   from app.core.schema_bootstrap import bootstrap_all
   bootstrap_all()
   "
   ```

5. **Verify**:
   ```bash
   curl https://apap.local/api/auth/healthz
   # Expected: {"db": "up", "storage": "up", "oauth": "configured"}
   ```
```

### 2.3 Runbook: reset password

```markdown
# Reset a user's password (operator procedure)

## When to use
- User forgot their password
- Account locked out after too many failed attempts (future feature)

## Steps

1. **Generate a reset token** (server-side):
   ```bash
   coolify exec apap-web python -c "
   from app.core.local_backend.magic_link import MagicLinkPort
   from app.core.local_backend.db import Psycopg2Executor
   from app.core.config import get_settings
   import sys
   settings = get_settings()
   db = Psycopg2Executor(settings.apap_local_db_url)
   port = MagicLinkPort(db)
   email = '$USER_EMAIL'
   token = port.create_token(email, purpose='password_reset')
   print(f'TOKEN={token}')
   print(f'EXPIRES_AT={(datetime.now(UTC) + timedelta(minutes=30)).isoformat()}')
   "
   ```

2. **Deliver the magic link** to the user via the trusted channel (WhatsApp, phone, in-person).

3. **User clicks the link**:
   ```
   https://apap.local/api/auth/magic?token=<TOKEN>
   ```
   This returns a session cookie. The user is now logged in.

4. **User goes to /account** and clicks "Set password" — they enter a new password which is hashed with argon2id and stored.
```

### 2.4 Runbook: view active magic links

```bash
# For operator: see all unexpired, unused magic links
coolify exec apap-web python -c "
from app.core.local_backend.magic_link import MagicLinkPort
from app.core.local_backend.db import Psycopg2Executor
from app.core.config import get_settings
db = Psycopg2Executor(settings.apap_local_db_url)
port = MagicLinkPort(db)
for t in port.list_active():
    print(f'{t[\"email\"]:<40s} {t[\"expires_at\"]}  {t[\"created_at\"]}')
"
```

## Decisiones técnicas (resumen)

| Decisión | Justificación |
|---|---|
| Multi-stage Dockerfile con `uv` | Tamaño de imagen final ~250MB, builds rápidos |
| `python:3.11-slim` (no alpine) | `pyodbc` requiere glibc; alpine necesita build-from-source que tarda 5 min extra |
| `psycopg2` (no asyncpg) | El Protocol `SqlExecutor` es sync; la app actual es sync. Asyncpsql es sobre-ingeniería. |
| `boto3` para storage | SDK estándar de AWS, habla con MinIO trivialmente via `endpoint_url` |
| `argon2id` (no bcrypt) | Más moderno, mejor resistencia a GPU |
| Magic link con SHA-256 hash del token en DB | DB leak no expone tokens activos. La DB solo ve hashes, no los raw tokens. |
| 30 min TTL para magic link | Balance entre UX y seguridad |
| `APAP_LOCAL_BACKEND=false` por default | Compatibilidad con setups existentes (InsForge remoto) |
| `/api/*` mismo prefijo que InsForge | El `InsForgeClient` no necesita saber del swap |
| Healthcheck vía `python -c` (no curl) | La imagen slim no tiene curl |
| `--proxy-headers` | Coolify-proxy agrega X-Forwarded-* que la app respeta |

## Out of scope del design (confirmado)

- SMTP real (post-M1)
- 2FA / TOTP (épica futura)
- Multi-tenant
- Rate limiting del login (se puede añadir via Coolify-proxy si es necesario)
- Audit log de sesiones (admin panel)

## Riesgos del design (específicos)

| # | Riesgo | Mitigación |
|---|---|---|
| 1 | `InsForgeClient` no es 100% compatible con el nuevo API | Test E2E del round-trip valida que sigue funcionando. Si hay incompatibilidades, se ajusta `local_backend/api.py`. |
| 2 | La app no se entera del swap (mismo JSON shape) | El test E2E legacy_postgres sigue corriendo contra el nuevo backend y verifica el shape. |
| 3 | argon2id timeout en imágenes slim | El runtime image incluye las libs nativas (`libc`); argon2-cffi las linkea. |
| 4 | MinIO no arranca con `--console-address :9001` | Documentado en runbook. Healthcheck es la otra ruta de detección. |
| 5 | Coolify-proxy no inyecta X-Forwarded-* | `--proxy-headers` en uvicorn los respeta. |
| 6 | El operator no genera `APAP_SESSION_SECRET` suficientemente fuerte | Validación en `app/main.py` (regla §32.P2) — falla startup si es <32 chars o es el placeholder. |
| 7 | La DB de Coolify se queda sin espacio | Coolify-db tiene volume `pgdata`. Cron + `pg_dump` en Coolify job. |
| 8 | MinIO se queda sin espacio | Volume `miniodata`. Lifecycle policy en Coolify. |

## Estimación de effort

| Tarea | Effort | Riesgo |
|---|---|---|
| Dockerfile + docker-compose.yml | 0.5 días | Bajo |
| `app/core/local_backend/db.py` (psycopg2) | 0.5 días | Bajo |
| `app/core/local_backend/storage.py` (boto3) | 0.5 días | Bajo |
| `app/core/local_backend/api.py` (3 endpoints InsForge-equivalentes) | 1 día | Bajo |
| `app/core/local_backend/auth_classic.py` (argon2id) | 0.5 días | Bajo |
| `app/core/local_backend/magic_link.py` | 0.5 días | Bajo |
| Schema migration SQL (0050, 0051) | 0.5 días | Bajo |
| Tests (test_local_backend, test_classic_password_auth, test_magic_link) | 1 día | Bajo |
| `InsForgeClient` apunta a la nueva API cuando `APAP_LOCAL_BACKEND=true` | 0.25 días | Bajo |
| Integración en `app/main.py` | 0.25 días | Bajo |
| Round-trip E2E actualizado | 0.5 días | Bajo |
| Runbook operador | 0.5 días | Bajo |
| `coolify.yaml` + metadata de provisioning | 0.5 días | Bajo |
| **Total** | **7 días** | |

## Conclusión

Este design implementa el backend self-hosted en Coolify respetando la hexagonal architecture del proyecto. La app no se entera del swap: `InsForgeClient` sigue siendo el cliente, solo cambia su URL. El `verify-fallback-ready` gate queda green al final. El flow de magic link self-contained elimina la dependencia de SMTP. El runbook es claro para el operador.
