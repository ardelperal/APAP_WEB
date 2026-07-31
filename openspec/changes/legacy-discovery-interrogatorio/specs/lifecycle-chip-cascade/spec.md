# Spec: LIFECYCLE — Chip Cascade / Cambio de Chip en Cascada (issue #29, task 3.3)

## Context

Issue #29. Cuando el número de microchip de un animal cambia, el sistema debe
actualizar todos los registros vinculados atómicamente (entradas, acogidas,
adopciones, actuaciones sanitarias, terapias). Si alguna tabla falla, toda la
operación se revierte (rollback). Este patrón se implementa como **saga**.

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
    Saga que actualiza el chip en cascada en todos los registros vinculados:
    animals, entradas, acogidas, adopciones, actuaciones_sanitarias, terapias.

    Si cualquier tabla falla → rollback total → retorna ChangeChipResult(success=False).

    Returns: ChangeChipResult(success=True, old_chip, new_chip) or
             ChangeChipResult(success=False, error="...")
    """
```

### Tablas a actualizar en cascada

| Tabla | Campo | Notes |
|-------|-------|-------|
| `animals` | `chip` | Tabla principal |
| `entradas` | `chip` | FK |
| `acogidas` | `chip` | FK |
| `adopciones` | `chip` | FK |
| `actuaciones_sanitarias` | `chip` | FK |
| `terapias` | `chip` | FK |

### Saga steps (en orden)

1. Validar que `new_chip` no esté ya asignado a otro animal (uniqueness check).
2. Validar que `old_chip` coincide con el chip actual del animal.
3. BEGIN TRANSACTION.
4. UPDATE `animals` SET `chip = new_chip` WHERE `id = animal_id AND chip = old_chip`.
5. UPDATE `entradas` SET `chip = new_chip` WHERE `chip = old_chip AND activo = true`.
6. UPDATE `acogidas` SET `chip = new_chip` WHERE `chip = old_chip AND activo = true`.
7. UPDATE `adopciones` SET `chip = new_chip` WHERE `chip = old_chip AND activo = true`.
8. UPDATE `actuaciones_sanitarias` SET `chip = new_chip` WHERE `chip = old_chip`.
9. UPDATE `terapias` SET `chip = new_chip` WHERE `chip = old_chip`.
10. INSERT INTO `animal_lifecycle_events` event_type='chip_cambiado' con `old_chip`,
    `new_chip`, `reason`, `operador_user_id`.
11. COMMIT (o ROLLBACK si cualquier paso falla).

### Validations

- `new_chip` no puede estar vacío ni ser igual a `old_chip`.
- `new_chip` uniqueness: `SELECT id FROM animals WHERE chip = new_chip AND id != animal_id`
  debe retornar vacío.
- `reason` es obligatorio (audit trail).

### Response

```json
{
  "success": true,
  "old_chip": "123456789012344",
  "new_chip": "123456789012345",
  "updated_tables": {
    "animals": 1,
    "entradas": 0,
    "acogidas": 1,
    "adopciones": 0,
    "actuaciones_sanitarias": 3,
    "terapias": 1
  }
}
```

## Dependencies

- Task 3.1 (LIFECYCLE state resolver) — para el INSERT en `animal_lifecycle_events`.
- Tablas `entradas`, `acogidas`, `adopciones`, `actuaciones_sanitarias`, `terapias`
  existentes en schema.

## Acceptance criteria

1. `PATCH /animales/{id}/chip` con chip nuevo válido → todos los registros
   vinculados se actualizan atómicamente.
2. `PATCH /animales/{id}/chip` con `new_chip` ya asignado a otro animal →
   409 Conflict, ningún registro modificado.
3. `PATCH /animales/{id}/chip` con chip que no coincide con el animal actual →
   422, ningún registro modificado.
4. Si una tabla de las 6 falla, todos los cambios se revierten (rollback).
5. `animal_lifecycle_events` registra el evento `chip_cambiado` con `old_chip`,
   `new_chip`, `reason`, `operador_user_id`.
6. Endpoint protegido con `require_writer_user`.
7. Logs via `log_safe("animal.chip_changed", ...)` con campos no sensibles.

## Out-of-scope

- Cambio de chip en la foto del animal (filename referencia `chip` en object storage).
  Esto se maneja separadamente en la integración con storage.
- Notificación a registros externos (ARIAC, RIAC) del cambio de chip.
- Deshacer un cambio de chip (requiere otro saga en dirección inversa).
