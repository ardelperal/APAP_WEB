# Integrations

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el inventario de integraciones externas (LocalBackend, CodeGraph, Dysflow, Coolify, GitHub) y los límites de configuración de cada una. No posee el contrato de stack — eso es [Arquitectura LocalBackend](../architecture/architecture-local-backend-stack.md) — ni el detalle de cada variable — eso vive en [`app/core/config.py`](../../app/core/config.py).

## Core invariants

- **PostgreSQL directo**: [`app/main.py`](../../app/main.py) construye `LocalPostgresExecutor`; no existe un cliente HTTP LocalBackend en el runtime actual.
- **API separada**: [`app/core/local_backend/app.py`](../../app/core/local_backend/app.py) conserva contratos para pruebas y verificadores, pero no está montada en `app.main`.
- **Secrets sin defaults de producción**: ningún campo `Settings` que porte un secreto puede arrancar con un valor usable en producción (§32.P2, validado en startup).
- **PII redactada en logs**: 12 campos cerrados (`email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for`) pasan por `log_safe` (§9).
- **Configuración cacheada**: `Settings()` se cachea con `lru_cache(maxsize=1)`; no se reparsea el `.env` por request (§3).
- **CodeGraph persistente**: el índice en `.codegraph/` se conserva entre ramas; nunca se re-inicializa (AGENTS §14).

## Integraciones externas

