[← Back to README](README.md)

# APAP_WEB — Technical Reference

**Índice navegable de la superficie técnica de APAP_WEB: rutas HTTP, variables de entorno, escenarios cross-surface y enlaces a la documentación canónica.**

Índice técnico navegable de APAP_WEB. Para empezar, vea el [README](README.md); para reglas de agente, [AGENTS.md](AGENTS.md); para el playbook operativo, [docs/proceso.md](docs/proceso.md).

> **Scope**: APAP_WEB es una aplicación web server-rendered (FastAPI + Jinja2 + LocalBackend) que reemplaza el legacy Access/VBA.
>
> Este doc describe las superficies externas. Las decisiones arquitectónicas viven en [docs/architecture/architecture-local-backend-stack.md](docs/architecture/architecture-local-backend-stack.md).

---

## Navegación rápida

| Sección | Qué contiene |
|---|---|
| [Índice de documentación](#índice-de-documentación) | Cada documento del repo y su rol. |
| [Superficie de API](#superficie-de-api) | Endpoints HTTP públicos, autenticados y de administración. |
| [Variables de entorno](#variables-de-entorno) | Configuración runtime leida por `Settings` con defaults. |
| [Matriz de visibilidad de estados](#matriz-de-visibilidad-de-estados) | Escenarios cross-surface y razón esperada. |
| [Referencias cruzadas](#referencias-cruzadas) | Enlaces a docs canónicos del repo. |

---

## Índice de documentación

Cada documento del repo ocupa un único rol. Este índice es la única ruta recomendada para localizar una pregunta sobre el proyecto.

| Doc | Rol |
|---|---|
| [README.md](README.md) | Overview de cinco minutos: producto, anclas, quick start, configuración. |
| [AGENTS.md](AGENTS.md) | Reglas del repo para IAs (33 secciones): code quality, merge workflow, anti-patrones. |
| [DOCS.md](DOCS.md) | Este archivo: índice técnico navegable. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow de contribución, labels, convención de rama y commit. |
| [CHANGELOG.md](CHANGELOG.md) | Cambios por versión (formato Keep a Changelog). |
| [SECURITY.md](SECURITY.md) | Proceso de disclosure de vulnerabilidades. |
| [CODEOWNERS](CODEOWNERS) | Owners por path para revisión automática en GitHub. |
| [docs/roadmap.md](docs/roadmap.md) | Hoja de ruta viva (fases y transversales). |
| [docs/proceso.md](docs/proceso.md) | Playbook operativo: preflight → issue → TDD → merge → cierre. |
| [docs/setup.md](docs/setup.md) | Setup local por desarrollador. |
| [docs/CODEBASE-GUIDE.md](docs/CODEBASE-GUIDE.md) | Overview de módulos (Tier 2 de #464, parcial). |
| [docs/architecture/architecture-local-backend-stack.md](docs/architecture/architecture-local-backend-stack.md) | Stack target, reglas LocalBackend, despliegue. |
| [docs/architecture/decisiones-proyecto.md](docs/architecture/decisiones-proyecto.md) | Registro formal de decisiones arquitectónicas (D-01…). |
| [docs/audits/](docs/audits/) | Auditorías por slice sensible (CSRF, RBAC, XSS, cookies). |
| [docs/runbooks/](docs/runbooks/) | Runbooks de operador (rotación de cookie, auth cache multi-worker). |
| [docs/uat/](docs/uat/) | Informes de UAT firmados por fecha. |
| [openspec/changes/](openspec/changes/) | Cambios SDD históricos y activos. |

---

## Superficie de API

Los routers se incluyen en `app/main.py` vía [`app/routes_registry.py`](app/routes_registry.py). El orden de `include_router` está fijado para preservar precedencia entre paths dinámicos solapados.

### Rutas públicas (sin sesión)

| Método | Path | Propósito |
|---|---|---|
| GET | `/` | Landing autenticada; redirige a `/login` si no hay sesión. |
| GET | `/healthz` | JSON health probe para Docker y Coolify. |
| GET | `/login` | Render del formulario de login. |
| GET | `/auth/google` | Inicio del flujo OAuth (proxy LocalBackend). |
| GET | `/auth/callback` | Intercambio de `code` por sesión firmada. |
| GET | `/logout` | Limpia la cookie de sesión. |
| GET | `/unauthorized` | Página de acceso denegado. |
| GET | `/static/*` | CSS compilado y otros assets estáticos. |

### Rutas autenticadas (módulos de dominio)

| Prefijo | Paths destacados | Propósito |
|---|---|---|
| `/animales` | `GET /`, `GET /search`, `GET /{id}`, `POST /{id}/update`, `PATCH /{id}/chip`, `GET /{id}/foto` | CRUD de animales; búsqueda JSON; foto fail-closed. |
| `/voluntarios` | `GET /`, `POST /`, `POST /{id}/deactivate` | Registro y desactivación de voluntarios. |
| `/entradas` | `GET /`, `POST /`, `POST /{id}/update`, `POST /{id}/delete` | Intake individual con cesión por dueño. |
| `/entradas/batch` | `GET /new`, `POST /`, `POST /{id}/commit`, `POST /{id}/cancel` | Intake por lotes (transacción CTE atómica). |
| `/casas-acogida` | `GET /`, `POST /{id}/update`, `POST /{id}/delete` | Red de casas con capacidad y especie preferida. |
| `/casas-acogida` | `GET /{id}/asignar`, `POST /{id}/asignar`, `GET /{id}/overrides` | Asignación de animales + auditoría de overrides. |
| `/acogidas` | `GET /`, `POST /{id}/update`, `POST /{id}/close`, `POST /{id}/delete` | Estancias con FK a `casas_acogida` y `voluntarios`. |
| `/cesiones` | `GET /new`, `POST /` | Transferencias de dueño atadas a `entrada_origen_id`. |
| `/adopciones` | `GET /`, `POST /`, `POST /{id}/update`, `POST /{id}/delete` | Adopciones con clave natural `(animal_id, fecha_adopcion)`. |
| `/sanidad` | `GET /`, `POST /{id}/update`, `POST /{id}/delete` | Actuaciones clínicas con validación D-24. |
| `/sanidad` | `GET /batch/new`, `POST /actuaciones/batch` | Batch sanitario. |
| `/salud` | `GET /terapias`, `GET /terapias/{id}`, `PATCH /recomendaciones/{id}`, `DELETE /recomendaciones/{id}` | Terapias y recomendaciones. |
| `/tareas` | `GET /`, `POST /{id}/asignar`, `POST /{id}/cerrar` | Tareas operativas. |
| `/materiales` | `GET /`, `POST /`, `POST /{id}/deactivate` | Catálogo de materiales. |
| `/acogidas` | `GET /acogidas/{id}/materiales`, `POST /acogidas/{id}/materiales` | Materiales asignados a estancia. |

### Administración (rol `developer`)

| Método | Path | Propósito |
|---|---|---|
| GET | `/admin` | Panel de gestión de usuarios. |
| POST | `/admin/users` | Alta de usuario por email y rol. |
| POST | `/admin/users/{id}/deactivate` | Desactivación de usuario (soft-delete). |

---

## Variables de entorno

Todas las variables llevan prefijo `APAP_`. La single source of truth es [`app/core/config.py`](app/core/config.py). Si diverge, gana el código (premisa P3 de [docs/proceso.md](docs/proceso.md) §0).

| Variable | Descripción | Default |
|---|---|---|
| `APAP_INSFORGE_URL` | URL base de LocalBackend (PostgREST-compatible). | `http://localhost:7130` |
| `APAP_INSFORGE_ANON_KEY` | JWT anónimo para uso cliente; el servidor no la usa hoy. | `""` |
| `APAP_INSFORGE_SERVICE_KEY` | Service key con privilegios para admin SQL (bootstrap, seed, gestión de usuarios). Vacía desactiva operaciones privilegiadas. | `""` |
| `APAP_GOOGLE_CLIENT_ID` | OAuth client id de Google. | `""` |
| `APAP_GOOGLE_CLIENT_SECRET` | OAuth client secret de Google. | `""` |
| `APAP_GOOGLE_REDIRECT_URI` | Callback OAuth registrado en Google; debe coincidir exacto. | `http://127.0.0.1:8000/auth/callback` |
| `APAP_INITIAL_ADMIN_EMAIL` | Email pre-sembrado como primer `developer` en el primer arranque. Vacío no siembra. | `""` |
| `APAP_SESSION_SECRET` | Secreto HMAC para firmar cookies (`itsdangerous`). Validado al arranque: placeholder o longitud menor a 32 falla salvo `debug=True`. | `dev-only-change-me-in-production` |
| `APAP_AUTH_CACHE_TTL_SECONDS` | TTL del caché de authorization por request. `0` desactiva el caché. | `300` |
| `APAP_AUTH_CACHE_BACKEND` | Backend del caché. Solo `in_process` está soportado; cualquier otro valor falla el arranque. | `in_process` |
| `APAP_CSRF_ENABLED` | Feature flag de `CsrfMiddleware`. Pasar a `false` solo en rollback de incidente. | `true` |
| `APAP_RATE_LIMIT_ENABLED` | Feature flag del middleware de rate limiting. | `true` |
| `APAP_RATE_LIMIT_OAUTH_PER_MIN` | Cupo por IP para el bucket OAuth (requests/min). | `10` |
| `APAP_RATE_LIMIT_WRITE_PER_MIN_USER` | Cupo por usuario para write buckets (requests/min). | `60` |
| `APAP_RATE_LIMIT_WRITE_PER_MIN_IP` | Cupo por IP para write buckets (requests/min). | `30` |
| `APAP_TRUST_XFF` | Confiar en `X-Forwarded-For` cuando hay proxy delante. | `false` |
| `APAP_MODE` | Modo runtime (`web` o `test`). En `test` el rate limit cortocircuita. | `web` |
| `APAP_LOG_LEVEL` | Nivel raíz del handler JSON a stdout. Valores desconocidos caen a `INFO`. | `INFO` |
| `APAP_DEBUG` | Toggle debug-only; desactiva validación de secretos al arranque. | `false` |

---

## Matriz de visibilidad de estados

APAP_WEB compone varias superficies (HTTP, OAuth Google, LocalBackend, CSRF, rate limit, caché de authorization). Esta matriz nombra los escenarios cross-surface y la razón esperada de cada uno.

| Escenario | Razón esperada | Superficies |
|---|---|---|
| GET sin sesión a path privado | 302 → `/login` | middleware auth + OAuth LocalBackend |
| GET con sesión y email no en `usuarios_autorizados` | 302 → `/unauthorized` | middleware auth + caché de authorization |
| POST sin token CSRF | 403 | `CsrfMiddleware` |
| POST con token CSRF inválido o de otra sesión | 403 | `CsrfMiddleware` + `itsdangerous` |
| Cookie firmada con secreto rotado | 302 → `/login` | `itsdangerous` + middleware auth |
| Rate limit OAuth superado (10/min/IP) | 429 | rate limit + OAuth Google |
| Rate limit write superado (60/min/user o 30/min/IP) | 429 | rate limit + router del módulo |
| `APAP_INSFORGE_URL` inalcanzable al arranque | lifespan lanza `StartupConfigError` | `httpx.Client` + LocalBackend |
| LocalBackend devuelve 401 al a service key | 500 con `log_safe("local_backend.unauthorized")` | `LocalBackendClient` + `log_safe` |
| Usuario desactivado, caché vigente | sigue autorizado hasta `APAP_AUTH_CACHE_TTL_SECONDS` | caché TTL + `usuarios_autorizados` |
| `APAP_SESSION_SECRET` placeholder en producción (`debug=False`) | lifespan lanza `StartupConfigError` | `Settings._validate_secrets` |
| `APAP_AUTH_CACHE_BACKEND` distinto de `in_process` | lifespan lanza `StartupConfigError` | `Settings` |

---

## Referencias cruzadas

| Recurso | Ruta |
|---|---|
| Reglas del repo (33 secciones) | [AGENTS.md](AGENTS.md) |
| Overview de producto | [README.md](README.md) |
| Playbook operativo por issue | [docs/proceso.md](docs/proceso.md) |
| Hoja de ruta viva | [docs/roadmap.md](docs/roadmap.md) |
| Setup local por desarrollador | [docs/setup.md](docs/setup.md) |
| Decisiones arquitectónicas | [docs/architecture/decisiones-proyecto.md](docs/architecture/decisiones-proyecto.md) |
| Stack target y reglas LocalBackend | [docs/architecture/architecture-local-backend-stack.md](docs/architecture/architecture-local-backend-stack.md) |
| Workflow de contribución | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Cambios por versión | [CHANGELOG.md](CHANGELOG.md) |
| Disclosure de vulnerabilidades | [SECURITY.md](SECURITY.md) |
| Owners por path | [CODEOWNERS](CODEOWNERS) |
| Releases firmados | [github.com/ardelperal/APAP_WEB/releases](https://github.com/ardelperal/APAP_WEB/releases) |

[Next: CONTRIBUTING →](CONTRIBUTING.md)