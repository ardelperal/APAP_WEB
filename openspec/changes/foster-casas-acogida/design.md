# Design: FOSTER-01 — Casas de Acogida

## Technical Approach

Implementar un slice CRUD mínimo sobre la entidad **Casa de Acogida** siguiendo el patrón ya establecido por `app/modules/entradas/` (INTAKE-01) y `app/modules/voluntarios/`: routes manejan HTTP/auth/templates únicamente; `service.py` owns SQL, validación, mapping y soft-delete.

La nueva tabla `casas_acogida` es 1:1 con las 19 columnas de negocio de `TbAcogidaCasas` (D-FOSTER-01) + 2 mejoras justificadas (D-FOSTER-02). El surface público del servicio es: `create_casa_acogida`, `list_casas_acogida(especie=None)`, `get_casa_acogida_by_id`, `update_casa_acogida`, `delete_casa_acogida` (soft-delete, mirror de `entradas.delete_entrada`).

FOSTER-02 añadirá `casa_acogida_id UUID REFERENCES casas_acogida(id)` a la tabla `acogidas` (scope fuera de esta issue). El orden de creación de tablas en `ensure_domain_schema` se mantiene compatible: `casas_acogida` va DESPUÉS de `acogidas` para no romper FKs existentes; cuando FOSTER-02 añada la FK desde `acogidas.casa_acogida_id` a `casas_acogida.id`, el orden puede reorganizarse (la FK nueva exige que `casas_acogida` exista ANTES de cualquier `INSERT INTO acogidas` que la referencie; pero `CREATE TABLE` no impone orden si las tablas referenciadas se crean en statements separados y el FK solo se evalúa en INSERT, no en CREATE — la opción más segura es crear `casas_acogida` ANTES de `acogidas` y dejar FOSTER-02 con un `ALTER TABLE`). Decisión: insertar `casas_acogida` justo ANTES de `acogidas` en `ensure_domain_schema` para que FOSTER-02 pueda añadir la FK con un simple `ALTER TABLE` sin reorganizar.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Tabla propia `casas_acogida` | Crear entidad nueva separada de `acogidas` (estancia) | Añadir columnas `nombre_casa`, `apellidos_casa`... inline en `acogidas` | Legacy tiene `TbAcogidaCasas` + `TbAcogidaAnimal` separadas; P1 fidelidad 1:1 |
| `id` UUID PK (mejora) | UUID en vez de INT legacy | Mantener `IDAcogidaCasa` INT | FK estable portable, ya patrón del proyecto (todos los `id` son UUID) |
| `capacidad` INTEGER NOT NULL (mejora) | Añadir campo que legacy no tiene | Dejar capacidad solo como `count(*) over TbAcogidaAnimal` | Discovery 2.2 lo documenta como requisito; sin él FOSTER-03 no es posible |
| Soft-delete vía `activo` | `activo = false` + `fecha_baja = now()` | Solo `fecha_baja IS NULL` | Patrón del proyecto (mirror `animales`, `voluntarios`, `entradas`); queries eficientes |
| Búsqueda con `especie_preferente IS NULL` cuenta como match | Service trata NULL como "cualquier especie" | Solo match exacto, NULL excluido | Patrón conservador legacy; casas con preferencia "todas" deben aparecer para CANINA y FELINA |
| FK ordering en `ensure_domain_schema` | `casas_acogida` ANTES de `acogidas` (sin FK en este PR) | Después de `acogidas` | FOSTER-02 va a añadir FK desde `acogidas`; si la tabla referenciada ya existe, el `ALTER TABLE` es trivial |
| Tests con `httpx.MockTransport` | Mismo patrón que `tests/test_entradas.py` | TestClient integration puro | Mock transport permite assert SQL exacto sin red |

## Data Flow

