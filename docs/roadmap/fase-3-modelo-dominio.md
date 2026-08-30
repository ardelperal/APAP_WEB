[← Back to roadmap hub](../roadmap.md)

# Fase 3 — Modelo de dominio limpio

Esta página posee el estado de la Fase 3: tablas `animals`, `volunteers`, `authorized_users` y la tabla mínima de anexos, sin UI de producto todavía. Fase cerrada. Las capacidades bloqueantes (animal_current_state, animal_event_log con composition) mergeadas en PR #627.

## Estado

cerrado — `usuarios_autorizados` (#25), `animals`/`voluntarios` (#26), `animal_current_state` (#69, #620) y `animal_event_log` (LIFECYCLE-02 #32 + PR #627 composition) todos cerrados. Pendiente: `attachments` (con bucket de Storage en Fase 7).

## Slices

| Slice | Estado | Issue |
|---|---|---|
| Tabla `usuarios_autorizados` + seed bootstrap | cerrado | #25 |
| Tablas `animals`, `volunteers`, `volunteer_roles` | cerrado | #26 |
| `animal_current_state` cache materializado + columnas auxiliares | cerrado | #69 (4bd4768 + 4d9ce7b aux columns, PR #363 + PR #620) |
| Tabla `animal_event_log` (schema) | cerrado | LIFECYCLE-02 #32 (f041275) |
| Tabla `animal_event_log` (composition en services) | cerrado | LIFECYCLE-02 #32 + PR #627 (acogidas y adopciones emiten `FOSTER_STARTED`/`ADOPTION_STARTED` + `actualizar_estado_animal`; entradas no necesita — es INTAKE, no placement) |
| Tabla `attachments` (bucket Storage) | pendiente (con anexos en Fase 7) | — |

## Issues abiertas relacionadas

- #33 state resolver (`DameSituacion()` legacy replication) — domain cerrado + DI + SQL + use cases; composition para placements (acogidas/adopciones) mergeada en PR #627. Entradas no necesita composition (INTAKE, no placement).
- #35–#38 VOL-02..05 — ver [`fase-5-flujos-operativos.md`](fase-5-flujos-operativos.md) (todas cerradas).
- #46 FOSTER-04 material assignment — cerrado (#46, c1b73f3 + b490e2c, PR #170 + #171); ver [`fase-5-flujos-operativos.md`](fase-5-flujos-operativos.md).
- #49 ADOPT-03 4-state follow-up state machine — cerrado (#49, 96ec631); ver [`fase-5-flujos-operativos.md`](fase-5-flujos-operativos.md).
- #69 cache materializado `estado_actual_animal` — cerrado (#69, 4bd4768, PR #363; columnas auxiliares en 4d9ce7b / PR #620).

## Issues pendientes de crear

- `feat(animals): CRUD + timeline + estado derivado` (Fase 4 — depende de Fase 3).

## Decisiones relacionadas

- [d-03-dominio-animal.md](../architecture/decisiones/d-03-dominio-animal.md) — dominio centrado en animal.
- [d-04-paridad-campos-legacy.md](../architecture/decisiones/d-04-paridad-campos-legacy.md) — paridad de campos con el Access legacy.
- [d-05-fidelidad-legacy-superset.md](../architecture/decisiones/d-05-fidelidad-legacy-superset.md) — superset funcional del legacy (P1).
- [d-20-stack-fastapi-htmx-insforge.md](../architecture/decisiones/d-20-stack-fastapi-htmx-insforge.md) § "Data model policy".
- [d-33-tdd-estricto.md](../architecture/decisiones/d-33-tdd-estricto.md) — TDD estricto.

## Documentación de referencia

- [docs/architecture/architecture-insforge-stack.md](../architecture/architecture-insforge-stack.md) § "Data model policy".
- [docs/discovery/data-model-notes.md](../discovery/data-model-notes.md).
- [docs/discovery/data-model-completeness.md](../discovery/data-model-completeness.md).
- [docs/legacy-lifecycle-transition-rules.md](../legacy-lifecycle-transition-rules.md) — reglas de transición del animal.
- [docs/legacy-volunteer-roles.md](../legacy-volunteer-roles.md) — modelo plano de voluntarios.

## Core invariants

- **Animales y voluntarios tienen entidades separadas**: la casa de acogida (`TbAcogidaCasas`) no es un voluntario del sistema ([legacy-volunteer-roles.md](../legacy-volunteer-roles.md) §3).
- **Paridad de campos con el Access**: cada campo del animal en `TbFichaAnimal` tiene su equivalente en `animals`; un gap abre `type:bug gap:legacy` (P1, D-04).
- **InsForgeClient solo bajo `adapters/` y `di/`**: ningún módulo toca el cliente directamente (§33 de AGENTS, regla de hexagonal).
- **Tablas se crean idempotentemente**: cada `ensure_domain_schema` puede correr más de una vez sin error.

## Contributor checklist

- [ ] Si añade una tabla nueva, documente la equivalencia con el legacy (campo a campo) en un ADR o en [docs/discovery/data-model-completeness.md](../discovery/data-model-completeness.md).
- [ ] Si descubre un campo del Access sin equivalente en `animals`, abra issue `type:bug gap:legacy` (P1).
- [ ] Si añade un slice de modelo, siga la regla §33: `app/modules/<slice>/` con `domain/`, `ports/`, `application/`, `adapters/insforge/`, `di/`, `routes.py` fino.
- [ ] Si implementa `state resolver` (#33), cubra con tests los seis invariantes de [legacy-lifecycle-transition-rules.md §7.2](../legacy-lifecycle-transition-rules.md).

## Navigation

Previous: [fase-2-auth-allowlist.md](fase-2-auth-allowlist.md) | Next: [fase-4-animal-crud.md](fase-4-animal-crud.md)
