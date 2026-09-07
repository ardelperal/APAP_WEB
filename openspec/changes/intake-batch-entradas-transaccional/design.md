# Design: INTAKE-02 — Entradas Batch Transaccional

## Technical Approach

Extend `app/modules/entradas/` (sin tocar el slice INTAKE-01) con un sub-módulo de batch que:

1. Recibe un array N de entrada records (mismo shape que `_WRITE_COLUMNS` de INTAKE-01).
2. Persiste cada record en una nueva tabla `entradas_batch_staging` agrupados por un `batch_id` UUID. Cada fila incluye `sequence` para preservar orden del operador.
3. Valida **dos veces**:
   - **Pre-staging**: cada record se valida contra `animales` (existe) y `voluntarios` (existe+activo). Los errores per-record se devuelven en la preview sin abortar el batch entero.
   - **Cross-batch**: dentro del array, no puede haber `(animal_id, fecha_entrada)` duplicado. Si lo hay, batch entero rechazado con 422 + error claro, SIN escribir staging.
4. En el commit, copia todas las filas de staging para `batch_id` a `entradas` usando un script SQL multi-statement transaccional (`BEGIN; INSERT ...; INSERT ...; COMMIT;` o equivalente PostgREST) ejecutado por `app/core/migration/sql_runner.py`. Cualquier `entradas_natural_key` violation o FK violation rollbackea total.
5. Tras commit exitoso: `DELETE FROM entradas_batch_staging WHERE batch_id = $1`.
6. Cancel explícito: `DELETE FROM entradas_batch_staging WHERE batch_id = $1`.

Esto preserva fidelidad al legacy `TbEntradasMultiplesAuxIniciales` (D-BATCH-01), la validación cross-batch pertenece al servicio antes de tocar la DB (D-BATCH-03), y la atomicidad se garantiza a nivel de transacción SQL (D-BATCH-02).

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Atomicidad | Script SQL multi-statement ejecutado por `sql_runner` con `BEGIN/COMMIT` | RPC dedicado LocalBackend; SAVEPOINT por statement | PostgREST soporta multi-statement via RPC legacy `/_mcp_query_runner` ya usado por la migración; sin necesidad de exponer endpoint adicional |
| Staging storage | Tabla física `entradas_batch_staging` con PK `(batch_id, sequence)` | JSON en sesión; tabla en memoria con TTL | Fidelidad al legacy + preview persistente + cancel/commit sobre mismo estado |
| Cross-batch validation | Service code antes de tocar DB (lista en memoria O(N²) sobre el batch) | App-level hash index; DB-side via una query `EXISTS` con `IN (SELECT ...)` | N operativa esperada <100; la validación es trivial y cubre tanto intra-batch como contra DB existente en una sola pasada |
| Error reporting | Preview muestra TODOS los errores per-record (no para en el primero) | First-error-wins | Operador quiere ver todo lo que tiene que arreglar antes de reintentar |
| Routes vs sub-router | Sub-router `app/modules/entradas/batch_routes.py` montado bajo `/entradas/batch` | Añadir a `app/modules/entradas/routes.py` | Mantiene `entradas/routes.py` enfocado en CRUD individual; sub-router más limpio |
| Form shape | 5 filas fijas en `batch_new.html` con botón "Añadir fila" vía HTMX | Filas dinámicas server-side con `?rows=N` | El repo usa HTMX; sin recargas; simple |
| Cancel HTTP verb | `DELETE /entradas/batch/{batch_id}` con un form que dispara el DELETE vía HTMX | `POST /entradas/batch/{batch_id}/cancel` | RESTful más correcto; el repo ya usa forms con `_method` override en otros módulos |

## Data Flow

