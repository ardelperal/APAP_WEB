[← Back to roadmap hub](../roadmap.md)

# Fase 2 — Autenticación y autorización

Esta página posee el estado de la Fase 2: login real con Google OAuth vía LocalBackend y allowlist de correos autorizados, con panel admin para el rol `developer`. Fase cerrada.

## Estado

cerrado — Issue **#16** mergeada en `main` como `1d22349`. Login con Google OAuth (PKCE nativo contra LocalBackend), tabla `usuarios_autorizados` con seed bootstrap, middleware de allowlist, panel `/admin` para developers. Pendiente solo el primer deploy real cuando el DNS esté resuelto ([fase-0-infra-cicd.md](fase-0-infra-cicd.md) §"Pendiente no automatizable").

## Slices

| Slice | Estado | Issue | SHA |
|---|---|---|---|
| Login real con Google OAuth + allowlist | cerrado | #16 | `1d22349` |
| Panel admin para developers (`/admin`) | cerrado | — | parte de #16 |
| Tabla `usuarios_autorizados` con seed bootstrap | cerrado | #25 | — |

## Decisiones relacionadas

- [d-01-product-standalone.md](../architecture/decisiones/d-01-product-standalone.md) — producto profesional standalone.
- [d-02-home-dashboard.md](../architecture/decisiones/d-02-home-dashboard.md) — home como bandeja operativa.
- [d-03-dominio-animal.md](../architecture/decisiones/d-03-dominio-animal.md) — dominio centrado en animal.
- [d-20-stack-fastapi-htmx-local_backend.md](../architecture/decisiones/d-20-stack-fastapi-htmx-local_backend.md) — stack base + auth contra LocalBackend.
- [d-40-virginia-uat.md](../architecture/decisiones/d-40-virginia-uat.md) — Virginia como validadora UAT (post-MVP).

## Documentación de referencia

- [docs/architecture/architecture-local-backend-stack.md](../architecture/architecture-local-backend-stack.md) § "Authentication and authorization".
- [docs/architecture/decisiones-proyecto.md](../architecture/decisiones-proyecto.md) § D-01, D-03, D-20, D-40.

## Core invariants

- **Allowlist única fuente de verdad**: solo los correos en `usuarios_autorizados` pasan el middleware. El seed bootstrap es idempotente (`CREATE TABLE IF not EXISTS`). <!-- alantyle-ignore:ALAN003 -->
- **PKCE nativo contra LocalBackend**: el flujo OAuth no delega a redirecciones de cliente externo; la app es la que intercambia el code por token.
- **Rol `developer` único**: el panel `/admin` solo se monta para correos con `rol = 'developer'` en `usuarios_autorizados`.
- **Sesión firmada con cookie `SameSite=Strict`**: cada request re-evalúa `is_authorized` y `rol` desde la cache in-process (no del payload de la cookie).

## Contributor checklist

- [ ] Si añade un nuevo rol o un nuevo flujo OAuth, regístrelo en un ADR antes de implementar.
- [ ] Si modifica el middleware de allowlist, cubra con tests la regresión documentada en [docs/audits/auth-revalidation-2026-Q3.md](../audits/auth-revalidation-2026-Q3.md).
- [ ] Si toca un secret (`APAP_SESSION_SECRET`, `APAP_OAUTH_CLIENT_ID`, etc.), siga [docs/runbooks/cookie-rotation.md](../runbooks/cookie-rotation.md) y §32.P2.
- [ ] Si rota el secret OAuth o cambia el redirect URI, abra runbook de rotación y refresque `APAP_INSFORGE_URL` en Coolify.

## Navigation

Previous: [fase-1-esqueleto.md](fase-1-esqueleto.md) | Next: [fase-3-modelo-dominio.md](fase-3-modelo-dominio.md)
