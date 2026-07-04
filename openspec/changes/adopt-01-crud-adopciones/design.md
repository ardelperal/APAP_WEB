# Design: ADOPT-01 — Adopciones (CRUD)

## Technical Approach

Implementar el módulo de adopciones siguiendo el patrón **service + routes** ya establecido por `app/modules/entradas/` (INTAKE-01): routes manejan HTTP/auth/templates; `service.py` owns SQL, validación de FKs, mapping y soft-delete.

El schema `adopciones` ya está creado en `app/core/domain.py:273-293` (16 columnas + UNIQUE en `(animal_id, fecha_adopcion)`). Sólo falta la columna `tipo_adopcion` (D-ADOPT-01), que se añade vía ALTER TABLE migration (`app/core/migration/sql/005_add_tipo_adopcion.sql`), siguiendo el patrón idempotente de FOSTER-02 (`app/core/domain.py:225-228` + `app/core/migration/sql_runner.py:35-54`).

El surface público del servicio es: `create_adopcion`, `list_adopciones`, `get_adopcion_by_id`, `update_adopcion`, `delete_adopcion` (soft-delete atómico) + `search_adopciones_by_adoptante(nombre_parcial)` (D-ADOPT-04).

Validación de FKs con check `activo = true`:
- `animal_id` (obligatorio): `SELECT id, activo FROM animales WHERE id = $1 AND activo = true`.
- `voluntario_seguimiento_id` (opcional): si presente, `SELECT id, activo FROM voluntarios WHERE id = $1 AND activo = true` (per VOL-05, D-ADOPT-02).

`is_active` es derivado (`fecha_devolucion IS NULL`), no persistido (D-ADOPT-05).

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Tipo de adopción como columna propia con CHECK | `tipo_adopcion TEXT NOT NULL DEFAULT 'regular' CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial'))` | Catálogo separado / inferencia desde otros campos | P1 fidelidad al dominio; 3 valores fijos no justifican tabla catálogo (D-ADOPT-01) |
| `tipo_adopcion` añadido vía ALTER TABLE migration | `app/core/migration/sql/005_add_tipo_adopcion.sql` con `ADD COLUMN IF NOT EXISTS` | Modificar el `ADOPCIONES_CREATE_TABLE_SQL` directamente | Patrón FOSTER-02: el CREATE TABLE queda congelado (tests `test_domain.py` no necesitan actualizarse), diff explícito del cambio |
| FK validation con check `activo = true` | `SELECT id FROM animales WHERE id = $1 AND activo = true` | Sin check de activo / check sólo de existencia | VOL-05: un voluntario inactivo no debe asignarse a una nueva adopción (D-ADOPT-02) |
| Soft-delete atómico | `UPDATE adopciones SET activo = false, updated_at = now() WHERE id = $1 AND activo = true RETURNING id` | SELECT + UPDATE / soft-delete con `fecha_baja` | Patrón del proyecto (mirror `entradas`, `casas_acogida`); la condición `activo = true` pliega existencia + activo (D-ADOPT-03) |
| `is_active` derivado, no persistido | `bool` property en `_row_to_adopcion` (`fecha_devolucion is None`) | Columna propia / flag en DB | Evita inconsistencia entre `activo` (DB-level) y `fecha_devolucion` (semántica) (D-ADOPT-05) |
| Búsqueda por adoptante con ILIKE | `search_adopciones_by_adoptante(client, nombre_parcial)` con `ILIKE '%' || $1 || '%'` | Búsqueda exacta / full-text search | Cubre el criterio de aceptación "búsqueda funciona" sin sobre-diseño (D-ADOPT-04) |
| Auth: `require_authorized_user` en los 7 endpoints | Permitir key_user+ en todas las operaciones | `require_writer_user` para POSTs | #144 ya merged — key_user es writer; `require_authorized_user` cubre key_user/admin/developer. `require_writer_user` rechazaría key_user, contradice el modelo del proyecto |
| Tests con `httpx.MockTransport` | Mismo patrón que `tests/test_entradas.py` y `tests/test_foster.py` | TestClient integration puro | Mock transport permite assert SQL exacto sin red |
| `_NoSqlRouteClient` para routes | Mismo patrón que `tests/test_foster_routes.py` | Sin spy / TestClient puro | Refuerza AGENTS.md §1 — cero `client.execute_sql` en routes |

