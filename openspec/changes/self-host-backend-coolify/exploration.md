# Exploration: self-host-backend-coolify

Estado del repositorio al momento de la propuesta (2026-08-31).

## Lo que existe hoy

### Cliente LocalBackend (`app/core/local_backend.py`)

El proyecto tiene un único cliente HTTP — `app.core.local_backend.LocalBackendClient` — que consume la API REST de LocalBackend. La superficie que usa:

- `POST /api/database/advance/rawsql` — SQL arbitrario. El método `execute_sql(query, params)` envía el query y parsea el envelope `{"rows": [...], "rowCount": N, "fields": [...]}`.
- `GET/POST /api/storage/buckets[/...]` — buckets S3-compatible para las fotos (`apap-photos`).
- `POST /api/auth/oauth/google` + `/callback` — el flow de Google OAuth. PKCE en el cliente.
- `POST /api/auth/oauth/exchange?client_type=web` — intercambio de code por session cookie.

El constructor toma `base_url` y `service_key`. La service key es la autenticación bearer para operaciones privilegiadas. El cliente es **stateless** — un objeto por request, instanciado en cada llamada.

### Login (`app/core/auth_flow.py` + `app/core/adapters/local-backend/oauth_local_backend_adapter.py`)

El único flow de login es **Google OAuth via LocalBackend**:

1. Frontend → `GET /auth/google` → backend genera PKCE → llama `LocalBackendClient.start_google_oauth(redirect_uri, code_challenge)` que hace `POST /api/auth/oauth/google?code_challenge=...`.
2. LocalBackend redirige al usuario a Google. Google redirige a `LocalBackendClient.exchange_google_oauth_code(code)` que hace `POST /api/auth/oauth/google/callback`.
3. LocalBackend devuelve una session cookie firmada.
4. El backend la pasa al frontend.

**No hay flujo email/password**. La tabla `usuarios_autorizados` solo tiene `id, email, rol, anadido_por, activo, fecha_alta` — sin columna password.

### Tabla `usuarios_autorizados` (auth)

Schema actual (`app/core/adapters/local-backend/auth_local_backend_queries.py`):

```sql
CREATE TABLE IF NOT EXISTS usuarios_autorizados (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    rol TEXT NOT NULL,
    anadido_por UUID,
    activo BOOLEAN NOT NULL DEFAULT true,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now()
)
```

Sin `password_hash`, sin `email_verified_at`, sin `failed_attempts`. Un atacante con acceso a la DB ve los emails en claro.

### Storage de fotos (LocalBackend)

El bucket `apap-photos` se crea en el bootstrap vía `LocalBackendClient.ensure_bucket(name, is_public=False)`. El upload es `POST /api/storage/buckets/{bucket}/upload-strategy` (devuelve URL pre-firmada) seguido de `PUT` directo a S3. El download es `GET /api/storage/download-strategy?path=...&expiresIn=...` (devuelve URL temporal) seguido de `GET` desde el cliente. **El cliente hace la subida/bajada directamente a S3**, no a través del API de LocalBackend.

El test unit `test_storage_methods.py` (29 átomos) cubre el flujo completo con `httpx.MockTransport`.

### Coolify ya en el sistema

`docker ps` muestra:

```
coolify:           8000/tcp, 8443/tcp, 9000/tcp, 0.0.0.0:8000->8080/tcp, [::]:8000->8080/tcp
coolify-db:         5432/tcp       # postgres:16-alpine, password Q7N9nLQh5vS4hE2Ue8PzYkLmXoA3fR6b
coolify-redis:      6379/tcp
coolify-realtime:   0.0.0.0:6001-6002->6001-6002/tcp, [::]:6001-6002->6001-6002/tcp
coolify-sentinel:   
coolify-proxy:      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp, 0.0.0.0:8080->8080/tcp, ...
```

Coolify es el panel de gestión. `coolify-db` es la Postgres que reutilizaremos. `coolify-proxy` ya provee TLS termination y routing — el operador solo configura el dominio en el panel.

### `verify-fallback-ready` gate

`migration/cli_verify_fallback_ready.py` corre 3 checks en modo `--ci-only`:

