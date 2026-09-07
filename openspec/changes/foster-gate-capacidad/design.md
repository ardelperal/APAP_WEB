# Design: FOSTER-03 — Gate de especie + advisory de capacidad con override auditado

## Technical Approach

Implementar un **slice de admisión** que evalúa "¿puedo asignar este animal a esta casa?" antes de crear la estancia. Sigue el patrón establecido por FOSTER-01 (`app/modules/foster/service.py`) y FOSTER-02 (`app/modules/acogidas/service.py`):

1. **Nuevo módulo** `app/modules/foster/assignment.py` con la lógica de gate + capacity check + audit de overrides. NO modifica `app/modules/foster/service.py` (CRUD de casas) ni `app/modules/acogidas/service.py` (CRUD de estancias).
2. **Tabla propia** `foster_capacity_overrides` (D-GC-01) para auditar overrides. Idempotente vía `CREATE TABLE IF NOT EXISTS`.
3. **Sub-router** `app/modules/foster/assignment_routes.py` con 3 endpoints: `GET/POST /casas-acogida/{id}/asignar` y `GET /casas-acogida/{id}/overrides`.
4. **Dos templates nuevos** (`casas_acogida/asignar.html`, `casas_acogida/overrides.html`) + modificación del `detail.html` existente.
5. **Sin cambios a `create_acogida`** (D-GC-05): el gate es ortogonal al create. El flow del operador pasa por el gate antes del create, pero el create sigue siendo FOSTER-02 puro.

El gate vive en su propio formulario con su propio audit log; el create vive en su propio formulario con su propio log.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Tabla para overrides | `foster_capacity_overrides` propia | Reusar `animal_lifecycle_events` con `event_type = 'CAPACITY_OVERRIDE'` | D-GC-01: query directa indexable; semántica distinta (operador sobre asignación vs evento del animal); cero ambigüedad para la derivación futura. |
| Identidad del operador | `user_id` UUID de `usuarios_autorizados` | Email del operador | D-GC-02: UUID es join key natural; email puede cambiar; `user_id` ya está en la sesión vía `read_session_payload`. |
| Capacity count JOIN | `JOIN acogidas JOIN animales WHERE (especie = casa.especie_preferente OR casa.especie_preferente IS NULL)` | Denormalizar especie en `acogidas`; contar todas las estancias | D-GC-03: cierra OD-3a (capacidad solo para la especie preferida); replica el patrón conservador de "cualquier especie" del FOSTER-01; sin índices adicionales hoy. |
| Response shape del gate | `AssignmentDecision(decision, reason, warnings)` | Tupla `(str, str)`; dict plano; boolean `is_blocked` + `warnings_list` separados | D-GC-04: `Literal` permite exhaustividad en tests; `warnings: tuple[str, ...]` es inmutable; `decision in {"admit", "admit_with_warning"}` deriva `can_proceed` sin campo redundante. |
| Gate como módulo separado | `foster.assignment` con `evaluate_assignment`, `record_override`, `list_overrides_for_casa` | Función dentro de `acogidas.service.create_acogida`; helper dentro de `foster.service` | D-GC-05: ortogonal al create; tests no regresan; scripts de seed/migration pueden bypass el gate sin tocar código de producción. |
| Override siempre registrado antes del redirect | `record_override` corre dentro del POST handler antes del 303 a `/acogidas/new` | Override opcional post-create de estancia | Si el operador abandona el create tras el warning, el override queda registrado. Trazabilidad completa. |
| Estancias activas en detail | COUNT(*) en service | JOIN con render de tabla completa en detail | Detail muestra SOLO el count (cuántas hay). Una tabla completa de estancias requeriría un módulo `acogidas.list_by_casa` out of scope. El operator puede ir a `/acogidas?activas_solo=1` para verlas. |
| Histórico de overrides en detail | `list_overrides_for_casa` con LIMIT 10 | Sin límite (volumetría impredecible) | 10 es razonable para vista rápida; el operator puede ir a `/casas-acogida/{id}/overrides` para la tabla completa. |

## Data Flow

