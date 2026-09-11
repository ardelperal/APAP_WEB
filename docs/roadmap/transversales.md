[← Back to roadmap hub](../roadmap.md)

# Capacidades transversales

Esta página posee las capacidades que cruzan varias fases del roadmap: seguridad, observabilidad, calidad y dev workflow. Cada bloque conserva su referencia al gate o skill que lo sostiene.

## Seguridad

Capacidades que cubren auth, CSRF, RBAC, redacción de PII y rotación de secretos.

| Capacidad | Estado | Doc de referencia |
|---|---|---|
| Auth + allowlist (`usuarios_autorizados`) | cerrado | [fase-2-auth-allowlist.md](fase-2-auth-allowlist.md) |
| `CsrfMiddleware` + token en cada form POST + `SameSite=Strict` | cerrado | [docs/codebase/csrf-defense.md](../codebase/csrf-defense.md) |
| Redacción de PII (12 → 15 campos: `dni`, `tel1`, `tel2`, etc.) | cerrado (auditoría **PASS**) | [docs/audits/pii-live-migration-2026-Q3.md](../audits/pii-live-migration-2026-Q3.md) |
| Re-validación de `is_authorized` y `rol` por request (auth cache in-process) | cerrado (auditoría **PASS**) | [docs/audits/auth-revalidation-2026-Q3.md](../audits/auth-revalidation-2026-Q3.md) |
| RBAC-01 matriz de permisos API | cerrado; regresión de rutas de escritura corregida en #679 | #66, #679 |
| Rotación de `APAP_SESSION_SECRET` | cerrado (runbook) | [docs/runbooks/cookie-rotation.md](../runbooks/cookie-rotation.md) |

Decisiones: [d-02-home-dashboard.md](../architecture/decisiones/d-02-home-dashboard.md), [d-20-stack-fastapi-htmx-local_backend.md](../architecture/decisiones/d-20-stack-fastapi-htmx-local_backend.md), [d-40-virginia-uat.md](../architecture/decisiones/d-40-virginia-uat.md).

## Observabilidad

Logging estructurado, traza canónica correlacionada y panel de control para configuración funcional y diagnóstico.

| Capacidad | Estado | Doc de referencia |
|---|---|---|
| `log_safe` único en `app/` con redacción de doce campos | cerrado | [docs/codebase/logging-conventions.md](../codebase/logging-conventions.md) |
| Traza canónica (eventos JSON correlacionados) | en curso | #749 ([docs/canonical-logs.md](../canonical-logs.md)) |
| Panel de control / configuración funcional | pendiente | issue por crear |
| Diagnóstico de entorno (Dysflow `dysflow_doctor`) | cerrado | [d-31-resolucion-dudas-dominio.md](../architecture/decisiones/d-31-resolucion-dudas-dominio.md) |

