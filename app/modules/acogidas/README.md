[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# acogidas

This README documents the domain, tables, endpoints, and risks of the `acogidas` module.

Este módulo gestiona las estancias de animales en casas de acogida dentro del flujo FOSTER-02. Una estancia registra el periodo durante el cual un animal vive en una casa bajo la supervisión de voluntarios.

The sentence that organizes this module: a stay is the time-bound record of an animal living in a foster home, opened by create, closed by lifecycle event, and never physically deleted.

## Quick navigation

| Section | Purpose |
|---|---|
| What this is / is not | The slice's ownership boundary. |
| Domain | What this module owns and the lifecycle split it preserves. |
| Tables backend | SQL surface the service depends on. |
| Endpoints | HTTP routes mounted at `/acogidas`. |
| Service layer | Public functions exported by `app.modules.acogidas.service`. |
| Layer type | How this module is wired (route, service, queries). |
| Risks and gotchas | Edge cases and rules operators must respect. |
| Cross-references | Audit, runbook, and adjacent-module docs. |
| Verification checklist | Acceptance items for a doc or code PR. |

## What this is / is not

| Is | Is not |
|---|---|
| The CRUD for `acogidas` rows and the foster-stay lifecycle. | The CRUD for the `casas_acogida` house records (FOSTER-01, lives in `app/modules/foster`). |
| The surface that links a `foster_capacity_overrides` row to a stay after the operator confirms a capacity override. | The gate that decides whether an animal MAY be assigned to a house (FOSTER-03, lives in `app/modules/foster/assignment.py`). |
| The publish surface for the `Acogida` dataclass and the `is_active` / `compute_duracion` helpers. | The lifecycle event log writer (LIFECYCLE-02, lives in `app/modules/animals/lifecycle_events.py`). |

## Domain

The `acogidas` slice owns the `acogidas` table and the foster-stay lifecycle. Each row models a stay opened for an animal at a casa de acogida, tracked by three independent lifecycle axes (D-EST-04). The axes never collapse into a single update statement.

`fecha_final` is editable through the form path. `close_acogida` is the canonical end-of-stay lifecycle event that sets `fecha_final = CURRENT_DATE` and keeps `activo = true`. `delete_acogida` is the real soft-delete that hides the stay from the default listing with `activo = false` + `fecha_baja = now()`. A closed stay is not a soft-deleted stay; a soft-deleted stay is not a closed stay.

The slice also writes to `foster_capacity_overrides.estancia_id` after a successful INSERT when the operator confirms a capacity override (issue #142). This closes the audit-log gap left when the operator cancelled the create after the override was recorded. The link UPDATE is scoped to `casa_acogida_id` + `animal_id` so a forged `override_id` from another operator cannot link to a different stay (judgment-day CRITICAL §1.2 / HIGH §3.2 follow-up).

The species gate lives in the route layer via `_enforce_species_gate` and consults `app.modules.foster.assignment.evaluate_assignment`. The service does not consult the gate, so any future direct service caller must replicate the gate (D-GC-05). The same gate fires on create and update to prevent the FOSTER-03 close-bypass P0.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `acogidas` | `id`, `animal_id`, `casa_acogida_id`, `voluntario_acogida_id`, `voluntario_seguimiento1_id`, `voluntario_seguimiento2_id`, `voluntario_sanitario_id`, `fecha_inicio`, `fecha_final`, `entrada_origen_id`, `direccion`, `telefono`, `observaciones`, `fecha_alta`, `fecha_baja`, `updated_at`, `activo` | One stay per row. Mirrors legacy `TbAcogidaAnimal` (15 legacy columns + `casa_acogida_id` FK + system columns). |
| `foster_capacity_overrides` | `estancia_id` (FK updated here) | Audit log for capacity overrides. The link from override to estancia is established after the INSERT in `create_acogida`. |

The SQL strings live in `app/modules/acogidas/queries.py` per AGENTS.md §22: `_ACOGIDA_INSERT_SQL`, `_ACOGIDA_LIST_ALL_SQL`, `_ACOGIDA_LIST_ACTIVAS_SQL`, `_ACOGIDA_GET_BY_ID_SQL`, `_ACOGIDA_UPDATE_SQL`, `_ACOGIDA_CLOSE_SQL`, `_ACOGIDA_DELETE_SQL`, and the FK-existence checks `_ACOGIDA_CHECK_ANIMAL_SQL`, `_ACOGIDA_CHECK_CASA_SQL`, `_ACOGIDA_CHECK_VOLUNTARIO_SQL`, `_ACOGIDA_CHECK_ENTRADA_SQL`, and the override-link UPDATE `_ACOGIDA_LINK_OVERRIDE_SQL`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/acogidas` | READ_ACOGIDAS | List stays, optional `?activas_solo=1` filter. |
| GET | `/acogidas/new` | READ_ACOGIDAS | Empty create form. |
| POST | `/acogidas` | WRITE_ACOGIDAS | Create stay; runs FOSTER-03 species gate before INSERT. |
| GET | `/acogidas/{id}` | READ_ACOGIDAS | Detail view with computed duration + active state. |
| GET | `/acogidas/{id}/edit` | READ_ACOGIDAS | Edit form prefilled from the row. |
| POST | `/acogidas/{id}/update` | WRITE_ACOGIDAS | Update stay; re-runs species gate. |
| POST | `/acogidas/{id}/close` | WRITE_ACOGIDAS | Lifecycle event: sets `fecha_final = CURRENT_DATE`. |
| POST | `/acogidas/{id}/delete` | WRITE_ACOGIDAS | Soft-delete: `activo = false` + `fecha_baja = now()`. |

Status codes: 200 on renders, 303 See Other on success, 404 when the stay is missing or already inactive on delete, 422 on validation failure or FK violation, 500 on unhandled transport errors. The route translates `InsForgeError` 4xx to 422 with a Spanish-friendly message that includes the violating constraint name when present.

## Service layer

| Function | Purpose |
|---|---|
| `create_acogida(client, params)` | INSERT a stay and link the override row when `override_id` is present. |
| `list_acogidas(client, activas_solo=False)` | Return stays; open only when `activas_solo=True`. |
| `get_acogida_by_id(client, estancia_id)` | One stay or `None`. |
| `update_acogida(client, estancia_id, params)` | Partial update; `fecha_final` is patch-only. |
| `close_acogida(client, estancia_id)` | Lifecycle close: `fecha_final = CURRENT_DATE`. |
| `delete_acogida(client, estancia_id)` | Atomic soft-delete under the row lock. |
| `compute_duracion(estancia)` | Days between `fecha_inicio` and `fecha_final`; `None` if open. |
| `is_active(estancia)` | `True` only when `activo = true` AND `fecha_final IS NULL`. |
| `Acogida` | Frozen dataclass; service-row representation. |
| `AcogidaConflictError` | Reserved for future parity; mirrors the conflict family. |

## Layer type

Legacy route → service → queries layout (per AGENTS.md §1 + §22). This slice is not yet converted to the hexagonal form described in §33. The conversion order lives in epic #420.

## Risks and gotchas

- The `fecha_final` column is patch-only. A partial update that omits the key leaves the column untouched; a form that sends `""` sets `NULL` (reopen) (issue #141).
- The species gate runs in the route layer via `_enforce_species_gate`. The service does not consult it, so any future direct service caller must replicate the gate (D-GC-05).
- `_validate_references` runs FK checks BEFORE the INSERT, but a concurrent deactivate between the SELECT and the INSERT can still produce a PostgreSQL FK violation. The route catches the resulting `InsForgeError` and translates it to 422 (issue #139 P1 #4).
- `close_acogida` is NOT filtered by `activo`. It can close an already-soft-deleted stay in data-cleanup flows. `delete_acogida` is the canonical soft-delete path.
- The override link UPDATE is scoped to `casa_acogida_id` + `animal_id`. A forged `override_id` from another operator cannot link to a different stay (judgment-day CRITICAL §1.2 / HIGH §3.2 follow-up).
- `compute_duracion` raises `ValueError` when `fecha_final < fecha_inicio`. The route surfaces this as 422 with the operator's input preserved.
- `_raise_validation_error` is never called in this slice; the FK validation funnels through `_validate_references` instead. The list of checked references is `animal_id` (required) → `casa_acogida_id` (optional) → four `voluntario_*_id` (optional) → `entrada_origen_id` (optional).

## Column constraints

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `animal_id` | NOT NULL, FK to `animales(id)` | Required (D-EST, _validate_references). |
| `casa_acogida_id` | NULLABLE, FK to `casas_acogida(id)` | D-EST-01 retro-compat with legacy stays without a casa. |
| `voluntario_*_id` (4 cols) | NULLABLE, FK to `voluntarios(id)` | D-EST-06 + VOL-05: only active voluntarios are valid. |
| `fecha_inicio` | NOT NULL | Required; legacy DDL constraint. |
| `fecha_final` | NULLABLE | Editable; NULL means open stay (D-EST-04). |
| `entrada_origen_id` | NULLABLE, FK to `entradas(id)` | Optional; no `activo` filter — legacy entries can be soft-deleted. |
| `direccion`, `telefono`, `observaciones` | NULLABLE TEXT | Legacy denormalized fields, preserved 1:1. |
| `fecha_alta`, `updated_at` | TIMESTAMP | System columns. |
| `fecha_baja` | NULLABLE TIMESTAMP | Set on `delete_acogida`. |
| `activo` | BOOLEAN default true | Soft-delete flag. |

## Sub-routers and sub-services

The module is a single package with one router and one service. The sub-routers and sub-services live in sibling modules:

- `app/modules/foster/assignment.py` — the species + capacity gate (FOSTER-03). Consumed by `acogidas/routes.py::_enforce_species_gate` and by `foster/assignment_routes.py`.
- `app/modules/foster/assignment_routes.py` — the gate's HTTP layer.

## Acceptance criteria (FOSTER-02)

The 17 numbered criteria in `openspec/changes/foster-estancias-acogida/proposal.md` §"Criterios de aceptación" define the contract. Highlights:

- Required-field validation renders 422 with a Spanish message and does NOT write to the DB.
- Soft-deleted volunteers are rejected for new FK references; existing stays with inactive volunteers stay valid (D-EST-06).
- The detail view shows the "Cerrar estancia" and "Dar de baja" buttons separately so the operator can distinguish the two lifecycle paths (D-EST-04).
- `log_safe` is emitted for create, update, close, and delete with non-sensitive fields only.

## Cross-references

- `docs/proceso.md` — end-to-end playbook for the FOSTER workstream.
- `app/modules/foster/README.md` — sibling module for foster houses (FOSTER-01).
- `app/modules/foster/assignment.py` — species + capacity gate consumed by this slice.
- `app/core/domain_foster.py` — DDL for `acogidas` and FK constraints (co-located with the FOSTER-01 DDL; the FOSTER-02 workstream lives in the same file).
- `app/core/domain_lifecycle.py` — append-only trigger for the event log (referenced for the D-23 rule).
- `openspec/changes/foster-estancias-acogida/proposal.md` — origin proposal for the FOSTER-02 work.

## Tests pinned

| Test file | Coverage |
|---|---|
| `tests/test_acogidas.py` | Service-level atoms for CRUD, validation, close, soft-delete. |
| `tests/test_acogidas_routes.py` | Route-level atoms for auth guards, CSRF, redirects, 404 / 422. |
| `tests/test_acogidas_queries.py` | Query-builder unit tests for the §22 seam. |
| `tests/integration/test_acogidas_queries_integration.py` | Integration tests against a live SQL backend. |
| `tests/test_acogidas_detail.py` | Detail view atoms (duration, active state). |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: `router`, `Acogida`, `AcogidaConflictError`, `compute_duracion`, `is_active`. |
| `routes.py` | HTTP layer: 8 endpoints, `_enforce_species_gate`, `_format_persisted_error`. |
| `service.py` | CRUD orchestration, validation helpers, lifecycle helpers. |
| `queries.py` | SQL builder seam per AGENTS.md §22. |
| `forms.py` | `AcogidaForm` Pydantic v2 model for form parsing. |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #44 (FOSTER-02) — origin slice.
- #45 (FOSTER-03) — close-bypass P0 fix (species gate in the route layer).
- #141 (issue #141) — `fecha_final` patch-only contract.
- #142 (issue #142) — override link UPDATE in `create_acogida`.
- #139 (issue #139, P1 #4) — TOCTOU mitigation: PostgREST FK violation → 422 translation.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/acogidas/list.html` | List stays, optional `?activas_solo=1` filter. |
| `templates/acogidas/form.html` | Create and edit form (shared by both flows). |
| `templates/acogidas/detail.html` | Detail view with duration, active state, close / delete buttons. |

## How to extend this slice

When adding a new field to the estancia surface, follow this order:

1. Add the column to `app/core/domain_acogidas.py` and to the `ACOGIDA_WRITE_COLUMNS` / `ACOGIDA_SELECT_COLUMNS` tuples in `app/modules/acogidas/queries.py`.
2. Extend `app/modules/acogidas/forms.py::AcogidaForm` (Pydantic v2). The route handlers consume this model; the service does not re-shape form input.
3. Extend `app/modules/acogidas/queries.py::_extract_write_value` if the new column needs a non-default extractor.
4. If the new column is a foreign key, add a `_ACOGIDA_CHECK_<TARGET>_SQL` constant and a `_validate_<target>` helper in `service.py`; thread it into `_validate_references`.
5. Update `tests/test_acogidas.py` (service atoms) and `tests/test_acogidas_routes.py` (route atoms). Add a query-builder unit test in `tests/test_acogidas_queries.py`.

The hexagonal conversion (AGENTS.md §33) is tracked in epic #420. New slices should follow the port / use-case layout; the FOSTER-02 module is a candidate for future conversion.

The `_UPDATE_PATCH_ONLY_COLUMNS` frozenset in `queries.py` is the single source of truth for partial-update semantics. Any column added to that frozenset follows the same defensive pattern as `fecha_final`: a partial update that omits the key leaves the column untouched.

The override link UPDATE in `queries.py::build_acogida_link_override` uses the `AND estancia_id IS NULL` guard so a second call to `create_acogida` with the same `override_id` is a no-op. The `AND casa_acogida_id` + `AND animal_id` guards scope the link to the override's recorded pair.

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/acogidas/routes.py`.
- [ ] Every function name in the Service layer section is exported by `app/modules/acogidas/service.py` or its `__all__`.
- [ ] Every table and column name matches `app/modules/acogidas/queries.py`.
- [ ] The Layer type section matches the actual folder shape: `__init__.py`, `routes.py`, `service.py`, `queries.py`, `forms.py`.
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
