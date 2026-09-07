# Diseño técnico: HEALTH-01 — CRUD de actuaciones sanitarias

skill_resolution: paths-injected

## Resumen arquitectónico

HEALTH-01 replica el patrón establecido por ADOPT-01 (#47) en `app/modules/adopciones/`:
- Service framework-agnostic con dataclass frozen, FK validation en CTE atómica, soft-delete vía `UPDATE ... WHERE activo = true`, search con parámetro explícito.
- Routes thin: HTTP glue, auth, CSRF, redirect/error render — cero `client.execute_sql` (regla §1 del AGENTS.md).
- Templates castellano, `{% extends base_template %}` (post UA-based selection).
- Logging seguro vía `log_safe` con `actor_user_id` desde `request.state.user`.

Diferencia principal respecto a adopciones: este slice añade una **regla de validación de fechas (D-24)** que se aplica en dos capas — pura (formato + futura) y dentro de la CTE (anterior al alta del animal).

## Cambios en el schema

### Nueva tabla: `actuacion_sanitaria`

Añadida a `app/core/domain.py` como constante `ACTUACION_SANITARIA_CREATE_TABLE_SQL` y cableada en `ensure_domain_schema` después de `contratos` (FKs a `animales`, `voluntarios` y `catalogos_pruebas`, todas ya existentes). Idempotente vía `CREATE TABLE IF NOT EXISTS`.

```sql
CREATE TABLE IF NOT EXISTS actuacion_sanitaria (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    fecha DATE NOT NULL,
    tipo_actuacion_id UUID REFERENCES catalogos_pruebas(id),
    veterinario TEXT,
    observaciones TEXT,
    voluntario_id UUID REFERENCES voluntarios(id),
    material_utilizado TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
```

Justificación de cada columna:
- `id UUID PK`: convención del proyecto.
- `animal_id UUID NOT NULL REFERENCES animales(id)`: FK requerida; validada en CTE con `activo = true`.
- `fecha DATE NOT NULL`: campo central del slice; validado por D-24.
- `tipo_actuacion_id UUID REFERENCES catalogos_pruebas(id)`: FK opcional (D-HEALTH-01).
- `veterinario TEXT`: nombre libre del veterinario (legacy lo guardaba así).
- `observaciones TEXT`: notas libres del operador.
- `voluntario_id UUID REFERENCES voluntarios(id)`: FK opcional, validada con `activo = true` per VOL-05.
- `material_utilizado TEXT`: producto / dosis (legacy free-text).
- `fecha_alta TIMESTAMP`: audit; DEFAULT now().
- `updated_at TIMESTAMP`: audit; actualizado en cada UPDATE vía CTE.
- `activo BOOLEAN`: soft-delete (D-HEALTH-03).

Sin UNIQUE constraint explícito (no hay clave natural única clara en el dominio: dos vacunas del mismo tipo el mismo día son válidas si el operador registra error+corrección). Se mantiene `ActuacionSanitariaConflictError` reservado para futuros UNIQUE.

### No se añade migration

La tabla es nueva, no una columna a tabla existente. El patrón proyecto es:
- Tabla nueva → `CREATE TABLE IF NOT EXISTS` en `domain.py` + emit en `ensure_domain_schema`.
- Columna a tabla existente → migration `app/core/migration/sql/NNN_*.sql` (ejemplo: `005_add_tipo_adopcion.sql`).

## Cambios en el código

### Nuevos archivos

```
app/modules/sanidad/__init__.py
app/modules/sanidad/service.py
app/modules/sanidad/routes.py
app/templates/sanidad/list.html
app/templates/sanidad/form.html
app/templates/sanidad/detail.html
openspec/changes/health-01-crud-actuaciones-sanitarias/{proposal,design,specs/.../spec,tasks}.md
tests/test_sanidad.py
tests/test_sanidad_routes.py
```

### Archivos modificados

- `app/core/domain.py`: añadir `ACTUACION_SANITARIA_CREATE_TABLE_SQL` después de `CONTRATOS_CREATE_TABLE_SQL`; añadir `client.execute_sql(ACTUACION_SANITARIA_CREATE_TABLE_SQL)` al final de `ensure_domain_schema`.
- `app/main.py`: `from app.modules.sanidad.routes import router as sanidad_router` + `application.include_router(sanidad_router)`.
- `app/templates/base.html`: nav link "Actuaciones" en la sección de navegación (mobile + desktop).
- `tests/test_domain.py`: añadir `test_actuacion_sanitaria_create_table_sql_columns` + `test_actuacion_sanitaria_create_table_sql_uses_if_not_exists` + `test_actuacion_sanitaria_create_table_sql_fk_animal_id_to_animales`.
- `docs/architecture/decisiones-proyecto.md`: añadir sección D-24 (regla de validación de fechas).
- `docs/roadmap.md`: mover #50 de §4 a §5-bis con SHA + commit.

## Interfaces

### Service (`app/modules/sanidad/service.py`)

```python
@dataclass(frozen=True, slots=True)
class ActuacionSanitaria:
    id: str
    animal_id: str
    fecha: str
    activo: bool = True
    tipo_actuacion_id: str | None = None
    veterinario: str | None = None
    observaciones: str | None = None
    voluntario_id: str | None = None
    material_utilizado: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


class ActuacionSanitariaConflictError(ValueError):
    """Reservado para futuros UNIQUE constraints (paralelo a AdopcionConflictError)."""


# --- Funciones públicas ---
def create_actuacion_sanitaria(
    client, params: dict, *, actor_user_id: str | None = None
) -> ActuacionSanitaria: ...

def list_actuaciones_sanitarias(
    client, *, animal_id: str | None = None
) -> list[ActuacionSanitaria]: ...

def get_actuacion_sanitaria_by_id(client, actuacion_id: str) -> ActuacionSanitaria | None: ...

def update_actuacion_sanitaria(
    client, actuacion_id: str, params: dict, *, actor_user_id: str | None = None
) -> ActuacionSanitaria | None: ...

def delete_actuacion_sanitaria(
    client, actuacion_id: str, *, actor_user_id: str | None = None
) -> bool: ...

def search_actuaciones_by_animal(client, animal_id: str) -> list[ActuacionSanitaria]: ...
```

### Routes (`app/modules/sanidad/routes.py`)

| Método | Path | Auth | Service |
|---|---|---|---|
| GET | `/sanidad` | require_authorized_user | list_actuaciones_sanitarias (?animal_id=) o search_actuaciones_by_animal |
| GET | `/sanidad/new` | require_authorized_user | (form vacío) + list_catalogos_pruebas |
| POST | `/sanidad` | require_writer_user | create_actuacion_sanitaria |
| GET | `/sanidad/{id}` | require_authorized_user | get_actuacion_sanitaria_by_id |
| GET | `/sanidad/{id}/edit` | require_authorized_user | get_actuacion_sanitaria_by_id + list_catalogos_pruebas |
| POST | `/sanidad/{id}/update` | require_writer_user | update_actuacion_sanitaria |
| POST | `/sanidad/{id}/delete` | require_writer_user | delete_actuacion_sanitaria |

Mapeo de errores:
- `ValueError` → 422 con form re-rendered (mismo patrón que adopciones).
- `BackendError` → 422 con form re-rendered.
- Id inexistente en detail/update/delete → 404.

CSRF: 3 forms (new, edit, delete) llevan `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` (regla §10).

## Data flow: create (camino feliz)

```
operador POST /sanidad (form con csrf_token)
  → CsrfMiddleware valida token
  → require_writer_user valida sesion + rol (key_user / admin / developer)
  → create_sanidad_view handler
    → form_data = _form_data_to_params(form_dict)
    → sanidad_service.create_actuacion_sanitaria(client, form_data, actor_user_id=...)
      → _build_write_params(form_data)  # pure validation: required text fields
      → _validate_fecha_d24(fecha)  # pure: format + future-date (D-24 reglas 1+2)
      → client.execute_sql(_INSERT_ACTUACION_SANITARIA_SQL, params)
        CTE atómica:
          checked_animal: WHERE id=$1 AND activo=true AND (fecha_alta IS NULL OR fecha_alta <= $3::date)  # D-24 regla 3 + FK
          checked_voluntario: WHERE id=$2 AND activo=true  # FK + VOL-05
          inserted: INSERT INTO actuacion_sanitaria (...) SELECT ... FROM checked_animal WHERE ($2 IS NULL OR EXISTS ...) RETURNING ...
      → if 0 rows: _raise_validation_error disambiguation (animal inexistente vs inactivo vs fecha pre-alta vs voluntario inactivo)
      → log_safe("sanidad.created", ...)
      → return ActuacionSanitaria
    → RedirectResponse(url=f"/sanidad/{actuacion.id}", status_code=303)
```

## Data flow: D-24 violación

```
operador POST /sanidad con fecha="2099-12-31"
  → ... (mismo preámbulo)
  → sanidad_service.create_actuacion_sanitaria(...)
    → _validate_fecha_d24("2099-12-31")
      → date.fromisoformat("2099-12-31") OK
      → date(2099, 12, 31) > date.today() → return "fecha no puede ser futura (hoy es 2026-07-04)"
    → ValueError raised BEFORE touching DB
  → handler catches ValueError → 422 con form re-rendered y mensaje en castellano
```

Para la regla 3 (anterior al alta del animal): la CTE devuelve 0 filas porque `fecha_alta <= $3::date` falla. `_raise_validation_error` re-ejecuta `SELECT fecha_alta FROM animales WHERE id=$1 AND activo=true`; si la fecha del form es anterior, levanta `"fecha es anterior al alta del animal (YYYY-MM-DD)"`.

## Testing strategy (39 atoms)

### `tests/test_sanidad.py` — service (25 atoms)

Cubren:
- **Happy path** (3): create, update, search
- **Required fields** (3): animal_id vacío, fecha vacía, fecha_alta antes del alta
- **FK animal** (3): inexistente, inactivo, activo OK
- **FK voluntario** (2): inactivo per VOL-05, NULL permitido
- **D-24 reglas 1+2** (3): fecha malformada, fecha futura, fecha hoy
- **D-24 regla 3** (2): fecha anterior a fecha_alta cuando animal tiene fecha_alta; fecha anterior permitida cuando fecha_alta NULL
- **Soft-delete** (2): activo→false, ya inactivo
- **CTE TOCTOU** (2): animal desactivado entre validación y write
- **List + filter** (2): list todas, list con animal_id
- **search_actuaciones_by_animal** (2): animal_id con resultados, animal_id sin resultados
- **Mapping _row_to_actuacion_sanitaria** (1): tipos correctos

### `tests/test_sanidad_routes.py` — routes (14 atoms)

Cubren:
- **Auth guard** (7 endpoints): cada uno rechaza anónimo → /login
- **require_writer_user** (3 writes): cada uno rechaza reader → 403
- **Form rendering** (2): new + edit cargan `csrf_token`
- **Sad validation** (1): form con fecha inválida → 422 con mensaje en castellano
- **Redirect** (1): POST exitoso → 303 a detail
- **404** (1): detail con id inexistente → 404
- **No SQL en routes** (1): spy `_NoSqlRouteClient` similar a `tests/test_adopciones_routes.py` valida que ninguna route ejecuta SQL fuera de reval de auth

## Decisiones NO tomadas (y por qué)

- **No UNIQUE constraint en `(animal_id, fecha, tipo_actuacion_id)`**: dos actuaciones del mismo tipo el mismo día pueden ser válidas (p. ej., dosis de refuerzo). `ActuacionSanitariaConflictError` queda reservado.
- **No FK a `catalogos_veterinarios` (no existe)**: el campo `veterinario` se queda como TEXT libre. Si en el futuro se quiere catálogo, se crea `catalogos_veterinarios` y se añade FK por migration.
- **No `proxima_fecha` (recordatorio)**: scope separado. El operador puede usar `observaciones` para apuntar la próxima dosis si lo necesita.
- **No JOIN con `animales` para mostrar nombre**: el detalle muestra el `animal_id` como UUID; un slice futuro puede añadir un JOIN para mostrar nombre + NCHIP.

## Compatibilidad

- ADOPT-01 (#47): no se rompe — la tabla `actuacion_sanitaria` es nueva.
- CATALOG-01 (#65): usa `catalogos_pruebas` como FK target; si los seeds no se ejecutan, la FK falla al primer INSERT. El proyecto ya tiene `ensure_catalogs` con `ON CONFLICT DO NOTHING` así que los seeds son idempotentes.
- VOL-05 (validación de voluntario activo): replicado en `sanidad` para `voluntario_id`.
- 1718 baseline tests: no se tocan — solo se añaden 39 nuevos + 3 domain tests.