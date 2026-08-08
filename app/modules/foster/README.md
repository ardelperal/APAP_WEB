[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# foster

This README documents the domain, tables, endpoints, and risks of the `foster` module.

Este módulo gestiona las casas de acogida y el gate de asignación (FOSTER-01 y FOSTER-03). Una casa es la ficha de un hogar colaborador; el gate decide qué animales pueden ser asignados a cada casa y deja un audit log cuando el operador excede la capacidad.

The sentence that organizes this module: a foster home is a household record with a species preference and a capacity, and every animal-to-house assignment flows through a gate that blocks on species mismatch and warns on capacity overflow.

## Quick navigation

| Section | Purpose |
|---|---|
| What this is / is not | The slice's ownership boundary. |
| Domain | What this module owns across houses and the assignment gate. |
| Tables backend | SQL surface the service depends on. |
| Endpoints | HTTP routes mounted at `/casas-acogida`. |
| Service layer | Public functions exported by `app.modules.foster`. |
| Layer type | How this module is wired (route, sub-routers, service, assignment). |
| Risks and gotchas | Edge cases, the FOSTER-03 species gate, override audit, and PII. |
| Cross-references | Audit, runbook, and adjacent-module docs. |
| Verification checklist | Acceptance items for a doc or code PR. |

## What this is / is not

| Is | Is not |
|---|---|
| The CRUD for the `casas_acogida` table (FOSTER-01, issue #43). | The CRUD for the `acogidas` estancia rows (lives in `app/modules/acogidas`, FOSTER-02). |
| The foster assignment gate (FOSTER-03, issue #45): species block + capacity check + override audit. | The CRUD for the `foster_capacity_overrides` rows; the slice WRITES to the audit log, the link UPDATE happens in `app/modules/acogidas/service.py::create_acogida` (issue #142). |
| The publish surface for `CasaAcogida`, `AssignmentDecision`, `FosterCapacityOverride`, `VALID_COCHE_VALUES`, and `VALID_ESPECIE_VALUES`. | The species or sex enums (live in `app/modules/animals`). |

## Domain

The `foster` slice owns two cooperating surfaces:

- The basic CRUD for the `casas_acogida` table (FOSTER-01, issue #43). 19 legacy columns + system columns, with `coche` and `especie_preferente` as constrained string fields and `capacidad` as a positive integer.
- The foster assignment gate (FOSTER-03, issue #45): a hard species block plus an advisory capacity check, with an audited override path. The gate lives in `assignment.py` so the CRUD service stays orthogonal to the policy (D-GC-05).

A house with `especie_preferente IS NULL` counts as match for any filter value (the operator's "cualquier especie" pattern, faithful to legacy). The capacity gate uses a different filter than the operator-visible "estancias activas" counter: the gate counts only the preferred species, the counter counts every active stay.

The validation contract for the CRUD is strict: required fields are `nombre`, `apellidos`, `calle`, `telefono`, `coche`, `capacidad`. `coche` must be exactly `'Sí'` (with tilde) or `'No'`. `especie_preferente` must be `None` or one of `{'CANINA', 'FELINA'}`. `capacidad` must be a positive integer (the `bool`-is-`int` guard rejects `True`).

The override path is audited via `record_override`. The `motivo` is free text from the operator and is NEVER logged (D-GC-12 / REQ-GC-12). The override is linked to the estancia via the create-acogida UPDATE in `app/modules/acogidas/service.py` (issue #142), so an orphan override row is a code defect, not a runtime one.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `casas_acogida` | `id`, `nombre`, `apellidos`, `dni_acogedor`, `calle`, `numero`, `piso`, `letra`, `localidad`, `provincia`, `cp`, `telefono`, `telefono2`, `email`, `vinculacion`, `caracteristicas`, `coche` (`'Sí'` or `'No'`), `especie_preferente` (`'CANINA'`, `'FELINA'`, or NULL), `observaciones`, `capacidad` (positive int), `fecha_alta`, `fecha_baja`, `updated_at`, `activo` | One foster home per row. Mirrors legacy `TbAcogidaCasas`. |
| `foster_capacity_overrides` | `id`, `casa_acogida_id`, `animal_id`, `operador_user_id`, `motivo`, `created_at`, `estancia_id` (FK to `acogidas.id`, nullable until linked) | Audit log. Written by the gate; linked to the estancia in `create_acogida` (issue #142). |

The SQL strings live in `app/modules/foster/service.py` (`_INSERT_CASA_SQL`, `_LIST_CASAS_SQL`, `_LIST_CASAS_BY_ESPECIE_SQL`, `_GET_CASA_BY_ID_SQL`, `_UPDATE_CASA_SQL`, `_DELETE_CASA_SQL`) and in `app/modules/foster/assignment.py` (`_ACTIVE_COUNT_PREFERRED_SQL`, `_INSERT_OVERRIDE_SQL`, `_LIST_OVERRIDES_FOR_CASA_SQL`, `_ACTIVE_ESTANCIAS_FOR_CASA_SQL`). The module does not follow the AGENTS.md §22 seam pattern; the SQL strings and the validators are co-located.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/casas-acogida` | READ_CASAS_ACOGIDA | List active houses, optional `?especie=` filter. |
| GET | `/casas-acogida/new` | READ_CASAS_ACOGIDA | Empty create form. |
| POST | `/casas-acogida` | WRITE_CASAS_ACOGIDA | Create house. |
| GET | `/casas-acogida/{id}` | READ_CASAS_ACOGIDA | Detail view; injects `estancias_activas` and (developers only) the override historial. |
| GET | `/casas-acogida/{id}/edit` | READ_CASAS_ACOGIDA | Edit form prefilled from the row. |
| POST | `/casas-acogida/{id}/update` | WRITE_CASAS_ACOGIDA | Update house. |
| POST | `/casas-acogida/{id}/delete` | WRITE_CASAS_ACOGIDA | Soft-delete. |
| GET | `/casas-acogida/{casa_id}/asignar` | AUTHORIZED | Gate evaluation form. |
| POST | `/casas-acogida/{casa_id}/asignar` | WRITER | Run the gate; redirect on admit, render warning when motivo required, 422 on block. |
| GET | `/casas-acogida/{casa_id}/overrides` | DEVELOPER | List capacity overrides for the casa. |

Status codes: 200 on renders, 303 See Other on success, 404 when the casa is missing, 422 on validation failure or species block, 401 when the session lacks `user_id` (POST `/asignar`), 403 when a non-developer hits `/overrides` (FOSTER-03 P1 risk-review fix).

## Service layer

| Function | Purpose |
|---|---|
| `create_casa_acogida(client, params)` | INSERT with required-field validation; emits `foster.casa_acogida.created`. |
| `list_casas_acogida(client, especie=None)` | Active houses; `especie=None` returns all, else filter on `especie_preferente` (NULL counts as match). |
| `get_casa_acogida_by_id(client, casa_id)` | One house or `None`. |
| `update_casa_acogida(client, casa_id, params)` | UPDATE; returns `None` when the id is missing. |
| `delete_casa_acogida(client, casa_id)` | Atomic soft-delete. |
| `evaluate_assignment(client, animal_id, casa_id)` | Run the gate; returns `AssignmentDecision`. |
| `record_override(client, casa_id, animal_id, operador_user_id, motivo)` | INSERT audit row; returns the override UUID. |
| `list_overrides_for_casa(client, casa_id)` | All overrides for a casa, newest first. |
| `count_active_estancias_for_casa(client, casa_id)` | Operator-visible active-stay count (every species). |
| `CasaAcogida`, `AssignmentDecision`, `FosterCapacityOverride` | Frozen dataclasses. |
| `VALID_COCHE_VALUES` | `frozenset({'Sí', 'No'})` — tilde preserved. |
| `VALID_ESPECIE_VALUES` | `frozenset({'CANINA', 'FELINA'})`. |
| `AssignmentOutcome` | `Literal["admit", "block", "admit_with_warning"]`. |

## Layer type

Legacy route → service layout with a dedicated `assignment_routes.py` and `assignment.py` (FOSTER-03). The split is a feature-bounded carve-out, not a hexagonal conversion. This slice is not yet converted to the hexagonal form described in §33.

## Risks and gotchas

- The species gate lives in `assignment.py`; `acogidas.service.create_acogida` does not consult it. The route layer in `acogidas/routes.py` re-runs the gate via `_enforce_species_gate` to close the FOSTER-03 close-bypass P0. Any future direct service caller must replicate the gate (D-GC-05).
- The `motivo` column of `foster_capacity_overrides` is free text from the operator and may carry PII. The `GET /casas-acogida/{id}` detail view injects the override historial ONLY when `user.rol == Rol.DEVELOPER.value`; the `/overrides` endpoint is `require_developer_user` (P1 risk-review fix).
- The override link UPDATE in `acogidas.service.create_acogida` is scoped to `casa_acogida_id` + `animal_id`. A forged `override_id` from another operator cannot link to a different stay (judgment-day CRITICAL §1.2 / HIGH §3.2 follow-up).
- `record_override` returns the UUID as `str` (not the dataclass) so the route can chain it in the redirect URL without attribute access.
- The capacity gate's preferred-species filter differs from the operator-visible "estancias activas" counter. The former joins `animales` and filters on `Especie`; the latter counts every active stay. The detail view uses the latter.
- `coche` must be exactly `'Sí'` (with tilde) or `'No'`. Anything else raises `ValueError` from `_validate_coche`. Same Spanish-tilde rule applies to `cartilla_sanitaria` in the cesiones module.
- `capacidad` is rejected when it is a `bool` (defense against `True` being a subclass of `int` in Python).

## Column constraints

### `casas_acogida`

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `nombre`, `apellidos`, `calle`, `telefono` | NOT NULL TEXT | Required. |
| `coche` | NOT NULL, CHECK in `{'Sí', 'No'}` | Spanish tilde preserved. |
| `especie_preferente` | NULLABLE, CHECK in `{'CANINA', 'FELINA'}` | NULL means "cualquier especie" (legacy). |
| `capacidad` | NOT NULL INT > 0 | `_validate_capacidad` rejects `bool` and non-positive integers. |
| 14 optional address / contact fields | NULLABLE | `dni_acogedor`, `numero`, `piso`, `letra`, `localidad`, `provincia`, `cp`, `telefono2`, `email`, `vinculacion`, `caracteristicas`, `observaciones`. |
| `fecha_alta`, `fecha_baja`, `updated_at` | TIMESTAMP | System columns. |
| `activo` | BOOLEAN default true | Soft-delete flag. |

### `foster_capacity_overrides`

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `casa_acogida_id` | NOT NULL, FK to `casas_acogida(id)` | Required. |
| `animal_id` | NOT NULL, FK to `animales(id)` | Required. |
| `operador_user_id` | NOT NULL, FK to `voluntarios(id)` | D-GC-02: from session, not from form. |
| `motivo` | NOT NULL TEXT | D-GC-12: free text, PII risk, never logged. |
| `created_at` | TIMESTAMP default now() | Set by DB. |
| `estancia_id` | NULLABLE, FK to `acogidas(id)` | Set by `create_acogida` after the estancia INSERT (issue #142). |

## Sub-routers and sub-services

The module is one package with two routers and two services, each with a clear responsibility split:

- `routes.py` + `service.py` — the FOSTER-01 CRUD (houses).
- `assignment_routes.py` + `assignment.py` — the FOSTER-03 gate (species + capacity + override audit).

The split is a feature-bounded carve-out, not a hexagonal conversion. D-GC-05 records the rationale: the gate is orthogonal to the create flow and must remain so for migration batch and seed bypass scenarios.

## Acceptance criteria (FOSTER-01 + FOSTER-03)

The 25 numbered criteria in `openspec/changes/foster-gate-capacidad/proposal.md` cover the gate contract. The 12 numbered criteria in `openspec/changes/foster-casas-acogida/proposal.md` cover the CRUD. Highlights:

- `evaluate_assignment` is a separate operation, not a change to `create_acogida`. The route in `acogidas/routes.py` re-runs the gate before persisting to close the FOSTER-03 close-bypass P0.
- `record_override` validates `motivo` non-empty BEFORE any INSERT. A test pins the no-SQL path: `record_override_no_sql_when_motivo_invalido`.
- The detail view shows the "Estancias activas" count from `count_active_estancias_for_casa` and (developers only) the override historial from `list_overrides_for_casa`. The guard is in the route, not the template.
- `log_safe` is emitted for `foster.casa_acogida.created`, `foster.casa_acogida.updated`, `foster.casa_acogida.deleted`, and `foster.capacity_override.recorded`. The `motivo` is never logged.

## Cross-references

- `docs/proceso.md` — end-to-end playbook for the FOSTER workstream.
- `app/modules/acogidas/README.md` — sibling module for the estancia lifecycle (FOSTER-02).
- `app/modules/animals/README.md` — sibling module for animal CRUD; the FK target of the gate.
- `app/core/domain_casas_acogida.py` — DDL for `casas_acogida`.
- `app/core/domain_foster.py` — DDL for `foster_capacity_overrides`.
- `openspec/changes/foster-gate-capacidad/proposal.md` — design decisions D-GC-01 through D-GC-05.
- `openspec/changes/foster-casas-acogida/proposal.md` — origin proposal for the FOSTER-01 work.

## Tests pinned

| Test file | Coverage |
|---|---|
| `tests/test_foster.py` | Service-level atoms for the CRUD: required-field validation, list filter, soft-delete. |
| `tests/test_foster_routes.py` | Route-level atoms for the CRUD: auth guards, CSRF, redirects, 404 / 422. |
| `tests/test_foster_assignment.py` | Service-level atoms for the gate: species block, capacity warning, override recording, override listing. |
| `tests/test_foster_assignment_routes.py` | Route-level atoms for the gate: form render, gate decision matrix, motivo validation, developer-only `/overrides`. |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: `router`, `CasaAcogida`, `VALID_COCHE_VALUES`, `VALID_ESPECIE_VALUES`, `AssignmentDecision`, `FosterCapacityOverride`, `assignment_service`. |
| `routes.py` | HTTP layer for the FOSTER-01 CRUD (7 endpoints, prefix `/casas-acogida`). |
| `service.py` | CRUD orchestration, required-field validation, soft-delete. SQL strings co-located (AGENTS.md §22 deviation, tracked in backlog). |
| `assignment_routes.py` | HTTP layer for the FOSTER-03 gate (3 endpoints, prefix `/casas-acogida`). |
| `assignment.py` | Gate evaluation, override recording, override listing, active-estancia count. |
| `forms.py` | `CasaAcogidaForm` Pydantic v2 model + `CASA_ACOGIDA_FORM_FIELDS` constant. |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #43 (FOSTER-01) — origin CRUD slice.
- #45 (FOSTER-03) — foster assignment gate.
- D-GC-01 through D-GC-05 — design decisions for the gate.
- D-GC-12 / REQ-GC-12 — `motivo` PII handling, never logged.
- #142 (issue #142) — override link UPDATE in `acogidas.service.create_acogida`.
- #140 (issue #140, W2) — silent `int()` try/except removed in favor of Pydantic form parsing.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/casas_acogida/list.html` | List active houses, optional `?especie=` filter. |
| `templates/casas_acogida/form.html` | Create and edit form. |
| `templates/casas_acogida/detail.html` | Detail view with `estancias_activas` and (developers only) the override historial. |
| `templates/casas_acogida/asignar.html` | Gate evaluation form (FOSTER-03). |
| `templates/casas_acogida/overrides.html` | Override historial (developer-only). |

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/foster/routes.py` or `assignment_routes.py`.
- [ ] Every function name in the Service layer section is exported by `app/modules/foster/service.py` or `assignment.py` (or their `__all__`).
- [ ] Every table and column name matches the SQL constants in `service.py` and `assignment.py`.
- [ ] The Layer type section matches the actual folder shape: `__init__.py`, `routes.py`, `assignment_routes.py`, `service.py`, `assignment.py`, `forms.py` (no `queries.py`).
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