1. `tests/migration/test_round_trip.py` — round-trip forward+reverse. ✅ Pasa contra FakeLocalBackend.
2. `docs/audits/pii-live-migration-2026-Q3.md` verdict — parsea el doc. ✅ "Verdict PASS".
3. `apply --direction web-to-legacy --check-only` — dry-run del camino inverso contra el backend. **❌ Falla** porque la app `c3uc9dk6.eu-central.local_backend.app` devuelve 503 "No backend services available".

El primer y segundo checks pasan siempre (mientras el código no rompa). El tercero es el que necesita el backend provisionado.

## Lo que NO existe

- Imagen Docker del backend APAP_WEB
- `Dockerfile` o `docker-compose.yml` en el repo
- `coolify.yaml` o metadata de provisioning
- Flujo de login email/password
- Servicio de email (SMTP, SES, Mailgun, etc.)
- Variable de entorno `SMTP_*` o similar
- Adapter de storage S3-compatible distinto de LocalBackend
- Tests E2E del login clásico

## Decisiones de la propuesta (resumen)

| ID | Decisión | Justificación |
|---|---|---|
| D-SELF-01 | API nueva en FastAPI en el mismo proceso de la app | Reduce superficie operacional |
| D-SELF-02 | Mantener `LocalBackendClient` como Port backend-agnostic | Hexagonal architecture (§31) |
| D-SELF-03 | Postgres de Coolify (`coolify-db`) como destino | Ya provisionado |
| D-SELF-04 | MinIO local (no servicio externo) | Self-hosted completo |
| D-SELF-05 | Magic link con log de tokens (operador los entrega manualmente) | Cero infra nueva |
| D-SELF-06 | argon2id (no bcrypt) | Más moderno, mejor resistencia |
| D-SELF-07 | OAuth de Google se queda | No aporta valor quitarlo |
| D-SELF-08 | El API nuevo vive en `app/core/local_backend/` con FastAPI router | Mismo proceso, distinto módulo |
| D-SELF-09 | Las fotos legacy se migran en una épica posterior | Esta verifica con datos sintéticos |

## Consecuencias operacionales

### Variables de entorno

**Eliminar** (cuando se usa `APAP_LOCAL_BACKEND=true`):
- `APAP_INSFORGE_URL`
- `APAP_INSFORGE_SERVICE_KEY`
- `APAP_INSFORGE_ANON_KEY`

**Añadir**:
- `APAP_LOCAL_BACKEND=true` (default false; si false, comportamiento actual)
- `APAP_LOCAL_DB_URL=postgresql://user:pass@coolify-db:5432/apap_web` (Django-style URL para SQLAlchemy/asyncpg)
- `APAP_S3_ENDPOINT_URL=http://coolify-minio:9000` (MinIO internal URL)
- `APAP_S3_ACCESS_KEY=<operator-provided>`
- `APAP_S3_SECRET_KEY=<operator-provided>`
- `APAP_S3_BUCKET=apap-photos` (default)

**Mantener** (sin cambios):
- `APAP_SESSION_SECRET` (se usa para firmar session cookies)
- `APAP_GOOGLE_CLIENT_ID` y `APAP_GOOGLE_CLIENT_SECRET` (OAuth de Google sigue funcionando)

### Cambios al schema

| Tabla | Cambio |
|---|---|
| `usuarios_autorizados` | Añadir `password_hash TEXT` (nullable) y `email_verified_at TIMESTAMPTZ` (nullable) |
| `magic_link_tokens` | Nueva tabla: `token TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()` |
| (8 tablas de dominio + 5 catálogos + tabla shadow) | Sin cambios (mismo schema) |

### Cambios al código

