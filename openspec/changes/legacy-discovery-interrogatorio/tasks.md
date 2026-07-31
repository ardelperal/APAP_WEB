# Tasks: legacy-discovery-interrogatorio — Path A SDD reconciliation

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~800 total (proposal ~100 + tasks ~50 + specs ~650) |
| 400-line budget risk | Low (docs-only, under budget) |
| Chained PRs recommended | No (single docs PR) |
| Delivery strategy | single-pr |
| Decision needed before apply | No |

## Task 3.1 — LIFECYCLE state resolver (#33)

- [ ] 3.1.1 Crear `specs/lifecycle/spec.md` documentando el state resolver
  (`calculateAnimalState()` + `persistAnimalState()` + `closeAllOnDeath()` +
  `closePreviousSituation()` + `canDeleteAnimal()`). Origen: `legacy-lifecycle-transition-rules.md`
  + `docs/discovery/state-machines.md` §1 + `docs/discovery/feature-01-animal-lifecycle.md`.
  required contract: service functions con signatures, DB state derivation rules,
  aceptación: 8 estados + transiciones por la matriz del legacy.

## Task 3.1b — LIFECYCLE-02 schema append-only + cache (#69) — YA IMPLEMENTADO

- [x] 3.1b.1 Nota: issue #69 (LIFECYCLE-02) ya mergeada en PR #320 (`0049708`).
  Tablas `animal_lifecycle_events` (append-only) y `animal_current_state` (cache materializado)
  creadas. La spec documenta el estado actual y referencias a los commits.
  Spec en: `specs/lifecycle-schema-cache/spec.md`.

## Task 3.2 — LIFECYCLE-05 search con filtros (#30)

- [ ] 3.2.1 Crear `specs/lifecycle-search/spec.md` documentando la búsqueda de animales
  con filtros: chip (exact/partial), nombre (substring case-insensitive), especie
  (CANINA/FELINA), sexo (Macho/Hembra), estado (8 estados), rango de fechas.
  Origen: `docs/discovery/feature-01-animal-lifecycle.md` §"Search behavior detail".
  Depende de: 3.1 (state resolver).

## Task 3.3 — LIFECYCLE-04 chip cascade (#29)

- [ ] 3.3.1 Crear `specs/lifecycle-chip-cascade/spec.md` documentando el cambio de chip
  en cascada: saga que actualiza todos los registros vinculados (entradas, acogidas,
  adopciones, salud) atómicamente. Origen: `docs/discovery/feature-01-animal-lifecycle.md`
  §"Chip change". Depende de: 3.1 (state resolver).

## Task 3.4 — VOL-04 FK migration de voluntarios (#37)

- [ ] 3.4.1 Crear `specs/voluntary-roles/spec.md` documentando la migración de roles
  de voluntario legacy: tabla `voluntarios` (nombre único → UUID), tabla pivote
  `voluntario_roles` (FK a `roles_catálogo`), replace de free-text en tablas de negocio
  (entradas, acogidas, adopciones, terapias) con FK. Origen:
  `docs/legacy-volunteer-roles.md` + `docs/discovery/feature-04-volunteer-roles.md`.
  Depende de: 3.1 (state resolver).

## Task 3.5 — ADOPT-03 state machine de adopciones (#49)

- [ ] 3.5.1 Crear `specs/adoption-state-machine/spec.md` documentando la state machine
  de adopciones: estados (Pendiente, Documento Entregado, Documento Adjunto,
  Seguimiento Completado), transiciones, eventos de triggered.
  Origen: `docs/discovery/state-machines.md` §5 + `docs/discovery/feature-02-intake-foster-adoption.md`
  §2.3.

## Task 3.6 — HEALTH-03 a HEALTH-06 (4 specs agrupadas) (#52, #53, #54, #55)

