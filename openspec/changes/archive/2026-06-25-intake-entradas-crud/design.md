# Design: Intake Entradas CRUD

## Technical Approach

Implement a minimal, TDD-first CRUD slice over the public intake-entry fields of `entradas` while preserving the physical columns already referenced by the migration mapping. The new `app/modules/entradas` module follows the current `animals` pattern: routes handle HTTP/auth/templates only; `service.py` owns SQL, dataclass mapping, validation, duplicate handling, and FK checks. Public service/form scope is limited to: `id`, `animal_id`, optional `voluntario_entrada_id`, `fecha_entrada`, `origen`, `motivo`, `observaciones`, `activo`, and timestamps if returned internally. The physical table keeps nullable `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, and `donativo_entregador` for `app/core/migration/mappings/entrada.yaml` compatibility, but this slice does not expose or write them through the CRUD surface. This change writes only the minimal public `entradas` fields; lifecycle event/state writes and salida/entrega/donativo workflows are out of scope.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Public intake scope | Expose only the spec-approved minimal intake fields in service contracts and forms | Surface all existing `entradas` columns such as salida/entrega/donativo | Prevents scope drift into deferred legacy workflows while still using the current physical table. |
| Physical schema compatibility | Keep nullable salida/entrega/donativo columns in `ENTRADAS_CREATE_TABLE_SQL` because `entrada.yaml` maps them | Remove the columns and change migration mapping in the same slice | Mapping changes are a separate migration decision; PR 1 must not break existing legacy-data import contracts. |
| SQL ownership | All `entradas` SQL lives in `app/modules/entradas/service.py` | Direct route SQL or shared route helpers | Enforces APAP layer rules and avoids copying the known `voluntarios` direct-SQL caveat. |
| Validation/errors | Service validates required fields, dates, FK existence/activity, and translates duplicate natural-key failures to `EntradaConflictError` (or a clearly named `ValueError` variant) | Leak `InsForgeError` to routes as the intended duplicate contract | Routes should translate service/domain errors to HTTP 409/422; infrastructure errors are not the route contract for this slice. |
| Volunteer eligibility | Eligible intake volunteer means `activo=true` for this slice | Require `RolVoluntario.INTAKE` now | The spec only says active volunteer eligible for intake; role enforcement is deferred unless RED tests/specs are updated before implementation. |
| Delivery | Force chained review slices under 400 changed lines | One large PR | Proposal spans schema, service, routes, templates, and tests; chained work protects reviewer focus. |

## Data Flow

```text
Browser form -> entradas.routes -> entradas.service -> InsForge/PostgREST
                  |                    |
                  |                    +-> animales/voluntarios FK lookups
                  +-> Jinja2 templates <- dataclass result / ValueError
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/modules/entradas/__init__.py` | Create | Module package marker. |
| `app/modules/entradas/service.py` | Create | `Entrada` dataclass, SQL constants, validation, CRUD API. |
| `app/modules/entradas/routes.py` | Create | Protected list/detail/new/create/edit/update/delete routes. |
| `app/templates/entradas/list.html` | Create | Spanish list page with create/detail/edit actions. |
| `app/templates/entradas/detail.html` | Create | Spanish read view for one entry. |
| `app/templates/entradas/form.html` | Create | Shared create/edit form exposing only minimal intake fields. |
| `app/main.py` | Modify | Import/include `entradas_router`. |
| `app/templates/base.html` | Modify | Add `Entradas` navigation link when route exists. |
| `tests/test_domain.py` | Modify if needed | RED test only if #87 requires schema/assertion adjustment for physical migration compatibility or the accepted minimal public contract. |
| `tests/test_entradas.py` | Create | Service SQL/validation tests. |
| `tests/test_entradas_routes.py` | Create | Route delegation/auth/render/redirect tests. |
| `tests/test_entradas_routes_redirects.py` | Create if useful | Unauthenticated/unauthorized redirect coverage. |

## Interfaces / Contracts

```python
@dataclass(frozen=True, slots=True)
class Entrada:
    id: str
    animal_id: str
    fecha_entrada: str
    activo: bool = True
    voluntario_entrada_id: str | None = None
    origen: str | None = None
    motivo: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None

class EntradaConflictError(ValueError): ...

def create_entrada(client, params: dict[str, Any]) -> Entrada: ...
def list_entradas(client) -> list[Entrada]: ...
def get_entrada_by_id(client, entrada_id: str) -> Entrada | None: ...
def update_entrada(client, entrada_id: str, params: dict[str, Any]) -> Entrada | None: ...
def delete_entrada(client, entrada_id: str) -> bool: ...
```

Validation contract: `animal_id` and `fecha_entrada` are required; `voluntario_entrada_id` is nullable but, when present, must resolve to an active volunteer. Duplicate `(animal_id, fecha_entrada)` is owned by the service and raised as `EntradaConflictError` (or an equivalent documented domain `ValueError` subtype) for routes to translate to 409. Physical deletes are forbidden; delete means `activo=false`.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Schema | Current `entradas` physical columns/FKs/natural key remain valid while public CRUD scope remains minimal | Existing `test_domain.py`; add RED only for required schema gap. |
| Unit | SQL shape, params, minimal mapping, active-volunteer validation, duplicate-to-domain-error translation, soft-delete | `tests/test_entradas.py` with real `InsForgeClient` + `httpx.MockTransport`. |
| Route | Auth guards, minimal form parsing, redirects, 404/409/422, no route SQL | FastAPI `AsyncClient`, dependency overrides/spies, Spanish template assertions. |
| Review | Architecture/security/SOLID per slice | Run `code-review-expert` before any slice promotion. |

## Migration / Rollout

No destructive migration required. PR 1 keeps the physical `entradas` columns required by the existing `entrada.yaml` mapping. If #87 adds a constraint, ship it as the first slice with a rollback SQL note. Rollback is by reverting the affected slice PR; data remains in `entradas` and soft-deleted rows are preserved.

## PR Slicing

1. #87 schema/spec clarification: domain test/schema only, `pytest`, `ruff check .`, `python -m build`, `code-review-expert`.
2. #88 service + TDD: `app/modules/entradas/service.py` and `tests/test_entradas.py`, same gates.
3. #89 routes/templates + route TDD: router, templates, app/nav wiring, route tests, same gates.

## Open Questions

None. Role-specific `RolVoluntario.INTAKE` enforcement is explicitly deferred unless the RED tests/spec change before implementation.

## Skill Resolution

skill_resolution: paths-injected
