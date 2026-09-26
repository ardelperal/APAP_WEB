# Decisiones de proyecto — APAP_WEB

[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

Registro canónico de decisiones de producto, UX, arquitectura y proceso. Cada decisión es un ADR individual que sigue la receta §14 (Decision, Quick path, Problem, Evidence, Options, Goals, Non-goals, Non-negotiable invariants, Consequences, When this changes). Si una decisión contradice el código o la doc, gana el código y este registro se actualiza en la misma sesión (ver [`proceso.md`](../proceso.md) P3 y [`roadmap.md`](../roadmap.md) §9).

**Mantenedor único:** aroman (ver [d-36](decisiones/d-36-mantenedor-aroman.md)).
**Última actualización del índice:** 2026-08-18 (refactor §14 — split por ADR individual).

## What this index is / is not

| Es | Evidencia |
|---|---|
| Índice navegable de las decisiones D-XX con un enlace al ADR individual. | `decisiones/d-01-product-standalone.md` hasta [d-43](decisiones/d-43-chip-cascade-fk-animal-id.md). |
| Single source of truth para divergencias formales con el legacy. | Premisa P1 en [`AGENTS.md`](../../AGENTS.md) y [`proceso.md`](../proceso.md) §0. |

| No es | Use este límite |
|---|---|
| Un doc monolítico con todas las decisiones. | Cada D-XX vive en su propio archivo bajo `decisiones/`. |
| Un changelog. | [`CHANGELOG.md`](../../CHANGELOG.md) registra releases; aquí se registran decisiones. |
| Una spec de implementación. | Las specs viven en [`openspec/specs/`](../../openspec/specs/). |

## Índice de decisiones

### Producto

| ID | Decisión | Status | ADR |
|---|---|---|---|
| D-01 | APAP_WEB es un producto profesional standalone | aceptado | [d-01](decisiones/d-01-product-standalone.md) |
| D-02 | Home = dashboard con tarjetas de pendientes operativos | aceptado | [d-02](decisiones/d-02-home-dashboard.md) |
| D-03 | Dominio centrado en Animal | aceptado | [d-03](decisiones/d-03-dominio-animal.md) |
| D-04 | Paridad de campos del animal con el Access legacy | aceptado | [d-04](decisiones/d-04-paridad-campos-legacy.md) |
| D-05 | Fidelidad al legacy = superset funcional (Premisa P1) | aceptado | [d-05](decisiones/d-05-fidelidad-legacy-superset.md) |

### UX y visual

| ID | Decisión | Status | ADR |
|---|---|---|---|
| D-10 | Idioma visible en UI: castellano de España | aceptado | [d-10](decisiones/d-10-castellano-ui.md) |
| D-11 | No clonar la UX del legacy | aceptado | [d-11](decisiones/d-11-no-clonar-ux-legacy.md) |
| D-12 | Design system reutilizable | pendiente | [d-12](decisiones/d-12-design-system.md) |

### Arquitectura y stack

| ID | Decisión | Status | ADR |
|---|---|---|---|
| D-20 | Stack base: FastAPI + HTMX + Jinja2 + LocalBackend | aceptado | [d-20](decisiones/d-20-stack-fastapi-htmx-local_backend.md) |
| D-21 | CodeGraph es el read path principal | aceptado | [d-21](decisiones/d-21-codegraph-read-path.md) |
| D-24 | Regla de validación de fechas en actuaciones sanitarias | aceptado | [d-24](decisiones/d-24-validacion-fechas-sanidad.md) |
| D-25 | Librería de fuzzy match: rapidfuzz (no thefuzz) | aceptado | [d-25](decisiones/d-25-rapidfuzz-fuzzy-match.md) |
| D-43 | Cascade de NCHIP legacy reemplazado por FK `animal_id` + evento `CHIP_CHANGED` (#916) | aceptado | [d-43](decisiones/d-43-chip-cascade-fk-animal-id.md) |

> **D-43 — detalle (issue #916, epic #911 A-04; 2026-09-26).** El saga de cambio de chip ya no propaga NCHIP a las tablas dependientes: el schema web referencia al animal por la FK sustituta `animal_id UUID REFERENCES animales(id)` (`app/core/domain_entradas.py:38`, `domain_adopciones.py:40`, `domain_foster.py:42`, `domain_terapias.py:11`, `domain_salud.py:35`) y ninguna de esas tablas tiene columna `chip` (la tabla real de salud es `actuacion_sanitaria`, singular). El legacy propagaba NCHIP porque era su join key (`docs/discovery/feature-01-animal-lifecycle.md:217`, `docs/discovery/data-model-notes.md:123`); la FK sustituye ese join key, así que los `UPDATE <tabla> SET chip` eran innecesarios y fallaban con `UndefinedColumn`. El saga conserva el preflight de unicidad y chip actual, el `UPDATE animales SET nchip` protegido por `old_chip` y el evento `CHIP_CHANGED`, todo dentro de un `transaction()` real (#914) — los `BEGIN`/`COMMIT`/`ROLLBACK` vía `execute_sql` (una conexión nueva por llamada) se eliminaron.

### Proceso y entrega

| ID | Decisión | Status | ADR |
|---|---|---|---|
| D-30 | Pre-MVP single-branch workflow | aceptado | [d-30](decisiones/d-30-pre-mvp-single-branch.md) |
| D-31 | Resolución de dudas del dominio en orden fijo (Premisa P2) | aceptado | [d-31](decisiones/d-31-resolucion-dudas-dominio.md) |
| D-32 | Documentación refleja código (Premisa P3) | aceptado | [d-32](decisiones/d-32-doc-refleja-codigo.md) |
| D-33 | TDD estricto | aceptado | [d-33](decisiones/d-33-tdd-estricto.md) |
| D-34 | Conventional Commits en inglés | aceptado | [d-34](decisiones/d-34-conventional-commits.md) |
| D-35 | Presupuesto de revisión: 400 líneas por PR | aceptado | [d-35](decisiones/d-35-presupuesto-400-lineas-pr.md) |
| D-36 | Mantenedor único: aroman | aceptado | [d-36](decisiones/d-36-mantenedor-aroman.md) |
| D-37 | Convenciones de idioma | aceptado | [d-37](decisiones/d-37-convenciones-idioma.md) |
| D-38 | `git config gentleai.stagingOnly` está unset en este repo | aceptado | [d-38](decisiones/d-38-stagingonly-unset.md) |

### UAT y validación

| ID | Decisión | Status | ADR |
|---|---|---|---|
| D-40 | Virginia como validadora UAT (post-MVP) | aceptado | [d-40](decisiones/d-40-virginia-uat.md) |
| D-41 | Trazabilidad obligatoria al cerrar issues | aceptado | [d-41](decisiones/d-41-trazabilidad-cierre-issues.md) |

## Decisiones heredadas del legacy (resumen)

Capacidades heredadas del comportamiento del Access legacy, en `docs/legacy-*.md` + `docs/discovery/feature-XX-*.md`. Cada una migra a un ADR individual cuando aterriza en el sistema nuevo.

| Capacidad legacy | Doc | Estado |
|---|---|---|
| Estados del animal + transiciones | [`legacy-lifecycle-transition-rules.md`](../legacy-lifecycle-transition-rules.md), [`discovery/state-machines.md`](../discovery/state-machines.md) | pendiente, Fase 4 |
| Roles de voluntario | [`legacy-volunteer-roles.md`](../legacy-volunteer-roles.md) | pendiente, Fase 5 |
| Flujo de contratos firmados | [`legacy-signed-contract-flow.md`](../legacy-signed-contract-flow.md) | pendiente, Fase 7 |
| Workflow de salud / pruebas periódicas | [`legacy-health-ui-workflow.md`](../legacy-health-ui-workflow.md), [`discovery/feature-03-health-care.md`](../discovery/feature-03-health-care.md) | pendiente, Fase 6 |
| Dashboard inicial con pendientes | [`legacy-initial-dashboard.md`](../legacy-initial-dashboard.md) | migrado a `/` (#127, #131) |

## Cómo añadir una nueva decisión

1. Abra issue `type:docs` con la pregunta, background, criterios y opciones consideradas.
2. Discuta en la issue hasta convergencia. Ciérrela con la decisión.
3. Cree `docs/architecture/decisiones/d-XX-<slug>.md` con la receta §14: Decision, Quick path, Problem, Evidence, Options, Goals, Non-goals, Non-negotiable invariants, Consequences, When this changes.
4. Añada la fila al índice en este archivo (orden por sección, siguiente correlativo).
5. Si contradice una decisión previa, marque la antigua como **SUPERSEDED por D-YY** dentro del ADR (no borrar).
6. Si afecta código o roadmap, sincronice en la misma PR (P3 y roadmap §9).
7. No borre decisiones históricas. El registro es auditable.

## Cómo revisar este índice

- En cada refresh de [`roadmap.md`](../roadmap.md), cruce referencias con este índice y viceversa.
- Cuando una decisión quede obsoleta por código real, abra PR de actualización (no borrar).
- Si una decisión contradice el código, gana el código y este índice se actualiza en la misma sesión.

## Navigation

Previous: [Arquitectura LocalBackend](architecture-local-backend-stack.md) | Next: [Capas y slices](capas-y-slices.md)