- [ ] 3.6.1 HEALTH-03: Crear `specs/health-crud/Resumen/spec.md` — resumen de última
  prueba por tipo. Origen: `docs/discovery/feature-03-health-care.md` §3.2.
  Depende de: HEALTH-01 (#50) ya mergeado.
- [ ] 3.6.2 HEALTH-04: Crear `specs/health-crud/Proximas/spec.md` — listado de próximas
  pruebas (recordatorios periódicos). Origen: `docs/discovery/feature-03-health-care.md`
  §3.5 + `legacy-health-ui-workflow.md` §10.
- [ ] 3.6.3 HEALTH-05: Crear `specs/health-crud/Terapias/spec.md` — CRUD de terapias
  + recomendaciones. Origen: `docs/discovery/feature-03-health-care.md` §3.3–3.4.
- [ ] 3.6.4 HEALTH-06: Crear `specs/health-crud/Batch/spec.md` — entrada múltiple
  (batch) de actuaciones sanitarias. Origen: `docs/discovery/feature-03-health-care.md`
  §9 + `legacy-health-ui-workflow.md` §9.

## Task 3.7 — DOC-01 a DOC-04 (4 specs) (#56, #57, #58, #59)

- [ ] 3.7.1 DOC-01: Crear `specs/documents-contracts/Anexos/spec.md` — CRUD de anexos
  (ficheros vinculados). Origen: `docs/discovery/feature-04-documents-contracts-reports.md`
  §4.1 + `legacy-signed-contract-flow.md`.
- [ ] 3.7.2 DOC-02: Crear `specs/documents-contracts/Plantillas/spec.md` — motor de
  plantillas documentales con cláusulas condicionales por especie/sexo/edad.
  Origen: `docs/discovery/feature-04-documents-contracts-reports.md` §4.2 + `legacy-signed-contract-flow.md`.
- [ ] 3.7.3 DOC-03: Crear `specs/documents-contracts/Contratos/spec.md` — 8 tipos de
  contrato con lifecycle (Borrador → Pendiente Firma → Firmado → Anulado).
  Origen: `docs/discovery/state-machines.md` §3 + `docs/discovery/feature-04-documents-contracts-reports.md`.
- [ ] 3.7.4 DOC-04: Crear `specs/documents-contracts/Materiales/spec.md` — catálogo
  de materiales (inventory). Origen: `docs/discovery/feature-04-documents-contracts-reports.md`
  §4.3.

## Task 3.8 — REPORT-01 a REPORT-05 (5 specs) (#60, #61, #62, #63, #64)

- [ ] 3.8.1 REPORT-01: Crear `specs/reports/Trimestral/spec.md` — informe trimestral
  (censo + movimientos por especie). Origen: `docs/discovery/feature-04-documents-contracts-reports.md`
  §4.5.
- [ ] 3.8.2 REPORT-02: Crear `specs/reports/Adopciones/spec.md` — informe de adopciones.
- [ ] 3.8.3 REPORT-03: Crear `specs/reports/Acogidas/spec.md` — informe de acogidas.
- [ ] 3.8.4 REPORT-04: Crear `specs/reports/Sanidad/spec.md` — informe sanitario.
- [ ] 3.8.5 REPORT-05: Crear `specs/reports/Custom/spec.md` — custom SQL reports con
  validación de seguridad (sandbox/plantillas parametrizadas). Origen:
  `docs/discovery/feature-04-documents-contracts-reports.md` §4.4.

## Task 3.9 — RBAC-01 control de acceso basado en roles (#66)

- [ ] 3.9.1 Crear `specs/rbac/spec.md` documentando el modelo RBAC:
  roles (developer, admin, operador), permisos por rol, endpoints protegidos,
  tabla de roles en InsForge. Depende de: 3.11 (UX foundation para el panel admin).

## Task 3.10 — Foundation tasks engine (#7)

- [ ] 3.10.1 Crear `specs/tasks-engine/spec.md` documentando el motor de tareas
  común: tareas manuales (creadas por operadores) y tareas automáticas (generadas
  desde eventos del dominio: recordatorios sanitarios, seguimientos de adopción).
  Motor unitario para ambos tipos. Depende de: 3.5 (adoption follow-up state machine)
  y 3.6 (health reminders).

## Task 3.11 — Foundation UX/UI base (#6)

- [ ] 3.11.1 Crear `specs/ux-ui-foundation/spec.md` documentando el design system
  base: tokens de diseño (del legacy o nuevos), componentes reutilizables, layout
  de la navegación, estructura de templates con Jinja2+HTMX+Tailwind.
  Origen: `docs/decisiones-proyecto.md` §D-11/D-12 + `docs/design-tokens-apap-actual.md`.
  Depende de: decisión de producto sobre si se usa Tailwind v4 o nuevo design system.
