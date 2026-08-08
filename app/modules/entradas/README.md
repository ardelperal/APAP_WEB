[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# entradas

This README documents the domain, tables, endpoints, and risks of the `entradas` module.

Este módulo gestiona las entradas de animales al albergue (INTAKE-01 e INTAKE-02). Una entrada registra el momento en que un animal ingresa al sistema, con soporte para captura individual y captura por lote con staging.

The sentence that organizes this module: an entry is the row that opens the animal's life in the protectora, with a single-record path for normal intake and a two-phase staging path for batch intake (Entradas Múltiples).

## Quick navigation

| Section | Purpose |
|---|---|
| What this is / is not | The slice's ownership boundary. |
| Domain | What this module owns across single-record and batch intake. |
| Tables backend | SQL surface the service depends on. |
| Endpoints | HTTP routes mounted at `/entradas` and `/entradas/batch`. |
| Service layer | Public functions exported by `app.modules.entradas`. |
| Layer type | How this module is wired (route, service, sub-routers, sub-service). |
| Risks and gotchas | Edge cases, natural-key conflicts, batch atomicity, and FK checks. |
| Cross-references | Audit, runbook, and adjacent-module docs. |
| Verification checklist | Acceptance items for a doc or code PR. |

## What this is / is not

| Is | Is not |
|---|---|
| The CRUD for the `entradas` table plus the batch staging table for multi-record intake. | The CRUD for `cesiones_propietario` (lives in `app/modules/cesiones`); the cesión references an existing entrada. |
| The publish surface for `Entrada`, `BatchRecord`, `BatchStaging`, `EntradaConflictError`, and `BatchValidationError`. | The CRUD for `acogidas` or `adopciones` (each is its own slice). |
| The route for the single-record form and the batch form. | The animal search or photo streaming endpoints (lives in `app/modules/animals`). |

## Domain

The `entradas` slice owns two cooperating surfaces:

- The single-record CRUD for the `entradas` table (INTAKE-01, issues #87, #88, #89). A row carries the `animal_id`, the `voluntario_entrada_id`, the `fecha_entrada`, and free-text origin and reason.
- The batch intake (INTAKE-02, issue #40) modelled on the legacy `TbEntradasMultiplesAuxIniciales` pre-commit staging pattern. The flow is `stage_batch` → `get_batch` preview → `commit_batch` atomic copy → `cancel_batch` cleanup.

The slice deliberately excludes the migration-compatibility physical columns `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, and `donativo_entregador`. They stay in the table for legacy import but are not written by this slice.

The slice runs the same FK-existence pattern as the adopciones and cesiones modules. The volunteer FK is checked against `voluntarios` with `activo = true` (VOL-05). The animal FK is checked against `animales` without the `activo` filter, so a soft-deleted animal can still own an entry during data cleanup. The UNIQUE on `(animal_id, fecha_entrada)` is the natural key.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `entradas` | `id`, `animal_id`, `voluntario_entrada_id`, `fecha_entrada`, `origen`, `motivo`, `observaciones`, `fecha_alta`, `updated_at`, `activo` | One entry per row. UNIQUE on `(animal_id, fecha_entrada)` is the natural key. |
| `entradas_batch_staging` | `batch_id`, `sequence`, `animal_id`, `voluntario_entrada_id`, `fecha_entrada`, `origen`, `motivo`, `observaciones` | Pre-commit staging. One batch per `batch_id`. Cleared on commit. |

The single-record INSERT uses a CTE with FK-existence checks (`checked_animal`, `checked_voluntario`). The batch commit is a single CTE that copies staging rows to `entradas` and DELETEs the staging rows in one statement. The whole copy is atomic under PostgreSQL: a failure rolls back the copy and leaves staging intact.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/entradas` | READ_ENTRADAS | List entries. |
| GET | `/entradas/new` | READ_ENTRADAS | Empty single-record form. |
| POST | `/entradas` | WRITE_ENTRADAS | Create entry; 409 on natural-key conflict. |
| GET | `/entradas/{id}` | READ_ENTRADAS | Detail view. |
| GET | `/entradas/{id}/edit` | READ_ENTRADAS | Edit form prefilled from the row. |
| POST | `/entradas/{id}/update` | WRITE_ENTRADAS | Update entry. |
| POST | `/entradas/{id}/delete` | WRITE_ENTRADAS | Soft-delete. |
| GET | `/entradas/batch/new` | AUTHORIZED | Empty batch form (5 blank rows by default). |
| POST | `/entradas/batch` | WRITER | Stage records; 422 on cross-batch duplicate. |
| GET | `/entradas/batch/{batch_id}` | AUTHORIZED | Preview page with per-record status. |
| POST | `/entradas/batch/{batch_id}/commit` | WRITER | Atomic copy staging → entradas. |
| POST | `/entradas/batch/{batch_id}/cancel` | WRITER | Cancel without commit. |

Status codes: 200 on renders, 303 See Other on success, 404 when the id or batch_id is missing, 409 on natural-key conflict, 422 on validation failure, 500 on unhandled transport errors.

## Service layer

| Function | Purpose |
|---|---|
| `create_entrada(client, params)` | INSERT with FK-existence CTE; raises `EntradaConflictError` on natural-key collision. |
| `list_entradas(client)` | All entries. |
| `get_entrada_by_id(client, entrada_id)` | One entry or `None`. |
| `update_entrada(client, entrada_id, params)` | UPDATE; same CTE; same conflict translation. |
| `delete_entrada(client, entrada_id)` | Atomic soft-delete. |
| `is_duplicate_error(exc)` | Helper used by both the single-record and batch paths. |
| `row_to_entrada(row)` | Row-to-dataclass mapper reused by the batch commit. |
| `stage_batch(client, records)` | Validate per-record FKs and cross-batch uniqueness; insert staging. |
| `get_batch(client, batch_id)` | Staging preview, or `None`. |
| `commit_batch(client, batch_id)` | Atomic CTE copy; returns `False` when staging is gone. |
| `cancel_batch(client, batch_id)` | Drop staging rows. |
| `Entrada`, `BatchRecord`, `BatchStaging` | Frozen dataclasses. |
| `EntradaConflictError`, `BatchValidationError` | Typed exceptions. |

The `batch_service.py` module imports the row mapper and the duplicate detector from `service.py` (intra-package helper sharing). The split lives in two files because the batch surface would otherwise push `service.py` past the 700-line budget (AGENTS.md rule 21).

## Layer type

Legacy route → service layout with a dedicated `batch_service.py` and `batch_routes.py`. The split is a budget-shaped carve-out, not a hexagonal conversion. The slice is not yet converted to the hexagonal form described in §33.

## Risks and gotchas

- The natural-key UNIQUE on `(animal_id, fecha_entrada)` is the only idempotence guard. A retry of the same logical entry collapses to a 409 the operator must resolve.
- The batch commit is atomic. A failure during the copy rolls back the entire copy and leaves staging intact, so the operator can fix the conflicting record and re-commit. A second operator cancelling the same batch surfaces 404 on commit because the staging rows are gone.
- The legacy compatibility columns `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, and `donativo_entregador` are NOT written by this slice. Code that needs them must read directly from the table.
- `voluntario_entrada_id` is checked against `voluntarios` with `activo = true`. Soft-deleted volunteers cannot own a new entry (VOL-05).
- The `animal_id` is checked against `animales` without the `activo = true` filter, so a soft-deleted animal can still own an entry during data cleanup.
- The batch form starts with 5 blank rows by default. The `_build_initial_rows` helper re-renders the form with the operator's preserved input on cross-batch duplicate.

## Column constraints

### `entradas`

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `animal_id` | NOT NULL, FK to `animales(id)` | Required. |
| `voluntario_entrada_id` | NULLABLE, FK to `voluntarios(id)` | Optional; VOL-05 active check. |
| `fecha_entrada` | NOT NULL DATE | Required. |
| `origen`, `motivo`, `observaciones` | NULLABLE TEXT | Free text. |
| `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, `donativo_entregador` | NULLABLE | Legacy compatibility columns; NOT written by this slice. |
| UNIQUE on `(animal_id, fecha_entrada)` | UNIQUE constraint | Natural key. |
| `fecha_alta`, `updated_at` | TIMESTAMP | System columns. |
| `activo` | BOOLEAN default true | Soft-delete flag. |

### `entradas_batch_staging`

| Column | Constraint | Reason |
|---|---|---|
| `batch_id` | UUID | Pre-commit batch identifier. |
| `sequence` | INT | Row order within the batch. |
| 6 record fields | NULLABLE | Mirror of `entradas` columns. |
| Cleared on commit | DELETE in the same CTE | Atomic copy + cleanup. |

## Sub-routers and sub-services

The module is one package with one primary service and a dedicated batch surface:

- `batch_routes.py` — the batch HTTP layer (5 endpoints). Mounted at `/entradas/batch` by `app/main.py`.
- `batch_service.py` — the staging lifecycle. Imports the row mapper and the duplicate detector from `service.py` for intra-package helper sharing (AGENTS.md §27 documented exception for same-directory helpers).

The split is a budget-shaped carve-out: the batch surface would otherwise push `service.py` past the 700-line budget (AGENTS.md rule 21).

## Acceptance criteria (INTAKE-01 + INTAKE-02)

The 10 numbered criteria in `openspec/changes/intake-batch-entradas-transaccional/proposal.md` cover the batch flow. The single-record flow inherits the same UNIQUE, FK, and 422-translation contract. Highlights:

- The `?adoptante=` filter is absent from this slice; it lives in the adopciones module. The entradas list endpoint returns the full entry set without search.
- The CSRF token is present in the three forms (`entradas/form.html`, `entradas/batch_new.html`, `entradas/batch_preview.html`).
- `log_safe` is emitted for `entradas.created`, `entradas.updated`, `entradas.deleted`, `entradas.batch.staged`, `entradas.batch.committed`, and `entradas.batch.cancelled` with non-sensitive fields only.

## Cross-references

- `docs/proceso.md` — end-to-end playbook for the INTAKE workstream.
- `app/modules/animals/README.md` — sibling module for animal CRUD; the FK target.
- `app/modules/cesiones/README.md` — adjacent module; cesión is 1-a-1 with an entrada.
- `app/core/domain_entradas.py` — DDL, UNIQUE on `(animal_id, fecha_entrada)`, and the staging table.
- `openspec/changes/intake-batch-entradas-transaccional/proposal.md` — origin proposal for the INTAKE-02 work.

## Tests pinned

| Test file | Coverage |
|---|---|
| `tests/test_entradas.py` | Service-level atoms for CRUD, FK checks, conflict translation. |
| `tests/test_entradas_routes.py` | Route-level atoms for the single-record flow. |
| `tests/test_entradas_batch.py` | Service-level atoms for the batch flow: stage, preview, commit, cancel. |
| `tests/test_entradas_batch_routes.py` | Route-level atoms for the batch endpoints. |
| `tests/test_entradas_shared_helpers.py` | Cross-module helper atoms (the `_opt` / `_required_text` / `_optional_text` watch-list). |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: `router`, `batch_router`, `Entrada`, `EntradaConflictError`, `BatchRecord`, `BatchStaging`, `BatchValidationError`. |
| `routes.py` | HTTP layer for the single-record CRUD (7 endpoints). |
| `service.py` | Single-record CRUD orchestration, FK checks, conflict translation. |
| `batch_routes.py` | HTTP layer for the batch flow (5 endpoints). |
| `batch_service.py` | Staging lifecycle: `stage_batch`, `get_batch`, `commit_batch`, `cancel_batch`. |
| `forms.py` | `EntradaForm` Pydantic v2 model for form parsing. |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #87, #88, #89 (INTAKE-01) — origin single-record slice.
- #40 (INTAKE-02) — batch intake (Entradas Múltiples).
- VOL-05 — `voluntario_entrada_id` active check on FK.
- D-EST-01 retro-compat — `voluntario_salida_id` legacy column NOT written by this slice.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/entradas/list.html` | List entries. |
| `templates/entradas/form.html` | Single-record create and edit form. |
| `templates/entradas/detail.html` | Detail view. |
| `templates/entradas/batch_new.html` | Batch intake form (5 blank rows by default). |
| `templates/entradas/batch_preview.html` | Batch preview with per-record status. |

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/entradas/routes.py` or `batch_routes.py`.
- [ ] Every function name in the Service layer section is exported by `app/modules/entradas/service.py` or `batch_service.py` (or their `__all__`).
- [ ] Every table and column name matches the SQL constants in `service.py` and `batch_service.py`.
- [ ] The Layer type section matches the actual folder shape: `__init__.py`, `routes.py`, `service.py`, `batch_routes.py`, `batch_service.py`, `forms.py` (no `queries.py`).
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
