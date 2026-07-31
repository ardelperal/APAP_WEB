# Spec: DOC-04 — Catálogo de Materiales (issue #59, task 3.7)

## Context

Issue #59. Catálogo de materiales (inventario) usados en acogidas, adopciones
y cuidado de animales: camas, transportines, collares, pienso donado, etc.
Búsqueda filtrable y exportable a spreadsheet.

## Current state on main@0ab533d

**Ya existe:**
- Tabla `materiales` (del CATALOG-01, #65) con `nombre`, `descripcion`.
- CRUD básico de catálogo en `app/modules/catalogos/`.

**Falta:**
- Tabla de inventario de materiales (stock real por material).
- Asignación de materiales a acogidas/adopciones.
- Historial de asignaciones.

**Fuente:** `docs/discovery/feature-04-documents-contracts-reports.md` §4.3 ("Materials").

## Required contract

### Tablas

#### `materiales` (ya existe via CATALOG-01)

Extender si es necesario con campos de inventario.

#### `inventario_materiales`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `material_id` | UUID | FK → materiales.id |
| `cantidad_disponible` | INTEGER | Stock disponible actualmente |
| `cantidad_total` | INTEGER | Stock total (incluído prestado/reservado) |
| `ubicacion` | TEXT | Dónde está almacenado |
| `fecha_actualizacion` | TIMESTAMPTZ | Última actualización del stock |
| `activo` | BOOLEAN | Soft-delete |

#### `asignaciones_materiales`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | UUID | PK |
| `inventario_id` | UUID | FK → inventario_materiales.id |
| `entity_type` | TEXT | 'acogida' \| 'adopcion' |
| `entity_id` | UUID | FK al registro |
| `cantidad` | INTEGER | Cuántas unidades |
| `fecha_asignacion` | DATE | Fecha de asignación |
| `fecha_devolucion` | DATE | Fecha de devolución (NULL si no devuelto) |
| `observaciones` | TEXT | Notas |
| `activo` | BOOLEAN | Soft-delete |

### Endpoints

```
# Materiales
GET    /materiales                            # list all
POST   /materiales                            # create
GET    /materiales/{id}                       # detail
PATCH  /materiales/{id}                       # update
DELETE /materiales/{id}                      # soft-delete

# Inventario
GET    /inventario                            # list all stock
GET    /inventario?material_id=<uuid>          # filter by material
POST   /inventario                            # add stock entry
PATCH  /inventario/{id}                        # update stock (cantidad)
GET    /inventario/{id}/historial              # historial de asignaciones

# Asignaciones
POST   /asignaciones_materiales               # asignar a entidad
PATCH  /asignaciones_materiales/{id}/devolver # registrar devolución
```

### Service functions

```python
def asignar_materiales(
    client: SqlExecutor,
    entity_type: str,
    entity_id: UUID,
    items: list[AsignacionItem],  # [{inventario_id, cantidad}]
    operador_user_id: str
) -> list[AsignacionMaterial]:
    """
    Crea asignación y decrementa cantidad_disponible en inventario.
    Validates: inventario_id existe, cantidad_disponible >= cantidad pedida.
    """

def devolver_materiales(
    client: SqlExecutor,
    asignacion_id: UUID,
    observaciones: str | None
) -> AsignacionMaterial:
    """
    Registra devolución: fecha_devolucion = hoy, cantidad_disponible += cantidad.
    """
```

## Dependencies

- CATALOG-01 (#65) — tabla `materiales` existente.

## Acceptance criteria

1. `GET /inventario` lista todos los stocks con cantidad disponible.
2. `POST /inventario` con `cantidad_pedida > cantidad_disponible` → 409 Conflict.
3. `POST /asignaciones_materiales` decrementa `cantidad_disponible` atómicamente.
4. `PATCH /asignaciones/{id}/devolver` incrementa `cantidad_disponible` y marca
   `fecha_devolucion`.
5. `GET /inventario/{id}/historial` lista todas las asignaciones (activas y devueltas).
6. `GET /materiales` filtrable por `nombre` (substring, case-insensitive).
7. Export a CSV: `GET /inventario?format=csv` descarga spreadsheet.

## Out-of-scope

- Notificaciones cuando el stock baja de un umbral mínimo.
- Proveedores y pedidos de reposición.
- Amortización o depreciación de materiales.