## Data Flow

```
Browser form (adopciones/form.html)
    |
    | POST /adopciones (form fields)
    v
adopciones_routes.create_adopcion_view
    |
    v
adopciones_service.create_adopcion
    |  -- required fields (animal_id, fecha_adopcion, nombre_adoptante)
    |  -- FK checks: animal activo, voluntario activo (si presente)
    |  -- tipo_adopcion enum (validado por CHECK en DB)
    v
INSERT INTO adopciones (...)  -- incluye tipo_adopcion DEFAULT 'regular'
    |
    v
Adopcion dataclass → redirect /adopciones/{id}
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/core/migration/sql/005_add_tipo_adopcion.sql` | Create | `ALTER TABLE adopciones ADD COLUMN IF NOT EXISTS tipo_adopcion TEXT NOT NULL DEFAULT 'regular' CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial'))` (D-ADOPT-01) |
| `app/modules/adopciones/__init__.py` | Create | Module marker; exports `service`, `router`, `Adopcion`, `AdopcionConflictError` |
| `app/modules/adopciones/service.py` | Create | `Adopcion` dataclass, SQL constants, FK validation, CRUD + search |
| `app/modules/adopciones/routes.py` | Create | 7 endpoints (list/new/create/detail/edit/update/delete) con CSRF en los 3 forms |
| `app/main.py` | Modify | Import + `include_router(adopciones_router)` |
| `app/templates/base.html` | Modify | Add "Adopciones" nav link en mobile + desktop |
| `app/templates/adopciones/list.html` | Create | Lista de adopciones activas con filtro `?adoptante=` |
| `app/templates/adopciones/form.html` | Create | Form compartido create/edit (form_action context-dependent) |
| `app/templates/adopciones/detail.html` | Create | Vista de detalle con datos del adoptante, animal, voluntario y estado |
| `tests/test_adopciones.py` | Create | 25 atoms service |
| `tests/test_adopciones_routes.py` | Create | 12 atoms routes |
| `tests/test_domain.py` | Modify | Update `ensure_domain_schema_creates_*` test (sin cambio — el CREATE TABLE no se toca, sólo se añade el ALTER) |
| `tests/test_sql_runner.py` | Modify | Verify `005_add_tipo_adopcion.sql` is applied on next lifespan |
| `docs/roadmap.md` | Modify | Remove #47 row from §4, add to §5-bis with SHA + commit |

## Interfaces / Contracts

```python
@dataclass(frozen=True, slots=True)
class Adopcion:
    """A public service-row representation for ``adopciones``."""

    id: str
    animal_id: str
    fecha_adopcion: str
    nombre_adoptante: str
    activo: bool = True
    voluntario_seguimiento_id: str | None = None
    fecha_devolucion: str | None = None
    donativo_preadopcion: float | None = None
    donativo_adopcion: float | None = None
    dni_adoptante: str | None = None
    telefono_adoptante: str | None = None
    email_adoptante: str | None = None
    entrada_origen_id: str | None = None
    observaciones: str | None = None
    tipo_adopcion: str = "regular"
    fecha_alta: str | None = None
    updated_at: str | None = None

    @property
    def is_active(self) -> bool:
        """True when the adoption is still vigente (no return date)."""
        return self.fecha_devolucion is None


class AdopcionConflictError(ValueError):
    """Raised when a natural-key conflict occurs (UNIQUE (animal_id, fecha_adopcion))."""


def create_adopcion(client, params: dict[str, Any]) -> Adopcion: ...
def list_adopciones(client) -> list[Adopcion]: ...
def get_adopcion_by_id(client, adopcion_id: str) -> Adopcion | None: ...
def update_adopcion(client, adopcion_id: str, params: dict[str, Any]) -> Adopcion | None: ...
def delete_adopcion(client, adopcion_id: str) -> bool: ...
def search_adopciones_by_adoptante(client, nombre_parcial: str) -> list[Adopcion]: ...
```

