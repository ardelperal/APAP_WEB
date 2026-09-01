# Propuesta: self-host-backend-coolify

skill_resolution: paths-injected (sdd-propose, vba-access, access-vba-tdd, web-tdd-philosophy, cognitive-doc-design)

## Intención

Traer el backend de APAP_WEB bajo nuestro control en Coolify, eliminando la dependencia del BaaS InsForge (instancia `c3uc9dk6.eu-central.insforge.app`). Hoy el `verify-fallback-ready` gate falla con `web_to_legacy_check_only` porque el InsForge de dev está "No backend services available" — la migration bidireccional no es operacionalmente confiable mientras dependa de un servicio gestionado cuyo provisioning depende de un OAuth interactivo que no puedo ejecutar desatendido. Esta propuesta cierra ese bloqueador: reemplaza InsForge por una API propia en FastAPI servida por el mismo proceso de la app, sobre Postgres 16 (Coolify `coolify-db` ya provisionado) y MinIO (S3-compatible) para las fotos. Mantiene el `InsForgeClient` como Port backend-agnostic — solo cambia la URL base cuando `APAP_LOCAL_BACKEND=true`. La hexagonal architecture del proyecto (regla §31) hace este cambio muy limpio: el dominio y la lógica de negocio no se enteran del swap.

Adicionalmente, introduce un flujo de **login clásico email/password con magic link** como alternativa al OAuth de Google. El proyecto hoy depende 100% de Google; un operador que no quiera configurar Google Client ID/Secret no puede hacer login. El magic link con un log de tokens (operador los entrega manualmente) es un patrón self-contained que no requiere SMTP. La pieza SMTP real queda como épica futura — el flow de magic link es compatible con SMTP porque ambos emiten el mismo tipo de token.

## Alcance

### Dentro (Milestone "Usable + Secure" → M0+M1+M2)

- **M0 — Backend self-hosted viable**: imagen Docker multi-stage con la app + el API nuevo, `docker-compose.yml` con `app+postgres+minio` para dev local, `coolify.yaml` con metadata para provisionar el servicio en producción. `InsForgeClient` se queda; cuando `APAP_LOCAL_BACKEND=true` apunta a `http://localhost:8000/api` (la nueva API).
- **M0 — Replicación de los 3 endpoints InsForge** (`POST /api/database/advance/rawsql`, `GET/POST /api/storage/buckets[/...]`, `POST /api/auth/oauth/google[/callback]`) en `app/core/local_backend/`. El cliente `InsForgeClient` no se entera del swap — los tipos y formas del JSON son los mismos.
- **M0 — MinIO en Coolify** como S3-compatible para fotos. Bucket `apap-photos` se crea idempotentemente en el bootstrap (como hoy hace `ensure_private_bucket` con InsForge). El Port de storage es `app/core/ports/storage_port.py` y el adapter `app/core/adapters/storage/s3_storage_adapter.py` lo implementa — la app no cambia.
- **M1 — Login clásico email/password con magic link**: columna `password_hash TEXT` (nullable, argon2id) en `usuarios_autorizados`. Adapter `app/core/adapters/auth_local/classic_password_auth_port.py` implementa `AuthUsersPort` con `verify_password` y `set_password`. Endpoints FastAPI nuevos: `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/forgot-password` (genera token, lo loguea), `GET /api/auth/magic?token=...` (valida, emite session), `POST /api/auth/reset-password`. El operador ve los magic links activos en `GET /admin/magic-links` (admin-only).
- **M1 — OAuth de Google se queda como opción secundaria**: el adapter `oauth_insforge_adapter` no se toca. La tabla `usuarios_autorizados` permite ambos flows (password O `anadido_por` que indica el flow original). Migrar usuarios existentes de OAuth → classic es opcional (pueden seguir con Google).
- **M2 — verify-fallback-ready gate verde contra el nuevo backend**: el round-trip E2E corre contra `APAP_LOCAL_BACKEND=true` + Postgres local. La pieza `web_to_legacy_check_only` del gate corre contra el API nuevo en lugar de InsForge. El test E2E legacy_postgres sigue verde.
- **M2 — Runbook operador**: cómo deployar, cómo resetear passwords, cómo rotar el session secret, cómo migrar fotos legacy a MinIO. `docs/runbooks/self-host-backend.md`.

### Fuera (Non-goals)

