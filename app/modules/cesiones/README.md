[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# cesiones

This README documents the domain, tables, endpoints, and risks of the `cesiones` module.

Este módulo registra las cesiones por propietario (INTAKE-03, issue #41). Una cesión captura los datos del representante legal que entrega el animal y crea el contrato documental asociado.

The sentence that organizes this module: an owner surrender is a 1-a-1 record linked to an existing entrada, with a single INSERT that also creates the matching contrato in `catalogos_tipos_contrato.codigo = 'Cesión'`.

## Quick navigation

| Section | Purpose |
|---|---|
| What this is / is not | The slice's ownership boundary. |
| Domain | What this module owns across the cesión and contrato surfaces. |
| Tables backend | SQL surface the service depends on. |
| Endpoints | HTTP routes mounted at `/cesiones`. |
| Service layer | Public functions exported by `app.modules.cesiones.service`. |
| Layer type | How this module is wired (route, service, no separate queries). |
| Risks and gotchas | Edge cases, FK UNIQUE, catalog dependency, and P1 fidelity. |
| Cross-references | Audit, runbook, and adjacent-module docs. |
| Verification checklist | Acceptance items for a doc or code PR. |

## What this is / is not

| Is | Is not |
|---|---|
| The CRUD for `cesiones_propietario` plus the linked `contratos` row. | The CRUD for the `entradas` row (lives in `app/modules/entradas`); the cesión references an existing entrada. |
| The publish surface for `Cesion`, `Contrato`, `CesionConflictError`, and `CONTRATO_TIPO_CESION`. | The catalog CRUD for `catalogos_tipos_contrato` (lives in `app/core/domain_contracts.py` and the seed migration). |
| The route for the surrender form (only write surface for the issue #41 acceptance). | A standalone detail view; deferred until Fase 7 ships the contract generation. |

## Domain

The `cesiones` slice owns the `cesiones_propietario` table (legacy `TbCesionPorPropietario`) and the matching `contratos` row. The relationship is 1-a-1 with `entradas` via a FK UNIQUE on `entrada_id`: one entrada can have at most one cesión. A second cesión for the same entrada surfaces as 409.

The `contratos` row carries the polymorphic FK to `cesion_id`; the other entity FKs (`entrada_id`, `acogida_id`, `adopcion_id`) stay NULL per the `contratos_exactly_one_entity` CHECK. The contract type is resolved from `catalogos_tipos_contrato` by `codigo = 'Cesión'` (iniciales `'CP'`) so the create call is self-contained.

The P1 fidelity deviation `nombre_representante NOT NULL` (legacy `required=False`) is recorded in `docs/architecture/decisiones-proyecto.md` as a gap-of-fidelity and stays `NOT NULL` here. Other free-text fields stay `TEXT` (not `BOOLEAN`) so the legacy `'Sí'` round-trips.

The slice runs the same FK-existence pattern as the entradas and adopciones modules: the service validates the entrada FK against `entradas` BEFORE the INSERT, and the catalog resolution happens before the contract INSERT. The UNIQUE on `cesiones_propietario.entrada_id` is the natural idempotence guard for the cesión row.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `cesiones_propietario` | `id`, `entrada_id` (FK UNIQUE), `numero_contrato`, `nombre_representante`, 16 optional address/health fields, `hora_cesion`, `fecha_alta`, `updated_at` | 20-column surrender record. UNIQUE on `entrada_id` is the natural idempotence guard. |
| `contratos` | `id`, `tipo_contrato_id`, `numero_contrato`, `fecha`, `cesion_id` (FK, NULL for non-cesión contracts), `entrada_id|acogida_id|adopcion_id` (polymorphic, exactly one per CHECK) | Linked contract row. The CHECK enforces exactly one entity FK. |
| `catalogos_tipos_contrato` | `id`, `codigo`, `iniciales`, `tabla_legacy`, `campo_legacy` | Catalog of contract types. CATALOG-01. |

The SQL constants `_INSERT_CESION_SQL` and `_INSERT_CONTRATO_SQL` live in `app/modules/cesiones/service.py`. The module does not follow the AGENTS.md §22 seam pattern; the SQL strings and the validators are co-located. The follow-up split is tracked in the project backlog.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/cesiones/new` | READ_CESIONES | Empty surrender form. |
| POST | `/cesiones` | WRITE_CESIONES | Create cesión + contrato; renders 409 on UNIQUE conflict. |

Status codes: 200 on renders, 303 See Other to `/entradas/{entrada_id}` on success, 409 on FK UNIQUE conflict, 422 on validation failure, 500 on unhandled transport errors.

A standalone detail view at `/cesiones/{id}` is deferred until Fase 7 (contract generation) ships, when the page will render alongside the generated contrato or PDF.

## Service layer

| Function | Purpose |
|---|---|
| `create_cesion(client, params)` | Two INSERTs in order: cesión then contrato; returns `(Cesion, Contrato)`. |
| `get_cesion_by_entrada_id(client, entrada_id)` | The cesión linked to an entrada, or `None`. |
| `list_cesiones(client)` | All cesiones, newest first. |
| `Cesion`, `Contrato` | Frozen dataclasses; service-row representations. |
| `CesionConflictError` | Raised on FK UNIQUE violation. |
| `CONTRATO_TIPO_CESION` | The literal `'Cesión'` resolved against `catalogos_tipos_contrato.codigo`. |

## Layer type

Legacy route → service layout without a separate `queries.py` seam (AGENTS.md §22 deviation). The SQL strings and the validators are co-located in `service.py`. This slice is not yet converted to the hexagonal form described in §33.

## Risks and gotchas

- The service raises `ValueError` when `catalogos_tipos_contrato` is missing the `'Cesión'` row. A well-seeded env guarantees the row; a missing seed surfaces as a 422 with the explicit `re-run ensure_catalogs()` message.
- The 1-a-1 UNIQUE on `cesiones_propietario.entrada_id` is the natural idempotence guard. The service translates the PostgREST 409 body via `_is_unique_conflict` (lowercased substring match on `cesiones_propietario`, `duplicate`, or `unique`).
- The `fecha` column on the contrato falls back to the first 10 characters of `cesiones.fecha_alta` when the form leaves `fecha_cesion` blank. The legacy contract numbering (`CPxxxx`) carries over verbatim from `numero_contrato`.
- `cartilla_sanitaria`, `certificado_veterinario`, and `autorizacion_recogida` accept free text (`'Sí'`, `'No'`, or other) for legacy round-trip. A future boolean migration would touch every read path.
- The P1 fidelity deviation `nombre_representante NOT NULL` is documented in `docs/architecture/decisiones-proyecto.md`; the legacy `required=False` is a known gap-of-fidelity.
- The two INSERTs in `create_cesion` are NOT wrapped in a transaction. A failure between the cesión INSERT and the contrato INSERT leaves the cesión row without its linked contrato. The follow-up migration to a single CTE is tracked in the backlog.

## Column constraints

### `cesiones_propietario`

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `entrada_id` | NOT NULL, FK UNIQUE to `entradas(id)` | 1-a-1 relationship; UNIQUE is the natural idempotence guard. |
| `numero_contrato` | NOT NULL TEXT | Legacy contract number (`CPxxxx`). |
| `nombre_representante` | NOT NULL TEXT | P1 deviation; legacy `required=False`, web narrows the surface. |
| `cartilla_sanitaria`, `certificado_veterinario`, `autorizacion_recogida` | NULLABLE TEXT | Legacy `'Sí'` round-trip. |
| `fecha_vacuna_rabia` | NULLABLE DATE | Optional. |
| `numero_colegiado`, `numero_colaborador` | NULLABLE TEXT | Optional. |
| 12 address fields | NULLABLE TEXT | Owner address (calle, numero, piso, letra, etc.). |
| `telefono_representante`, `email_representante` | NULLABLE TEXT | PII — redacted by the log_safe list. |
| `hora_cesion` | NULLABLE TIME | Optional. |
| `fecha_alta`, `updated_at` | TIMESTAMP | System columns. |

### `contratos` (linked row)

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `tipo_contrato_id` | NOT NULL, FK to `catalogos_tipos_contrato(id)` | Resolved by `codigo = 'Cesión'`. |
| `numero_contrato` | NOT NULL TEXT | Carries over from `cesiones_propietario.numero_contrato`. |
| `fecha` | NOT NULL DATE | Falls back to `cesiones.fecha_alta[:10]` when form omits `fecha_cesion`. |
| `cesion_id` | NULLABLE, FK to `cesiones_propietario(id)` | Set on the cesión create path; NULL for other contract types. |
| `entrada_id`, `acogida_id`, `adopcion_id` | NULLABLE, polymorphic FK | CHECK enforces exactly one entity FK. |
| `fecha_alta` | TIMESTAMP | System column. |

## Sub-routers and sub-services

The module is a single package with one router and one service. There is no sub-router or sub-service; the slice is small enough to live in one file each.

## Acceptance criteria (INTAKE-03)

The proposal at `openspec/changes/legacy-discovery-interrogatorio/proposal.md` and the issue #41 acceptance define the contract. Highlights:

- A surrender form renders with the 19 legacy columns + `hora_cesion` (20 total inputs) so the superset is visible at a glance.
- The 1-a-1 UNIQUE on `entrada_id` makes a second cesión for the same entrada a 409 form error, not a silent override.
- The linked `contratos` row is created in the same call so the operator never sees a partial state.

## Cross-references

- `docs/proceso.md` — end-to-end playbook for the INTAKE workstream.
- `app/modules/entradas/README.md` — parent module; cesión is 1-a-1 with an entrada.
- `app/core/domain_cesiones.py` — DDL for `cesiones_propietario`.
- `app/core/domain_contracts.py` — DDL for `contratos` and `catalogos_tipos_contrato`.
- `docs/architecture/decisiones-proyecto.md` — gap-of-fidelity log.

## Tests pinned

| Test file | Coverage |
|---|---|
| `tests/test_cesiones.py` | Service-level atoms for the two-INSERT flow, FK checks, conflict translation. |
| `tests/test_cesiones_routes.py` | Route-level atoms for auth guards, CSRF, redirects, 404 / 409 / 422. The test pins that `routes.py` does NOT call `client.execute_sql` (AGENTS.md §1). |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: re-exports the `service` module (no top-level dataclasses). |
| `routes.py` | HTTP layer: 2 endpoints (`/cesiones/new`, `POST /cesiones`). |
| `service.py` | Two-INSERT orchestration, FK validation, catalog resolution. SQL strings co-located (AGENTS.md §22 deviation, tracked in backlog). |
| `forms.py` | `CesionForm` Pydantic v2 model for the 22 form fields. |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #41 (INTAKE-03) — origin slice (Cesión por Propietario).
- CATALOG-01 — `catalogos_tipos_contrato.codigo = 'Cesión'`, iniciales `'CP'`.
- P1 deviation (issue #41, gap-of-fidelity) — `nombre_representante NOT NULL` despite legacy `required=False`.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/cesiones/form.html` | Surrender form with the 19 legacy columns + `hora_cesion`. |

## How to extend this slice

When adding a new field to the cesión surface, follow this order:

1. Add the column to `app/core/domain_cesiones.py` and to the `_INSERT_CESION_COLUMNS` / `_CESION_RETURNING_COLUMNS` tuples in `app/modules/cesiones/service.py`. SQL strings and column tuples are co-located here; the §22 split is a tracked follow-up.
2. Extend `app/modules/cesiones/forms.py::CesionForm` (Pydantic v2). The route handlers consume this model.
3. Extend `app/modules/cesiones/service.py::_build_cesion_insert_params` (parameter list is positional; index alignment is critical).
4. Update `Cesion` and `_row_to_cesion` so the dataclass shape and the SELECT mapper stay in sync.
5. Update `tests/test_cesiones.py` (service atoms) and `tests/test_cesiones_routes.py` (route atoms).

When the two-INSERT flow is migrated to a single CTE (the backlog item), the slice becomes §22-compliant. The hexagonal conversion (AGENTS.md §33) is tracked in epic #420; the slice is small enough that the conversion can follow the same atomic-write pattern as a hexagonal slice's adapter.

A standalone detail view at `/cesiones/{id}` is deferred until Fase 7 (contract generation) ships. When the deferred view lands, the route will follow the same auth + CSRF + soft-delete pattern as the other slices, and the `cesiones_propietario.entrada_id` UNIQUE constraint will be reused as the idempotence guard for the create flow.

The contract type lookup uses `catalogos_tipos_contrato.codigo = 'Cesión'` as the single resolution key. A change to the catalog (a rename, a split) must be coordinated with the seed migration and the integration test that pins the catalog row's presence.

The two-INSERT pattern in `create_cesion` is a project-wide pattern (mirror `app/modules/entradas/batch_service.py` for the staging lifecycle). When the slice moves to a single CTE, the change is contained to `service.py::create_cesion`; the route and the form stay untouched.

The `entrada_id` UNIQUE constraint is the natural idempotence guard for the surrender form. A retry of the same surrender (same animal, same fecha_cesion) collapses to a 409 the operator must resolve.

The route returns 303 to the parent `/entradas/{entrada_id}` on success so the cesión is inspected from the parent intake detail page rather than a standalone view.

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/cesiones/routes.py`.
- [ ] Every function name in the Service layer section is exported by `app/modules/cesiones/service.py` or its `__all__`.
- [ ] Every table and column name matches the SQL constants in `service.py` and the DDL in `app/core/domain_cesiones.py` and `app/core/domain_contracts.py`.
- [ ] The Layer type section matches the actual folder shape: `__init__.py`, `routes.py`, `service.py`, `forms.py` (no `queries.py`).
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