```
Browser form (batch_new.html)
    |
    | POST /entradas/batch (array of records)
    v
batch_routes.create_batch_view
    |
    v
batch_service.stage_batch
    |  -- cross-batch uniqueness check (in-memory)
    |  -- per-record FK validation (SELECT animales, SELECT voluntarios)
    |  -- INSERT INTO entradas_batch_staging (one per record)
    v
BatchStaging { batch_id, records[(idx, params, status, error)] }
    |
    v
redirect /entradas/batch/{batch_id}  --> batch_preview.html
    
    POST /entradas/batch/{batch_id}/commit
        |
        v
    batch_service.commit_batch
        |  -- script SQL transaccional via sql_runner
        |       BEGIN;
        |       INSERT INTO entradas ... [for each staging row];
        |       DELETE FROM entradas_batch_staging WHERE batch_id = $1;
        |       COMMIT;
        v
    list[Entrada] --> redirect /entradas with success message
        |
        | on failure: rollback + staging intact
        v
    redirect /entradas/batch/{batch_id} with error overlay
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/core/domain.py` | Modify | Add `ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL` constant; add to ensure_domain_schema execution list |
| `app/modules/entradas/batch_service.py` | Create | `stage_batch`, `commit_batch`, `cancel_batch`, `get_batch`, plus helpers `_validate_batch_records`, `_check_cross_batch_uniqueness` |
| `app/modules/entradas/batch_routes.py` | Create | Sub-router with 5 endpoints (new, post, preview, commit, cancel) |
| `app/modules/entradas/__init__.py` | Modify | Export sub-router and batch_service public API |
| `app/main.py` | Modify | Include the batch sub-router (mounts `/entradas/batch`) |
| `app/templates/entradas/batch_new.html` | Create | Form with 5 rows + HTMX "add row" + CSRF token |
| `app/templates/entradas/batch_preview.html` | Create | Preview table with per-record status + Confirmar/Cancelar forms + CSRF token |
| `app/templates/base.html` | Modify | Add "Entradas en lote" nav link |
| `tests/test_entradas_batch.py` | Create | Service unit tests: validation, cross-batch, atomic commit, atomic rollback, staging lifecycle |
| `tests/test_entradas_batch_routes.py` | Create | Route tests: auth, form render, redirects, CSRF, no SQL in routes |

## Interfaces / Contracts

```python
@dataclass(frozen=True, slots=True)
class BatchRecord:
    sequence: int
    params: dict[str, Any]
    status: Literal["valid", "invalid"]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BatchStaging:
    batch_id: str
    created_at: str
    records: tuple[BatchRecord, ...]


class BatchValidationError(ValueError):
    """Raised when the entire batch is rejected before staging (e.g., cross-batch duplicate)."""


def stage_batch(client, records: list[dict[str, Any]]) -> BatchStaging: ...
def commit_batch(client, batch_id: str) -> list[Entrada]: ...
def cancel_batch(client, batch_id: str) -> None: ...
def get_batch(client, batch_id: str) -> BatchStaging | None: ...
```

Validation contract:
- Each record: required fields (`animal_id`, `fecha_entrada`), FK checks against `animales` / `voluntarios` (same as INTAKE-01).
- Cross-batch: no two records with same `(animal_id, fecha_entrada)`. If detected, `BatchValidationError` raised BEFORE any DB write.
- Per-record errors during staging are NOT fatal — they go into `BatchRecord.error` so preview shows all of them.

Routes:
- `GET /entradas/batch/new` → render form.
- `POST /entradas/batch` → call `stage_batch`; on `BatchValidationError` render form again with 422 + error; on success redirect to `/entradas/batch/{batch_id}`.
- `GET /entradas/batch/{batch_id}` → render preview; if not found → 404.
- `POST /entradas/batch/{batch_id}/commit` → call `commit_batch`; on success redirect to `/entradas` with success message; on failure (FK / natural key violation during copy) redirect back to preview with error overlay.
- `DELETE /entradas/batch/{batch_id}` (via form with `_method`) → call `cancel_batch`; redirect to `/entradas/batch/new`.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Service unit | per-record validation (happy/sad/edge), cross-batch uniqueness (intra-batch dupe), atomic commit happy path, atomic rollback on mid-batch failure (FK violation during copy), staging lifecycle (stage → preview → commit → staging empty; stage → cancel → staging empty) | `tests/test_entradas_batch.py` with real `LocalBackendClient` + `httpx.MockTransport` capturing SQL calls in order |
| Routes | auth guard, form render, stage POST redirect to preview, commit POST redirect to /entradas, cancel DELETE redirect, CSRF token in all 3 forms, no `client.execute_sql(...)` in routes (regex check) | `tests/test_entradas_batch_routes.py` with `AsyncClient` + dependency overrides/spies |
| Review | Architecture/security/SOLID | R1 risk + R3 reliability lens before PR |

## Migration / Rollout

Schema adds one new table `entradas_batch_staging`. Forward path: `ensure_domain_schema` includes the new constant, so the table is created at app startup via `CREATE TABLE IF NOT EXISTS`. No destructive migration. No data backfill needed (staging is empty on fresh deploy).

Rollback: revert the PR. Staging table is dropped via the next `DROP TABLE` on rollback migration if needed; for v1 we simply leave the table empty post-rollback.

## PR Slicing

Single PR if changes < 400 lines. If over budget:
- PR A: phase 1 (schema + service + tests) — ~250 lines
- PR B: phase 2 (routes + templates + tests) — ~200 lines

Stacked on `main` (pre-MVP). Both PRs share the same final shape and are merged consecutively.

## Open Questions

None. The atomicity strategy is solid (sql_runner multi-statement), staging matches legacy semantics, and the cross-batch uniqueness rule is in scope for issue #40's acceptance criteria.

## Skill Resolution

skill_resolution: paths-injected