- **NO** SMTP real (Postfix / SES / Mailgun). El flow de magic link es compatible con SMTP pero la pieza SMTP es una épica futura.
- **NO** multi-tenant. El schema actual asume una sola protectora; el de siempre.
- **NO** 2FA / TOTP. Necesita columna `two_factor_secret` y flow de doble factor; épica futura.
- **NO** OAuth de Apple / Facebook / GitHub. El Protocol es backend-agnostic; añadir providers es solo nuevos adapters.
- **NO** migración de datos reales del `.accdb` legacy. Eso es la ÉPICA SIGUIENTE (issue #637 + plan E2E). Esta épica verifica que el backend está bien provisionado con un subconjunto del `.accdb` o con datos sintéticos.
- **NO** auditoría de sesiones (log de cada login/logout, panel admin). La pieza admin la cubre el openspec `tasks-engine-foundation` si existe.
- **NO** eliminación del OAuth de Google. Quitarlo es migración de datos de sesión que no aporta valor.

## Decisiones de producto (key)

| ID | Decisión | Justificación |
|---|---|---|
| **D-SELF-01** | API propia en FastAPI en el mismo proceso de la app, no side-car | Reduce superficie operacional. La hexagonal architecture permite que `InsForgeClient` apunte a la nueva API sin reescribir la app (mismo JSON). Si en el futuro el tráfico crece, la API se mueve a un side-car con un cambio de URL en `APAP_INSFORGE_URL`. |
| **D-SELF-02** | Mantener `InsForgeClient` como Port backend-agnostic | Regla §31 (domain depende de Protocol, no de transport). Migrar el código que llama a `InsForgeClient` al nuevo Port sería reescribir la app entera. Mantener el cliente con un nuevo `base_url` es un cambio de una línea por llamada. |
| **D-SELF-03** | Postgres de Coolify como destino de la migration | `coolify-db` ya existe y corre Postgres 16. Cero infra nueva. El schema se crea en una migration SQL idempotente (mismo patrón que `apply_sql_migrations`). |
| **D-SELF-04** | MinIO local (no servicio externo) | Todo el stack self-hosted, control operacional completo. Migrar a R2/Backblaze/S3 real es cambiar 2 env vars + 1 línea de config en el adapter — el Port está bien aislado. |
| **D-SELF-05** | Magic link con log de tokens (operador los entrega manualmente) | Cero infra nueva (tabla en Postgres que ya tenemos). El operador es el "servidor de email" durante el MVP. SMTP real es una épica futura sin tocar el flow. |
| **D-SELF-06** | argon2id para password hash (no bcrypt) | Más moderno (RFC 9106, 2021), mejor resistencia a GPU/ASIC y side-channel. La librería `argon2-cffi` es la implementación de referencia. |
| **D-SELF-07** | OAuth de Google se queda | Quitarlo es migración de datos de sesión, no aporta valor. Usuarios actuales siguen entrando con Google. |
| **D-SELF-08** | El API nuevo vive en `app/core/local_backend/` con FastAPI router | Mismo proceso que la app principal, distinto módulo. La integración es un flag `APAP_LOCAL_BACKEND=true` que cambia la URL del `InsForgeClient`. Si el flag es false, el comportamiento es idéntico al actual (InsForge remoto). |
| **D-SELF-09** | Las fotos legacy se migran en una épica posterior (post-M2) | Esta épica provisiona el backend y verifica con datos sintéticos. El round-trip con datos reales es un check de M2 del plan de migration existente. |

## Self-host vs InsForge (comparación operacional)

| Aspecto | InsForge (hoy) | Coolify self-host (M0) |
|---|---|---|
| Provisioning del backend | Requiere login interactivo OAuth o panel web de InsForge (no automatizable) | `coolify up` desde el CLI o `docker-compose up` en local |
| DB PostgreSQL | Compartida, gestionada por el vendor | Dedicada, en nuestro Coolify |
| Storage de fotos | S3-compatible gestionado (InsForge) | MinIO (S3-compatible, self-hosted) |
| Latencia DB | Cross-cloud (eu-central) | Mismo host (Coolify VPS) |
| Costo mensual | Variable según tier de InsForge | Fijo (Coolify VPS ya pagado) |
| Backups | Depende del plan de InsForge | Cron + pg_dump en Coolify |
| OAuth de Google | Built-in (gestionado por InsForge) | Sigue vía `oauth_insforge_adapter` (sin cambios) |
| Login email/password | NO soportado por InsForge directamente | Clásico email/password + magic link |
| Multi-tenant | Requiere separar apps en InsForge | Costo cero extra (otro schema) |
| Rollback | Depende de InsForge, soporte 24/7 de pago | Local: restaurar DB desde backup |
| Tiempo de provisioning del backend | Días (soporte de InsForge) | Minutos (terraform/CLI de Coolify) |

## Runtime boundary del backend self-host (cómo difiere de InsForge)

| Capa | InsForge (hoy) | Coolify self-host (M0) |
|---|---|---|
| DB SQL | `POST /api/database/advance/rawsql` (HTTP) | `psycopg2.connect(...)` directo vía la nueva API FastAPI que envuelve psycopg |
| Storage S3 | `GET/POST /api/storage/buckets[/...]` (HTTP) | `boto3.client("s3", endpoint_url=...)` (MinIO SDK) |
| Auth OAuth Google | `/api/auth/oauth/google[/callback]` (HTTP) | Idéntico — el adapter `oauth_insforge_adapter` no se toca |
| Login email/password | NO EXISTE | `POST /api/auth/login` (form-encoded) → session cookie |
| Reset password | NO EXISTE | `POST /api/auth/forgot-password` + `GET /api/auth/magic?token=...` + `POST /api/auth/reset-password` |
| Magic link log | NO EXISTE | `GET /admin/magic-links` (admin-only) |

## Decisión arquitectónica clave (sub-discusión)

**¿API nueva en el mismo proceso de la app o side-car separado?**

| Aspecto | Mismo proceso | Side-car separado |
|---|---|---|
| Latencia | Nula (in-process function call) | Red (1-2ms) |
| Deploy | Una sola imagen | Dos imágenes a sincronizar |
| Recursos | Compartido (mismo proceso Python) | Aislado (se puede escalar independiente) |
| Costo operacional | Bajo (1 servicio) | Medio (2 servicios + orchestration) |
| Hoy (Fase 1) | ✅ Recomendado | ❌ YAGNI |

**Recomendación**: Mismo proceso durante Fase 1. **Si el tráfico crece**, migrar a side-car es cambiar `APAP_INSFORGE_URL` de `http://localhost:8000/api` a `http://api-internal:8000/api` y separar el deployment. El `InsForgeClient` se queda igual.

## Decisiones operacionales

| Aspecto | Decisión | Justificación |
|---|---|---|
| Versión de Python | 3.11 (coolify-db ya corre Python 3.11 en otra imagen) | Compatibilidad con `uv` y la imagen base `python:3.11-slim` |
| Imagen Docker | Multi-stage: builder con `python:3.11-slim` + `uv pip install --system`; runtime con `python:3.11-slim` | Tamaño de imagen final ~250MB |
| Base path de la API nueva | `/api/*` (mismo prefijo que InsForge, para no tocar el cliente) | El `InsForgeClient` actual no necesita saber del swap |
| Healthcheck | `GET /healthz` devuelve 200 con `{"db": "up", "storage": "up", "oauth": "configured"}` | Para que el panel de Coolify sepa si el servicio está vivo |
| TLS | Coolify-proxy ya provee TLS termination; la app sirve plain HTTP en el puerto interno | El certificado lo gestiona el reverse proxy, no la app |
| Logs | `stdout` (coolify los recoge) en formato JSON estructurado (mismo `log_safe` actual) | Cero configuración adicional; el stack de logging del proyecto ya hace esto |
| Métricas | `/metrics` opcional (Prometheus) — Fase 3 si se necesita | No en Fase 1 |

## Decisiones que necesito de ti (recordatorio)

1. **Magic link vs SMTP real**: magic link (recomendado). ✅ confirmado.
2. **S3-compatible**: MinIO en Coolify (recomendado). ✅ confirmado.
3. **OAuth de Google**: se queda. ✅ confirmado.
4. **Migración de datos legacy**: en una épica posterior, pero esta sirve para verificar el backend con un subconjunto. ✅ confirmado.
5. **Openspec workflow completo**: sí. ✅ confirmado.

## Out of scope (repetido para claridad)

- SMTP real (épica futura)
- Multi-tenant (épica futura)
- 2FA / TOTP (épica futura)
- OAuth de Apple / Facebook / GitHub (cada provider es un adapter nuevo)
- Auditoría de sesiones (admin panel — épica futura)
- Eliminación del OAuth de Google

## Acceptance

### Fase 1 — Backend self-hosted (M0)

- [ ] `Dockerfile` multi-stage + `docker-compose.yml` con app+postgres+minio
- [ ] `app/core/local_backend/api.py` con FastAPI router que replica los 3 endpoints que `InsForgeClient` consume
- [ ] `InsForgeClient` apunta a `http://localhost:8000/api` cuando `APAP_LOCAL_BACKEND=true`
- [ ] Postgres migration SQL idempotente (las 13 tablas actuales)
- [ ] MinIO bucket `apap-photos` creado en bootstrap con `isPublic=false`
- [ ] `/healthz` y `/metrics` (opcional) en la nueva API
- [ ] `docs/runbooks/self-host-backend.md` (cómo deployar, cómo resetear el session secret, cómo ver los magic links activos)
- [ ] El verify-fallback-ready gate verde contra el backend self-hosted (3/3 CI checks PASS)

### Fase 2 — Login clásico con magic link (M1)

- [ ] Adapter `classic_password_auth_port.py` con argon2id
- [ ] Migración de tabla `usuarios_autorizados` con columna `password_hash` (nullable)
- [ ] Endpoints `/api/auth/login`, `/api/auth/logout`, `/api/auth/forgot-password`, `/api/auth/magic?token=...`, `/api/auth/reset-password`
- [ ] Panel admin `GET /admin/magic-links` que lista los tokens activos (admin-only)
- [ ] Test E2E del login clásico (happy path + wrong password + magic link expired + magic link used)
- [ ] `APAP_S3_*` env vars configuradas en Coolify (endpoint, access key, secret key)
- [ ] La foto se sube a MinIO (no a InsForge storage) y se sirve vía el mismo endpoint autenticado

### Fase 3 — Coolify + Producción (M2)

- [ ] `coolify.yaml` con metadata para provisionar el servicio
- [ ] DNS + reverse proxy (coolify-proxy ya cubre esto)
- [ ] Healthcheck conectado al panel de Coolify
- [ ] Runbook operador: deploy, reset password, rotar session secret, ver magic links
- [ ] Smoke test E2E con un subconjunto del `.accdb` legacy (TbFichaAnimal con 5-10 filas) que ejercite el round-trip end-to-end

## Trazabilidad

- **Issue #641** — la épica completa
- **Issue #637** (verify-fallback-ready gate) — gate queda green al provisionar
- **Issue #638** (drift schema) — cerrado
- **Issue #639** (drift de valores) — cerrado
- **Live-data-migration-sandbox openspec** — M2 fallback-ready se cumple
- **Migration E2E plan** (`docs/quality/migration-e2e-plan.md`) — el round-trip corre contra el nuevo backend
- **Hexagonal architecture** (regla §31) — el dominio y la lógica no cambian
- **`InsForgeClient` como Port** — la app no se entera del swap

## Consecuencias operacionales

- El operador pasa de depender de InsForge a depender de su propio Coolify. Backups locales, logs locales, control total.
- El `APAP_INSFORGE_*` env vars se convierten en `APAP_LOCAL_BACKEND=true` + `APAP_LOCAL_DB_URL` + `APAP_S3_*` para el bucket.
- El `.env` (o equivalente) necesita actualizarse con las nuevas vars.
- El verify-fallback-ready gate cambia de "InsForge unreachable" a "self-host local reachable" — un check de cableado, no un test de carga.

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| El `InsForgeClient` asume HTTP con el shape de InsForge; el nuevo API no es 100% compatible | La hexagonal architecture (Port) significa que el shape de los endpoints es la superficie. Tests E2E del round-trip validan que el cliente sigue funcionando. Si algo cambia, se ajusta en un solo lugar (`app/core/local_backend/api.py`). |
| El operator no provisiona Coolify correctamente (DB mal configurada, MinIO sin bucket) | El verify-fallback-ready gate detecta el problema: `web_to_legacy_check_only` falla con mensaje claro. El runbook incluye paso a paso. |
| argon2id tiene un costo de CPU que bcrypt no tiene | El login no es un hot path (decenas de logins/día, no miles/segundo). El cost de argon2id es ~100ms por hash, aceptable. |
| La migración del schema a Postgres local falla silenciosamente | El CI tiene el integration test que prueba `apply_legacy_to_web` contra el schema. Si el schema no está bien, el test falla loudly. |
| El operador pierde el `.accdb` legacy al provisionar el nuevo backend | El `.accdb` está en `tests/migration/local-access/`, gitignored y separado del backend. No se toca. |
| Las sesiones existentes en InsForge se pierden | El session secret es nuevo; los usuarios tienen que re-loguearse. Es un trade-off aceptable para evitar mantener un InsForge residual. |
| El DNS del deployment cambia | Coolify-proxy ya provee el routing. El operador configura el dominio en el panel de Coolify. |

## Por qué ahora

1. **Operacional**: el verify-fallback-ready gate falla sin backend provisionado. Sin esta épica, la migration bidireccional queda en estado "demo only".
2. **Seguridad**: OAuth de Google como login único es una dependencia operacional. Un magic link self-contained reduce esa dependencia.
3. **Costo**: ya pagamos el Coolify VPS. El cambio usa infra que ya tenemos.
4. **Hexagonal**: la arquitectura del proyecto hace este cambio muy limpio. El dominio no cambia; solo adapters y configuración.

## Conclusión

Esta propuesta reemplaza el BaaS InsForge por un backend self-hosted en Coolify, manteniendo la hexagonal architecture del proyecto. El cambio se hace en 3 fases (M0 backend viable, M1 login clásico con magic link, M2 deployment en Coolify), cada una con su acceptance y sus tests. La app no se entera del swap — solo cambia la URL del `InsForgeClient`. El verify-fallback-ready gate queda green al final, lo que es la prueba operacional de que el backend está bien provisionado.
