# Tasks: self-host-backend-coolify

Plan de aplicación concreto para reemplazar InsForge con un backend self-hosted en Coolify.

## M0 — Backend self-hosted viable (target: 4-5 días)

### 0.1 Infra local
- [ ] **0.1.1** Crear `Dockerfile` multi-stage con `uv pip install` y runtime slim
- [ ] **0.1.2** Crear `docker-compose.yml` con app+postgres+minio
- [ ] **0.1.3** Verificar `docker-compose build` produce imagen <300MB
- [ ] **0.1.4** Verificar `docker-compose up` arranca los 3 servicios healthy

### 0.2 Módulo `app/core/local_backend/`
- [ ] **0.2.1** `app/core/local_backend/__init__.py` — entry point
- [ ] **0.2.2** `app/core/local_backend/db.py` — `Psycopg2Executor` que satisface `SqlExecutor`
- [ ] **0.2.3** `app/core/local_backend/storage.py` — `S3StorageAdapter` con boto3
- [ ] **0.2.4** `app/core/local_backend/api.py` — FastAPI router con `/healthz`,
      `/api/database/advance/rawsql`, `/api/storage/buckets[/...]`,
      `/api/auth/oauth/google[/callback]`
- [ ] **0.2.5** `app/core/local_backend/health.py` — `/healthz` endpoint

### 0.3 Integración con `InsForgeClient`
- [ ] **0.3.1** Modificar `InsForgeClient.__init__` para default a
      `http://localhost:8000/api` cuando `APAP_LOCAL_BACKEND=true`
      y `APAP_INSFORGE_URL=""` (ver issue #275 / regla §32.P2 para
      no romper setups existentes)
- [ ] **0.3.2** Añadir el router local_backend en `app/main.py` cuando
      `APAP_LOCAL_BACKEND=true`
- [ ] **0.3.3** Test E2E: `InsForgeClient(base_url="", ...)` con
      `APAP_LOCAL_BACKEND=true` apunta a localhost
- [ ] **0.3.4** Test E2E: la app real, con `APAP_LOCAL_BACKEND=true`,
      habla con el API local sin tocar código de negocio

### 0.4 Schema migration
- [ ] **0.4.1** Crear `migration/sql/0049_initial_local_backend.sql` con las 13
      tablas (8 dominio + 5 catálogos + usuarios_autorizados + shadow)
- [ ] **0.4.2** Conectar el bootstrap existente (`schema_bootstrap.py`)
      al nuevo path cuando `APAP_LOCAL_BACKEND=true`
- [ ] **0.4.3** Test: la migration es idempotente (re-ejecución no falla)

### 0.5 Verify-fallback-ready gate
- [ ] **0.5.1** El check `web_to_legacy_check_only` funciona contra el
      nuevo backend local (3/3 checks verde)
- [ ] **0.5.2** El test E2E legacy_postgres sigue funcionando
- [ ] **0.5.3** El `InsForgeClient` standalone apunta a `http://localhost:8000/api`
      en CI cuando se usa docker-compose

## M1 — Login clásico con magic link (target: 2-3 días)

### 1.1 Schema migration
- [ ] **1.1.1** `migration/sql/0050_add_password_hash.sql` — añade
      `password_hash`, `email_verified_at`, `failed_attempts` a
      `usuarios_autorizados` (idempotente)
- [ ] **1.1.2** `migration/sql/0051_create_magic_link_tokens.sql` — crea
      `magic_link_tokens` con índice
- [ ] **1.1.3** Aplicar migrations al nuevo DB local
- [ ] **1.1.4** Test: la migration es idempotente

### 1.2 Ports
- [ ] **1.2.1** `app/core/ports/auth_classic_port.py` — Protocol
      con `verify_password` y `set_password`
- [ ] **1.2.2** `app/core/ports/magic_link_port.py` — Protocol
      con `create_token`, `consume_token`, `list_active`

### 1.3 Adapters
- [ ] **1.3.1** `app/core/adapters/auth_local/classic_password_auth_port.py`
      con argon2id (`time_cost=3, memory_cost=65536, parallelism=4`)
- [ ] **1.3.2** `app/core/adapters/auth_local/magic_link_port.py` con
      SHA-256 hash de token
- [ ] **1.3.3** Adapter InsForge gana no-op default para los nuevos
      métodos (compatibilidad)

