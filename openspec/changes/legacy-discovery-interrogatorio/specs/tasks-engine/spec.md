# Spec: FOUNDATION — Tasks Engine / Motor de Tareas (issue #7, task 3.10)

## Context

Issue #7. Motor unificado de tareas manuales y automáticas. Las tareas manuales
las crean operadores; las tareas automáticas se generan desde eventos del dominio
(seguimientos de adopción pendientes, recordatorios sanitarios, etc.).

## Current state on main@0ab533d

**No existe** este feature. El sistema actual no tiene motor de tareas.

**GAP:** El feature de tareas es transversal a múltiples dominios pero aún no hay
evidencia suficiente en los discovery docs para definir todos los tipos de tareas
automáticas y sus triggers. La spec actual documenta el esqueleto con los triggers
identificados y marca los gaps.

**Fuente:** `docs/discovery/feature-02-intake-foster-adoption.md` §2.3 +
`docs/discovery/feature-03-health-care.md` §3.5.

## Required contract

### GAP: Motor de tareas — diseño incomplete

> **[GAP: needs discovery before implementation]** No hay suficiente evidencia para
> definir todos los tipos de tareas automáticas y sus triggers con precisión.
> Faltan por documentar:
> - Exactamente qué eventos del dominio generan tareas automáticas.
> - El formato de los recordatorios (email, push, in-app).
> - La política de re-intento si la tarea falla.
>
> Esta spec cubre el esqueleto + los triggers ya identificados en discovery docs.
> Los gaps se marcan explícitamente.

### Tipos de tarea identificados

| Tipo | Origen | Trigger |
|------|--------|---------|
| MANUAL | Operador | Operador crea tarea manualmente |
| RECORDATORIO_SANITARIO | HEALTH-04 | `próxima_fecha <= hoy` para alguna prueba |
| SEGUIMIENTO_ADOPCION | ADOPT-03 | Transición `PENDIENTE → DOCUMENTO_ENTREGADO` (tarea: enviar documento) |
| SEGUIMIENTO_ACOGIDA | FOSTER | Acogida nearing end date (30 días antes de `fecha_final`) |

### Tabla `tareas`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `tipo` | TEXT | MANUAL \| RECORDATORIO_SANITARIO \| SEGUIMIENTO_ADOPCION \| SEGUIMIENTO_ACOGIDA |
| `titulo` | TEXT | Título de la tarea |
| `descripcion` | TEXT | Detalle |
| `estado` | TEXT | PENDIENTE \| COMPLETADA \| CANCELADA |
| `prioridad` | INTEGER | 1 (alta) — 5 (baja) |
| `entity_type` | TEXT | Entidad relacionada (animal, adopcion, etc.) |
| `entity_id` | UUID | ID del registro relacionado |
| `asignado_a` | TEXT | email del operador (NULL = sin asignar) |
| `fecha_limite` | DATE | Fecha límite (opcional) |
| `completada_en` | TIMESTAMPTZ | Cuándo se completó |
| `completada_por` | TEXT | Operador que completó |
| `metadata` | JSONB | Datos adicionales específicos del tipo |
| `creada_en` | TIMESTAMPTZ | Timestamp de creación |
| `activo` | BOOLEAN | Soft-delete |

### Endpoints

```
GET  /tareas?estado=PENDIENTE&asignado_a=<email>&limit=50
POST /tareas                            # crear tarea manual
GET  /tareas/{id}
PATCH /tareas/{id}/completar           # marca completada
DELETE /tareas/{id}                    # soft-delete
```

### Servicio de generación automática

```python
def generate_auto_tareas(client: SqlExecutor) -> int:
    """
    Called periodically (cron job or on-demand).
    Genera tareas automáticas según los triggers identificados.
    Retorna el número de tareas creadas.
    """
    # 1. HEALTH-04: next_proximate_tests → RECORDATORIO_SANITARIO
    # 2. ADOPT-03: adopciones en estado PENDIENTE → SEGUIMIENTO_ADOPCION
    # 3. FOSTER: acogidas con fecha_final en ~30 días → SEGUIMIENTO_ACOGIDA
    # No crea duplicados: CHECK tarea con mismo entity_type+entity_id+tipo ya existe
```

### Tarea manual

```python
@dataclass
class CreateTareaInput:
    titulo: str
    descripcion: str | None
    prioridad: int = 3
    entity_type: str | None = None
    entity_id: UUID | None = None
    asignado_a: str | None = None
    fecha_limite: date | None = None
```

## Dependencies

- ADOPT-03 (#49) — state machine de seguimiento de adopción (para trigger).
- HEALTH-04 (#53) — motor de próximas pruebas (para trigger).
- FOSTER-02 (#44) — fechas de estancia de acogida (para trigger).

## Acceptance criteria

1. `POST /tareas` crea tarea manual y retorna 201 con el registro.
2. `generate_auto_tareas` no crea duplicados de tareas ya existentes para la
   misma entity.
3. `PATCH /tareas/{id}/completar` actualiza `estado=COMPLETADA` + `completada_en`.
4. `GET /tareas?estado=PENDIENTE&asignado_a=<email>` lista tareas pendientes
   filtradas por assignee.
5. Logs via `log_safe("tarea.created|completed|deleted", ...)` con entity info.

## Out-of-scope

- Notificaciones push/email a operadores (todavía no hay canal definido).
- Reintento automático de tareas fallidas.
- UI del dashboard de tareas (#6 UX foundation primero).
- Scheduling de tareas recurrentes.
