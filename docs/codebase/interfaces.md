# Interfaces

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el catálogo de superficies que expone el sistema (HTTP, OAuth, storage, healthcheck) y por dónde fluye cada una. No posee el detalle de comportamiento de cada ruta — eso vive en el `routes.py` del módulo afectado — ni el contrato de stack — eso es [Arquitectura LocalBackend](../architecture/architecture-local-backend-stack.md).

## Core invariants

- **Routes delgadas**: cada handler hace parse, delega, render; la lógica vive en service o use case (§1, §28).
- **CSRF por defecto**: todo POST/PUT/DELETE/PATCH pasa por `CsrfMiddleware`; cada `<form method="post">` lleva `csrf_token` (§10).
- **Auth en capas**: el middleware de auth corre antes que la validación de FastAPI; el cookie `SameSite=Strict` se firma con `APAP_SESSION_SECRET` (§10, AGENTS §29).
- **Plantillas server-rendered**: el producto devuelve HTML por defecto; solo se devuelve JSON cuando la UI lo requiere (HTMX, fetch explícito).

## Superficies HTTP

| Surface | Where | Auth | Notes |
|---|---|---|---|
| Landing `/` | [`app/main.py`](../../app/main.py) | Auth required | Página de marketing para usuarios autenticados. |
| Health `/healthz` | [`app/main.py`](../../app/main.py) | Public | Sonda JSON para Docker y Coolify (CD-02). |
| Login `/login` | [`app/main.py`](../../app/main.py) | Public | Renderiza la página de login de APAP. |
| OAuth `/auth/google` | [`app/main.py`](../../app/main.py) | Public | Inicia el flujo OAuth hospedado por LocalBackend. |
| OAuth callback `/auth/callback` | [`app/main.py`](../../app/main.py) | Public | Intercambia `oauth_code` (o `code`) por JWT y emite cookie de sesión. |
| Logout `/logout` | [`app/main.py`](../../app/main.py) | Any user | Limpia la cookie de sesión. |
| Unauthorized `/unauthorized` | [`app/main.py`](../../app/main.py) | Auth required | Página de acceso denegado; usuarios desactivados ven el copy amigable. |
| Admin `/admin` | [`app/main.py`](../../app/main.py) | Developer only | Panel de gestión de usuarios desarrolladores. |
| Estáticos `/static/*` | [`app/main.py`](../../app/main.py) | Public | CSS compilado y otros assets. |
| Módulos de negocio `/animales`, `/entradas`, `/voluntarios`, etc. | [`app/modules/<slice>/routes.py`](../../app/modules/) | Auth + RBAC | Una superficie por slice; el módulo define los verbos y paths. |
| Endpoints HTMX internos | `routes.py` del módulo | Auth + RBAC | Mismo origen; usan el header `X-CSRFToken` (§10). |

## Storage LocalBackend

| Bucket / Surface | Purpose | Auth |
|---|---|---|
| Tablas de dominio (animales, voluntarios, entradas, etc.) | Estado de negocio | RLS vía JWT de sesión |
| Tabla `authorized_users` | Allowlist de emails autorizados | Servicio (seed inicial con service key) |
| Tabla `web_only_feature_shadow` | Tracking de divergencias web ↔ legacy para sync idempotente (§18.1) | Servicio |

## MCP servers

| Server | Purpose | Where configured |
|---|---|---|
| `local_backend` | Backend LocalBackend: SQL, schema, buckets, funciones, deploy, AI, realtime | MCP server del cliente |
| `codegraph` | Índice de inteligencia de código; permite `codegraph_explore` sin `Read`/`Grep` | AGENTS §14 |
| `coolify` | Operación del despliegue en Coolify (deploy, restart, env vars, logs) | MCP server del cliente |
| `dysflow` | Acceso de solo lectura al binario `.accdb` del legacy para resolver dudas de dominio (P2 en [proceso.md](../proceso.md)) | MCP server del cliente |
| `engram` | Memoria persistente entre sesiones y tras compactación | MCP server del cliente |
| `context7` | Documentación actualizada de librerías para verificar versiones (§8) | MCP server del cliente |
| `playwright` | Verificación E2E de features de UI (§23) | MCP server del cliente |

## CLI scripts

| CLI | Purpose | Entry point |
|---|---|---|
| Sync bidireccional | Mueve datos entre web y legacy con idempotencia y auditoría | `python -m migration reconcile` ([CLI](../../migration/cli.py), §18.2) |
| Linters | Ejecutables individuales del arnés de calidad | `python scripts/check_*.py` |
| Lint consolidado | Atajo para correr el arnés completo | `make check-rules` / `make lint` |

## Contributor checklist

- [ ] Si añade una ruta pública, declárela en `PUBLIC_PATHS` dentro de [`app/main.py`](../../app/main.py) para que el middleware de auth la salte.
- [ ] Si añade una ruta autenticada, use `require_authorized_user` o `require_permission` de [`app/core/auth_dependencies.py`](../../app/core/auth_dependencies.py); no duplique la lógica de auth en el módulo (§27).
- [ ] Si añade un endpoint que cambia estado, incluya el token CSRF en la plantilla del formulario y la verificación por header o campo (§10).
- [ ] Si añade una dependencia que crea un cliente (`httpx`, `httpx.AsyncClient`, etc.), use `yield` en la dependencia de FastAPI (§2).
- [ ] Si añade un bucket LocalBackend nuevo, declárelo también en `openspec/specs/` con su RLS y su caso de uso.

## Navigation

Previous: [Repository map](repository-map.md) | Next: [Integrations](integrations.md)