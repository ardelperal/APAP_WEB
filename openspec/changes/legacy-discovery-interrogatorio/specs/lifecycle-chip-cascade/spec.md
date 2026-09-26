# Spec: LIFECYCLE — Chip Cascade / Cambio de Chip en Cascada (issue #29, task 3.3)

> **Superseded por D-43 (issue #916, epic #911 A-04; 2026-09-26).** Los bloques
> de esta spec que exigen `UPDATE` en las cinco tablas dependientes y el mapa
> `updated_tables` de 6 claves describían el diseño original de discovery y ya
> no reflejan el código. Verdad actual: el saga actualiza solo `animales.nchip`
> (protegido por `old_chip`) y añade el evento `CHIP_CHANGED`, todo dentro de
> un `transaction()` real; `updated_tables` reporta `{"animals": <n>}`. Las
> tablas dependientes referencian al animal por la FK `animal_id` y no tienen
> columna de chip. Este archivo conserva el resto de su estructura original.

## Context

Issue #29. Cuando el número de microchip de un animal cambia, el sistema debe
actualizar todos los registros vinculados atómicamente. En el legacy Access el
NCHIP era la join key y se propagaba a mano; en el schema web la FK sustituta
`animal_id UUID REFERENCES animales(id)` reemplaza esa join key, así que no hay
nada que propagar. Si el saga falla, toda la operación se revierte (rollback
real). Este patrón se implementa como **saga**.

## Current state on main@0ab533d

**No existe** implementación del cambio de chip. La tabla `animals` tiene columna
`chip` pero no hay endpoint ni servicio para cambiarla en cascada.

**Origen:** `docs/discovery/feature-01-animal-lifecycle.md` §"Chip change":
> "When a chip number changes, the update cascades across all linked records and files"

**Regla del negocio:** Un chip es un identificador permanente. Solo cambia si
el chip original estaba mal registrado o fue reemplazado físicamente.

## Required contract

### Endpoint

```
PATCH /animales/{animal_id}/chip
Body: { "new_chip": "123456789012345", "reason": "Chip físico reemplazado" }
```

### Service function (saga)

```python
def change_animal_chip(
    client: SqlExecutor,
    animal_id: UUID,
    old_chip: str,
    new_chip: str,
    reason: str,
    operador_user_id: str
) -> ChangeChipResult:
    """
    Saga que cambia el chip del animal. Desde D-43 (issue #916) la unidad de
    trabajo toca solo ``animales``: UPDATE de ``nchip`` protegido por
    ``old_chip`` más el evento ``CHIP_CHANGED`` en ``animal_lifecycle_events``,
    ambos dentro de un ``transaction()`` real. Las tablas dependientes no se
    escriben: referencian al animal por la FK ``animal_id``.

    Si el UPDATE protegido no encuentra fila o el INSERT del evento falla →
    rollback real → retorna ChangeChipResult(success=False).

    Returns: ChangeChipResult(success=True, old_chip, new_chip,
    updated_tables={"animals": 1}) or
             ChangeChipResult(success=False, error="...")
    """
```

### Tablas tocadas por el saga (post D-43, issue #916)

| Tabla | Campo | Notes |
|-------|-------|-------|
| `animales` | `nchip` | Única tabla escrita; UPDATE protegido por `old_chip`. |
| `animal_lifecycle_events` | (INSERT) | Evento `chip_changed` con `old_chip`, `new_chip`, `reason`. |
| `entradas`, `acogidas`, `adopciones`, `actuacion_sanitaria`, `terapias` | — | No se escriben: referencian al animal por la FK `animal_id` y no tienen columna de chip. |

### Saga steps (en orden)

1. Validar que `new_chip` no esté ya asignado a otro animal (uniqueness check).
2. Validar que `old_chip` coincide con el chip actual del animal.
3. BEGIN TRANSACTION (vía `transaction()` del executor transaccional).
4. UPDATE `animales` SET `nchip = new_chip` WHERE `id = animal_id AND nchip = old_chip`; si no encuentra fila, el unit se aborta y se revierte.
5. INSERT INTO `animal_lifecycle_events` event_type='chip_changed' con `old_chip`,
    `new_chip`, `reason`, `operador_user_id`.
6. COMMIT (o ROLLBACK si cualquier paso falla).

### Validations

- `new_chip` no puede estar vacío ni ser igual a `old_chip`.
- `new_chip` uniqueness: `SELECT id FROM animales WHERE nchip = new_chip AND id != animal_id`
  debe retornar vacío (preflight, antes de abrir la transacción).
- `old_chip` debe coincidir con el chip actual del animal (preflight; el UPDATE
  protegido re-verifica dentro de la transacción para cerrar la ventana de carrera).

### Response

```json
{
  "success": true,
  "old_chip": "123456789012344",
  "new_chip": "123456789012345",
  "updated_tables": {
    "animales": 1
  }
}
```

El mapa `updated_tables` de 6 claves de la spec original quedó reducido a una
clave: desde #916 la única tabla escrita es `animales` (la clave usa el nombre
de tabla real del schema web, minúscula).

## Dependencies

- Task 3.1 (LIFECYCLE state resolver) — para el INSERT en `animal_lifecycle_events`.
- Executor transaccional (`TransactionalSqlExecutor.transaction()`, #914) para
  el rollback real.
- Tablas `entradas`, `acogidas`, `adopciones`, `actuacion_sanitaria`, `terapias`:
  solo lecturas de contexto; el saga no las escribe (D-43).

## Acceptance criteria

1. `PATCH /animales/{id}/chip` con chip nuevo válido → `animales.nchip` se
   actualiza y el evento `CHIP_CHANGED` se registra en la misma transacción;
   las tablas dependientes quedan intactas (resuelven por FK `animal_id`).
2. `PATCH /animales/{id}/chip` con `new_chip` ya asignado a otro animal →
   409 Conflict, ningún registro modificado.
3. `PATCH /animales/{id}/chip` con chip que no coincide con el animal actual →
   422, ningún registro modificado.
4. Si el UPDATE protegido o el INSERT del evento falla dentro de la transacción,
   todos los cambios se revierten (rollback real vía `transaction()`).
5. `animal_lifecycle_events` registra el evento `chip_changed` con `old_chip`,
   `new_chip`, `reason`, `operador_user_id`.
6. Endpoint protegido con `require_writer_user`.
7. Logs via `log_safe("animal.chip_changed", ...)` con campos no sensibles.

## Out-of-scope

- Cambio de chip en la foto del animal (filename referencia `chip` en object storage).
  Esto se maneja separadamente en la integración con storage.
- Notificación a registros externos (ARIAC, RIAC) del cambio de chip.
- Deshacer un cambio de chip (requiere otro saga en dirección inversa).