### 1.4 Endpoints
- [ ] **1.4.1** `POST /api/auth/login` — email+password → session cookie
- [ ] **1.4.2** `POST /api/auth/logout` — limpia session
- [ ] **1.4.3** `POST /api/auth/forgot-password` — genera token, lo loguea
- [ ] **1.4.4** `GET /api/auth/magic?token=...` — consume token, emite session
- [ ] **1.4.5** `POST /api/auth/reset-password` — cambia password
- [ ] **1.4.6** `GET /admin/magic-links` — admin-only, lista tokens activos

### 1.5 Tests
- [ ] **1.5.1** `tests/test_classic_password_auth.py` — happy path,
      wrong password, no password, hash timing
- [ ] **1.5.2** `tests/test_magic_link.py` — create/consume, expiry,
      one-time-use, hash-stored
- [ ] **1.5.3** `tests/test_local_backend_auth.py` — end-to-end del flow
      de login clásico

### 1.6 Compatibilidad OAuth
- [ ] **1.6.1** `oauth_insforge_adapter` no se toca (sigue funcionando)
- [ ] **1.6.2** Test: un usuario con `password_hash IS NULL` puede
      loguearse con Google pero no con clásico
- [ ] **1.6.3** Test: un usuario con password puede usar ambos flows

## M2 — Coolify + producción (target: 2-3 días)

### 2.1 Coolify provisioning
- [ ] **2.1.1** Crear `coolify.yaml` con metadata del servicio
- [ ] **2.1.2** `coolify deploy --from-file coolify.yaml` provisiona el servicio
- [ ] **2.1.3** `coolify-db` (Postgres 16) ya provisionado
- [ ] **2.1.4** Provisionar `coolify-minio` (imagen `minio/minio:latest`,
      puerto 9000)
- [ ] **2.1.5** Configurar secrets en Coolify:
      `APAP_SESSION_SECRET`, `APAP_S3_ACCESS_KEY`,
      `APAP_S3_SECRET_KEY`, `APAP_LOCAL_DB_URL`,
      `APAP_GOOGLE_CLIENT_ID`, `APAP_GOOGLE_CLIENT_SECRET`
- [ ] **2.1.6** Configurar DNS wildcard `*.apap.example.org`

### 2.2 Runbook
- [ ] **2.2.1** `docs/runbooks/self-host-backend.md` con secciones:
      provisioning, reset password, rotate secret, backup, magic link
- [ ] **2.2.2** Procedimiento de deploy paso a paso
- [ ] **2.2.3** Procedimiento de reset password (operador genera magic
      link, lo entrega al usuario)
- [ ] **2.2.4** Procedimiento de rotación de secrets
- [ ] **2.2.5** Procedimiento de backup (cron pg_dump + mc mirror)

### 2.3 Verificación
- [ ] **2.3.1** `https://apap.example.org/healthz` retorna 200
      con `{"db": "up", "storage": "up"}`