Validation contract:
- Required: `animal_id`, `fecha_adopcion`, `nombre_adoptante` (the only mandatory adoptante field per discovery 2.3).
- `animal_id` MUST reference an active `animales` row.
- `voluntario_seguimiento_id` (optional) MUST reference an active `voluntarios` row when present.
- `tipo_adopcion` MUST be one of `{'regular', 'preadopcion', 'judicial'}` (CHECK constraint at DB level; service does not validate — DB error surfaces as `ValueError` to routes).
- `fecha_adopcion` ISO date (`YYYY-MM-DD`); empty string → `ValueError`.
- Empty strings (after `.strip()`) count as missing for required fields.
- `donativo_preadopcion`, `donativo_adopcion` numeric; non-numeric → `ValueError`.
- Soft-delete via `activo = false` + `updated_at = now()`; physical deletes forbidden.
- `search_adopciones_by_adoptante` is case-insensitive (`ILIKE`).

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Service unit | create happy path with all fields, create rejects empty required fields (animal_id, fecha_adopcion, nombre_adoptante), create rejects inactive animal (FK), create rejects inactive voluntario (FK per VOL-05), create accepts NULL voluntario_seguimiento_id, create rejects non-numeric donativo, list returns active only, list ordered by fecha_alta DESC, get by id (found/None), update happy + sad validation, delete soft-delete (atomic via `WHERE activo = true`), delete returns False when already inactive, search by adoptante (ILIKE %parcial%), search case-insensitive, is_active True when fecha_devolucion IS NULL, is_active False when fecha_devolucion IS NOT NULL | `tests/test_adopciones.py` with `httpx.MockTransport` capturing SQL |
| Routes | Auth guard on 7 endpoints, form render with CSRF, create POST redirect to detail, sad validation re-render form with 422, delete POST redirect to list, detail 404 when id missing, list with filter `?adoptante=`, edit form prefill, update POST redirect to detail, no `client.execute_sql` in routes | `tests/test_adopciones_routes.py` with `AsyncClient` + dependency overrides + `_NoSqlRouteClient` |
| Migration | `005_add_tipo_adopcion.sql` applies idempotently, adds `tipo_adopcion` column with CHECK constraint, default `'regular'` | `tests/test_sql_runner.py` (verify the migration appears in `apply_sql_migrations` output) |
| Review | Architecture/security/SOLID | R1 risk + R3 reliability lens before merge |

## Migration / Rollout

Schema additions:

1. New column `tipo_adopcion` via `app/core/migration/sql/005_add_tipo_adopcion.sql`:
   ```sql
   ALTER TABLE adopciones
   ADD COLUMN IF NOT EXISTS tipo_adopcion TEXT NOT NULL DEFAULT 'regular'
   CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial'))
   ```

Forward path: `apply_sql_migrations` (already wired in `app/main.py:204` lifespan) detects the new file on next cold start, applies it idempotently, records `005_add_tipo_adopcion.sql` in `web_sql_migrations` bookkeeping. No downtime.

Rollback: revert the PR. Migration file remains on disk; re-running `apply_sql_migrations` on a rolled-back DB is a no-op (`IF NOT EXISTS` + `INSERT ... ON CONFLICT DO NOTHING`).

## PR Slicing

Single PR (pre-MVP single-branch per AGENTS.md §15.2). The change is similar in size to FOSTER-01 (#43) which was approved as a single feature commit (~800 lines total). The schema change (ALTER TABLE migration) is the smallest possible surface; the rest is service + routes + templates + tests that mirror the established FOSTER-01/INTAKE-01 patterns.

## Open Questions

None for this slice. The `animal_lifecycle_events` integration (writing `ADOPTION_STARTED` / `ADOPTION_RETURNED` events when an adoption is created/returned) is scope of PR 2 of `web-only-feature-preservation` and depends on the derivation engine landing first.

## Skill Resolution

skill_resolution: paths-injected