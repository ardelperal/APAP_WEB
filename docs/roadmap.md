# Hoja de Ruta Viva — APAP_WEB

El roadmap de APAP_WEB codifica las fases del producto, el estado actual por epic y los gates que hay que cerrar para llegar a MVP; se mantiene vivo en cada ciclo de entrega (no es una tarea aparte).

[Quick Navigation](#quick-navigation) · [Proceso](proceso.md) · [AGENTS.md](../AGENTS.md) · [README](../README.md)

---

## Quick Navigation

| Sección | Para qué |
|---|---|
| [Estado actual](#estado-actual) | Snapshot de infra, auth, módulos y slices hexagonales. |
| [Arquitectura: hexagonal por vertical slices](#arquitectura-hexagonal-por-vertical-slices) | Regla de ubicación y slices ya en `main`. |
| [Hoja de ruta por fases](#hoja-de-ruta-por-fases) | Fases 0–7 + transversales con estado y epic. |
| [Issues abiertos](#issues-abiertos) | Representativa de issues `open`; el comando `gh` es autoritativo. |
| [Issues pendientes de crear](#issues-pendientes-de-crear) | Lo que falta abrir en GitHub. |
| [Cuándo ir al legacy directamente](#cuándo-ir-al-legacy-directamente) | Orden discovery → legacy doc → Dysflow. |
| [Convenciones del proyecto](#convenciones-del-proyecto) | Idioma, commits, labels, merge, RBAC. |
| [Índice de documentación](#índice-de-documentación) | Dónde mirar para cada pregunta. |
| [Cómo mantener este documento](#cómo-mantener-este-documento) | Regla de sync con `main` en cada merge. |

**Mantenedor único:** aroman (autoaprueba issues y PRs).
**Rama objetivo actual:** pre-MVP single-branch — todo va a `main`, una sola rama al final del ciclo (ver §"Convenciones del proyecto" y [`AGENTS.md`](../AGENTS.md) §15).
**Idioma:** castellano (España) para docs, issues y PRs; inglés para artefactos técnicos (código, comentarios, docstrings).

---

## Estado actual

| Área | Estado | Detalle |
|---|---|---|
| Repositorio `ardelperal/APAP_WEB` | en verde | Creado, `main` como rama por defecto. |
| CI local (`pytest` + `ruff` + `mypy` + `build`) | en verde | Fase 0 de `ci-cd-foundation` mergeada en `main`. |
| GitHub Actions | en verde | Jobs `lint`, `typecheck`, `test`, `build` en PRs y push a `main`; `deploy` en push a `main` (skip en merge commits). Pre-MVP single-branch: ya no hay push a `staging` ([AGENTS.md](../AGENTS.md) §15). |
| Branch protection en la rama protegida activa | pendiente | Documentado en `.github/branch-protection.md`; pendiente de activar en la UI de GitHub. |
| Coolify + app `apap-web` | en verde | Aprovisionado, apunta a `ardelperal/APAP_WEB:main`, fqdn `apap.romancaba.com`. |
| DNS `apap.romancaba.com` | pendiente | Pendiente de crear por el mantenedor antes del primer deploy real. |
| Fix de dominio OAuth (redirect URI) | en verde | `APAP_GOOGLE_REDIRECT_URI` corregido en Coolify; redeploy OK. |
| Build y push del runnable a Coolify | en verde | Mergeado en `main` como `dc98c1c` (PR #24) — Dockerfile corregido, build verificado. |
| Webhook automático GitHub → Coolify en `push: main` | en verde | Implementado y verificado (CI run 28674612470 el 2026-07-03). Job `deploy` ejecuta `scripts/coolify_webhook.py` con HMAC SHA-256 contra `COOLIFY_WEBHOOK_URL` + `COOLIFY_WEBHOOK_SECRET`. |
| Backend InsForge | en verde | Verificado, MCP configurado; `APAP_INSFORGE_URL` apuntando a `c3uc9dk6.eu-central.insforge.app`. |
| Tabla `usuarios_autorizados` en InsForge | en verde | Creada y seedeada; idempotente con `CREATE TABLE IF NOT EXISTS`. |
| Esqueleto de la app FastAPI | en verde | Mergeado en `main` como `d0b1ed1` (issue #17). |
| Login real con Google OAuth + allowlist | en verde | Mergeado en `main` como `1d22349` (issue #16). Pendiente solo el primer deploy real cuando el DNS esté resuelto. |
| Foundation UX/UI | pendiente | Issue #6 abierta. |
| Motor común de tareas | pendiente | Issue #7 abierta. |
| Hoja de ruta viva | en verde | Esta issue #14 (mergeada en `69b509e`), regen. Tier 1 en PR #464. |

---

## Arquitectura: hexagonal por vertical slices

> **Si vas a escribir código nuevo, esta sección manda sobre los ejemplos de §"Hoja de ruta por fases".**
> Fuentes autoritativas: [`AGENTS.md`](../AGENTS.md) §33 (la regla, enforceable en review) y la épica #420 (índice vivo de slices, orden de ejecución y definition of done). Este bloque es el resumen; si discrepan, gana `AGENTS.md`.

### Qué cambió

La arquitectura dejó de ser "FastAPI + service layer" y pasó a **hexagonal con vertical slices**. El detonante: `app/core/*.py` importaba `InsForgeClient` directamente, así que el backend no era sustituible y la lógica no era testeable sin transporte.

### Slices en `main`

| Slice | PR | Qué encapsula |
|---|---|---|
| auth-users | #414 | `usuarios_autorizados` — plantilla del patrón para el resto. |
| catalogos | #415 | Tablas de catálogo (`list_periodicidad`, `list_tipos_contrato`, …). |
| schema-bootstrap | #416 | `ensure_domain_schema` + `run_idempotent_sql`. |
| migration-web | #417 | Lado lectura de migración web (`WebReaderPort`). |
| admin | #419 | Rutas admin → casos de uso + `AdminTemplateAdapter`. |
| auth-flow / oauth | #418 | Flujo OAuth completo (PKCE, sesión, 4 casos de uso). |

### Dónde va cada cosa (regla corta; la larga en [AGENTS.md](../AGENTS.md) §33.2)

- **`app/core/<capa>/<slice>/`** — transversal: lo consumen **2+ slices** *y* no tiene razón de negocio propia para cambiar. Las dos mitades son obligatorias.
- **`app/modules/<slice>/`** — capacidad de negocio; el slice entero en una carpeta: `domain/`, `ports/`, `application/` (un caso de uso por fichero), `adapters/insforge/` (con su `<slice>_insforge_queries.py`, [AGENTS.md](../AGENTS.md) §22), `di/`, y un `routes.py` fino.
- **Ante la duda, módulo.** Promover a `core` después es barato; sacarlo de `core` con cinco consumidores colgando, no.

Invariantes: `InsForgeClient`/`InsForgeError` solo bajo `adapters/` y `di/` (más `app/main.py`, que construye el cliente); ningún `service.py` nuevo que ejecute SQL; ningún criterio de aceptación que nombre al proveedor; un test de pin arquitectónico por slice que falle si un import de transporte se cuela de capa.

**Deuda registrada:** `admin` está en `core` sin cumplir la regla (un solo consumidor). Excepción deliberada documentada en [AGENTS.md](../AGENTS.md) §33.5 y en #420 — **no sirve de precedente** para meter la siguiente capacidad de negocio en `core`.

### Lo que falta

1. `auth-dependencies` — `app/core/auth_dependencies.py`, último seam de auth en core.
2. **Slices de módulo** — 22 ficheros en 11 módulos (`acogidas`, `adopciones`, `animals`, `cesiones`, `entradas`, `foster`, `materiales`, `salud`, `sanidad`, `tasks`, `voluntarios`). Independientes entre sí → PRs encadenables.
3. Cola de migración/infra — `migration/{apply,bootstrap,cli,cli_apply_reverse}.py`, `app/core/migration/sql_runner.py`, `app/core/tasks/scheduler.py`.

Medición de progreso (un solo comando):

```bash
git grep -n "^\s*from app.core.insforge import" -- 'app/**.py' 'migration/**.py' | wc -l
```

Legítimos son los `app/core/di/*_di.py` y `app/main.py`; el resto es backlog.

### Backlog ya alineado

16 issues anteriores al refactor se adaptaron para que su implementación futura no sea ambigua: #33, #54, #56–#64 llevan un bloque "Contrato de arquitectura"; #341, #387, #390, #392 y #395 llevan nota de coordinación porque tocan ficheros que el refactor reubica.

---

## Hoja de ruta por fases

Leyenda: en verde = completado · en curso = en curso · pendiente = pendiente · bloqueado = bloqueado.

### Fase 0 — Infraestructura y CI/CD

Objetivo: repositorio sano, CI verde, deploy automatizado a Coolify + InsForge.

| Slice | Estado | Issue | PR / SHA | SDD |
|---|---|---|---|---|
| CI-01 superficie de tests local | en verde | — | merged | `ci-cd-foundation` Phase 0 |
| CI-02 workflow de GitHub Actions | en verde | — | merged | `ci-cd-foundation` Phase 1 |
| CD-02 build y push del runnable a Coolify | en verde | #1 | #24 (`dc98c1c`) | `ci-cd-foundation` Phase 2 |
| CD-01 webhook automático GitHub → Coolify en `push: main` | en verde (código en `225ef9c` + dry-run real verificado en CI run 28674612470 el 2026-07-03) | #1 | — | `ci-cd-foundation` Phase 2 |
| Branch protection activado en la rama protegida activa | pendiente | — | — | `ci-cd-foundation` tarea 1.5 |
| Harness E2E (Playwright) | pendiente | — | — | `E2E-01` (diferido a `staging`) |

**Pendiente del primer deploy real (no automatizable):** crear el registro DNS A de `apap.romancaba.com` apuntando al servidor Coolify y verificar que el redirect URI registrado en Google Cloud Console / InsForge shared OAuth es `https://apap.romancaba.com/auth/callback`.

**Documentación de referencia:** [`docs/setup.md`](setup.md) (setup por desarrollador), [`docs/architecture/architecture-insforge-stack.md`](architecture/architecture-insforge-stack.md) (decisiones de stack), [`openspec/changes/ci-cd-foundation/`](../openspec/changes/ci-cd-foundation/) (propuesta, diseño, tareas, spec, apply-progress).

### Fase 1 — Esqueleto de la aplicación web (#17)

Objetivo: `app/` mínimo con FastAPI + Jinja2 + Tailwind compilando, sin reglas de negocio todavía.

en verde — Cerrada. Issue **#17** mergeada en `main` como `d0b1ed1`. Desbloquea Fase 2 (#16) y Fase 3.

### Fase 2 — Autenticación y autorización (#16)

Objetivo: login real con Google OAuth vía InsForge y allowlist de correos autorizados, con panel admin para el rol `developer`.

en verde — Cerrada. Issue **#16** mergeada en `main` como `1d22349`. Login con Google OAuth (PKCE nativo contra InsForge), tabla `usuarios_autorizados` con seed bootstrap, middleware de allowlist, panel `/admin` para developers. Pendiente solo el primer deploy real cuando el DNS esté resuelto.

Documentación de referencia: [`docs/architecture/architecture-insforge-stack.md`](architecture/architecture-insforge-stack.md) § "Authentication and authorization", [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § D-01, D-03, D-20, D-40.

### Fase 3 — Modelo de dominio limpio (Animal + Volunteer + anexos)

Objetivo: tablas `animals`, `volunteers`, `authorized_users` y la tabla mínima de anexos. Sin UI de producto todavía.

en curso — `usuarios_autorizados` en verde (#25). `animals`, `volunteers`, `volunteer_roles` en verde (#26). Pendiente: `animal_event_log` (Fase 4 con CRUD) y `attachments` (Fase 7 con bucket de Storage). Bloquea Fases 4–7.

Documentación de referencia: [`docs/architecture/architecture-insforge-stack.md`](architecture/architecture-insforge-stack.md) § "Data model policy", [`docs/discovery/data-model-notes.md`](discovery/data-model-notes.md), [`docs/discovery/data-model-completeness.md`](discovery/data-model-completeness.md), [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § D-04 (paridad de campos), D-05 (fidelidad al legacy).

### Fase 4 — Entidad Animal (Feature 01)

Objetivo: CRUD de animales, búsqueda parametrizada, timeline de eventos y motor de estado derivado.

pendiente — pendiente de crear issue. Depende de Fase 3.

Documentación de referencia: [`docs/discovery/feature-01-animal-lifecycle.md`](discovery/feature-01-animal-lifecycle.md), [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Timeline del animal" / "Ficha del animal: inspiración legacy" / "Propuesta automática de transición".

### Fase 5 — Voluntarios + Entradas + Acogidas + Adopciones (Feature 02)

Objetivo: flujos operativos centrales con asistentes por pasos y snapshots históricos de personas.

en curso — Fases 5a INTAKE y 5b FOSTER cerradas; Fases 5c ADOPT y 5d VOL en curso. Próximos slices abiertos: VOL-02..05 (#35–#38), ADOPT-03 (#49), FOSTER-04 (#46, atomicidad `record_override` ↔ `create_acogida`).

Documentación de referencia: [`docs/discovery/feature-02-intake-foster-adoption.md`](discovery/feature-02-intake-foster-adoption.md), [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § D-03 (dominio centrado en Animal), D-05 (fidelidad al legacy), [`docs/legacy-volunteer-roles.md`](legacy-volunteer-roles.md), [`docs/legacy-lifecycle-transition-rules.md`](legacy-lifecycle-transition-rules.md).

### Fase 6 — Salud, Terapias e Inventario de Material (Feature 03)

Objetivo: registro sanitario con periodicidad, terapias con recomendaciones, inventario de material con disponibilidad e historial de asignaciones.

pendiente — pendiente de crear issues (uno por sub-flujo). Depende de Fases 3–4. Próximos: HEALTH-02..06 (#51–#55).

Documentación de referencia: [`docs/discovery/feature-03-health-care.md`](discovery/feature-03-health-care.md), [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md), [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Pestaña Salud del animal" / "Pestaña Terapias del animal" / "Terapias: inventario de material y asignación".

### Fase 7 — Documentos, Contratos, Informes y Consultas (Feature 04)

Objetivo: anexos, motor de plantillas documentales, los 8 tipos de contrato, módulo de Consultas propio e informe trimestral.

pendiente — pendiente de crear issues (uno por sub-flujo). Depende de Fases 3–6. Próximos: DOC-01..04 (#56–#59), REPORT-01..05 (#60–#64).

Documentación de referencia: [`docs/discovery/feature-04-documents-contracts-reports.md`](discovery/feature-04-documents-contracts-reports.md), [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Motor de plantillas documentales" / "Documentos generados como fuente de verdad" / "Organización de documentos y anexos" / "Flujo de contratos para firma y firmados" / "Consultas como módulo de primer nivel" / "Informe trimestral — alcance core", [`docs/legacy-signed-contract-flow.md`](legacy-signed-contract-flow.md).

### Fase transversal — Migración en vivo del legacy

Objetivo: disponer de un backend privado (InsForge) poblado con los datos y las fotos reales del Access legacy, en una sola dirección controlada y verificable, antes de abrir Fases 4–7 a datos productivos.

en curso — PR1/M0 → PR6/M2 cerrados; **PR7/`verify-fallback-ready` es el siguiente paso obligatorio** antes de cualquier decisión de retirar el Access legacy como fuente operativa. El round-trip M2 ya prueba ida-y-vuelta como capacidad, pero no certifica la decisión de retirar el legacy — esa certificación la cierra PR7.

**Invariantes no negociables (definidas por `proposal.md` y `tasks.md`):**

- **Privacidad de datos y fotos**: bucket `apap-photos` con `isPublic=false`. La ruta `GET /animales/{animal_id}/foto` exige sesión válida (302 a `/login` si no autenticado), consume el stream antes de construir la respuesta para convertir fallos iniciales, mid-stream y de lookup SQL en el PNG placeholder, y nunca expone la URL presignada. `REDACTED_FIELDS` pasó de 12 a 15 (`dni`, `tel1`, `tel2`); la auditoría de PII quedó en **PASS**.
- **M1 forward usable NO es fallback-ready**: tener M1 verde (animales, voluntarios, entradas y fotos migrados vía `apply_legacy_to_web`) NO equivale a poder volver atrás mientras el legacy siga siendo la fuente. **El gate `verify-fallback-ready` (PR7) sigue siendo obligatorio** antes de cualquier decisión de retirar el Access legacy como fuente operativa.
- **TDD estricto, fixture-first, idempotente**: cada PR arranca con RED (tests antes de código) bajo `tests/migration/` y `tests/test_*.py`. No existe E2E autenticado en CI todavía — `tests/e2e/` sigue siendo público-only. La ampliación de cobertura E2E real está trackeada en #206 (bloqueada por secretos OAuth en CI) y #223 (runner autoalojado dedicado).
- **Ejecución con datos reales solo tras los gates de código**: las unidades de trabajo de operador (`ensure-bucket --check-only`, `apply --check-only`, `apply`, `reconcile --check-only`, `status --photos`, `verify-fallback-ready --full`) se ejecutan exclusivamente después de que los gates de código (lint + test + build + `verify-fallback-ready --ci-only` en CI) estén verdes.

**Documentación de referencia:** [`openspec/changes/live-data-migration-sandbox/proposal.md`](../openspec/changes/live-data-migration-sandbox/proposal.md) (D-LIVE-01), [`openspec/changes/live-data-migration-sandbox/tasks.md`](../openspec/changes/live-data-migration-sandbox/tasks.md) (PR1–PR7 + Phase 4 operador + Phase 5 E2E; forecast de revisión y chain strategy `auto-chain`), [`openspec/changes/live-data-migration-sandbox/specs/`](../openspec/changes/live-data-migration-sandbox/specs/) (invariantes por capacidad), [`docs/runbooks/live-migration-apply.md`](runbooks/live-migration-apply.md) (runbook canónico), [`docs/discovery/migration-risks.md`](discovery/migration-risks.md) (riesgos abiertos).

### Fase transversal — Foundation UX/UI y Dashboard

Objetivo: design system reutilizable (cargando el skill `frontend-design`) y dashboard de pendientes con realtime.

| Slice | Estado | Issue |
|---|---|---|
| Foundation UX/UI | pendiente | #6 |
| Dashboard inicial + bandeja de pendientes | pendiente | pendiente (issue por crear) |
| Búsqueda global | pendiente | pendiente (issue por crear) |

**Documentación de referencia:** [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Dirección visual" / "Relación con la UX legacy" / "Dashboard de pendientes y navegación" / "Búsqueda global", [`docs/design-tokens-apap-actual.md`](design-tokens-apap-actual.md), [`docs/legacy-initial-dashboard.md`](legacy-initial-dashboard.md).

### Fase transversal — Motor de tareas

Objetivo: motor único para tareas manuales y tareas automáticas generadas desde eventos del legacy o del dominio.

| Slice | Estado | Issue |
|---|---|---|
| Motor común de tareas | pendiente | #7 |

Documentación de referencia: (crear al arrancar la issue).

### Fase transversal — Traza canónica y panel de control

Objetivo: eventos estructurados correlacionados, panel de control para configuración funcional y diagnóstico.

| Slice | Estado | Issue |
|---|---|---|
| Traza canónica (eventos JSON correlacionados) | pendiente | pendiente (issue por crear) |
| Panel de control / configuración | pendiente | pendiente (issue por crear) |

Documentación de referencia: [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Traza canónica del sistema" / "Panel de control / configuración".

### Fase transversal — Documentación unificada en castellano

Objetivo: alinear toda la documentación técnica con el idioma del proyecto (decisión del 2026-06-17).

| Slice | Estado | Issue |
|---|---|---|
| Traducción al castellano de `docs/architecture/architecture-insforge-stack.md` | pendiente | pendiente (issue por crear) |
| Traducción al castellano de `docs/development.md` | pendiente | pendiente (issue por crear) |
| Revisión y traducción de los `docs/discovery/*.md` que aún estén en inglés | pendiente | pendiente (issue por crear) |

---

## Issues abiertos

> Lista representativa — auto-actualizable con `gh issue list --state open`. Muestra priorizada por recencia + relación con roadmap, no exhaustiva. Las cerradas en masa se consolidan en `docs/proceso.md` §6 (cierre con trazabilidad) y en los merges con `git log --grep=`.

> **Estado de PRs abiertos al 2026-08-05** (tras la limpieza que dejó el remoto en `main` + 3 ramas):
>
> - **#406** `chore/issue-392-deadcode` — CI en rojo. Borrado de 5 símbolos muertos (#392).
> - **#408** `fix/issue-387-s608-sql-v2` — CI en rojo y **~97 commits por detrás de `main`**. Cubre la mitad `app/modules/` del triaje S608. **No mergear tal cual:** su triaje se midió cuando había 57 sitios; hoy hay 54 (tras #422) y su rama no lo sabe. El harness de #387 obliga a re-medir y comentar cuando el número difiere, no a ajustar el objetivo. Los conflictos con `main` que aparentan reescrituras de fichero completo son artefacto de finales de línea: con `--ignore-all-space` el cambio real son ~16 líneas.
> - Dos ramas remotas corresponden a PRs **cerrados sin mergear** (#362, #413) y se mantienen a propósito; #413 fue el intento por capas que sustituyeron los slices verticales.
>
> **Rama local sin PR:** `rescue/329-mvp-ready-gate` conserva dos commits recuperados que añadían un gate `APAP_MVP_READY` al job `e2e`. **No aplicar:** su propósito era apagar e2e en pre-MVP, pero hoy e2e corre y pasa en `main`, así que aplicarlo restaría señal. Se conserva solo como registro.

| # | Título | Área |
|---|---|---|
| #6 | Foundation UX/UI | transversal |
| #7 | Motor común de tareas | transversal |
| #29 | LIFECYCLE-04 cambio de chip con cascade | animales |
| #30 | LIFECYCLE-05 search API | animales |
| #33 | state resolver (`DameSituacion()` legacy replication) | animales |
| #35 | VOL-02 roles_voluntario junction table | voluntarios |
| #36 | VOL-03 pipeline de deduplicación fuzzy | voluntarios |
| #37 | VOL-04 migración FK free-text → FK estructurada | voluntarios |
| #38 | VOL-05 active validation gate | voluntarios |
| #46 | FOSTER-04 material assignment | foster |
| #49 | ADOPT-03 4-state follow-up state machine | adopciones |
| #51 | HEALTH-02 batch API | sanidad |
| #52 | HEALTH-03 summary API | sanidad |
| #53 | HEALTH-04 therapies CRUD | sanidad |
| #54 | HEALTH-05 periodicity engine | sanidad |
| #55 | HEALTH-06 prueba-catalog migration | sanidad |
| #56 | DOC-01 contract-PDF generation | documentos |
| #57 | DOC-02 signed-upload registration | documentos |
| #58 | DOC-03 polymorphic attachments | documentos |
| #59 | DOC-04 legacy-to-object-storage migration | documentos |
| #60 | REPORT-01 parameterized query builder | informes |
| #61 | REPORT-02 server-side execution con export PDF/Excel | informes |
| #62 | REPORT-03 quarterly report | informes |
| #63 | REPORT-04 notification engine | informes |
| #64 | REPORT-05 live dashboard counters | informes |
| #66 | RBAC-01 matriz de permisos API | transversal |
| #69 | cache materializado `estado_actual_animal` | animales |
| #142 | feat(foster) override→estancia atomicity (follow-up) | foster |
| #206 | E2E real (bloqueada por `APAP_OAUTH_CLIENT_ID` en CI) | transversal |
| #217 | `apply_reverse` increment semantics del `dni_collision_counter` | migración |
| #218 | `execute_legacy_write` swallowing `conn.commit()` failure | migración |
| #219 | `_PII_VALUE_PATTERNS` NIE/NIF-especiales/numeric-NCHIP | migración |
| #223 | runner autoalojado dedicado | transversal |

---

## Issues pendientes de crear

> Refresco 2026-07-03: las issues de INTAKE (Fase 5a) ya están abiertas como #87–#89 + #41/#42. Las de FOSTER, ADOPT, HEALTH, DOC, REPORT, RBAC, CATALOG también están abiertas (ver §"Issues abiertos"). Lo que queda **sin abrir** está aquí abajo.

| Fase / Área | Título tentativo | Depende de | Estado |
|---|---|---|---|
| Migración en vivo PR7 | `feat(migration): verify-fallback-ready + gate CI` | PR6 cerrado (`2782cb6`) | pendiente (gate M2) — crear con el skill `issue-creation`; naming propuesto `feat(migration): PR7 verify-fallback-ready + gate CI`. Tras su creación, añadir fila a §"Issues abiertos". |
| Fase 4 | `feat(animals): CRUD + timeline + estado derivado` | Fase 3 | pendiente (los #50–#55/#69 cubren pedazos) |
| Transversal | `feat(dashboard): bandeja de pendientes + realtime` | Fase 2 | pendiente |
| Transversal | `feat(search): búsqueda global` | Fases 3–4 | pendiente |
| Transversal | `feat(canonical-logs): traza canónica del sistema` | Fase 1 | pendiente (ref `docs/canonical-logs.md` no existe; el doc hay que crearlo cuando arranque la issue) |
| Transversal | `feat(admin-panel): panel de control / configuración` | Fases 1–2 | pendiente |
| Docs | `docs(architecture): traducir architecture-insforge-stack.md al castellano` | — | pendiente (la ruta canónica es `docs/architecture/architecture-insforge-stack.md`; la traducción sigue siendo de ese archivo) |
| Docs | `docs(development): traducir development.md al castellano` | — | pendiente |
| Docs | `docs(discovery): revisar y traducir los discovery en inglés al castellano` | — | pendiente |
| Docs | `docs(canonical-logs): crear el doc fundacional de traza canónica` | — | bloqueado por la issue de arriba |
| Docs | `docs(decisiones-proyecto): crear el doc de decisiones de proyecto` | — | en verde (creado en el refresh 2026-07-03, consolidado por #130) |
| Docs | `docs(proceso): playbook operativo por issue` | — | en verde (PR #132 merge `5329ec5`; regen. Tier 1 en PR #464) |
| Docs | `docs(roadmap): regenerar Tier 1 (README + proceso + roadmap) per documentation-patterns` | — | en curso (este PR, refs #464) |
| Docs | `docs(CODEBASE-GUIDE): crear guía de mantenedores 90-second mental model` | — | pendiente (Tier 2 de #464) |
| Docs | `docs(runbooks/<area>): runbooks adicionales por área` | — | pendiente (Tier 2 de #464) |
| Docs | `docs(audits/<feature>-audit-YYYY-Qn.md): auditorías adicionales` | — | pendiente (Tier 2 de #464) |
| Docs | `app/modules/<area>/README.md: README por módulo (mantenedor)` | — | pendiente (Tier 3 de #464) |
| Fase 6b | `feat(therapies): terapias y recomendaciones` | Fases 3–4 | pendiente |
| Fase 6c | `feat(material): inventario de material y asignaciones` | Fases 3–4 | pendiente |
| Fase 7a | `feat(attachments): anexos e historial documental` | Fases 3–6 | pendiente |
| Fase 7b | `feat(templates): motor de plantillas y contratos` | Fases 3–6 | pendiente |
| Fase 7c | `feat(consultas): módulo Consultas + informe trimestral` | Fases 3–6 | pendiente |

---

## Cuándo ir al legacy directamente

Reglas de uso de la documentación generada vs. el Access:

1. **Si `docs/discovery/feature-XX-*.md` cubre la pregunta → leer el discovery primero.** Es la versión revisada y consolidada.
2. **Si el discovery no entra en detalle suficiente y existe un `docs/legacy-*.md` específico para el área → leer el legacy documentado.** Ejemplo: [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md) para la pestaña Salud.
3. **Solo ir al Access directamente (vía Dysflow) si**:
   - La pregunta no está cubierta en discovery ni en `legacy-*`.
   - Hay que validar un dato concreto del schema o de los datos que no se puede inferir de la documentación.
   - Aparece un dato incoherente que requiere inspección de los formularios VBA (`Form_*`).
4. **Cualquier descubrimiento nuevo del Access debe documentarse** como `docs/legacy-<área>.md` antes de cerrar la tarea, no como nota efímera.

**Herramienta canónica para tocar el Access en este proyecto:** Dysflow MCP (`projectId: apap`). El skill `vba-access` es el único skill VBA permitido; los skills `access-vba-sync`, `access-query`, `access-form-creation` y `access-sandbox` están excluidos del workflow de APAP_WEB.

---

## Convenciones del proyecto

| Tema | Convención |
|---|---|
| Idioma de issues y PRs | Castellano (España). |
| Idioma de artefactos técnicos (código, comentarios, docstrings) | Inglés por defecto; documentación de producto en castellano. |
| Idioma de documentación | Castellano (España) para docs de producto, arquitectura y SDD. |
| Mantenedor | aroman (autoaprueba issues y PRs). |
| Rama objetivo actual | pre-MVP single-branch — todo va a `main`, una sola rama al final del ciclo. `git config gentleai.stagingOnly` está **unset** para este repo (D-38, [AGENTS.md](../AGENTS.md) §15). Reversión post-MVP: re-armar el flag, recrear `staging`, deferir al global `staging-acceptance-contract` con Virginia como validadora UAT. |
| Convención de commits | Conventional Commits. |
| Tipo de PR label | Exactamente uno de `type:bug` / `type:feature` / `type:docs` / `type:refactor` / `type:chore` / `type:breaking-change`. |
| TDD | Estricto: tests antes de código (excepto docs y ops puros). Cada unidad de trabajo = 1 issue → tests rojo → implementación → verde → integración en `main` → cerrar issue con trazabilidad (SHA + test path). |
| Skill para frontend | `frontend-design` cargado en cualquier issue que toque UI/UX. |
| Skill para workflow VBA/Access | Solo `dysflow` MCP, `vba-access` y `access-vba-tdd`; los demás skills de Access están excluidos (D-31). |
| Presupuesto de revisión | 400 líneas por PR; usar PRs encadenados cuando se supere. |
| Cadena de PRs | `force-chained`; base normal `main` (pre-MVP); post-MVP vuelve a `staging`. |
| Trazabilidad de SDD | Cada PR enlaza la issue (`Closes #N`) y referencia el change de OpenSpec cuando aplique. |
| Fidelidad al legacy | D-05 (P1): superset funcional del Access; gap = `type:bug` con label `gap:legacy`. |

---

## Índice de documentación

### Producto y dominio

- [`docs/discovery/README.md`](discovery/README.md) — índice maestro del discovery.
- [`docs/discovery/business-feature-map.md`](discovery/business-feature-map.md) — visión general y orden de generación.
- [`docs/discovery/feature-01-animal-lifecycle.md`](discovery/feature-01-animal-lifecycle.md)
- [`docs/discovery/feature-02-intake-foster-adoption.md`](discovery/feature-02-intake-foster-adoption.md)
- [`docs/discovery/feature-03-health-care.md`](discovery/feature-03-health-care.md)
- [`docs/discovery/feature-04-documents-contracts-reports.md`](discovery/feature-04-documents-contracts-reports.md)
- [`docs/discovery/state-machines.md`](discovery/state-machines.md)
- [`docs/discovery/data-model-notes.md`](discovery/data-model-notes.md)
- [`docs/discovery/data-model-completeness.md`](discovery/data-model-completeness.md)
- [`docs/discovery/migration-risks.md`](discovery/migration-risks.md)
- [`docs/discovery/open-decisions.md`](discovery/open-decisions.md)
- [`docs/discovery/acceptance-checklist.md`](discovery/acceptance-checklist.md)
- [`docs/discovery/inventory-baseline.md`](discovery/inventory-baseline.md)
- [`docs/discovery/dysflow-notes.md`](discovery/dysflow-notes.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) — registro canónico de decisiones de producto (D-01–D-07), UX (D-10–D-12), arquitectura (D-20–D-21), proceso (D-30–D-38) y UAT (D-40–D-41).

### Arquitectura, plan y desarrollo

- [`docs/architecture/architecture-insforge-stack.md`](architecture/architecture-insforge-stack.md) — stack base y reglas InsForge/Coolify *(pendiente de traducir al castellano)*.
- [`docs/proceso.md`](proceso.md) — playbook operativo por issue: premisas (P1 fidelidad al legacy, P2 resolución de dudas, P3 docs reflejan código, P4 pre-MVP single-branch) + workflow completo (pre-flight → triaje → SDD/TDD → validación → merge → cierre con trazabilidad). **Leer al iniciar cualquier issue que vaya más allá de un doc trivial.**
- [`docs/setup.md`](setup.md) — setup por desarrollador y credenciales InsForge.
- [`docs/development.md`](development.md) — flujo local de desarrollo *(pendiente de traducir al castellano)*.
- [`docs/hardening-2026-q2-rule-history.md`](hardening-2026-q2-rule-history.md) — tracker resuelto del Q2 hardening.
- [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — auditoría de re-validación de `is_authorized`/`rol` por request (issue #143, **PASS**).
- [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) — auditoría PR4b + PR5 + PR6 de controles PII (**PASS**).

### UX y visual

- [`docs/design-tokens-apap-actual.md`](design-tokens-apap-actual.md) — tokens heredados del legacy como referencia.

### Legacy — análisis detallado (no clonar UX)

- [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md)
- [`docs/legacy-initial-dashboard.md`](legacy-initial-dashboard.md)
- [`docs/legacy-signed-contract-flow.md`](legacy-signed-contract-flow.md)
- [`docs/legacy-volunteer-roles.md`](legacy-volunteer-roles.md)
- [`docs/legacy-lifecycle-transition-rules.md`](legacy-lifecycle-transition-rules.md)

### SDD (OpenSpec)

- [`openspec/config.yaml`](../openspec/config.yaml) — configuración del motor SDD.
- [`openspec/changes/`](../openspec/changes/) — cambios SDD históricos y activos.
- [`openspec/specs/`](../openspec/specs/) — specs archivados.

---

## Cómo mantener este documento

**Regla base:** este roadmap se mantiene actualizado como efecto directo de cualquier acción que afecte a su contenido. No es una tarea aparte, se hace en el mismo flujo. Las decisiones, la documentación, las issues y el roadmap viven sincronizados: si algo cambia, el roadmap cambia en esa misma sesión, sin esperar a que el usuario lo pida.

**Ritmo de trabajo actual:** abrir issue → escribir el test rojo (TDD estricto) → implementación mínima que lo pone en verde → integrar en `main` → cerrar issue con trazabilidad (SHA + test path). En pre-MVP no hay promoción separada; todo va directo a `main`. Post-MVP, la cadencia vuelve a ser staging → UAT con Virginia → main.

Acciones que obligan a actualizar el roadmap en la misma sesión:

- **Apertura de una issue**: añadir fila a §"Issues abiertos", retirar de §"Issues pendientes de crear" (si estaba), enlazar desde la fase correspondiente en §"Hoja de ruta por fases" y abrir una PR de docs en el mismo flujo.
- **Cierre de una issue**: eliminar la fila de §"Issues abiertos" (o reemplazar el pendiente por en verde con SHA + PR), reflejar el cambio en §"Estado actual" si toca algo visible allí y actualizar la fase correspondiente en §"Hoja de ruta por fases".
- **Cambio de estado de una fase** (pendiente → en curso → en verde): actualizar la fase en §"Hoja de ruta por fases" y la fecha de "Última actualización".
- **Nueva documentación**: añadir a §"Índice de documentación" en el mismo PR.
- **Nueva decisión de arquitectura o proceso**: añadir a `docs/decisiones-proyecto.md`; el roadmap debe enlazarla, no duplicarla.
- **Cierre de una fase completa**: marcar en verde la fila en §"Hoja de ruta por fases", mantener el enlace al histórico (no borrar) y proponer la siguiente fase.
- **Obsolescencia detectada**: si el doc se desactualiza respecto a `main`, abrir `docs(roadmap): refrescar hoja de ruta` y ejecutar el refresco en la misma sesión.
- **Auditoría de enlaces de §"Índice de documentación"**: en cada refresh, verificar que cada `path/to/doc.md` referenciado existe realmente. Si no existe, marcar como **referencia rota** en la fila y/o crear el doc correspondiente en la misma PR. El checklist concreto se hace con:

  ```bash
  grep -oE '\[.*\]\(([^)]+\.(md|html|yaml))' docs/roadmap.md \
    | sed -E 's/.*\(([^)]+)\)/\1/' \
    | sort -u \
    | while read p; do test -e "$p" || echo "ROTA: $p"; done
  ```

  Las referencias marcadas como **ROTA** en el refresh 2026-07-03 son: `docs/plan-completo.md`, `docs/canonical-logs.md`. Plan de remediación documentado en §"Issues pendientes de crear".
