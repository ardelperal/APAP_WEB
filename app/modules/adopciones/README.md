[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# adopciones

This README documents the domain, tables, endpoints, and risks of the `adopciones` module.

Este módulo registra las adopciones y su ciclo de seguimiento (ADOPT-01 + ADOPT-03). Una adopción fija el adoptante, la fecha de salida del animal del albergue y el flujo documental posterior.

The sentence that organizes this module: an adoption is a permanent record of an animal leaving the protectora under the responsibility of an adopter, with a seguimiento state machine that closes when the operator marks the follow-up complete.

## Quick navigation

| Section | Purpose |
|---|---|
| What this is / is not | The slice's ownership boundary. |
| Domain | What this module owns across the adoption and seguimiento lifecycles. |
| Tables backend | SQL surface the service depends on. |
| Endpoints | HTTP routes mounted at `/adopciones`. |
| Service layer | Public functions exported by `app.modules.adopciones.service`. |
| Layer type | How this module is wired (route, service, queries). |
| Risks and gotchas | Edge cases, conflict rules, and state-machine constraints. |
| Cross-references | Audit, runbook, and adjacent-module docs. |
| Verification checklist | Acceptance items for a doc or code PR. |

## What this is / is not

| Is | Is not |
|---|---|
| The CRUD for the `adopciones` table plus the seguimiento state machine (issue #49). | The CRUD for the `adoptantes` table (separate slice, defer until a real adopter master is needed). |
| The publish surface for `Adopcion`, `SeguimientoEstado`, `SeguimientoAction`, `SeguimientoTransitionResult`, and `AdopcionConflictError`. | The CRUD for the `contratos` row (lives in `app/modules/cesiones` for the cesión variant; this slice does not write one). |
| The route for the `?adoptante=` ILIKE search and the PATCH transition endpoint. | The animal search or the photo streaming endpoints (lives in `app/modules/animals`). |

## Domain

The `adopciones` slice owns the `adopciones` table and the seguimiento state machine (issue #49). Each row carries the adopter contact details, donation amounts, return date, the responsible volunteer (VOL-04, issue #37), and the seguimiento columns populated by the transition function.

The seguimiento state machine has four states and three actions. The valid transitions are pinned in `_VALID_TRANSITIONS` as the single source of truth (AGENTS.md §4). Unknown actions raise `ValueError` from `resolve_seguimiento_action`; invalid transitions render as 409 from the route. The `ANEXAR` action requires `documento_url`; the service raises `ValueError` when the URL is missing.

The write endpoints require the `writer` role (issue #144, RBAC P1-3). Read endpoints use `require_authorized_user` and stay open to any authorized operator. The PATCH seguimiento endpoint is auth-guard-by-authorized, not by-permission, because the operator does not need the WRITE_ADOPCIONES permission to mark the follow-up complete.

The slice runs the same FK-existence pattern as the entradas and cesiones modules: the INSERT and UPDATE use a CTE that pre-checks the animal, voluntario, entrada, and responsable FKs so the SQL raises no rows when a target is missing or inactive. The UNIQUE on `(animal_id, fecha_adopcion)` is the natural key.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `adopciones` | `id`, `animal_id`, `voluntario_seguimiento_id`, `fecha_adopcion`, `fecha_devolucion`, `donativo_preadopcion`, `donativo_adopcion`, `nombre_adoptante`, `dni_adoptante`, `telefono_adoptante`, `email_adoptante`, `entrada_origen_id`, `observaciones`, `tipo_adopcion`, `responsable_adopcion_id`, `fecha_alta`, `updated_at`, `activo` | One adoption per row. UNIQUE on `(animal_id, fecha_adopcion)` is the natural key. |
| Seguimiento fields (4 columns in `adopciones`) | `seguimiento_estado`, `seguimiento_documento_url`, `seguimiento_documento_entregado_at`, `seguimiento_completado_at` | State machine fields. ADOPT-03 (issue #49). |

The INSERT and UPDATE use CTEs that pre-check FK existence (`checked_animal`, `checked_voluntario`, `checked_entrada`, `checked_responsable`) so the SQL raises no rows when an FK target is missing or inactive. The seguimiento update uses `COALESCE` so partial updates preserve existing values.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/adopciones` | READ_ADOPCIONES | List active adoptions, optional `?adoptante=` ILIKE filter. |
| GET | `/adopciones/new` | READ_ADOPCIONES | Empty create form. |
| POST | `/adopciones` | WRITE_ADOPCIONES | Create adoption; renders 409 on natural-key conflict. |
| GET | `/adopciones/{id}` | READ_ADOPCIONES | Detail view. |
| GET | `/adopciones/{id}/edit` | READ_ADOPCIONES | Edit form prefilled from the row. |
| POST | `/adopciones/{id}/update` | WRITE_ADOPCIONES | Update adoption; same 409 translation. |
| POST | `/adopciones/{id}/delete` | WRITE_ADOPCIONES | Soft-delete. |
| PATCH | `/adopciones/{id}/seguimiento` | AUTHORIZED | State transition; `action` is required. |

Status codes: 200 on renders, 303 See Other on success, 404 when the id is missing, 409 on natural-key conflict, 422 on validation failure, 500 on unhandled transport errors during a seguimiento transition.

## Service layer

| Function | Purpose |
|---|---|
| `create_adopcion(client, params, *, actor_user_id=None)` | INSERT with FK-existence CTE; raises `AdopcionConflictError` on natural-key collision. |
| `list_adopciones(client)` | Active adoptions, most recent first, capped at 100. |
| `get_adopcion_by_id(client, adopcion_id)` | One adoption or `None`. |
| `update_adopcion(client, adopcion_id, params, *, actor_user_id=None)` | UPDATE with same FK-existence CTE; raises `AdopcionConflictError` on collision. |
| `delete_adopcion(client, adopcion_id, *, actor_user_id=None)` | Atomic soft-delete. |
| `search_adopciones_by_adoptante(client, nombre_parcial)` | ILIKE search with `_escape_like` to neutralise `%` and `_`. |
| `resolve_seguimiento_action(action)` | String to `SeguimientoAction` enum; raises `ValueError` on unknown. |
| `transition_seguimiento(client, id, action, operador_user_id, documento_url=None)` | State machine; raises `ValueError` on invalid transition. |
| `transition_seguimiento_for_route(...)` | Route-facing wrapper that translates exceptions to a typed result. |
| `Adopcion` | Frozen dataclass; service-row representation. |
| `AdopcionConflictError` | Raised on `(animal_id, fecha_adopcion)` UNIQUE violation. |
| `SeguimientoEstado` | `PENDIENTE`, `DOCUMENTO_ENTREGADO`, `DOCUMENTO_ADJUNTO`, `SEGUIMIENTO_COMPLETADO`. |
| `SeguimientoAction` | `MARCAR_ENTREGADO`, `ANEXAR`, `COMPLETAR`. |
| `SeguimientoTransitionResult` | Frozen dataclass returned on successful transition. |

## Layer type

Legacy route → service → queries layout (per AGENTS.md §1 + §22). This slice is not yet converted to the hexagonal form described in §33. The conversion order lives in epic #420.

## Risks and gotchas

- The UNIQUE on `(animal_id, fecha_adopcion)` surfaces as an `BackendError` 409. The service catches it via `_is_duplicate_error` and re-raises as `AdopcionConflictError`. Both create and update must translate it to 409 (P2-1, risk review 2026-07-04).
- The responsable FK is checked against `voluntarios` with `activo = true`. Soft-deleted volunteers cannot own a new adoption (VOL-05).
- The seguimiento `ANEXAR` action requires `documento_url`. A `None` raises `ValueError` from the service; the route wrapper translates it to 500 because the action is reached only through the form which always sends the field.
- The state machine is read from `seguimiento_estado`; an unknown or `NULL` value is treated as `PENDIENTE` on the first transition.
- `_escape_like` is mandatory for the adoptante search: the `%` and `_` literals are escaped before the parameter reaches the SQL, so partial-match input never injects wildcards beyond the search term.
- `donativo_preadopcion` and `donativo_adopcion` are coerced via `_optional_numeric`. Boolean values are rejected (defense against `True` being a subclass of `int`).
- The list endpoint caps at `LIMIT 100` rows. A paginated variant is deferred until a real adopter master is built.

## Column constraints

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `animal_id` | NOT NULL, FK to `animales(id)` | Required. |
| `voluntario_seguimiento_id` | NULLABLE, FK to `voluntarios(id)` | Optional; only active voluntarios are valid (VOL-05). |
| `fecha_adopcion` | NOT NULL DATE | Required. |
| `fecha_devolucion` | NULLABLE DATE | When populated, the adoption is no longer current (`is_active` returns `False`). |
| `donativo_preadopcion`, `donativo_adopcion` | NULLABLE NUMERIC | Coerced via `_optional_numeric`; booleans rejected. |
| `nombre_adoptante` | NOT NULL TEXT | Required. |
| `dni_adoptante`, `telefono_adoptante`, `email_adoptante` | NULLABLE TEXT | Adopter contact; PII — redacted by the log_safe list. |
| `entrada_origen_id` | NULLABLE, FK to `entradas(id)` | Optional; no `activo` filter. |
| `observaciones` | NULLABLE TEXT | Free text. |
| `tipo_adopcion` | NOT NULL TEXT with CHECK | D-ADOPT-01: `regular`, `preadopcion`, `judicial`. |
| `responsable_adopcion_id` | NULLABLE, FK to `voluntarios(id)` | VOL-04 (#37); only active voluntarios are valid. |
| `seguimiento_estado` | NULLABLE TEXT | ADOPT-03 (issue #49); `NULL` treated as `PENDIENTE`. |
| `seguimiento_documento_url` | NULLABLE TEXT | ADOPT-03. |
| `seguimiento_documento_entregado_at` | NULLABLE TIMESTAMP | ADOPT-03; set on `MARCAR_ENTREGADO`. |
| `seguimiento_completado_at` | NULLABLE TIMESTAMP | ADOPT-03; set on `COMPLETAR`. |
| UNIQUE on `(animal_id, fecha_adopcion)` | UNIQUE constraint | Natural key; conflict surfaces as 409. |
| `activo` | BOOLEAN default true | Soft-delete flag. |

## Sub-routers and sub-services

The module is a single package with one router and one service. The seguimiento state machine is part of the same service (not a sub-service) so the lifecycle stays in one place.

## Acceptance criteria (ADOPT-01 + ADOPT-03)

The 16 numbered criteria in `openspec/changes/adopt-01-crud-adopciones/proposal.md` §"Criterios de aceptación" cover the CRUD contract. The seguimiento contract is documented in the service module docstring (issue #49). Highlights:

- RBAC: write endpoints require `WRITE_ADOPCIONES`; read endpoints use `require_authorized_user` (issue #144, P1-3).
- The `tipo_adopcion` CHECK constraint enforces the three values at the DB level. The service does not pre-validate the value beyond coercing to `str`.
- P1 fidelity: the module covers all legacy `TbAdopcion` columns plus the structured FK to `voluntarios` (verified via Dysflow `projectId=apap`).

## Cross-references

- `docs/proceso.md` — end-to-end playbook for the adoption workstream.
- `app/modules/animals/README.md` — sibling module for animal CRUD (LIFECYCLE work).
- `app/modules/sanidad/` — adjacent health summary endpoint (`get_resumen_sanitario`); no README yet.
- `app/core/domain_adopciones.py` — DDL, UNIQUE constraint, and CHECK on `tipo_adopcion`.
- `openspec/changes/adopt-01-crud-adopciones/proposal.md` — origin proposal for the ADOPT-01 work.

## Tests pinned

| Test file | Coverage |
|---|---|
| `tests/test_adopciones.py` | Service-level atoms for CRUD, FK checks, conflict translation. |
| `tests/test_adopciones_routes.py` | Route-level atoms for auth guards, CSRF, redirects, 404 / 409 / 422. |
| `tests/test_adopciones_queries.py` | Query-builder unit tests for the §22 seam. |
| `tests/integration/test_adopciones_queries_integration.py` | Integration tests against a live SQL backend. |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: `router`, `Adopcion`, `AdopcionConflictError`, `SeguimientoAction`, `SeguimientoEstado`, `SeguimientoTransitionResult`, `transition_seguimiento`. |
| `routes.py` | HTTP layer: 7 CRUD endpoints + 1 PATCH transition. |
| `service.py` | CRUD orchestration, FK checks, seguimiento state machine. |
| `queries.py` | SQL builder seam per AGENTS.md §22. |
| `forms.py` | `AdopcionForm` Pydantic v2 model for form parsing. |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #47 (ADOPT-01) — origin CRUD slice.
- #49 (ADOPT-03) — seguimiento state machine.
- #37 (VOL-04) — `responsable_adopcion_id` FK to `voluntarios`.
- #144 (issue #144) — RBAC: write endpoints require `WRITE_ADOPCIONES` (P1-3).
- #66 (RBAC matrix) — permission checks in `require_permission`.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/adopciones/list.html` | List active adoptions, optional `?adoptante=` filter. |
| `templates/adopciones/form.html` | Create and edit form (shared by both flows). |
| `templates/adopciones/detail.html` | Detail view with adopter, animal, volunteer, seguimiento estado. |

## How to extend this slice

When adding a new field to the adoption surface, follow this order:

1. Add the column to `app/core/domain_adopciones.py` and to the `ADOPCION_WRITE_COLUMNS` / `ADOPCION_SELECT_COLUMNS` tuples in `app/modules/adopciones/queries.py`.
2. Extend `app/modules/adopciones/forms.py::AdopcionForm` (Pydantic v2). The route handlers consume this model; the service does not re-shape form input.
3. Extend `app/modules/adopciones/queries.py::_build_write_params` (parameter list is positional; index alignment is critical).
4. If the new column is a foreign key, add a CHECK CTE to the INSERT / UPDATE SQL and a `_CHECK_<TARGET>_SQL` constant + `_validate_<target>` helper. The CTE pre-checks keep the FK-existence pattern consistent with the entradas and cesiones modules.
5. For seguimiento state machine changes, add a new `SeguimientoEstado` value to the `StrEnum`, extend `_VALID_TRANSITIONS`, and update the integration test that pins the enum ↔ CHECK constraint parity.

The hexagonal conversion (AGENTS.md §33) is tracked in epic #420. The slice is a candidate for future conversion because the adoption lifecycle is a clear bounded context.

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/adopciones/routes.py`.
- [ ] Every function name in the Service layer section is exported by `app/modules/adopciones/service.py` or its `__all__`.
- [ ] Every table and column name matches `app/modules/adopciones/queries.py`.
- [ ] The Layer type section matches the actual folder shape: `__init__.py`, `routes.py`, `service.py`, `queries.py`, `forms.py`.
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