- [ ] **2.3.2** TLS activo (certificado Let's Encrypt válido)
- [ ] **2.3.3** `verify-fallback-ready --ci-only` verde desde Coolify
- [ ] **2.3.4** `apap-migrate apply --table animal --legacy-path
      /path/to/copy.accdb` funciona contra el backend de Coolify
- [ ] **2.3.5** Smoke test: un usuario real puede loguearse (Google o
      magic link), navegar /animales, ver una foto
- [ ] **2.3.6** El operador puede ver los magic links activos via
      `GET /admin/magic-links`

## Out of scope (diferido a futuras épicas)

- **SMTP real para magic link**: en M1, el operador entrega los
  magic links manualmente desde el log. SMTP real es una épica
  separada.
- **Migración del `.accdb` legacy real**: el plan E2E
  (`docs/quality/migration-e2e-plan.md`) ya cubre el forward + reverse
  con datos sintéticos. La migración de los 1363 animales del
  `.accdb` real es una épica posterior.
- **2FA / TOTP**: el campo `failed_attempts` está en el schema pero
  no se usa. Rate limiting + 2FA son épicas futuras.
- **Multi-tenant**: el schema actual asume una sola protectora.
- **Email verification enforcement**: el campo `email_verified_at` está
  en el schema pero no se enforza.
- **Auditoría de sesiones**: el operador puede ver magic links activos
  pero no hay un log de "quién hizo login cuándo". Eso es admin panel
  completo, épica futura.
- **OAuth de Apple / Facebook / GitHub**: el Protocol es
  backend-agnostic; añadir providers es solo nuevos adapters.
- **Coolify CLI version pinning**: el `coolify deploy` puede cambiar
  su output. Documentamos la versión que usamos.

## Dependencias externas (operador)

- **Coolify VPS** ya provisionado
- **Dominio** `apap.example.org` con wildcard `*.apap.example.org`
- **MinIO** provisionado en Coolify (imagen oficial)
- **Postgres 16** provisionado en Coolify
- **DNS records** apuntando al Coolify-proxy IP

## Riesgos detallados por tarea

| Tarea | Riesgo | Mitigación |
|---|---|---|
| 0.1.1 Dockerfile | Imagen demasiado grande | Multi-stage con `--no-install-recommends` y limpieza de apt cache |
| 0.2.2 db.py | Pool exhaustion bajo carga | `pool_size=10, max_overflow=5` — suficiente para 50-100 usuarios concurrentes |
| 0.2.3 storage.py | boto3 latency a MinIO | `boto3.client("s3", ...)` con `config=Config(retries={'max_attempts': 3})` |
| 0.2.4 api.py | Endpoint shape mismatch con InsForge | El test E2E legacy_postgres verifica el shape |
| 0.4 schema | Migration fails on populated DB | `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` (idempotent) |
| 1.1.1 password_hash | Argon2 no disponible en slim image | Verificar con `RUN python -c "import argon2"` en el build |
| 1.3.1 argon2 | Hash timeout en CI | `time_cost=2` en CI, `time_cost=3` en prod (configurable via env) |
| 1.5 tests | Test flakiness con magic link expiry | Usar `freezegun` o `time_machine` para el control de tiempo |
| 2.1.5 secrets | Operador los guarda en .env en vez de Coolify | El runbook es claro: `coolify secrets set` |
| 2.2.1 runbook | Out of date cuando el sistema cambia | El runbook incluye un header "Last reviewed" con date |

## Plan de aplicación (orden de ejecución)

1. **M0.1** (Dockerfile) → foundation de infra
2. **M0.2** (módulo local_backend) → API + DB + storage
3. **M0.3** (InsForgeClient integration) → swap path
4. **M0.4** (schema) → DB real
5. **M0.5** (verify-fallback-ready) → gate verde
6. **M1.1** (schema migration) → columnas nuevas
7. **M1.2 + 1.3** (ports + adapters) → contratos
8. **M1.4** (endpoints) → flow completo
9. **M1.5** (tests) → coverage
10. **M1.6** (OAuth compat) → no breaking change
11. **M2.1** (Coolify yaml) → metadata
12. **M2.2** (runbook) → operator procedure
13. **M2.3** (verification) → smoke test end-to-end

## Estimación de effort (resumen)

| Fase | Effort | Riesgo |
|---|---|---|
| M0 | 4-5 días | Bajo |
| M1 | 2-3 días | Bajo |
| M2 | 2-3 días | Medio |
| **Total** | **8-11 días** | |

## Criterio de "done"

La épica está completa cuando:

- [ ] `docker-compose up` arranca el stack self-hosted
- [ ] `python -m migration.cli_verify_fallback_ready --ci-only` exit 0
- [ ] `apap-migrate apply --legacy-path <.accdb>` funciona contra el
      backend local
- [ ] Login clásico email/password funciona (operator genera magic
      link desde CLI, usuario hace click, session cookie)
- [ ] Login OAuth de Google sigue funcionando
- [ ] `docs/runbooks/self-host-backend.md` cubre los flujos del
      operador
- [ ] `coolify.yaml` se commitea y el operador lo puede deployar
- [ ] El claim "M2 fallback-ready" del openspec `live-data-migration-sandbox`
      queda habilitado (con la signatura del operador)

## Rollback plan

Si algo sale mal en producción:

1. **`coolify restart apap-web`** con `APAP_LOCAL_BACKEND=false` →
   la app vuelve a InsForge remoto. Las sesiones existentes se
   invalidan (el session secret cambió).
2. El `.accdb` legacy en `local-access/` no se toca.
3. Las fotos en MinIO no se mueven (queda bucket vacío hasta que se
   re-aplique).
4. `apap-migrate apply --direction web-to-legacy --legacy-path
   /path/to/copy.accdb` se vuelve a correr contra InsForge remoto.

El rollback es **doloroso pero seguro** — el operador puede
re-deployar contra InsForge en minutos con la configuración anterior
guardada en Coolify's history.

## Métricas de éxito post-M2

- **Cero dependencias externas críticas**: el operador no necesita
  un BaaS externo. InsForge es opcional.
- **Login funciona sin Google**: el operador puede entregar magic
  links impresos a usuarios sin email configurado.
- **Migration M2 verde**: el verify-fallback-ready gate confirma que
  el apply bidireccional funciona contra el nuevo backend.
- **Tiempo de provisioning del backend**: <10 minutos (vs días con
  InsForge).
- **Backups locales**: el operador sabe exactamente dónde están sus
  datos y cómo restaurarlos.
