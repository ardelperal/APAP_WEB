[← Back to roadmap hub](../roadmap.md)

# Fase 4 — Entidad Animal (Feature 01)

Esta página posee el estado de la Fase 4: CRUD de animales, búsqueda parametrizada, timeline de eventos y motor de estado derivado. Fase pendiente. Depende de Fase 3.

## Estado

pendiente — issue por crear. Los #29 (LIFECYCLE-04 cambio de chip con cascade), #30 (LIFECYCLE-05 search API), #33 (state resolver) y #69 (cache `estado_actual_animal`) cubren pedazos del scope; falta el slice que los integra como capacidad de usuario.

## Slices previstos

| Slice | Estado | Issue / PR |
|---|---|---|
| CRUD de animales (alta, edición, baja lógica) | pendiente | issue por crear |
| Búsqueda parametrizada de animales | pendiente | #30 |
| Timeline de eventos del animal | pendiente | issue por crear |
| Motor de estado derivado (`estado_actual_animal`) | pendiente | #33 |
| Cache materializado de `estado_actual_animal` | pendiente | #69 |
| Cambio de chip con cascade | pendiente | #29 |

## Issues pendientes de crear

- `feat(animals): CRUD + timeline + estado derivado` — integra #29, #30, #33, #69 como capacidad de usuario. Depende de Fase 3.

## Decisiones relacionadas

- [d-03-dominio-animal.md](../architecture/decisiones/d-03-dominio-animal.md) — dominio centrado en animal.
- [d-04-paridad-campos-legacy.md](../architecture/decisiones/d-04-paridad-campos-legacy.md) — paridad de campos.
- [d-05-fidelidad-legacy-superset.md](../architecture/decisiones/d-05-fidelidad-legacy-superset.md) — superset funcional.

## Documentación de referencia

- [docs/discovery/feature-01-animal-lifecycle.md](../discovery/feature-01-animal-lifecycle.md) — diseño del feature.
- [docs/discovery/state-machines.md](../discovery/state-machines.md) — state machine del animal.
- [docs/legacy-lifecycle-transition-rules.md](../legacy-lifecycle-transition-rules.md) — fuente de verdad de los 8 estados y la matriz de transiciones.
- [docs/architecture/decisiones-proyecto.md](../architecture/decisiones-proyecto.md) § "Timeline del animal" / "Ficha del animal: inspiración legacy" / "Propuesta automática de transición".

## Core invariants

- **State machine replicada del legacy**: los 8 estados y las transiciones de [legacy-lifecycle-transition-rules.md §1](../legacy-lifecycle-transition-rules.md) son la fuente de verdad; cualquier divergencia abre ADR (§32).
- **Modo estricto por defecto**: las validaciones de integridad temporal y el control de estados se aplican siempre en la web (legacy §7.4).
- **Borrado solo con ficha limpia**: solo se elimina un animal si no tiene entradas, acogidas, adopciones, actuaciones sanitarias ni terapias (legacy §7.2 regla 6, ya implementado parcialmente en `app/modules/lifecycle/application/can_delete_animal.py`).
- **Cierre automático al cambiar de estado**: la transición cierra la situación anterior (`CerrarSituacionNoEjecutivas` → `closePreviousSituation()`).
- **Defunción cierra todo**: `closeAllOnDeath()` cierra todas las situaciones abiertas.

## Contributor checklist

- [ ] Si implementa el CRUD de animales, abra primero la issue y cite [docs/discovery/feature-01-animal-lifecycle.md](../discovery/feature-01-animal-lifecycle.md).
- [ ] Si implementa `state resolver` (#33), cubra con tests los seis invariantes de [legacy-lifecycle-transition-rules.md §7.2](../legacy-lifecycle-transition-rules.md).
- [ ] Si cambia la matriz de transiciones, actualice [legacy-lifecycle-transition-rules.md §3](../legacy-lifecycle-transition-rules.md) en la misma PR (P3).
- [ ] Si descubre un campo de `TbFichaAnimal` sin equivalente en `animals`, abra issue `type:bug gap:legacy` (P1).

## Navigation

Previous: [fase-3-modelo-dominio.md](fase-3-modelo-dominio.md) | Next: [fase-5-flujos-operativos.md](fase-5-flujos-operativos.md)