```
Browser → GET /casas-acogida/{id}/asignar
    ↓
assignment_routes.asignar_form (GET)
    ↓ renderiza form con animal_id UUID (vacío), motivo (vacío, hidden)

Browser → POST /casas-acogida/{id}/asignar  (animal_id, motivo?)
    ↓
assignment_routes.asignar_submit (POST)
    ↓
assignment_service.evaluate_assignment(client, animal_id, casa_id)
    ↓ SELECT animal FROM animales WHERE id = $1
    ↓ SELECT casa FROM casas_acogida WHERE id = $1
    ↓ casa.activo == false → raise ValueError
    ↓ gate de especie: si casa.especie_preferente != animal.especie → block
    ↓ SELECT count FROM JOIN acogidas JOIN animales WHERE casa_acogida_id = $1 AND fecha_final IS NULL AND activo = true AND (especie = casa.especie_preferente OR casa.especie_preferente IS NULL)
    ↓ si count >= capacidad → admit_with_warning
    ↓ else → admit
    ↓
AssignmentDecision dataclass
    ↓
[caso block] render form con error 422
    ↓
[caso admit] 303 redirect /acogidas/new?animal_id=X&casa_acogida_id=Y
    ↓
[caso admit_with_warning + motivo]
    ↓
assignment_service.record_override(client, casa_id, animal_id, user_id, motivo)
    ↓ INSERT INTO foster_capacity_overrides
    ↓ log_safe("foster.capacity_override.recorded", ...)
    ↓
303 redirect /acogidas/new?animal_id=X&casa_acogida_id=Y
    ↓
[caso admit_with_warning sin motivo] re-render form con warning visible + mensaje "el motivo es obligatorio para continuar"
```

```
Browser → GET /casas-acogida/{id}/overrides
    ↓
assignment_routes.overrides_list (GET)
    ↓
assignment_service.list_overrides_for_casa(client, casa_id)
    ↓ SELECT * FROM foster_capacity_overrides WHERE casa_acogida_id = $1 ORDER BY created_at DESC
    ↓
foster_capacity_overrides/*.html → tabla con created_at, animal_id, motivo, operador_user_id
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/core/domain.py` | Modify | Add `FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL` constant; `ensure_domain_schema` calls it AFTER `ACOGIDAS_ADD_CASA_FK_SQL` |
| `app/modules/foster/__init__.py` | Modify | Re-export `assignment_service` (sub-module) |
| `app/modules/foster/assignment.py` | Create | `AssignmentDecision` + `FosterCapacityOverride` dataclasses, `evaluate_assignment`, `record_override`, `list_overrides_for_casa` |
| `app/modules/foster/assignment_routes.py` | Create | Sub-router con 3 endpoints (asignar GET/POST, overrides GET) |
| `app/main.py` | Modify | Import + `include_router(assignment_router)` after `foster_router` |
| `app/templates/casas_acogida/asignar.html` | Create | Form con campo `animal_id` + campo `motivo` (visible solo si hay warning) + sección de resultado |
| `app/templates/casas_acogida/overrides.html` | Create | Tabla del historial de overrides |
| `app/templates/casas_acogida/detail.html` | Modify | Sección "Estancias activas" + botón "Asignar animal" + "Histórico de overrides" (últimos 10) |
| `openspec/changes/foster-gate-capacidad/proposal.md` | Create | Issue scope + decisiones + trazabilidad |
| `openspec/changes/foster-gate-capacidad/design.md` | Create | Technical approach + data flow + interfaces |
| `openspec/changes/foster-gate-capacidad/specs/foster-gate-capacidad/spec.md` | Create | Requirements + scenarios |
| `openspec/changes/foster-gate-capacidad/tasks.md` | Create | Implementation phases |
| `tests/test_foster_assignment.py` | Create | Service unit tests (~25 atoms) |
| `tests/test_foster_assignment_routes.py` | Create | Route tests (~15 atoms) |
| `tests/test_xss_audit.py` | Modify | Add `casas_acogida/asignar.html` + `casas_acogida/overrides.html` to `TEMPLATE_SPECS`; extend `handler_controlled` allowlist if needed |
| `tests/test_domain.py` | Modify | Add test for the new `FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL` constant; update `test_ensure_domain_schema_creates_twelve_tables_plus_one_alter` to expect 14 CREATE TABLE + 1 ALTER = 15 total |
| `docs/roadmap.md` | Modify | Quita #45 de §4 abiertas, añade a §5-bis cerradas con SHA (post-commit) |

## Interfaces / Contracts

```python
@dataclass(frozen=True, slots=True)
class AssignmentDecision:
    """Result of evaluating a potential foster assignment."""

    decision: Literal["admit", "block", "admit_with_warning"]
    reason: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FosterCapacityOverride:
    """One audit row for a capacity override."""

    id: str
    casa_acogida_id: str
    animal_id: str
    operador_user_id: str
    motivo: str
    created_at: str


def evaluate_assignment(
    client: LocalBackendClient, animal_id: str, casa_id: str
) -> AssignmentDecision:
    """Evaluate a foster assignment.

    Raises ValueError when:
    - animal_id does not reference an active animal
    - casa_id does not reference an active casa_acogida (casa inactiva
      o inexistente)
    """


def record_override(
    client: LocalBackendClient,
    casa_id: str,
    animal_id: str,
    operador_user_id: str,
    motivo: str,
) -> FosterCapacityOverride:
    """Record a capacity override.

    Raises ValueError when motivo is empty or whitespace-only.
    No INSERT executed when motivo is invalid.
    """


def list_overrides_for_casa(
    client: LocalBackendClient, casa_id: str
) -> list[FosterCapacityOverride]:
    """List overrides for one casa, ordered by created_at DESC."""
```

