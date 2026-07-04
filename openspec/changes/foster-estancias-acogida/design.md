# Design: FOSTER-02 — Estancias de Acogida (CRUD con FK a casa y voluntarios)

## Technical Approach

Implementar un slice CRUD sobre la entidad **Estancia de Acogida** (legacy `TbAcogidaAnimal`, ya migrada como tabla `acogidas` en INTAKE-01) siguiendo el patrón ya establecido por `app/modules/entradas/` (INTAKE-01) y `app/modules/foster/` (FOSTER-01). La mejora principal de este slice es:

1. Añadir la columna `casa_acogida_id UUID REFERENCES casas_acogida(id)` mediante `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (idempotente, sin reorganizar `ensure_domain_schema`).
2. Validar que cualquier `voluntario_*_id` presente apunte a un voluntario **activo** (active check de VOL-05).
3. Helpers públicos `compute_duracion` e `is_active` para que la UI pueda mostrar la duración de la estancia y filtrar activas sin recalcular en cada template.
4. Separar `close_acogida` (evento de ciclo de vida) de `delete_acogida` (soft-delete real), manteniendo `activo = true` en el close.

El service surface público: `create_acogida`, `list_acogidas(activas_solo=False)`, `get_acogida_by_id`, `update_acogida`, `close_acogida`, `delete_acogida`, `compute_duracion`, `is_active`.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| `casa_acogida_id` opcional | Nullable FK a `casas_acogida(id)` | NOT NULL | Retro-compat con legacy (algunas estancias históricas no tienen casa asignada tras soft-delete). FOSTER-03 decidirá si lo hace obligatorio. |
| FK estructurada a `casas_acogida` | UUID FK en vez de free-text o INT legacy | Mantener free-text como legacy | P1 fidelidad: legacy tenía `IDAcogidaCasa` INT con FK estructurada. Web mantiene FK estructurada (UUID en vez de INT — patrón del proyecto). Cero pérdida. |
| FKs estructuradas a `voluntarios` | UUID FKs en vez de TEXT nombres legacy | Mantener TEXT libre como legacy | Mejora de fidelidad: legacy guardaba nombres en free-text, lo que rompía si el voluntario cambiaba de nombre. Web tiene FKs estructuradas; el nombre se resuelve por JOIN. Validación active-check evita asignar a voluntarios inactivos. |
| `close_acogida` mantiene `activo = true` | Solo `fecha_final = current_date` | `activo = false` también | D-EST-04: `close` es evento de ciclo de vida (animal vuelve al albergue), NO soft-delete. Soft-delete = `delete_acogida` con `activo = false`. |
| Migración ALTER TABLE explícita | `ACOGIDAS_ADD_CASA_FK_SQL` constante separada | Añadir al `CREATE TABLE` directamente | D-EST-05: el diff entre FOSTER-01 y FOSTER-02 muestra el cambio explícitamente. El `CREATE TABLE` permanece congelado. `ADD COLUMN IF NOT EXISTS` es idempotente. |
| `compute_duracion` e `is_active` en service | Helpers públicos puros (sin DB) | Recalcular en cada template / query | Service owns la lógica; templates consumen los helpers como atributos. Tests atómicos sin mock de DB. |
| Validación animal_id activo | Igual que entradas (animal debe existir) | No validar (aceptar cualquier UUID) | Consistencia con `entradas._validate_references`. Animal inactivo no debería recibir nuevas estancias. |
| Orden de creación: `casas_acogida` ANTES de `acogidas` | Sin cambios (ya correcto en FOSTER-01) | Reordenar `ensure_domain_schema` | FOSTER-01 ya posicionó `casas_acogida` antes de `acogidas` para que FOSTER-02 pudiese añadir la FK con un simple `ALTER TABLE`. No requiere reorden. |
| Tests con `httpx.MockTransport` | Mismo patrón que `tests/test_foster.py` y `tests/test_entradas.py` | TestClient integration puro | Mock transport permite assert SQL exacto sin red; permite verificar el patrón de active check de voluntarios. |

## Data Flow

```
Browser form (acogidas/form.html)
    |
    | POST /acogidas (form fields)
    v
acogidas_routes.create_acogida_view
    |
    v
acogidas_service.create_acogida
    |  -- required: animal_id (existe y activo)
    |  -- required: fecha_inicio (no vacía)
    |  -- opcional: casa_acogida_id (existe y activo en casas_acogida)
    |  -- opcional: voluntario_*_id (existe y activo en voluntarios, x4)
    v
INSERT INTO acogidas (...)
    |
    v
Acogida dataclass → redirect /acogidas/{id}
```

```
Browser detail (acogidas/detail.html)
    |
    v
acogidas_service.get_acogida_by_id
    |
    v
Acogida dataclass
    |
    v