| Archivo | Cambio |
|---|---|
| `app/core/local_backend.py` | Modificar `LocalBackendClient.__init__` para aceptar `base_url` configurable (sin cambios al comportamiento HTTP). Si `APAP_LOCAL_BACKEND=true`, `base_url = APAP_LOCAL_DB_URL`; si no, el actual. |
| `app/core/local_backend/__init__.py` | Nuevo: API FastAPI en el mismo proceso |
| `app/core/local_backend/api.py` | Nuevo: router con los 3 endpoints que `LocalBackendClient` consume |
| `app/core/local_backend/db.py` | Nuevo: psycopg2 wrapper que satisface el Protocol `SqlExecutor` |
| `app/core/local_backend/storage.py` | Nuevo: boto3 wrapper para MinIO |
| `app/core/local_backend/auth_classic.py` | Nuevo: implementación de `AuthUsersPort` con password + magic link |
| `app/core/local_backend/magic_link.py` | Nuevo: implementación de `MagicLinkPort` con log de tokens |
| `app/core/ports/storage_port.py` | Nuevo: Protocol para storage S3-compatible |
| `app/core/ports/magic_link_port.py` | Nuevo: Protocol para magic links |
| `app/core/ports/auth_classic_port.py` | Nuevo: Protocol para autenticación clásica |
| `app/core/adapters/storage/s3_storage_adapter.py` | Nuevo: adapter que implementa el Protocol `StoragePort` con boto3 |
| `app/core/adapters/auth_local/classic_password_auth_port.py` | Nuevo: adapter que implementa `AuthUsersPort` con password |
| `app/core/adapters/auth_local/magic_link_port.py` | Nuevo: adapter que implementa `MagicLinkPort` |
| `app/core/di/local_backend_di.py` | Nuevo: wiring de los nuevos adapters |
| `app/main.py` | Añadir el FastAPI router local_backend si `APAP_LOCAL_BACKEND=true` |
| `Dockerfile` | Nuevo: multi-stage con `uv pip install` y runtime slim |
| `docker-compose.yml` | Nuevo: app+postgres+minio para dev local |
| `coolify.yaml` | Nuevo: metadata para provisionar el servicio en producción |
| `docs/runbooks/self-host-backend.md` | Nuevo: cómo deployar, resetear passwords, rotar session secret, ver magic links activos |
| `tests/test_local_backend.py` | Nuevo: smoke tests del nuevo API |
| `tests/test_classic_password_auth.py` | Nuevo: tests del nuevo login |
| `tests/test_magic_link.py` | Nuevo: tests del flow de magic link |
| `tests/test_e2e_self_host.py` | Nuevo: smoke E2E del stack self-hosted completo |

**Estimación de tamaño**: ~1500-2000 líneas de código + tests + docs. Por eso va por openspec (regla §17).

## Diagrama de secuencia (M0: round-trip end-to-end)

```
operador   navegador        APAP_WEB app         local backend API      Postgres      MinIO
   │           │                    │                      │                │            │
   │  GET /animales/123  ────────►   │                      │                │            │
   │           │                    │  require_authorized_user                │            │
   │           │                    │  (lee session cookie)                  │            │
   │           │                    │                      │                │            │
   │           │                    │  SELECT * FROM animales ────────────────► │            │
   │           │                    │  WHERE id=$1          ◄────────────────  │            │
   │           │                    │                      │                │            │
   │           │  GET /animales/123/foto  ──────►           │                │            │
   │           │                    │  ensure_bucket("apap-photos")          │            │
   │           │                    │  get_download_strategy(...)────────────►│            │
   │           │                    │  ◄── (presigned URL) ──────────────────  │            │
   │           │  GET <presigned-url> ────────────────────────────────────────────────────► │
   │           │  ◄── (image bytes) ────────────────────────────────────────────────────  │
   │           │                    │                      │                │            │
```

## Diagrama de secuencia (M1: login clásico con magic link)

```
operador   navegador        APAP_WEB app         local backend API      Postgres
   │           │                    │                      │                │
   │  POST /api/auth/forgot-password  ──►                  │                │
   │     body: {email}                │                    │                │
   │           │                    │  INSERT INTO magic_link_tokens  ────►  │
   │           │                    │  (token, email, expires_at)         │
   │           │                    │  ◄── (ok) ──────────────────────    │
   │           │                    │                      │                │
   │           │                    │  log: "magic_link_generated"  ─────►  │
   │           │                    │  {email, token, expires_at}           │
   │           │                    │                      │                │
   │  ◄── 200 OK {ok: true}         │                      │                │
   │           │                    │                      │                │
   │  ── El operador ve el token en el log ──             │                │
   │  ── Le pasa el link al usuario por WhatsApp ──────  │                │
   │           │                    │                      │                │
   │  GET /api/auth/magic?token=abc  ──►                │                │
   │           │                    │  SELECT FROM magic_link_tokens  ──►  │
   │           │                    │  ◄── (token, email) ────────────    │
   │           │                    │  UPDATE used_at = now()          ──►  │
   │           │                    │                      │                │
   │           │                    │  SELECT FROM usuarios_autorizados ──►  │
   │           │                    │  ◄── (user, password_hash) ─────    │
   │           │                    │                      │                │
   │           │                    │  verify password (argon2id)          │
   │           │                    │  update session cookie              │
   │           │                    │  ◄── (set-cookie: session=...)      │
   │  ◄── 302 /                     │                      │                │
   │           │                    │                      │                │
```

