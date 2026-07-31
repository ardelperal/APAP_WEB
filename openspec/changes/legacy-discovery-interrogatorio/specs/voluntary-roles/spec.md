# Spec: VOLUNTARIOS — FK de Voluntario en Tablas de Negocio (issue #37, task 3.4)

## Context

Issue #37 (VOL-04). Reemplazar los campos de voluntario free-text en las tablas
de negocio (entradas, acogidas, adopciones, terapias) con FK estructuradas a la
tabla `voluntarios`. El modelo legacy tiene `TbVoluntariosParaAutorrellenables`
como lookup plano sin roles; las tablas de negocio usan texto libre para el
voluntario que realizó la acción.

## Current state on main@0ab533d

**Ya existe:**
- Tabla `voluntarios` con `id` UUID, `nombre`, `email`, `tel1`, `tel2`, `activo`.
- Tabla `voluntario_roles` (pivote many-to-many) con `voluntario_id`, `rol`,
  `fecha_inicio`, `fecha_fin`, `activo`.
- Issue #36 (VOL-03) mergeada PR #321 (`e0f6eeb`): deduplicación fuzzy de voluntarios
  legacy con `rapidfuzz>=3.0`.
- FK en `acogidas` referenciando `voluntarios.id` para `voluntario_seguimiento_1_id`.

**Falta:**
- FK en `entradas.voluntario_entrada` → `voluntarios.id` (reemplazar texto libre).
- FK en `adopciones.voluntario_seguimiento_id` → `voluntarios.id` (reemplazar texto libre).
- FK en `terapias.voluntario_id` → `voluntarios.id` (reemplazar texto libre).
- Las tablas `TbEntradas`, `TbAdopcion`, `TbTerapias` del legacy tienen los campos
  como texto libre: `VoluntarioEntrada`, `VoluntarioSeguimiento`, `ResponsableAdopcion`.

**Fuente:** `docs/legacy-volunteer-roles.md` + `docs/discovery/feature-04-volunteer-roles.md`.

## Required contract

### Modelo de voluntario (ya existente en schema)

```python
class Voluntario:
    id: UUID
    nombre: str          # unique
    email: str | None
    tel1: str | None
    tel2: str | None
    dni: str | None     # unique, opcional
    activo: bool

class VoluntarioRol:
    id: UUID
    voluntario_id: UUID  # FK → voluntarios
    rol: VoluntarioRolEnum  # ENTRADA | SEGUIMIENTO | SALUD | TERAPIA | ACOGIDA | RESPONSABLE
    fecha_inicio: date | None
    fecha_fin: date | None
    activo: bool
```

### Validación de voluntario activo (regla VOL-05)

En todas las operaciones de negocio que referencian un voluntario:

> **Regla VOL-05:** El voluntario referenciado DEBE existir Y tener `activo = true`
> en la tabla `voluntarios`. Un voluntario dado de baja (`activo = false`) no puede
> ser asignado a nuevas operaciones, pero sus registros históricos se preservan.

### Campos a migrar (tablas de negocio)

| Tabla legacy | Campo legacy | Target FK | Notas |
|------------|-------------|-----------|-------|
| `TbEntradas` | `VoluntarioEntrada` (texto) | `entradas.voluntario_entrada_id` → `voluntarios.id` | required |
| `TbAdopcion` | `VoluntarioSeguimiento` (texto) | `adopciones.voluntario_seguimiento_id` → `voluntarios.id` | required |
| `TbAdopcion` | `ResponsableAdopcion` (texto libre, no referenciable) | `adopciones.responsable_adopcion_id` → `voluntarios.id` | optional |
| `TbTerapias` | `Voluntario` (texto) | `terapias.voluntario_id` → `voluntarios.id` | required |
| `TbAcogidaAnimal` | `VoluntarioSeguimiento1` (texto) | `acogidas.voluntario_seguimiento_1_id` → `voluntarios.id` | required (ya existe) |
| `TbAcogidaAnimal` | `VoluntarioSeguimiento2` (texto) | `acogidas.voluntario_seguimiento_2_id` → `voluntarios.id` | optional |
| `TbAcogidaAnimal` | `VoluntarioCosasSanitarias` (texto) | `acogidas.voluntario_sanitario_id` → `voluntarios.id` | required |
| `TbAcogidaAnimal` | `VoluntarioAcogida` (texto) | `acogidas.voluntario_acogida_id` → `voluntarios.id` | optional |
| `TbEntradas` | `Voluntario` (texto en TbTerapias) | `terapias.voluntario_id` → `voluntarios.id` | required |

### Estrategia de migración de datos

1. Para cada fila con texto libre en `voluntario_*`:
   a. Buscar voluntario por nombre exacto en `voluntarios`.
   b. Si encontrado y activo → link directo FK.
   c. Si encontrado e inactivo → crear registro activo nuevo (reactivación) → link.
   d. Si no encontrado → crear nuevo voluntario con solo nombre → link. Marcar como
      `[needs_enrichment]` en un reporte de migración.
2. Todos los inserts son idempotentes (ON CONFLICT DO NOTHING).

## Dependencies

- Task 3.1b (LIFECYCLE-02 schema append-only) — `animal_lifecycle_events` para audit trail.
- Issue #36 (VOL-03 deduplicación fuzzy) — PR #321 ya mergeado.

## Acceptance criteria

1. Los servicios de `entradas`, `acogidas`, `adopciones`, `terapias` que crean
   o actualizan registros usan FK `voluntario_*_id` (no texto libre).
2. Todo `INSERT`/`UPDATE` que referencia un `voluntario_*_id` valida que el
   voluntario existe y está activo (VOL-05).
3. Los mensajes de error en español indican el nombre del voluntario problemático
   si la validación falla.
4. El historical lookup (ver registros pasados) no requiere que el voluntario
   esté activo — la FK es hacia un registro histórico en `voluntarios`.
5. La migración de datos legacy convierte texto libre → FK existente donde es
   posible, y reporta los nombres no encontrados.
6. Logs via `log_safe("volunteer.linked", ...)` para cada link creado.

## Out-of-scope

- Gestión de roles de voluntario (alta/baja/editar rol) — eso es VOL-02.
- Deduplicación fuzzy de voluntarios — ya cubierta por VOL-03 (PR #321).
- Notificaciones automáticas a voluntarios por email/SMS.
