# Hoja de Ruta Viva — APAP_WEB

> Documento vivo. Punto de entrada único para saber qué hay que construir, en qué orden, qué issues lo cubren y qué documentación ya existe. Si una pregunta se responde aquí, no hay que rebuscar.

**Última actualización:** 2026-06-17
**Mantenedor único:** aroman (autoaprueba issues y PRs)
**Rama objetivo actual:** `main` (pre-MVC; la transición a `staging` queda diferida a CD-03)
**Idioma de toda la documentación, issues y PRs:** castellano (España)

---

## 1. TL;DR

- **CI/CD foundation (Fase 0):** CI-01 y CI-02 están en verde en `main`. Falta CD-01 + CD-02 para activar el deploy automático (issue #1).
- **Infraestructura:** repositorio, Coolify y backend de InsForge ya aprovisionados. Falta el runnable de la aplicación.
- **Producto (Fases 1-7):** todo pendiente. Los próximos frentes abiertos son #6 (UX/UI) y #7 (motor de tareas).
- **Documentación de discovery:** generada y consistente. Antes de tocar el legacy, leer `docs/discovery/`.

---

## 2. Estado actual (2026-06-17)

| Área | Estado | Detalle |
|---|---|---|
| Repositorio `ardelperal/APAP_WEB` | ✅ | Creado, `main` como rama por defecto |
| CI local (pytest + ruff + build) | ✅ | Phase 0 de `ci-cd-foundation` merged en `main` |
| GitHub Actions workflow | ✅ | `ci / lint`, `ci / test`, `ci / build` en verde en PRs y pushes a `main` |
| Branch protection en `main` | 🔲 | Documentado en `.github/branch-protection.md`; pendiente de activar en la UI de GitHub (tarea 1.5) |
| Proyecto Coolify + app `apap-web` | ✅ | Aprovisionado, apunta a `ardelperal/APAP_WEB:main` |
| DNS `apap.romancabanillas.com` | 🔲 | Pendiente de crear por el mantenedor antes del primer deploy real |
| Deploy automático (CD-01 + CD-02) | 🔲 | Issue #1 abierto |
| Backend InsForge | ✅ | Verificado, MCP configurado |
| Esqueleto de la app FastAPI | 🔲 | Todavía no existe (siguiente bloque técnico) |
| Login POC InsForge | ✅ | `docs/mockups/login-simple-insforge.html` |
| Foundation UX/UI | 🔲 | Issue #6 abierto |
| Motor común de tareas | 🔲 | Issue #7 abierto |
| Hoja de ruta viva | 🔲 | Esta issue #14 (en cuanto se mergee la PR) |

---

## 3. Hoja de ruta por fases

> Leyenda: ✅ completado · 🟡 en curso · 🔲 pendiente · 🚫 bloqueado

### Fase 0 — Infraestructura y CI/CD

**Objetivo:** repositorio sano, CI verde, deploy automatizado a Coolify + InsForge.

| Slice | Estado | Issue | PR | SDD |
|---|---|---|---|---|
| CI-01 superficie de tests local | ✅ | — | merged | `ci-cd-foundation` Phase 0 |
| CI-02 workflow de GitHub Actions | ✅ | — | merged | `ci-cd-foundation` Phase 1 |
| CD-01 + CD-02 deploy a Coolify + InsForge | 🔲 | #1 | — | `ci-cd-foundation` Phase 2 |
| Branch protection activado en `main` | 🔲 | — | — | `ci-cd-foundation` tarea 1.5 |
| Harness E2E (Playwright) | 🔲 | — | — | `E2E-01` (diferido a `staging`) |

**Documentación de referencia:**

- [`docs/development.md`](development.md) — flujo local del desarrollador
- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) — decisiones de stack
- [`docs/setup.md`](setup.md) — setup por desarrollador y credenciales InsForge
- [`openspec/changes/ci-cd-foundation/`](../../openspec/changes/ci-cd-foundation/) — propuesta, diseño, tareas, spec, apply-progress

### Fase 1 — Esqueleto de la aplicación web