Validation contract:

- `animal_id` must reference an active `animales` row (same pattern as `acogidas._validate_references`).
- `casa_id` must reference an active `casas_acogida` row (FOSTER-01 pattern).
- `motivo` non-empty after `.strip()`.
- `operador_user_id` is taken from the session payload (`request.session["user_id"]`); never user input from a form field.

Capacity count SQL (D-GC-03):

```sql
SELECT COUNT(*) AS active_count
FROM acogidas a
JOIN animales ani ON ani.id = a.animal_id
WHERE a.casa_acogida_id = $1
  AND a.fecha_final IS NULL
  AND a.activo = true
  AND (
    ani.Especie = (
      SELECT especie_preferente FROM casas_acogida WHERE id = $1
    )
    OR (SELECT especie_preferente FROM casas_acogida WHERE id = $1) IS NULL
  )
```

A single statement folds the casa load + active count. Two reads instead of three (no separate `SELECT casa` followed by `SELECT count`). The COUNT result is compared against `casa.capacidad` (already loaded in the same statement via subquery — alternatively two queries are fine; the count query already implicitly asserts the casa exists by returning 0 if missing, so a casa-missing check could be done implicitly, but we prefer the explicit `raise ValueError` on casa-missing for cleaner error messages).

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Service unit | Happy path admit, species mismatch block, capacity OK admit, capacity exceeded warning, casa sin especie_preferente admite cualquier especie, animal no existe raise, casa no existe raise, casa inactiva raise, count solo especie preferida, count incluye cualquier-especie, record_override happy, motivo vacío raise, motivo whitespace raise, no INSERT cuando motivo inválido, list_overrides_for_casa ordenado DESC, lista vacía si sin overrides | `tests/test_foster_assignment.py` con `httpx.MockTransport` capturando SQL |
| Routes | Auth guard en 3 endpoints, CSRF en form, no SQL en routes, GET asignar renderiza form, POST admit → 303 con query params, POST block → 422 con error, POST admit_with_warning + motivo → graba override + 303, POST admit_with_warning sin motivo → re-render con warning, GET overrides renderiza tabla | `tests/test_foster_assignment_routes.py` con `AsyncClient` + dependency overrides + `_NoSqlRouteClient` |
| Schema | `FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL` constant exists, is referenced in `ensure_domain_schema` after the ALTER TABLE for `acogidas`, has FKs to `casas_acogida` + `animales` + `usuarios_autorizados`, has NOT NULL on motivo | Extend `tests/test_domain.py` |
| XSS | Los 2 nuevos templates cubiertos en `TEMPLATE_SPECS`; `form_action` allowlist para `casas_acogida/asignar.html` | `tests/test_xss_audit.py` |
| Review | Architecture/security/SOLID | R1 risk + R3 reliability lens antes de merge |

## Migration / Rollout

Schema adds one table (`foster_capacity_overrides`) via `CREATE TABLE IF NOT EXISTS`. The new table is positioned AFTER `ACOGIDAS_ADD_CASA_FK_SQL` (so both `casas_acogida` and `animales` exist before the FKs are declared). Idempotent: re-runs are no-ops on a database that already has the table.

Rollback: revert the PR. The table remains on rollback (empty) — re-running the migration is a no-op.

Forward compatibility: a future issue can add columns (e.g. `metadata JSONB` for context override reasons) via ALTER TABLE without disrupting existing rows.

## PR Slicing

Single PR (pre-MVP single-branch per AGENTS.md §15.2). The change is medium-sized: ~600 LOC of new code + ~400 LOC of new tests, plus the 4 SDD docs. Well within the precedent set by FOSTER-02 (~2400 lines merged in a single commit) and FOSTER-01 (~3000 lines).

No chained PR split needed. The slice is self-contained: schema + service + routes + templates + tests. Review surface is bounded.

## Open Questions

None. The D-GC-01/02/03/04/05 decisions resolve all known ambiguities. D-18 está cerrado (capacity counted only for preferred species). D-19 está cerrado (override auditado con motivo obligatorio).

Future work (out of scope):

- FOSTER-04+: añadir material assignment, abrir la puerta a gates por rol.
- FOSTER-04+: añadir índice BTREE en `acogidas(casa_acogida_id, fecha_final) WHERE activo = true` si la volumetría crece.
- Future: separación de capacidad por especie cuando `especie_preferente = NULL` se vuelve un patrón común (JSONB `capacidad_por_especie`).

## Skill Resolution

skill_resolution: paths-injected