Template renders:
  - duracion = compute_duracion(acogida)  (en días o "Abierta")
  - active = is_active(acogida)  (para botones contextuales)
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/core/domain.py` | Modify | Add `ACOGIDAS_ADD_CASA_FK_SQL` constant; `ensure_domain_schema` calls it AFTER `ACOGIDAS_CREATE_TABLE_SQL` |
| `app/modules/acogidas/__init__.py` | Create | Module package marker; re-exports `service` public surface |
| `app/modules/acogidas/service.py` | Create | `Acogida` dataclass, `AcogidaConflictError`, SQL constants, validation, CRUD API, helpers `compute_duracion` + `is_active` |
| `app/modules/acogidas/routes.py` | Create | Protected list/new/create/detail/edit/update/close/delete routes |
| `app/main.py` | Modify | Import + `include_router(acogidas_router)` (after `foster_router`) |
| `app/templates/acogidas/list.html` | Create | List of stays (active + closed) with filter by `activas_solo` |
| `app/templates/acogidas/form.html` | Create | Shared create/edit form (form_action context-dependent) |
| `app/templates/acogidas/detail.html` | Create | Read view of one stay with edit/close/delete actions + duration field |
| `app/templates/base.html` | Modify | Add "Estancias de acogida" nav link between "Casas de acogida" and "Voluntarios" |
| `tests/test_acogidas.py` | Create | Service unit tests (~25 atoms) |
| `tests/test_acogidas_routes.py` | Create | Route tests (~15 atoms) |
| `tests/test_xss_audit.py` | Modify | Add `acogidas/*` entries to `TEMPLATE_SPECS`; extend `handler_controlled` allowlist |
| `tests/test_domain.py` | Modify | Verify `ensure_domain_schema` still produces 12 tables + add test for the new ALTER TABLE statement |

## Interfaces / Contracts

```python
@dataclass(frozen=True, slots=True)
class Acogida:
    id: str
    animal_id: str
    fecha_inicio: str
    activo: bool = True
    casa_acogida_id: str | None = None
    voluntario_acogida_id: str | None = None
    voluntario_seguimiento1_id: str | None = None
    voluntario_seguimiento2_id: str | None = None
    voluntario_sanitario_id: str | None = None
    fecha_final: str | None = None
    entrada_origen_id: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    fecha_baja: str | None = None  # populated by delete_acogida (soft-delete timestamp)


class AcogidaConflictError(ValueError):
    """Raised when a natural-key conflict occurs."""


def create_acogida(client, params: dict[str, Any]) -> Acogida: ...
def list_acogidas(client, activas_solo: bool = False) -> list[Acogida]: ...
def get_acogida_by_id(client, acogida_id: str) -> Acogida | None: ...
def update_acogida(client, acogida_id: str, params: dict[str, Any]) -> Acogida | None: ...
def close_acogida(client, acogida_id: str) -> Acogida | None: ...  # fecha_final = current_date, activo stays true
def delete_acogida(client, acogida_id: str) -> bool: ...  # activo = false, fecha_baja = now()
def compute_duracion(acogida: Acogida) -> int | None: ...  # None when open
def is_active(acogida: Acogida) -> bool: ...  # activo AND fecha_final IS NULL
```

Validation contract:
- Required: `animal_id`, `fecha_inicio`.
- `animal_id` must reference an active `animales` row.
- `casa_acogida_id` optional; if present, must reference an active `casas_acogida` row.
- `voluntario_*_id` (4 of them) optional; if present, must reference an active `voluntarios` row (rechaza inactivos — VOL-05).
- `fecha_inicio` non-empty after `.strip()`.
- `entrada_origen_id` optional; if present, must reference an existing `entradas` row (NOT active-checked: legacy entries might be soft-deleted, but the FK should still work).
- `direccion`, `telefono`, `observaciones` optional, free-text (legacy denormalized).
- Empty strings (after `.strip()`) count as missing for required fields.
- Soft-delete via `activo = false` + `fecha_baja = now()`. Physical deletes are forbidden.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Service unit | create happy path, create with casa_acogida_id null, create rejects animal missing, create rejects casa missing, create rejects casa inactive, create rejects volunteer inactive (parametrized over 4 *_id), create rejects empty fecha_inicio, list returns active+closed ordered, list with activas_solo filter, get_by_id (found/None), update happy + sad, close_acogida (fecha_final=today, activo stays true), delete_acogida (activo=false), compute_duracion (open/closed/same-day), is_active (open/closed/soft-deleted) | `tests/test_acogidas.py` with `httpx.MockTransport` capturing SQL |
| Routes | Auth guard on 7 endpoints, form render with CSRF, create POST redirect to detail, sad validation re-render form with 422, detail 404 when missing, edit form prefilled, update happy + sad, close happy + 404, delete happy + 404, no SQL in routes | `tests/test_acogidas_routes.py` with `AsyncClient` + dependency overrides + `_NoSqlRouteClient` |
| Schema | `ACOGIDAS_ADD_CASA_FK_SQL` constant exists, is referenced in `ensure_domain_schema` after the CREATE TABLE for acogidas, has `ADD COLUMN IF NOT EXISTS` and the FK to `casas_acogida` | Extend `tests/test_domain.py` |
| XSS | All 3 new templates covered; `form_action` allowlist for `acogidas/form.html`; no user data in URL attributes | `tests/test_xss_audit.py` updated for `acogidas/list.html`, `form.html`, `detail.html` |
| Review | Architecture/security/SOLID | R1 risk + R3 reliability lens before merge |

## Migration / Rollout

Schema adds one column to `acogidas` via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Forward path: `ensure_domain_schema` includes the new constant after the CREATE TABLE for `acogidas`. Idempotent: re-runs are no-ops on a database that already has the column.

Rollback: revert the PR. The column remains on rollback (empty) — re-running the migration is a no-op.

## PR Slicing

Single PR (pre-MVP single-branch per AGENTS.md §15.2). The change is large but stays within the precedent set by FOSTER-01 (#43, ~3000 lines merged in a single commit) and #41 INTAKE-03 (~2700 lines).

## Open Questions

None for this slice. Capacity computation against active foster stays is scope of FOSTER-03 (depends on this FK being in place).

## Skill Resolution

skill_resolution: paths-injected
