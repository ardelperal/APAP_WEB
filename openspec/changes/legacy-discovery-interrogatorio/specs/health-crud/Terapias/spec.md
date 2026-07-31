# Spec: HEALTH-05 — CRUD de Terapias + Recomendaciones (issue #54, task 3.6)

## Context

Issue #54. CRUD de sesiones de terapia para animales con sus recomendaciones
asociadas (follow-up notes). Una terapia es una intervención de más alto nivel
que las actuaciones sanitarias; puede generar recomendaciones de seguimiento.

## Current state on main@0ab533d

**No existe** este feature. No hay tabla `terapias` ni `recomendaciones`.

**Fuente:** `docs/discovery/feature-03-health-care.md` §3.3–3.4 ("Terapias" + "Recommendations").

## Required contract

### Tablas

#### `terapias`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `animal_id` | UUID | FK → animals.id |
| `fecha` | DATE | Fecha de la sesión |
| `voluntario_id` | UUID | FK → voluntarios.id (requerido, activo per VOL-05) |
| `descripcion` | TEXT | Descripción de la terapia |
| `created_at` | TIMESTAMPTZ | Timestamp de creación |
| `updated_at` | TIMESTAMPTZ | Timestamp de update |
| `activo` | BOOLEAN | Soft-delete |

#### `recomendaciones`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `terapia_id` | UUID | FK → terapias.id (ON DELETE CASCADE) |
| `fecha` | DATE | Fecha de la recomendación |
| `texto` | TEXT | Descripción de la acción recomendada |
| `completada` | BOOLEAN | Marcada como completada |
| `created_at` | TIMESTAMPTZ | Timestamp de creación |
| `activo` | BOOLEAN | Soft-delete |

### Endpoints

```
GET    /terapias?animal_id=<uuid>           # lista terapias de un animal
POST   /terapias                             # crea terapia
GET    /terapias/{id}                        # detalle
PATCH  /terapias/{id}                        # actualiza
DELETE /terapias/{id}                        # soft-delete

GET    /terapias/{terapia_id}/recomendaciones           # lista
POST   /terapias/{terapia_id}/recomendaciones           # crea
PATCH  /recomendaciones/{id}                              # actualiza
DELETE /recomendaciones/{id}                              # soft-delete
```

### Service functions

```python
def create_terapia(client: SqlExecutor, data: CreateTerapiaInput) -> Terapia:
    # Validates: animal_id exists, voluntario_id exists AND activo (VOL-05)
    # Returns: Terapia with id

def list_terapias(client: SqlExecutor, animal_id: UUID | None) -> list[Terapia]:
    # If animal_id: filter by animal. Else: all (paginated).
    # Only activo=true

def create_recomendacion(client: SqlExecutor, terapia_id: UUID,
                         data: CreateRecomendacionInput) -> Recomendacion:
    # Validates: terapia_id exists, terapia.activo=true
    # ON DELETE CASCADE enforced at DB level

def complete_recomendacion(client: SqlExecutor, recomendacion_id: UUID) -> Recomendacion:
    # Sets completada=true
```

### Validación de voluntario (VOL-05)

> La misma regla que en voluntary-roles (task 3.4): el `voluntario_id` de la
> terapia DEBE existir y estar activo. Esta validación se aplica tanto en
> `create_terapia` como en `update_terapia`.

### Restricción de borrado de terapia

> No se puede borrar una terapia que tenga recomendaciones activas
> (`completada=false`). Primero hay que marcar las recomendaciones como
> completadas o borrarlas.

## Dependencies

- HEALTH-01 (#50) — `actuaciones_sanitarias` relacionada.
- VOL-05 validación de voluntario activo (task 3.4).

## Acceptance criteria

1. `POST /terapias` con `voluntario_id` inactivo → 422.
2. `POST /terapias` crea la terapia y retorna 201 con el registro.
3. `GET /terapias/{id}` incluye las recomendaciones asociadas.
4. `DELETE /terapias/{id}` con recomendaciones pendientes (completada=false) →
   409 Conflict.
5. `DELETE /terapias/{id}` con todas las recomendaciones completadas → soft-delete OK.
6. `POST /terapias/{id}/recomendaciones` crea recomendación linked a la terapia.
7. `PATCH /recomendaciones/{id}` marca `completada=true`.
8. Logs via `log_safe("therapy.created|updated|deleted", ...)` y
   `log_safe("recomendacion.created|completed|deleted", ...)`.

## Out-of-scope

- Integración con el motor de tareas (#7) para crear tareas desde recomendaciones.
- Adjuntar documentos a terapias.
- El campo `situacion_actual` de la actuación sanitaria (heredado del legacy).