```
Browser form (casas_acogida/form.html)
    |
    | POST /casas-acogida (form fields)
    v
foster_routes.create_casa_acogida_view
    |
    v
foster_service.create_casa_acogida
    |  -- required fields (nombre, apellidos, calle, telefono, coche, capacidad)
    |  -- coche enum (Sí, No)
    |  -- especie_preferente enum (CANINA, FELINA, null)
    |  -- capacidad positive int
    v
INSERT INTO casas_acogida (...)
    |
    v
CasaAcogida dataclass → redirect /casas-acogida/{id}
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/core/domain.py` | Modify | Add `CASAS_ACOGIDA_CREATE_TABLE_SQL` constant; insert in `ensure_domain_schema` BEFORE `acogidas` |
| `app/modules/foster/__init__.py` | Create | Module package marker; re-exports `service` public surface |
| `app/modules/foster/service.py` | Create | `CasaAcogida` dataclass, SQL constants, validation, CRUD API |
| `app/modules/foster/routes.py` | Create | Protected list/new/create/detail/edit/update/delete routes |
| `app/modules/foster/__init__.py` | Modify | Export `router` |
| `app/main.py` | Modify | Import + `include_router(foster_router)` |
| `app/templates/casas_acogida/list.html` | Create | List of active houses with link to detail |
| `app/templates/casas_acogida/form.html` | Create | Shared create/edit form (form_action context-dependent) |
| `app/templates/casas_acogida/detail.html` | Create | Read view of one house with edit/delete actions |
| `app/templates/base.html` | Modify | Add "Casas de acogida" nav link |
| `tests/test_foster.py` | Create | Service unit tests (validation, CRUD, search) |
| `tests/test_foster_routes.py` | Create | Route tests (auth, form render, redirects, CSRF) |
| `tests/test_xss_audit.py` | Modify | Add `casas_acogida/*` entries to `TEMPLATE_SPECS` |
| `tests/test_domain.py` | Modify | Update `ensure_domain_schema_creates_*` test for 12 tables + correct ordering |

## Interfaces / Contracts

```python
@dataclass(frozen=True, slots=True)
class CasaAcogida:
    id: str
    nombre: str
    apellidos: str
    dni_acogedor: str | None
    calle: str
    numero: str | None
    piso: str | None
    letra: str | None
    localidad: str | None
    provincia: str | None
    cp: str | None
    telefono: str
    telefono2: str | None
    email: str | None
    vinculacion: str | None
    caracteristicas: str | None
    coche: str  # "Sí" | "No"
    especie_preferente: str | None  # "CANINA" | "FELINA" | None
    observaciones: str | None
    capacidad: int
    fecha_alta: str | None
    fecha_baja: str | None
    updated_at: str | None
    activo: bool = True


class CasaAcogidaConflictError(ValueError):
    """Raised when a natural-key conflict occurs (e.g., duplicate DNI)."""


def create_casa_acogida(client, params: dict[str, Any]) -> CasaAcogida: ...
def list_casas_acogida(client, especie: str | None = None) -> list[CasaAcogida]: ...
def get_casa_acogida_by_id(client, casa_id: str) -> CasaAcogida | None: ...
def update_casa_acogida(client, casa_id: str, params: dict[str, Any]) -> CasaAcogida | None: ...
def delete_casa_acogida(client, casa_id: str) -> bool: ...
```

Validation contract:
- Required: `nombre`, `apellidos`, `calle`, `telefono`, `coche`, `capacidad`.
- `coche` ∈ {"Sí", "No"} (with tilde).
- `especie_preferente` ∈ {"CANINA", "FELINA", None}.
- `capacidad` positive int (≥ 1).
- Empty strings (after `.strip()`) are treated as missing.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Service unit | create happy path, required-field validation (5 fields), coche enum (Sí/No/sad path), especie_preferente enum (CANINA/FELINA/null/sad), capacidad positive int (3 valid, 0/-1/non-int invalid), list without filter, list with especie filter (incl. IS NULL match), get by id (found/None), update happy + sad validation, soft-delete (`activo=false` + `fecha_baja=now()`) | `tests/test_foster.py` with `httpx.MockTransport` capturing SQL |
| Routes | Auth guard on 5 endpoints, form render with CSRF, stage POST redirect to detail, sad validation re-render form with 422, delete redirect, no SQL in routes | `tests/test_foster_routes.py` with `AsyncClient` + dependency overrides + `_NoSqlRouteClient` |
| XSS | All new templates covered; no user data in URL attributes | `tests/test_xss_audit.py` updated for `casas_acogida/list.html`, `form.html`, `detail.html` |
| Review | Architecture/security/SOLID | R1 risk + R3 reliability lens before merge |

## Migration / Rollout

Schema adds one new table `casas_acogida`. Forward path: `ensure_domain_schema` includes the new constant via `CREATE TABLE IF NOT EXISTS`. Idempotent.

Rollback: revert the PR. Table remains (empty) on rollback.

## PR Slicing

Single PR (pre-MVP single-branch per AGENTS.md §15.2). The change is large but stays within the precedent set by #41 INTAKE-03 (~2700 lines) and #65 CATALOG-01 in the same project.

## Open Questions

None for this slice. Capacity computation against active foster stays (`acogidas` with `fecha_final IS NULL`) is scope of FOSTER-03 and depends on FOSTER-02 adding the FK from `acogidas` to `casas_acogida`.

## Skill Resolution

skill_resolution: paths-injected