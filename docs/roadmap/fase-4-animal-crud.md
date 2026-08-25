[← Back to roadmap hub](../roadmap.md)

# Fase 4 — Entidad Animal (Feature 01)

Esta página posee el estado de la Fase 4: CRUD de animales, búsqueda parametrizada, timeline de eventos y motor de estado derivado. La integración hexagonal del epic #420 está completada. Depende de Fase 3.

## Estado

Integración hexagonal completada. El epic #420 migró lectura, escritura, chip y foto a `AnimalsPort`:

| Método hexagonal | PR | Notas |
|---|---|---|
| `AnimalsPort.get_animal_by_nchip` | #587 | Read por clave de negocio. |
| `AnimalsPort.list_animals` | #596 | Read paginado, oldest-first por NCHIP. |
| `AnimalsPort.create_animal` | #597 | INSERT con validación de campos requeridos. |
| `AnimalsPort.update_animal` | #603 | Partial UPDATE (kwargs opcionales). |
| `AnimalsPort.delete_animal` | #604 | Soft-delete (UPDATE activo=FALSE). |
| `AnimalsPort.record_lifecycle_event` | #609 | INSERT idempotente (vía índice único natural y cláusula de conflicto). |
| `AnimalsPort.list_lifecycle_events` | #610 | Read cronológico del timeline con filtro opcional por tipo. |
| `AnimalsPort.change_animal_chip` | #612, PR-C | Saga transaccional sobre 6 tablas; la ruta usa el port. |
| `AnimalsPort.resolve_animal_photo` | #613, PR-C | Recurso neutral con stream cerrable; la ruta ya usa el port. |
| `AnimalsPort.get_animal_by_id` | PR-A.1 | Read por UUID para detalle e integración foster. |
| `AnimalsPort.search_animals` | PR-A.1 | Búsqueda paginada con nueve filtros. |

Pendiente en el port: ninguno. Los once métodos de `AnimalsPort` han aterrizado y todas las rutas de animales los usan.

La conversión está completada al 100 %. Los shims legacy de servicio, chip, foto y queries se retiraron al cerrar el epic #420.

La entidad hexagonal `Animal` contiene los 28 campos de lectura. PR-B migró los payloads de escritura al port; `updated_at` permanece interno al sistema.

Fuera del alcance del epic #420 quedan el state resolver (#33), la cache de `estado_actual_animal` (#69) y el pulido de la API de búsqueda (#30).

## Slices previstos

| Slice | Estado | Issue / PR |
|---|---|---|
| CRUD de animales (alta, edición, baja lógica) | completado en rutas hexagonales | #587, #596, #597, #603, #604, epic #420 PR-B |
| Búsqueda parametrizada de animales | completada; pendiente de pulido | #30, epic #420 PR-A.2b |
| Timeline de eventos del animal | pendiente | issue por crear |
| Motor de estado derivado (`estado_actual_animal`) | pendiente | #33 |
| Cache materializado de `estado_actual_animal` | pendiente | #69 |
| Cambio de chip con cascade | completado en ruta hexagonal | #29, epic #420 PR-C |

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