## Diagrama de secuencia (M2: round-trip con datos reales del .accdb)

```
operador   APAP_WEB app         local backend API      Postgres
   │             │                      │                │
   │  ./apap-migrate apply --table animal       │                │
   │  --legacy-path local-access/backend/...   │                │
   │             │  load_legacy_snapshot_batched  │                │
   │             │  ── mdb-export ──►  │                │
   │             │  (lee 1363 filas del .accdb)      │                │
   │             │                      │                │
   │             │  INSERT INTO animales (x1363) ────►                │
   │             │                      │                │
   │  ◄── ApplyResult(applied=1363,  │                │
   │              errors=[])         │                │
   │             │                      │                │
```

## Stack tecnológico final

| Capa | Componente | Imagen / Versión |
|---|---|---|
| Web app | Python + FastAPI | `python:3.11-slim` |
| DB | PostgreSQL | `postgres:16-alpine` (Coolify `coolify-db`) |
| Storage S3 | MinIO | `minio/minio:latest` (imagen oficial) |
| Reverse proxy | Coolify proxy | `traefik:v3.0` (ya en Coolify) |
| TLS | Let's Encrypt | via Coolify proxy automático |
| Hash passwords | argon2id | `argon2-cffi` 23.x |
| OAuth | Google | sin cambios (usa LocalBackend OAuth o local OAuth si se quiere eliminar) |
| Migración legacy | mdbtools | `mdbtools 1.0.0` (ya instalado) |
| Tests | pytest | `pytest 9.1.0` |

## Riesgos detallados y mitigaciones

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| 1 | `LocalBackendClient` no es 100% compatible con el nuevo API | Media | Alto | El Port hexagonal permite ajustar el shape en `local_backend/api.py` sin tocar la app. Tests E2E del round-trip validan. |
| 2 | El operador no sabe cómo provisionar Coolify | Baja | Alto | Runbook paso a paso. El verify-fallback-ready gate detecta problemas. |
| 3 | argon2id tiene un costo de CPU inesperado | Baja | Bajo | El login no es hot path. Aceptable. |
| 4 | La migración del schema falla silenciosamente | Baja | Alto | CI tiene integration test que falla loudly. |
| 5 | El operador pierde el `.accdb` legacy | Baja | Medio | Está en `local-access/`, separado del backend. |
| 6 | Sesiones existentes se invalidan | Alta | Bajo | Usuarios tienen que re-loguearse. Aceptable. |
| 7 | DNS no apunta al nuevo deployment | Media | Medio | Coolify-proxy ya maneja esto. Documentado en runbook. |
| 8 | El .env no se actualiza | Media | Alto | Pull request incluye la actualización del .env.example. |
| 9 | MinIO requiere configuración manual del bucket | Alta | Bajo | El bootstrap crea el bucket idempotentemente. |
| 10 | argon2-cffi no está disponible en la imagen Docker | Baja | Alto | La imagen base `python:3.11-slim` tiene `pip`; instalamos en el stage de build. |

## Estimación de effort

| Fase | Effort | Riesgo |
|---|---|---|
| M0 — Backend self-hosted viable | 4-5 días | Bajo |
| M1 — Login clásico con magic link | 2-3 días | Bajo |
| M2 — Coolify + producción | 2-3 días | Medio |
| **Total** | **8-11 días** | |

## Comentarios finales

Esta propuesta saca una dependencia operacional crítica (LocalBackend gestionado) y la trae a nuestro control (Coolify self-hosted). El proyecto gana:

- Confiabilidad operacional (no dependemos de un SaaS cuyo provisioning requiere login interactivo)
- Seguridad (login clásico con magic link; sin dependencia única de Google)
- Costo predecible (Coolify VPS ya pagado; cero costo marginal)
- Control completo (backups, logs, configuración, scaling)
- Compliance (PII no sale de nuestro stack)

El cambio respeta la hexagonal architecture del proyecto: el dominio y la lógica de negocio no se enteran del swap. Solo cambia un flag de configuración (`APAP_LOCAL_BACKEND=true`) y la URL del `LocalBackendClient`. El verify-fallback-ready gate queda green al final — eso es la prueba operacional de que el backend está bien provisionado.