**Objetivo:** `app/` mínimo con FastAPI + Jinja2 + Tailwind compilando, sin reglas de negocio todavía.

> Pendiente de crear issue. Bloquea todas las fases de producto.

**Decisiones pendientes:**

- Estructura exacta de `app/` (ver `docs/architecture-insforge-stack.md` § "Recommended project shape").
- Cómo se compila Tailwind v4 dentro del Dockerfile.
- Endpoint de health check (necesario para CD-02).
- Convenciones de `app/core/` (config, security, database) y de `app/modules/<dominio>/`.

### Fase 2 — Autenticación y autorización

**Objetivo:** login real con Google OAuth vía InsForge y allowlist de correos autorizados, con panel admin para el rol `developer`.

> Pendiente de crear issue. Depende de Fase 1.

**Documentación de referencia:**

- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) § "Authentication and authorization"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Usuarios autorizados y roles"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Bootstrap inicial"

### Fase 3 — Modelo de dominio limpio (Animal + Volunteer + anexos)

**Objetivo:** tablas `animals`, `volunteers`, `authorized_users` y la tabla mínima de anexos. Sin UI de producto todavía.

> Pendiente de crear issue. Bloquea las Fases 4-7.

**Documentación de referencia:**

- [`docs/plan-completo.md`](plan-completo.md) § "Fase 1: Modelo de Dominio Limpio"
- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) § "Data model policy"
- [`docs/discovery/data-model-notes.md`](discovery/data-model-notes.md)
- [`docs/discovery/data-model-completeness.md`](discovery/data-model-completeness.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Migración y convivencia con legacy"

### Fase 4 — Entidad Animal (Feature 01)

**Objetivo:** CRUD de animales, búsqueda parametrizada, timeline de eventos y motor de estado derivado.

> Pendiente de crear issue. Depende de Fase 3.

**Documentación de referencia:**

- [`docs/discovery/feature-01-animal-lifecycle.md`](discovery/feature-01-animal-lifecycle.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Timeline del animal"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Ficha del animal: inspiración legacy"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Propuesta automática de transición"
- [`docs/mockups/ficha-animal-timeline.html`](mockups/ficha-animal-timeline.html) — mockup de referencia

### Fase 5 — Voluntarios + Entradas + Acogidas + Adopciones (Feature 02)

**Objetivo:** flujos operativos centrales con asistentes por pasos y snapshots históricos de personas.

> Pendiente de crear issues (uno por sub-flujo). Depende de Fases 3-4.

**Documentación de referencia:**

- [`docs/discovery/feature-02-intake-foster-adoption.md`](discovery/feature-02-intake-foster-adoption.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Personas y apartados operativos"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Adoptantes"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Propietarios/personas que entregan animales"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Casas de acogida"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Voluntarios"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Formularios por pasos y edición por secciones"
- [`docs/legacy-volunteer-roles.md`](legacy-volunteer-roles.md)
- [`docs/legacy-lifecycle-transition-rules.md`](legacy-lifecycle-transition-rules.md)

### Fase 6 — Salud, Terapias e Inventario de Material (Feature 03)

**Objetivo:** registro sanitario con periodicidad, terapias con recomendaciones, inventario de material con disponibilidad e historial de asignaciones.

> Pendiente de crear issues (uno por sub-flujo). Depende de Fases 3-4.

**Documentación de referencia:**

- [`docs/discovery/feature-03-health-care.md`](discovery/feature-03-health-care.md)
- [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md) — análisis detallado del workflow legacy de salud
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Pestaña Salud del animal"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Pestaña Terapias del animal"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Terapias: inventario de material y asignación"

### Fase 7 — Documentos, Contratos, Informes y Consultas (Feature 04)

**Objetivo:** anexos, motor de plantillas documentales, los 8 tipos de contrato, módulo de Consultas propio e informe trimestral.

> Pendiente de crear issues (uno por sub-flujo). Depende de Fases 3-6.

**Documentación de referencia:**

- [`docs/discovery/feature-04-documents-contracts-reports.md`](discovery/feature-04-documents-contracts-reports.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Motor de plantillas documentales"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Documentos generados como fuente de verdad"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Organización de documentos y anexos"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Flujo de contratos para firma y firmados"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Consultas como módulo de primer nivel"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Informe trimestral — alcance core"
- [`docs/legacy-signed-contract-flow.md`](legacy-signed-contract-flow.md)

### Fase transversal — Foundation UX/UI y Dashboard

**Objetivo:** design system reutilizable (cargando el skill `frontend-design`) y dashboard de pendientes con realtime.

| Slice | Estado | Issue |
|---|---|---|
| Foundation UX/UI | 🔲 | #6 |
| Dashboard inicial + bandeja de pendientes | 🔲 | pendiente (issue por crear) |
| Búsqueda global | 🔲 | pendiente (issue por crear) |

**Documentación de referencia:**

- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Dirección visual"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Relación con la UX legacy"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Dashboard de pendientes y navegación"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Búsqueda global"
- [`docs/design-tokens-apap-actual.md`](design-tokens-apap-actual.md) — tokens heredados del legacy como referencia
- [`docs/mockups/login-simple-insforge.html`](mockups/login-simple-insforge.html) — mockup login
- [`docs/mockups/login-dashboard.html`](mockups/login-dashboard.html) — mockup dashboard interno
- [`docs/mockups/ficha-animal-timeline.html`](mockups/ficha-animal-timeline.html) — mockup ficha animal
- [`docs/legacy-initial-dashboard.md`](legacy-initial-dashboard.md)

### Fase transversal — Motor de tareas

**Objetivo:** motor único para tareas manuales y tareas automáticas generadas desde eventos del legacy o del dominio.

| Slice | Estado | Issue |
|---|---|---|
| Motor común de tareas | 🔲 | #7 |

**Documentación de referencia:** (crear al arrancar la issue)

### Fase transversal — Traza canónica y panel de control

**Objetivo:** eventos estructurados correlacionados, panel de control para configuración funcional y diagnóstico.

| Slice | Estado | Issue |
|---|---|---|
| Traza canónica (eventos JSON correlacionados) | 🔲 | pendiente (issue por crear) |
| Panel de control / configuración | 🔲 | pendiente (issue por crear) |

**Documentación de referencia:**

- [`docs/canonical-logs.md`](canonical-logs.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Traza canónica del sistema"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Panel de control / configuración"

### Fase transversal — Documentación unificada en castellano

**Objetivo:** alinear toda la documentación técnica con el idioma del proyecto.

> Decisión del 2026-06-17: toda la documentación, issues y PRs van en castellano. Los docs `docs/architecture-insforge-stack.md` y `docs/development.md` siguen en inglés y deben traducirse.

| Slice | Estado | Issue |
|---|---|---|
| Traducción al castellano de `docs/architecture-insforge-stack.md` | 🔲 | pendiente (issue por crear) |
| Traducción al castellano de `docs/development.md` | 🔲 | pendiente (issue por crear) |
| Revisión y traducción de los `docs/discovery/*.md` que aún estén en inglés | 🔲 | pendiente (issue por crear) |

**Documentación de referencia:**

- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Idioma de documentación"
- [`docs/plan-completo.md`](plan-completo.md) Fase 0, fila "Traducir documentación al español" (en `untracked`, se commitea junto con esta issue o por separado)

---

## 4. Issues abiertos

| # | Título | Labels | Estado |
|---|---|---|---|
| #1 | feat(cd): deploy APAP through Coolify and InsForge | `status:approved`, `priority:medium` | 🔲 |
| #6 | feat(ux): definir la base UX/UI de APAP | `status:approved`, `priority:medium` | 🔲 |
| #7 | feat(tasks): definir motor común de tareas manuales y automáticas | `status:approved`, `priority:medium` | 🔲 |
| #14 | docs(roadmap): documentar hoja de ruta viva de APAP_WEB | `documentation`, `status:approved`, `priority:medium` | 🟡 (este PR) |

> Nota: la issue #14 no estaba enlazada en el cuerpo de la PR durante el descubrimiento de este roadmap. Se referencia aquí como punto de partida del propio documento.

---

## 5. Issues pendientes de crear (por fase)

Estos son los títulos tentativos; se abren cuando arranca cada fase, no antes.

| Fase / Área | Título tentativo | Depende de |
|---|---|---|
| Fase 1 | `feat(app): esqueleto FastAPI + HTMX + Tailwind v4` | — |
| Fase 2 | `feat(auth): Google OAuth + allowlist + panel admin` | Fase 1 |
| Fase 3 | `feat(domain): modelo limpio (animals, volunteers, authorized_users)` | Fase 1 |
| Fase 4 | `feat(animals): CRUD + timeline + estado derivado` | Fase 3 |
| Fase 5a | `feat(intake): entradas y cesiones (asistente por pasos)` | Fases 3-4 |
| Fase 5b | `feat(foster): casas de acogida y estancias` | Fases 3-4 |
| Fase 5c | `feat(adoption): adopciones y devoluciones` | Fases 3-4 |
| Fase 6a | `feat(health): actuaciones sanitarias y resumen` | Fases 3-4 |
| Fase 6b | `feat(therapies): terapias y recomendaciones` | Fases 3-4 |
| Fase 6c | `feat(material): inventario de material y asignaciones` | Fases 3-4 |
| Fase 7a | `feat(attachments): anexos e historial documental` | Fases 3-6 |
| Fase 7b | `feat(templates): motor de plantillas y contratos` | Fases 3-6 |
| Fase 7c | `feat(consultas): módulo Consultas + informe trimestral` | Fases 3-6 |
| Transversal | `feat(dashboard): bandeja de pendientes + realtime` | Fase 2 |
| Transversal | `feat(search): búsqueda global` | Fases 3-4 |
| Transversal | `feat(canonical-logs): traza canónica del sistema` | Fase 1 |
| Transversal | `feat(admin-panel): panel de control / configuración` | Fases 1-2 |
| Docs | `docs(architecture): traducir architecture-insforge-stack.md al castellano` | — |
| Docs | `docs(development): traducir development.md al castellano` | — |
| Docs | `docs(discovery): revisar y traducir los discovery en inglés al castellano` | — |

---

## 6. Índice de documentación de referencia

### Producto y dominio

- [`docs/discovery/README.md`](discovery/README.md) — índice maestro del discovery
- [`docs/discovery/business-feature-map.md`](discovery/business-feature-map.md) — visión general y orden de generación
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
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) — decisiones de producto, UX, arquitectura y proceso

### Arquitectura, plan y desarrollo

- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) — stack base y reglas InsForge/Coolify *(pendiente de traducir al castellano)*
- [`docs/plan-completo.md`](plan-completo.md) — plan detallado de Fases 0-7 *(borrador en `untracked`, no commiteado todavía)*
- [`docs/development.md`](development.md) — flujo local de desarrollo *(pendiente de traducir al castellano)*
- [`docs/setup.md`](setup.md) — setup por desarrollador y credenciales InsForge

### UX y visual

- [`docs/design-tokens-apap-actual.md`](design-tokens-apap-actual.md) — tokens heredados del legacy como referencia
- [`docs/mockups/login-simple-insforge.html`](mockups/login-simple-insforge.html) — mockup del login
- [`docs/mockups/login-dashboard.html`](mockups/login-dashboard.html) — mockup del dashboard interno
- [`docs/mockups/ficha-animal-timeline.html`](mockups/ficha-animal-timeline.html) — mockup de la ficha del animal
- [`docs/features-showcase.html`](features-showcase.html) — escaparate interactivo de features

### Legacy — análisis detallado (no clonar UX)

- [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md)
- [`docs/legacy-initial-dashboard.md`](legacy-initial-dashboard.md)
- [`docs/legacy-signed-contract-flow.md`](legacy-signed-contract-flow.md)
- [`docs/legacy-volunteer-roles.md`](legacy-volunteer-roles.md)
- [`docs/legacy-lifecycle-transition-rules.md`](legacy-lifecycle-transition-rules.md)

### Trazas y diagnóstico

- [`docs/canonical-logs.md`](canonical-logs.md) — formato y contrato de la traza canónica

### SDD (OpenSpec)

- [`openspec/config.yaml`](../../openspec/config.yaml) — configuración del motor SDD
- [`openspec/changes/ci-cd-foundation/`](../../openspec/changes/ci-cd-foundation/) — change actual (CI/CD)
- [`openspec/specs/migration-discovery-docs/spec.md`](../../openspec/specs/migration-discovery-docs/spec.md) — spec archivado de la discovery

---

## 7. Cuándo ir al legacy directamente

**Reglas de uso de la documentación generada vs. el Access:**

1. **Si `docs/discovery/feature-XX-*.md` cubre la pregunta → leer el discovery primero.** Es la versión revisada y consolidada.
2. **Si el discovery no entra en detalle suficiente y existe un `docs/legacy-*.md` específico para el área → leer el legacy documentado.** Ejemplo: `docs/legacy-health-ui-workflow.md` para la pestaña Salud.
3. **Solo ir al Access directamente (vía Dysflow) si**:
   - La pregunta no está cubierta en discovery ni en legacy-*.
   - Hay que validar un dato concreto del schema o de los datos que no se puede inferir de la documentación.
   - Aparece un dato incoherente que requiere inspección de los formularios VBA (`Form_*`).
4. **Cualquier descubrimiento nuevo del Access debe documentarse** como `docs/legacy-<área>.md` antes de cerrar la tarea, no como nota efímera.

**Herramienta canónica para tocar el Access en este proyecto:** Dysflow MCP (`projectId: apap`). El skill `vba-access` es el único skill VBA permitido; los skills `access-vba-sync`, `access-query`, `access-form-creation` y `access-sandbox` están excluidos del workflow de APAP_WEB.

---

## 8. Convenciones del proyecto

| Tema | Convención |
|---|---|
| Idioma de issues y PRs | Castellano (España) |
| Idioma de artefactos técnicos (código, comentarios, docstrings) | Inglés por defecto; documentación de producto en castellano |
| Idioma de documentación | Castellano (España) para docs de producto, arquitectura y SDD |
| Mantenedor | aroman (autoaprueba issues y PRs) |
| Rama objetivo pre-MVC | `main` (la transición a `staging` queda diferida a CD-03) |
| Convención de commits | Conventional Commits |
| Tipo de PR label | exactamente uno de `type:bug` / `type:feature` / `type:docs` / `type:refactor` / `type:chore` / `type:breaking-change` |
| TDD | Estricto: tests antes de código (excepto docs y ops puros) |
| Skill para frontend | `frontend-design` cargado en cualquier issue que toque UI/UX |
| Skill para workflow VBA/Access | Solo `dysflow` MCP y `vba-access`; los demás skills de Access están excluidos |
| Presupuesto de revisión | 400 líneas por PR; usar PRs encadenados cuando se supere |
| Cadena de PRs | `force-chained` + `stacked-to-main` mientras estamos en pre-MVC |
| Trazabilidad de SDD | Cada PR enlaza la issue (`Closes #N`) y referencia el change de OpenSpec cuando aplique |

---

## 9. Cómo mantener este documento

Este roadmap es **vivo**. Se actualiza en el mismo PR que avanza el estado, no en PRs separados.

- **Cambio de estado** (de 🔲 a 🟡 o ✅): en el PR que cierra la issue correspondiente, actualizar la fila afectada y la fecha de "Última actualización".
- **Apertura de nueva issue**: añadir fila a la sección "Issues abiertos" en el mismo PR donde se crea la issue, o en un PR de docs aparte si la issue ya existía.
- **Nueva documentación**: añadir a la sección "Índice de documentación" en el mismo PR.
- **Nueva decisión de arquitectura o proceso**: añadir a `docs/decisiones-proyecto.md`; este roadmap debe enlazarla, no duplicarla.
- **Cierre de fase**: marcar ✅ la fila completa, mover el enlace al histórico (no borrar) y proponer la siguiente fase.
- **Obsolescencia**: si este documento se desactualiza más de 2 semanas respecto a `main`, abrir una issue `docs(roadmap): refrescar hoja de ruta`.
