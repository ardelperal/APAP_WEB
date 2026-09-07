[← Back to roadmap hub](../roadmap.md)

# Fase 0 — Infraestructura y CI/CD

Esta página posee el estado y los gates de la Fase 0: repositorio sano, CI verde, deploy automatizado a Coolify + LocalBackend. Fase cerrada. El detalle vivo de cada gate vive en su PR o SDD enlazado.

## Estado

cerrado — CI local verde, GitHub Actions verde, deploy automático a Coolify verificado, LocalBackend configurado. Pendiente solo lo no automatizable: crear el registro DNS de `apap.romancaba.com` y activar branch protection en la UI de GitHub.

## Slices

| Slice | Estado | Issue | PR / SHA | SDD |
|---|---|---|---|---|
| CI-01 superficie de tests local | cerrado | — | merged | `ci-cd-foundation` Phase 0 |
| CI-02 workflow de GitHub Actions | cerrado | — | merged | `ci-cd-foundation` Phase 1 |
| CD-02 build y push del runnable a Coolify | cerrado | #1 | #24 (`dc98c1c`) | `ci-cd-foundation` Phase 2 |
| CD-01 webhook automático GitHub → Coolify en `push: main` | cerrado | #1 | `225ef9c` (CI run 28674612470, 2026-07-03) | `ci-cd-foundation` Phase 2 |
| Branch protection activado en la rama protegida | pendiente | — | — | `ci-cd-foundation` tarea 1.5 |
| Harness E2E (Playwright) | pendiente | — | — | `E2E-01` (diferido a `staging`) |

## Pendiente no automatizable

Antes del primer deploy real, el mantenedor debe:

1. Crear el registro DNS A de `apap.romancaba.com` apuntando al servidor Coolify.
2. Verificar que el redirect URI registrado en Google Cloud Console / LocalBackend shared OAuth es `https://apap.romancaba.com/auth/callback`.
3. Activar branch protection en la UI de GitHub según `.github/branch-protection.md`.

## Decisiones relacionadas

- [d-20-stack-fastapi-htmx-local_backend.md](../architecture/decisiones/d-20-stack-fastapi-htmx-local_backend.md) — stack base de la Fase 0.
- [d-30-pre-mvp-single-branch.md](../architecture/decisiones/d-30-pre-mvp-single-branch.md) — todo a `main`, sin promoción a `staging`.
- [d-34-conventional-commits.md](../architecture/decisiones/d-34-conventional-commits.md) — mensajes de commit.
- [d-38-stagingonly-unset.md](../architecture/decisiones/d-38-stagingonly-unset.md) — `git config gentleai.stagingOnly` está `unset` en este repo.

## Documentación de referencia

- [docs/setup.md](../setup.md) — setup por desarrollador.
- [docs/architecture/architecture-local-backend-stack.md](../architecture/architecture-local-backend-stack.md) — composición y límites vigentes del stack LocalBackend.
- `openspec/changes/ci-cd-foundation/` — propuesta, diseño, tareas, spec, apply-progress.

## Core invariants

- **Webhook a Coolify es obligatorio en push a `main`**: cada merge a `main` ejecuta el job `deploy` con HMAC SHA-256 contra `COOLIFY_WEBHOOK_URL` + `COOLIFY_WEBHOOK_SECRET`.
- **CI gates no se saltan**: lint + typecheck + test + build deben estar en verde antes de merge (D-30, pre-MVP single-branch).
- **Deploy no se ejecuta en commits de merge**: el job `deploy` salta commits que matchean `^Merge pull request #`. Documentado como §32.P7.

## Contributor checklist

- [ ] Si un nuevo gate CI/CD entra en producción, actualice esta página y cruce referencia con [docs/architecture/architecture-local-backend-stack.md](../architecture/architecture-local-backend-stack.md).
- [ ] Si crea el DNS o activa branch protection, retire los pendientes de "no automatizable" en la misma PR.
- [ ] Si añade un paso al job `deploy`, pinee la condición en `tests/test_ci_workflow.py` (§32.P7).
- [ ] Si un secret nuevo entra en `Settings`, siga §32.P2: pydantic falla o el lifespan rehúsa servir.

## Navigation

Previous: [roadmap.md](../roadmap.md) | Next: [fase-1-esqueleto.md](fase-1-esqueleto.md)
