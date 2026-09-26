# D-43 — Cascade de NCHIP reemplazado por la FK `animal_id` + evento `CHIP_CHANGED`

## Decision

A partir del merge del PR que cierra el issue #916 (epic #911, A-04), el saga de cambio de chip deja de propagar el NCHIP a las tablas dependientes. La unidad de trabajo se reduce a dos pasos dentro de un `transaction()` real del executor transaccional (#914):

1. `UPDATE animales SET nchip = $new WHERE id = $animal AND nchip = $old` (protegido por `old_chip`; si no encuentra fila, el unit se aborta).
2. `INSERT INTO animal_lifecycle_events` del evento `CHIP_CHANGED` con `{old_chip, new_chip, reason}` en el `metadata`.

Ambos pasos se confirman juntos o no se confirman; cualquier fallo revierte el unit completo. Las tablas dependientes (`entradas`, `acogidas`, `adopciones`, `actuacion_sanitaria`, `terapias`) no se escriben: referencian al animal por la FK sustituta `animal_id UUID REFERENCES animales(id)` y no tienen columna de chip. El resultado `ChangeChipResult.updated_tables` reporta `{"animales": <n>}`.

Este ADR formaliza la divergencia con el legacy que el bloque de detalle de `decisiones-proyecto.md` venía registrando.

## Quick path

Si necesita cambiar el chip de un animal, llame a `AnimalsPort.change_animal_chip(animal_id=..., old_chip=..., new_chip=..., reason=..., operador_user_id=...)` (caso de uso `app/modules/animals/application/change_animal_chip.py`; implementación `app/modules/animals/adapters/local_backend/animals_local_backend_chip_cascade.py`). No añada `UPDATE <tabla dependiente> SET chip` ni copias del NCHIP en otras tablas: la FK `animal_id` es el único vínculo correcto. Si una consulta necesita el chip actual, haga join con `animales` por `animal_id`.

## Problem statement

El saga original (issue #29, LIFECYCLE-04) trasladaba literalmente el comportamiento del Access legacy, donde el NCHIP era la join key y un cambio de chip exigía propagarlo a mano por todas las tablas vinculadas. El schema web sustituyó esa join key por la FK sustituta `animal_id`, de modo que los `UPDATE <tabla> SET chip` del saga referenciaban una columna inexistente y fallaban con `UndefinedColumn`. Además, el saga enviaba `BEGIN`/`COMMIT`/`ROLLBACK` vía `execute_sql`, que abre una conexión nueva por llamada: la "transacción" no protegía nada. El drift quedó documentado en la auditoría de tests (`docs/quality/test-audit.md`, entrada del PR #635) antes del fix.

## Evidence and scope

- Ninguna de las cinco tablas dependientes tiene columna de chip: `app/core/domain_entradas.py:38`, `domain_adopciones.py:40`, `domain_foster.py:42`, `domain_terapias.py:11`, `domain_salud.py:35` declaran la FK `animal_id UUID REFERENCES animales(id)`.
- La tabla real de salud es `actuacion_sanitaria` (singular); la tabla `actuaciones_sanitarias` citada por la doc antigua no existe en el schema.
- El legacy propagaba NCHIP porque era su join key: `docs/discovery/feature-01-animal-lifecycle.md:217` y `docs/discovery/data-model-notes.md:123`.
- Los `BEGIN`/`COMMIT`/`ROLLBACK` previos vía `execute_sql` abrían una conexión nueva por llamada y no protegían el unit; el patrón transaccional real llega de `app/modules/adopciones/service.py::create_adoption` tras el issue #914.
- Átomos de verificación: `tests/integration/test_chip_cascade_integration.py` (éxito con entidades relacionadas activas, rollback real ante fallo forzado, ausencia de columna de chip, pin estático del source) y `tests/test_animals_chip_cascade_saga.py` (helpers del saga contra executor falso).

## Options considered

### Opción A — Reducir el saga a `animales` + evento, con `transaction()` real (aceptada)

**A favor**: refleja el schema real, elimina los `UndefinedColumn`, da atomicidad verificable y conserva el contrato público del port y del endpoint.

**En contra**: diverge del literal del legacy (la propagación ya no existe); la divergencia queda documentada aquí y en `decisiones-proyecto.md`.

### Opción B — Añadir columnas de chip a las tablas dependientes para conservar el cascade (rechazada)

**A favor**: haría el flujo idéntico al legacy.

**En contra**: duplica el dato, exige triggers o propagación manual para mantenerlo consistente y contradice el diseño de FK sustituta ya asentado en el schema web.

### Opción C — Eliminar el saga y hacer un UPDATE simple de CRUD (rechazada)

**A favor**: menos código.

**En contra**: pierde el preflight de unicidad, la protección por `old_chip` (que cierra la ventana de carrera entre lectura y escritura) y el evento `CHIP_CHANGED` que alimenta la timeline del detalle.

## Goals

- Conservar la fidelidad semántica al legacy (un cambio de chip queda registrado y es consistente) sin copiar su mecánica de join key (premisa P1: superset funcional, no clon).
- Atomicidad real: el UPDATE y el evento se confirman o se revierten juntos.
- Contrato público estable: `AnimalsPort.change_animal_chip`, `ChangeChipResult` y `PATCH /animales/{id}/chip` no cambian de forma.

## Non-goals

- Renombrar o migrar datos históricos de las tablas dependientes.
- Replicar el `metadata` del evento con más campos que `{old_chip, new_chip, reason}`.
- Cambiar el endpoint, sus códigos HTTP (409 por duplicado en preflight, 422 en los demás fallos) o su permiso `AUTHORIZED`.

## Non-negotiable invariants

- El `UPDATE animales` va siempre protegido por `old_chip`; un UPDATE sin guarda reabriría la ventana de carrera que el preflight no puede cerrar.
- El evento `CHIP_CHANGED` se inserta dentro de la misma `transaction()` que el UPDATE; nunca en una conexión separada.
- Ningún código nuevo añade columnas de chip a tablas dependientes ni propagaciones manuales de NCHIP; el vínculo es la FK `animal_id`.

## Consequences

**Cambia**: `updated_tables` pasa de un mapa de 6 claves a `{"animales": <n>}`; los consumidores que leían claves de tablas dependientes dejan de encontrarlas.

**Cambia**: los fallos dentro de la transacción revierten el unit completo de verdad; antes el "rollback" vía `execute_sql` no protegía nada.

**No cambia**: el preflight de unicidad y de chip actual, la validación de entrada en el caso de uso, el contrato HTTP del endpoint ni el permiso requerido.

## When this changes

- Si el schema web vuelve a denormalizar el NCHIP en tablas dependientes (no hay razón prevista), este ADR se revierte y el saga recupera los UPDATE en cascada.
- Si el evento `CHIP_CHANGED` necesita campos adicionales en el `metadata` (por ejemplo, el operador que autorizó la reimplantación física), se amplía aquí con su issue y su test.