| Integration | Purpose | Where configured | Failure mode |
|---|---|---|---|
| PostgreSQL local | Persistencia del servicio web y del proceso de migración | [`app/core/local_backend/db.py`](../../app/core/local_backend/db.py) + `APAP_LOCAL_DB_URL` | Los fallos SQL se clasifican como `QueryError`; los de conexión, como `DatabaseError` |
| API LocalBackend separada | Compatibilidad HTTP para integración y verificadores de fallback | [`app/core/local_backend/app.py`](../../app/core/local_backend/app.py) | Falla al arrancar si falta `APAP_LOCAL_DB_URL`; OAuth y storage son stubs explícitos |
| CodeGraph CLI + MCP | Índice de inteligencia de código que reemplaza `Read`/`Grep`/`Glob` en código indexado | `.codegraph/` en raíz, daemon de auto-sync, MCP server `codegraph_explore` | Daemon caído → re-arrancar con `codegraph daemons` y `codegraph sync .`; nunca `codegraph init` (AGENTS §14.1, §14.6) |
| Dysflow MCP | Acceso de solo lectura al binario Access legacy (`.accdb`) para resolver dudas de dominio | MCP server Dysflow; `projectId: apap`, `accessPath` resuelve al `.accdb` | Sin acceso al `.accdb` → ascender la duda al usuario (P2 en [proceso.md](../proceso.md)) |
| Coolify (deploy) | Plataforma de despliegue del servicio `app.main:app`, PostgreSQL y variables de entorno | [`deploy.yml`](../../.github/workflows/deploy.yml) y [`operator-deploy-2026.md`](../runbooks/operator-deploy-2026.md) | Falta de webhook o URL de salud falla cerrado; una revisión pública incorrecta activa rollback |
| SMTP (Resend) | Entrega de magic-link en producción; lee `APAP_SMTP_HOST/PORT/USER/PASSWORD/FROM` desde env (issue #649 + M3.4) | Variable de entorno; wiring en `app/core/local_backend/` tras M3.4 | Sin `APAP_SMTP_HOST`, el envío es no-op y el flujo magic-link queda inactivo en producción |
| MinIO (S3) | Almacenamiento de fotos de animales; conecta con un bucket MinIO autocreado en ``apap-photos`` (issue #641) | Variable de entorno; `APAP_S3_ENDPOINT`, `APAP_S3_ACCESS_KEY`, `APAP_S3_SECRET_KEY`, `APAP_S3_BUCKET`, `APAP_S3_SECURE` | Sin `APAP_S3_ACCESS_KEY`, `PhotoStorageClient` retorna la imagen placeholder PNG y el healthz reporta ``storage: unconfigured`` |
| GitHub Actions (CI) | Verificación aislada y entrega por digest | [`.github/workflows/`](../../.github/workflows/) | `ci / required` agrega los jobs fail-closed y bloquea el merge; deploy usa únicamente el runner con etiqueta `deploy` |
| Google OAuth | Identidad de usuario mediante ports de OAuth y auth | [`app/core/auth_flow.py`](../../app/core/auth_flow.py), `app/core/application/oauth/` | Sin `APAP_GOOGLE_CLIENT_ID` y `APAP_GOOGLE_CLIENT_SECRET`, el login responde 503 |
| Tailwind v4 CSS-first | Estilos sin `tailwind.config.js` | [`app/static/`](../../app/static/) + build command | Si el build falla, el CSS no se compila y la UI se ve sin estilos |
| Playwright (E2E) | Verificación end-to-end de UI; red contra template, route y CSRF (§23) | Smoke requerido en [`tests/e2e_ci/`](../../tests/e2e_ci/) y regresión amplia en [`tests/e2e/`](../../tests/e2e/) | El smoke requerido falla cerrado; la suite amplia conserva deuda explícita hasta su saneamiento |

## Variables de entorno

| Variable | Purpose | Default | Source of truth |
|---|---|---|---|
| `APAP_MODE` | Modo de middleware `web` o `test`; no selecciona backend de datos | `web` | [`app/core/config.py`](../../app/core/config.py) |
| `APAP_LOCAL_BACKEND` | Declaración heredada del contrato Coolify; el código Python actual no la consume | `true` en Coolify | [`coolify/apap-web-coolify.yaml`](../../coolify/apap-web-coolify.yaml) |
| `APAP_LOCAL_DB_URL` | DSN de PostgreSQL usado por el servicio web y la API separada | Vacío en `Settings`; producción debe configurarlo | [`app/core/config.py`](../../app/core/config.py) |
| `APAP_LOCAL_DB_SCHEMA` | `search_path` opcional | Vacío, conserva el default de PostgreSQL | [`app/core/config.py`](../../app/core/config.py) |
| `APAP_SESSION_SECRET` | Secreto de firma de cookies | Required (validado en startup) | [Runbook cookie-rotation](../runbooks/cookie-rotation.md) |
| `APAP_GOOGLE_CLIENT_ID` | Identificador OAuth de Google | Vacío | [`app/core/config.py`](../../app/core/config.py) |
| `APAP_GOOGLE_CLIENT_SECRET` | Secreto OAuth de Google | Vacío | [`app/core/config.py`](../../app/core/config.py) |
| `APAP_AUTH_CACHE_TTL_SECONDS` | TTL del caché de autorización en proceso | `300` | AGENTS §29, [Runbook auth-cache-multi-worker](../runbooks/auth-cache-multi-worker.md) |
| `APAP_SMTP_HOST` | Host SMTP (Resend en producción); activa `SMTPMailTransport` para magic-link | unset (no-op) | issue #649 + M3.4 |
| `APAP_SMTP_PORT` | Puerto SMTP (`465` para Resend TLS) | `587` | issue #649 + M3.4 |
| `APAP_SMTP_USER` | Usuario SMTP (`resend` en producción) | unset | issue #649 + M3.4 |
| `APAP_SMTP_PASSWORD` | API key / password SMTP | unset | issue #649 + M3.4 |
| `APAP_SMTP_FROM` | Dirección `From` de los magic-link | unset | issue #649 + M3.4 |
| `APAP_S3_ENDPOINT` | Host de MinIO (``minio:9000``) | `minio:9000` | [`app/core/local_backend/s3.py`](../../app/core/local_backend/s3.py) |
| `APAP_S3_ACCESS_KEY` | Usuario de MinIO | unset | [`app/core/local_backend/s3.py`](../../app/core/local_backend/s3.py) |
| `APAP_S3_SECRET_KEY` | Contraseña de MinIO | unset (secreto) | [`app/core/local_backend/s3.py`](../../app/core/local_backend/s3.py) |
| `APAP_S3_BUCKET` | Nombre del bucket de fotos | `apap-photos` | [`app/core/local_backend/s3.py`](../../app/core/local_backend/s3.py) |
| `APAP_S3_SECURE` | Usar HTTPS (``true/false``) | `false` | [`app/core/local_backend/s3.py`](../../app/core/local_backend/s3.py) |
| `COOLIFY_WEBHOOK_URL` | Webhook de deploy a Coolify | Required para deploy | AGENTS §15.1 |

## Contributor checklist

- [ ] Si añade una variable `APAP_*`, declárela en [`app/core/config.py`](../../app/core/config.py) con su `Field(...)` y, si porta un secreto, sin default usable (§32.P2).
- [ ] Si añade una integración nueva, agregue una fila a la tabla de integraciones con su `Purpose`, `Where configured` y `Failure mode`.
- [ ] Si modifica `LocalPostgresExecutor` o la API separada, actualice [Arquitectura LocalBackend](../architecture/architecture-local-backend-stack.md) en la misma sesión.
- [ ] Si añade un runbook nuevo (rotación de secreto, acción manual de operador), declárelo en [`docs/runbooks/`](../../docs/runbooks/) según §13.
- [ ] Si la integración toca un path sensible (auth, secretos, PII, SQL cruda), cree o actualice un doc en [`docs/audits/`](../../docs/audits/) según §12.

## Navigation

Previous: [Interfaces](interfaces.md) | Next: [Maintainer playbook](maintainer-playbook.md)