Doc fundacional publicado en [docs/canonical-logs.md](../canonical-logs.md); trazabilidad end-to-end (header + log JSON) pineada por `tests/test_log_safe_correlation_id.py` (ya cerrado en #334) y `tests/e2e/test_correlation_id_e2e.py`.

## Calidad

Cobertura, linter, mypy, E2E y ratchets. Estado del arnés en [docs/quality/hardening-roadmap.md](../quality/hardening-roadmap.md).

| Capacidad | Estado | Doc / Gate |
|---|---|---|
| Cobertura 85% (global) | cerrado (con BASELINE shrink-only por capa) | [docs/codebase/quality-gates.md](../codebase/quality-gates.md) |
| Linter APAP (ruff + custom) | cerrado | [docs/codebase/code-quality-rules.md](../codebase/code-quality-rules.md) |
| mypy zero errores | cerrado | [docs/codebase/quality-gates.md](../codebase/quality-gates.md) |
| E2E smoke (Playwright) | cerrado; CI levanta aplicación real, PostgreSQL y autenticación aislada | #694 |
| Suite E2E histórica sin skips condicionales | pendiente; fuera del required check hasta su saneamiento | #694 |

#### Batería E2E por slice

Cada slice que aterriza en `main` necesita su batería E2E con Playwright. La batería se escribe al mismo tiempo que el slice (no como tarea posterior). El estado de cada batería se documenta en la página radial de su fase.

**Política de ejecución en CI:**

| Gatillo | ¿Corre la batería E2E? |
|---|---|
| PR a `main` (cualquier slice) | **Sí** — aplicación real, PostgreSQL efímero y Chromium |
| Ejecución programada | **No** — el contrato del agregador autoriza este único skip |
| Push de tag `v*` | **Sí** — batería completa antes de distribuir |

**Objetivo:** validar que todos los flujos end-to-end operan con datos reales de LocalBackend antes de cada release. La batería no sustituye los tests unitarios ni de integración — los complementa cubriendo la cadena completa HTTP → servicio → base de datos → HTML.

**Formato de cada batería E2E:**

```
tests/e2e/test_<slice>_crud.py  —  CRUD Happy path
tests/e2e/test_<slice>_errors.py  —  Errores: 409, 422, 404, 403
tests/e2e/test_<slice>_lifecycle.py  —  Transiciones de estado
tests/e2e/test_<slice>_auth.py  —  Auth: 302, 403 según rol
```

Un slice puede necesitar 1 o 4 ficheros según su complejidad. Lo mínimo es `*_crud.py`.

**Inventario de baterías por fase:** ver las páginas radiales de cada fase.
| Mutation testing | cerrado (runbook) | [docs/runbooks/mutation-testing.md](../runbooks/mutation-testing.md) |
| Anti-patrones documentados (§32) | cerrado (auditoría 2026-07-25) | [docs/codebase/anti-patterns.md](../codebase/anti-patterns.md) |

Decisiones: [d-33-tdd-estricto.md](../architecture/decisiones/d-33-tdd-estricto.md), [d-35-presupuesto-400-lineas-pr.md](../architecture/decisiones/d-35-presupuesto-400-lineas-pr.md).

## Dev workflow

Workflow de mantenedor: migraciones en vivo, UX/UI, motor de tareas, idioma y documentación, merge, commits.

### Migración en vivo del legacy

Objetivo: backend privado LocalBackend poblado con datos y fotos reales del Access legacy, en una sola dirección controlada y verificable, antes de abrir Fases 4–7 a datos productivos.

| Sub-fase | Estado |
|---|---|
| PR1/M0 → PR6/M2 | cerrado |
| PR7 / `verify-fallback-ready` (gate obligatorio antes de retirar el Access legacy como fuente operativa) | pendiente |

**Issues de migración abiertas** (sub-fallos de PR5 forward / pendientes para PR6 reverse):

- #217 `apply_reverse` increment semantics del `dni_collision_counter`.
- #218 `execute_legacy_write` swallowing `conn.commit()` failure.
- #219 `_PII_VALUE_PATTERNS` NIE/NIF-especiales/numeric-NCHIP.

**Invariantes no negociables:**

- **Privacidad de datos y fotos**: bucket `apap-photos` con `isPublic=false`. La ruta `GET /animales/{animal_id}/foto` exige sesión válida (302 a `/login` si no autenticado), consume el stream antes de construir la respuesta para convertir fallos iniciales, mid-stream y de lookup SQL en el PNG placeholder, y nunca expone la URL presignada.
- **M1 forward usable no es fallback-ready**: tener M1 verde (animales, voluntarios, entradas y fotos migrados vía `apply_legacy_to_web`) no equivale a poder volver atrás mientras el legacy siga siendo la fuente. El gate `verify-fallback-ready` (PR7) sigue siendo obligatorio.
- **TDD estricto, fixture-first, idempotente**: cada PR arranca con RED (tests antes de código) bajo `tests/migration/` y `tests/test_*.py`.
- **Ejecución con datos reales solo tras los gates de código**: las unidades de trabajo de operador (`ensure-bucket --check-only`, `apply --check-only`, `apply`, `reconcile --check-only`, `status --photos`, `verify-fallback-ready --full`) se ejecutan exclusivamente después de que los gates de código estén verdes.

Documentación: `openspec/changes/live-data-migration-sandbox/{proposal.md,tasks.md,specs/}`, [docs/runbooks/live-migration-apply.md](../runbooks/live-migration-apply.md), [docs/discovery/migration-risks.md](../discovery/migration-risks.md).

### Foundation UX/UI y Dashboard

| Slice | Estado | Issue |
|---|---|---|
| Foundation UX/UI | pendiente | #6 |
| Dashboard inicial + bandeja de pendientes | cerrado (capacidad migrada a `/` por #127, #131) | ver [legacy-initial-dashboard.md](../legacy-initial-dashboard.md) |
| Búsqueda global | pendiente | issue por crear |

Documentación: [docs/architecture/decisiones-proyecto.md](../architecture/decisiones-proyecto.md) § "Dirección visual" / "Relación con la UX legacy" / "Dashboard de pendientes y navegación" / "Búsqueda global", [docs/design-tokens-apap-actual.md](../design-tokens-apap-actual.md).

### Motor de tareas

| Slice | Estado | Issue |
|---|---|---|
| Motor común de tareas (manual + automáticas) | pendiente | #7 |

Documentación por crear al arrancar la issue.

### Traza canónica y panel de control

| Slice | Estado | Issue |
|---|---|---|
| Traza canónica (eventos JSON correlacionados) | en curso | #749 ([docs/canonical-logs.md](../canonical-logs.md)) |
| Panel de control / configuración funcional | pendiente | issue por crear |

### Documentación unificada en castellano

Alineación de toda la documentación técnica con el idioma del proyecto (decisión del 2026-06-17).

| Slice | Estado | Issue |
|---|---|---|
| Documentación actual en castellano de `docs/architecture/architecture-local-backend-stack.md` | completada | issue #676 |
| Traducción al castellano de `docs/development.md` | pendiente | issue por crear |
| Revisión y traducción de los `docs/discovery/*.md` que aún estén en inglés | pendiente | issue por crear |

### Workflow de merge y commits

Decisiones: [d-30-pre-mvp-single-branch.md](../architecture/decisiones/d-30-pre-mvp-single-branch.md), [d-34-conventional-commits.md](../architecture/decisiones/d-34-conventional-commits.md), [d-35-presupuesto-400-lineas-pr.md](../architecture/decisiones/d-35-presupuesto-400-lineas-pr.md), [d-37-convenciones-idioma.md](../architecture/decisiones/d-37-convenciones-idioma.md), [d-38-stagingonly-unset.md](../architecture/decisiones/d-38-stagingonly-unset.md).

Documentación: [docs/codebase/merge-workflow.md](../codebase/merge-workflow.md), [docs/codebase/orchestrator-discipline.md](../codebase/orchestrator-discipline.md).

### Arquitectura hexagonal por vertical slices

Si va a escribir código nuevo, esta subsección manda sobre los ejemplos de las páginas de fase. El detonante del refactor: `app/core/*.py` importaba `LocalBackendClient` directamente; el backend no era sustituible y la lógica no era testeable sin transporte.

**Slices en `main`** (hexagonal, transversales en `app/core/`, capacidades en `app/modules/`):

| Slice | PR | Encapsula |
|---|---|---|
| auth-users | #414 | `usuarios_autorizados` — plantilla del patrón. |
| catalogos | #415 | Tablas de catálogo (`list_periodicidad`, `list_tipos_contrato`, …). |
| schema-bootstrap | #416 | `ensure_domain_schema` + `run_idempotent_sql`. |
| migration-web | #417 | Lado lectura de migración web (`WebReaderPort`). |
| auth-flow / oauth | #418 | Flujo OAuth completo (PKCE, sesión, 4 casos de uso). |
| admin | #419 | Rutas admin → casos de uso + `AdminTemplateAdapter`. |

**Regla de ubicación** ([AGENTS.md](../../AGENTS.md) §33.2):

- **`app/core/<capa>/<slice>/`** — transversal: lo consumen 2+ slices y no tiene razón de negocio propia para cambiar.
- **`app/modules/<slice>/`** — capacidad de negocio; el slice entero en una carpeta: `domain/`, `ports/`, `application/`, `adapters/local-backend/`, `di/`, `routes.py` fino.
- **Ante la duda, módulo.** Promover a `core` después es barato; sacarlo de `core` con cinco consumidores colgando, no.

**Invariantes**: `LocalBackendClient`/`BackendError` solo bajo `adapters/` y `di/` (más `app/main.py`, que construye el cliente); ningún `service.py` nuevo que ejecute SQL; ningún criterio de aceptación que nombre al proveedor; un test de pin arquitectónico por slice que falle si un import de transporte se cuela de capa.

**Deuda registrada**: `admin` está en `core` sin cumplir la regla (un solo consumidor). Excepción deliberada documentada en [AGENTS.md](../../AGENTS.md) §33.5 y en #420 — **no sirve de precedente** para meter la siguiente capacidad de negocio en `core`.

**Backlog del refactor**:

1. `auth-dependencies` — `app/core/auth_dependencies.py`, último seam de auth en core.
2. **Slices de módulo** — 22 ficheros en 11 módulos (`acogidas`, `adopciones`, `animals`, `cesiones`, `entradas`, `foster`, `materiales`, `salud`, `sanidad`, `tasks`, `voluntarios`). Independientes entre sí → PRs encadenables.
3. Cola de migración/infra — `migration/{apply,bootstrap,cli,cli_apply_reverse}.py`, `app/core/migration/sql_runner.py`, `app/core/tasks/scheduler.py`.

Medición de progreso (un solo comando):

```bash
git grep -n "^\s*from app.core.local_backend import" -- 'app/**.py' 'migration/**.py' | wc -l
```

Legítimos son los `app/core/di/*_di.py` y `app/main.py`; el resto es backlog.

Documentación: [docs/architecture/capas-y-slices.md](../architecture/capas-y-slices.md), [docs/codebase/architecture.md](../codebase/architecture.md), épica #420 (índice vivo de slices).

### Self-host backend (Coolify)

Reemplazo del backend LocalBackend por un contenedor FastAPI propio desplegado en Coolify, en el mismo VPS que el front. El branch activo del esfuerzo es `feat/641-self-host-backend-coolify` (issue umbrella #641). El switch de runtime vive en `app/core/local_backend_url.py` con la variable `APAP_LOCAL_BACKEND`; los commits `c12b361 feat(local_backend): default to local backend when APAP_LOCAL_BACKEND=true` y `b10a88d fix(local_backend): local backend base_url must not carry /api prefix` documentan el corte.

| Sub-fase | Estado en branch | Issue |
|---|---|---|
| M0 — `LocalPostgresExecutor` + healthz + storage + client switch | cerrado | #641 |
| M1 — `MagicLinkPort` + `ClassicPasswordAuthPort` (self-host auth) | cerrado | #641 |
| M2 — `.env.example` + runbook + docs de deploy Coolify | cerrado | #641 |
| M3 — UI: form magic-link + CSP (M3-login, M3.2-csp) | cerrado | — |
| M3.1 — Helper + fixtures + unit tests del helper | wip (round-trip E2E skip'd) | #649 |
| M3.4 — Magic-link wiring + `SMTPMailTransport` en `local_backend/app.py` | pendiente | issue a crear |
| Phase 3 — Coolify deploy manifest + `.accdb` legacy migration + runbook operador | pendiente | #648 |
| Phase 5 — Deploy step separado del lifespan bootstrap | pendiente | #647 |
| Hygiene — Pre-existing ruff errors + failing e2e | pendiente | #646 |

**Estado del round-trip M3.1**: el helper lee de MailDev HTTP API (`apap-smtp-dev`); los unit tests del helper están verdes en el suite default (regex, polling, timeout, retry sobre 5xx); el test E2E se archiva con `pytest.mark.skip` cuya razón apunta a M3.4. La unidad de trabajo "M3.1 wip" cierra cuando se commitee el helper + conftest + unit tests + skip documentado.

**Invariante no negociable:**

- **Contenedor único en Coolify, sin LocalBackend en producción**: el contenedor `app/core/local_backend/app.py` reemplaza a LocalBackend para el path de datos autenticado. Mantener `APAP_LOCAL_BACKEND=true` en Coolify; el binario de LocalBackend queda solo como fallback de desarrollo local.

## Issues pendientes de crear (consolidado)

| Fase / Área | Título tentativo | Depende de |
|---|---|---|
| Self-host | `feat(m3-4): magic-link wiring + SMTPMailTransport en local_backend/app.py` | #649 cerrado |
| Self-host | `chore(phase-3): Coolify deploy manifest + .accdb legacy migration + runbook operador` | M3.4 cerrado |
| Self-host | `chore(phase-5): separar deploy step del lifespan bootstrap` | Phase 3 |
| Hygiene | `chore(hygiene): pre-existing ruff errors + failing e2e test` | — |
| Migración en vivo PR7 | `feat(migration): verify-fallback-ready + gate CI` | PR6 cerrado |
| Transversal | `feat(dashboard): bandeja de pendientes + realtime` | Fase 2 |
| Transversal | `feat(search): búsqueda global` | Fases 3–4 |
| Transversal | `feat(canonical-logs): traza canónica del sistema` | Fase 1 |
| Transversal | `feat(admin-panel): panel de control / configuración` | Fases 1–2 |
| Docs | `docs(architecture): traducir architecture-local-backend-stack.md al castellano` | — |
| Docs | `docs(architecture): d-42-self-host-backend-coolify.md — decisión arquitectónica del corte` | — |
| Docs | `docs(development): traducir development.md al castellano` | — |
| Docs | `docs(discovery): revisar y traducir los discovery en inglés al castellano` | — |
| Docs | `docs(canonical-logs): crear el doc fundacional de traza canónica` | bloqueado por la issue de arriba |
| Docs | `docs(CODEBASE-GUIDE): crear guía de mantenedores 90-second mental model` | — |
| Docs | `docs(runbooks/<area>): runbooks adicionales por área` | — |
| Docs | `docs(audits/<feature>-audit-YYYY-Qn.md): auditorías adicionales` | — |
| Docs | `app/modules/<area>/README.md: README por módulo (mantenedor)` | — |

## Core invariants

- **TDD estricto**: tests antes de código en cualquier issue que produzca código ([d-33-tdd-estricto.md](../architecture/decisiones/d-33-tdd-estricto.md)).
- **Pre-MVP single-branch**: todo va a `main` ([d-30-pre-mvp-single-branch.md](../architecture/decisiones/d-30-pre-mvp-single-branch.md), §15 de AGENTS).
- **Castellano para docs de producto, inglés para artefactos técnicos** ([d-37-convenciones-idioma.md](../architecture/decisiones/d-37-convenciones-idioma.md)).
- **Superset funcional del legacy**: gap abre `type:bug gap:legacy` ([d-05-fidelidad-legacy-superset.md](../architecture/decisiones/d-05-fidelidad-legacy-superset.md), P1).
- **CodeGraph es read path principal** ([d-21-codegraph-read-path.md](../architecture/decisiones/d-21-codegraph-read-path.md), §14 de AGENTS).

## Contributor checklist

- [ ] Si un transversal toca varias fases, abra primero un change SDD en `openspec/changes/` y cite esta página en `proposal.md`.
- [ ] Si descubre una referencia rota en esta página, márquela como **ROTA** y abra issue `type:docs`.
- [ ] Si un gate de calidad baja del suelo declarado, abra runbook de remediación en `docs/runbooks/`.
- [ ] Si traduce un doc al castellano, siga el patrón `documentation-alan-style` y actualice la tabla de estado de "Documentación unificada".

## Navigation

Previous: [fase-7-documentos-contratos-informes.md](fase-7-documentos-contratos-informes.md) | Back: [roadmap.md](../roadmap.md)
