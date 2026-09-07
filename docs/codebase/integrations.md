# Integrations

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el inventario de integraciones externas (LocalBackend, CodeGraph, Dysflow, Coolify, GitHub) y los límites de configuración de cada una. No posee el contrato de stack — eso es [Arquitectura LocalBackend](../architecture/architecture-local_backend-stack.md) — ni el detalle de cada variable — eso vive en [`app/core/config.py`](../../app/core/config.py).

## Core invariants

- **Cliente único hacia LocalBackend**: solo [`app/core/local_backend.py`](../../app/core/local_backend.py) habla con LocalBackend; nadie lo importa fuera de `adapters/`, `di/` y `app/main.py` (§33.4). En producción el contenedor self-hosted en Coolify actúa como backend; LocalBackend queda como fallback de desarrollo local.
- **Self-host en producción**: el contenedor `app/core/local_backend/app.py` reemplaza a LocalBackend cuando `APAP_LOCAL_BACKEND=true`. El switch vive en [`app/core/local_backend_url.py`](../../app/core/local_backend_url.py) con la precedencia `APAP_LOCAL_BACKEND_URL` > `APAP_LOCAL_BACKEND` > producción LocalBackend. La rama activa del esfuerzo es `feat/641-self-host-backend-coolify` (issue #641).
- **Secrets sin defaults de producción**: ningún campo `Settings` que porte un secreto puede arrancar con un valor usable en producción (§32.P2, validado en startup).
- **PII redactada en logs**: 12 campos cerrados (`email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for`) pasan por `log_safe` (§9).
- **Configuración cacheada**: `Settings()` se cachea con `lru_cache(maxsize=1)`; no se reparsea el `.env` por request (§3).
- **CodeGraph persistente**: el índice en `.codegraph/` se conserva entre ramas; nunca se re-inicializa (AGENTS §14).

## Integraciones externas

| Integration | Purpose | Where configured | Failure mode |
|---|---|---|---|
| Local backend (self-hosted Coolify) | Contenedor FastAPI propio (`local_backend/app.py`) que reemplaza a LocalBackend en producción; expone `/healthz`, `/api/rawsql`, `/api/storage`, `/api/oauth` y, tras M3.4, `/api/magic/*` | [`app/core/local_backend/`](../../app/core/local_backend/) + variables `APAP_LOCAL_BACKEND`, `APAP_LOCAL_DB_URL`, `APAP_LOCAL_DB_SCHEMA` | Si `APAP_LOCAL_DB_URL` falta, el lifespan falla con RuntimeError al arrancar; sin DB reachable, `DatabaseError` → HTTP 503 |
| LocalBackend (PostgreSQL + Auth + Storage) | Backend de datos y auth gestionado; usado como fallback de desarrollo local cuando `APAP_LOCAL_BACKEND` está unset | [`app/core/local_backend.py`](../../app/core/local_backend.py) + variables `APAP_LOCAL_BACKEND_URL`, `APAP_INSFORGE_SERVICE_KEY` | Si no responde, las requests devuelven 5xx; el seed bootstrap falla si las tablas no existen |
| CodeGraph CLI + MCP | Índice de inteligencia de código que reemplaza `Read`/`Grep`/`Glob` en código indexado | `.codegraph/` en raíz, daemon de auto-sync, MCP server `codegraph_explore` | Daemon caído → re-arrancar con `codegraph daemons` y `codegraph sync .`; nunca `codegraph init` (AGENTS §14.1, §14.6) |
| Dysflow MCP | Acceso de solo lectura al binario Access legacy (`.accdb`) para resolver dudas de dominio | MCP server Dysflow; `projectId: apap`, `accessPath` resuelve al `.accdb` | Sin acceso al `.accdb` → ascender la duda al usuario (P2 en [proceso.md](../proceso.md)) |
| Coolify (deploy) | Plataforma de despliegue: webhook de push a `main`, healthcheck, gestión de env vars, hosting del contenedor local_backend | MCP server Coolify + job `deploy` en [`ci.yml`](../../.github/workflows/ci.yml); variable `COOLIFY_WEBHOOK_URL` | Sin `COOLIFY_WEBHOOK_URL` el job `deploy` se salta; no es merge blocker en pre-MVP (AGENTS §15.1) |
| SMTP (Resend) | Entrega de magic-link en producción; lee `APAP_SMTP_HOST/PORT/USER/PASSWORD/FROM` desde env (issue #649 + M3.4) | Variable de entorno; wiring en `app/core/local_backend/` tras M3.4 | Sin `APAP_SMTP_HOST`, el envío es no-op y el flujo magic-link queda inactivo en producción |
| GitHub Actions (CI) | Pipeline: lint, test, typecheck, build, e2e, deploy | [`.github/workflows/`](../../.github/workflows/) (`ci.yml`, `deploy.yml`, `e2e-self-hosted.yml`, `pr-name.yml`, `pr-size.yml`) | Job `lint` rojo bloquea merge; `e2e` se salta sin `APAP_OAUTH_CLIENT_ID` (AGENTS §15.1) |
| Google OAuth (vía LocalBackend) | Identidad de usuario; LocalBackend actúa como proxy | [`app/core/oauth/`](../../app/core/oauth/), callback en [`app/main.py`](../../app/main.py) | Sin `APAP_OAUTH_CLIENT_ID` el flujo no inicia; ver runbook [auth-email-normalization](../runbooks/auth-email-normalization.md) |
| Tailwind v4 CSS-first | Estilos sin `tailwind.config.js` | [`app/static/`](../../app/static/) + build command | Si el build falla, el CSS no se compila y la UI se ve sin estilos |
| Playwright (E2E) | Verificación end-to-end de UI; única red que caza regresiones de template/route/CSRF (§23) | [`tests/e2e/`](../../tests/e2e/), job `e2e` opcional en CI | Sin `APAP_OAUTH_CLIENT_ID` el job se salta; las features nuevas deben crecer la red |

## Variables de entorno

| Variable | Purpose | Default | Source of truth |
|---|---|---|---|
| `APAP_MODE` | `web` o `legacy`; toggle runtime (§18.4) | `web` | [Sync and cloud](sync-and-cloud.md) |
| `APAP_LOCAL_BACKEND` | Truthy (`1|true|yes|on`) activa el contenedor `local_backend/app.py` como destino de `LocalBackendClient`; en producción siempre `true` | unset (LocalBackend remoto) | [`app/core/local_backend_url.py`](../../app/core/local_backend_url.py) |
| `APAP_LOCAL_DB_URL` | DSN de Postgres que el contenedor local_backend usa en su lifespan | Required cuando `APAP_LOCAL_BACKEND=true`; el lifespan falla con RuntimeError si falta | [`app/core/local_backend/app.py`](../../app/core/local_backend/app.py) |
| `APAP_LOCAL_DB_SCHEMA` | Schema al que apunta el lifespan (tests de integración pasan el schema efímero) | `public` | [`app/core/local_backend/app.py`](../../app/core/local_backend/app.py) |
| `APAP_LOCAL_BACKEND_URL` | URL del backend LocalBackend (operador override; gana sobre `APAP_LOCAL_BACKEND`) | unset | [`app/core/local_backend_url.py`](../../app/core/local_backend_url.py) |
| `APAP_INSFORGE_SERVICE_KEY` | Service key para seed bootstrap y tablas privilegiadas | Required cuando `APAP_LOCAL_BACKEND` está unset | [`app/core/config.py`](../../app/core/config.py) |
| `APAP_SESSION_SECRET` | Secreto de firma de cookies | Required (validado en startup) | [Runbook cookie-rotation](../runbooks/cookie-rotation.md) |
| `APAP_OAUTH_CLIENT_ID` | Identificador OAuth de Google | Required | [Runbook auth-email-normalization](../runbooks/auth-email-normalization.md) |
| `APAP_AUTH_CACHE_TTL_SECONDS` | TTL del caché de autorización en proceso | `300` | AGENTS §29, [Runbook auth-cache-multi-worker](../runbooks/auth-cache-multi-worker.md) |
| `APAP_SMTP_HOST` | Host SMTP (Resend en producción); activa `SMTPMailTransport` para magic-link | unset (no-op) | issue #649 + M3.4 |
| `APAP_SMTP_PORT` | Puerto SMTP (`465` para Resend TLS) | `587` | issue #649 + M3.4 |
| `APAP_SMTP_USER` | Usuario SMTP (`resend` en producción) | unset | issue #649 + M3.4 |
| `APAP_SMTP_PASSWORD` | API key / password SMTP | unset | issue #649 + M3.4 |
| `APAP_SMTP_FROM` | Dirección `From` de los magic-link | unset | issue #649 + M3.4 |
| `COOLIFY_WEBHOOK_URL` | Webhook de deploy a Coolify | Required para deploy | AGENTS §15.1 |

## Contributor checklist

- [ ] Si añade una variable `APAP_*`, declárela en [`app/core/config.py`](../../app/core/config.py) con su `Field(...)` y, si porta un secreto, sin default usable (§32.P2).
- [ ] Si añade una integración nueva, agregue una fila a la tabla de integraciones con su `Purpose`, `Where configured` y `Failure mode`.
- [ ] Si modifica el contrato con LocalBackend, actualice [Arquitectura LocalBackend](../architecture/architecture-local_backend-stack.md) y la sección correspondiente en este radial en la misma sesión.
- [ ] Si añade un runbook nuevo (rotación de secreto, acción manual de operador), declárelo en [`docs/runbooks/`](../../docs/runbooks/) según §13.
- [ ] Si la integración toca un path sensible (auth, secretos, PII, SQL cruda), cree o actualice un doc en [`docs/audits/`](../../docs/audits/) según §12.

## Navigation

Previous: [Interfaces](interfaces.md) | Next: [Maintainer playbook](maintainer-playbook.md)