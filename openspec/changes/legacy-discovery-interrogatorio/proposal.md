# Proposal: legacy-discovery-interrogatorio — Path A SDD reconciliation

skill_resolution: paths-injected

## Contexto

Este change consolida los specs para 22 features del legacy que fueron identificados en
`docs/discovery/` y `docs/roadmap.md` §4, todos con `status:approved` y referencias
pendientes al SDD `legacy-discovery-interrogatorio`. La ausencia de este SDD bloquea la
ejecución de las 22 issues (tareas 3.1 a 3.11).

El GATE crítico está documentado en `docs/roadmap.md` §4:

> "Los 22 features con `status:approved` referencian `SDD: legacy-discovery-interrogatorio`
> que NO existe en `openspec/changes/`. Feature work bloqueado hasta que ese SDD se abra."

## Por qué ahora

- 22 issues aprobadas referencing this SDD cannot advance.
- El trabajo de discovery en `docs/discovery/` está completo y estable.
- La decisión de producto P1 (fidelidad al legacy como superset funcional) requiere specs
  que documenten el contrato actual del legacy antes de implementar.

## Scope — 22 features por área

| Task | Issue | Área | Feature |
|------|-------|------|---------|
| 3.1 | #33 | LIFECYCLE | State resolver — `calculateAnimalState()` + `persistAnimalState()` |
| 3.1b | #69 | LIFECYCLE | LIFECYCLE-02 schema append-only + cache materializado (ya mergeado PR #320) |
| 3.2 | #30 | LIFECYCLE | Búsqueda de animales con filtros por estado, especie, chip, nombre |
| 3.3 | #29 | LIFECYCLE | Chip cascade — cambio de chip en cascada via saga |
| 3.4 | #37 | VOLUNTARIOS | FK de voluntario en tablas (VOL-04: migration de roles legacy) |
| 3.5 | #49 | ADOPTION | ADOPT-03: state machine de adopciones (devolución, preadopción) |
| 3.6 | #52 | HEALTH | HEALTH-03: resumen de última prueba por tipo |
| 3.6 | #53 | HEALTH | HEALTH-04: listado de próximas pruebas (recordatorios) |
| 3.6 | #54 | HEALTH | HEALTH-05: CRUD de terapias + recomendaciones |
| 3.6 | #55 | HEALTH | HEALTH-06: entrada múltiple (batch) de actuaciones sanitarias |
| 3.7 | #56 | DOCS | DOC-01: CRUD de anexos (ficheros vinculados) |
| 3.7 | #57 | DOCS | DOC-02: motor de plantillas documentales |
| 3.7 | #58 | DOCS | DOC-03: 8 tipos de contrato con cláusulas condicionales |
| 3.7 | #59 | DOCS | DOC-04: catálogo de materiales |
| 3.8 | #60 | REPORTS | REPORT-01: informe trimestral (censo + movimientos) |
| 3.8 | #61 | REPORTS | REPORT-02: informe de adopciones |
| 3.8 | #62 | REPORTS | REPORT-03: informe de acogidas |
| 3.8 | #63 | REPORTS | REPORT-04: informe sanitario |
| 3.8 | #64 | REPORTS | REPORT-05: custom SQL reports |
| 3.9 | #66 | RBAC | RBAC-01: control de acceso basado en roles |
| 3.10 | #7 | FOUNDATION | Tasks engine — motor común de tareas (automáticas + manuales) |
| 3.11 | #6 | FOUNDATION | UX/UI base — design system + componentes |

**Total: 22 features, 11 números de tarea (3.1, 3.1b, 3.2–3.11).**

## Approach

- **Path A — reconciliación**: se creael SDD `legacy-discovery-interrogatorio` en
  `openspec/changes/` con specs que documentan el estado actual del legacy (qué existe,
  qué falta), usando los discovery docs como fuente primaria.
- Cada spec sigue la plantilla estándar: Context, Current state on main@0ab533d,
  Required contract, Dependencies, Acceptance criteria, Out-of-scope.
- Las specs con GAP marker indican dónde la evidencia del legacy no es suficiente
  para definir el contrato (falta discovery).
- Las specs ya implementadas (#69 LIFECYCLE-02, #50 HEALTH-01 ya mergeado) se marcan
  con acceptance `[x]` y referencia al PR/commit.

## Dependencies

- Depende de: spec documents existentes en `docs/discovery/feature-0[1-4]-*.md`.
- Las tasks 3.6–3.8 (HEALTH, DOCS, REPORTS) dependen de que la tabla
  `actuacion_sanitaria` (HEALTH-01, #50) esté mergeada.
- Las tasks 3.9–3.11 (RBAC, tasks, UX) son foundation y no dependen de features de dominio.

## Out-of-Scope

- Implementación de código: estas specs son documentación, no código.
- Migración de datos legacy (en `live-data-migration-sandbox` SDD).
- E2E tests de UI (bloqueados por #6 y #7 foundation).

## Acceptance

- 1 `proposal.md`, 1 `tasks.md`, ~20 `specs/<area>/spec.md`.
- Cada spec cubre una feature con: contexto, estado en main@0ab533d, contrato requerido,
  dependencias, criteria de aceptación, fuera de alcance.
- Gaps marcados explícitamente con `[GAP: needs discovery]`.
- Commit + push + PR abierta contra `main`.
