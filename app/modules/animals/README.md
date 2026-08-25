[← Back to CODEBASE-GUIDE](../../docs/CODEBASE-GUIDE.md)

# animals

This README documents the domain, tables, endpoints, and risks of the `animals` module.

Este módulo es la pieza central del dominio: gestiona la ficha de cada animal (TbFichaAnimal), el log de eventos del ciclo de vida, el cambio de chip en cascada y la resolución de fotos para el detalle HTML.

The sentence that organizes this module: the animal is the aggregate root that every other slice references, with a strict column-naming contract inherited from the legacy Access backend and a lifecycle event log that drives the current_state derivation.

## Quick navigation

| Section | Purpose |
|---|---|
| What this is / is not | The slice's ownership boundary. |
| Domain | What this module owns across CRUD, lifecycle events, chip changes, and photos. |
| Tables backend | SQL surface the service depends on. |
| Endpoints | HTTP routes mounted at `/animales`. |
| Service layer | Public functions exported by `app.modules.animals`. |
| Layer type | How this module is wired (route, service, queries, sub-services). |
| Risks and gotchas | Edge cases, chip cascade, photo streaming, and storage key validation. |
| Cross-references | Audit, runbook, and adjacent-module docs. |
| Verification checklist | Acceptance items for a doc or code PR. |

## What this is / is not

| Is | Is not |
|---|---|
| The CRUD for the `animales` table (legacy `TbFichaAnimal`). | The CRUD for entradas, acogidas, or adopciones (each is its own module slice). |
| The lifecycle event log writer and the D-23 causal-pair validator. | The CRUD for `animal_current_state` (a derived view, never written directly). |
| The chip cascade saga that updates the NCHIP field across 6 tables. | The CRUD for the `terapias` or `actuaciones_sanitarias` rows (lives in `app/modules/salud`). |
| The streaming photo contract for the `apap-photos` storage bucket. | The health summary endpoint (`/animales/{id}/salud/resumen`), which delegates to `app/modules/sanidad.get_resumen_sanitario`. |

## Domain

The `animals` slice owns four cooperating surfaces:

- Basic CRUD for the `animales` table (legacy `TbFichaAnimal`, 24 user-facing columns + system columns).
- The `animal_lifecycle_events` append-only log with the D-23 causal-pair rule (FOSTER_CLOSED_BY_ADOPTION must precede ADOPTION_STARTED for the same animal).
- The chip cascade saga that updates the NCHIP field across 6 tables in a single transaction (LIFECYCLE-04, issue #29).
- The photo streaming contract for the `apap-photos` storage bucket, with sentinel detection and ETag-based conditional responses (issue #285).

The `Situacion` legacy column is not persisted: the current state is derived from the event log via `animal_current_state` and exposed through the search API as a snake_case enum. Adding a new derived state means BOTH adding an enum value AND extending the `DB_LABEL_TO_ESTADO` map; the integration test `test_core_event_types_set_matches_strenum_members` pins the contract.

The slice runs the same FK-existence pattern as the entradas and adopciones modules. The required-field contract comes from Access `TbFichaAnimal.Required=True` plus the required-animal-data list in `docs/discovery/feature-01-animal-lifecycle.md`. The validation runs in `_validate_required_fields` BEFORE any SQL, so the service never writes a row with broken required fields.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `animales` | `id`, `NCHIP`, `NombreAnimal`, `Especie`, `Sexo`, `FNacimiento`, 19 optional legacy columns, `fecha_alta`, `updated_at`, `activo` | The ficha. UNIQUE on `NCHIP`; `activo` is the soft-delete flag. |
| `animal_lifecycle_events` | `id`, `animal_id`, `event_type`, `event_timestamp`, `caused_by_event_id`, `operador_user_id`, `metadata`, `created_at` | Append-only log. CHECK on `event_type` mirrors the `LifecycleEventType` enum. |
| `animal_current_state` | `animal_id`, `current_state`, `derived_at` | Derived view materialised from the event log. |
| `entradas`, `acogidas`, `adopciones`, `actuaciones_sanitarias`, `terapias` | `NCHIP` columns | Cascade targets of the chip-change saga. |

The search query lives in `app/modules/animals/queries.py` as `build_animal_search` and `build_animal_count`. The search joins `animal_current_state` to surface the derived state. The `DB_LABEL_TO_ESTADO` map is the single source of truth for DB-to-API state translation (AGENTS.md §4).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/animales` | READ_ANIMALES | List active animals through `AnimalsPort` (`NCHIP ASC` until PR-A.2b restores legacy ordering). |
| GET | `/animales/search` | AUTHORIZED | JSON search with 9 query filters, pagination. |
| GET | `/animales/new` | READ_ANIMALES | Empty create form. |
| POST | `/animales` | WRITE_ANIMALES | Create animal; renders 409 on duplicate NCHIP. |
| GET | `/animales/{id}` | READ_ANIMALES | Detail view through `AnimalsPort`. |
| GET | `/animales/{id}/salud/resumen` | AUTHORIZED | JSON health summary (HEALTH-03, issue #52). |
| GET | `/animales/{id}/edit` | READ_ANIMALES | Edit form prefilled from the row. |
| POST | `/animales/{id}/update` | WRITE_ANIMALES | Update animal. |
| POST | `/animales/{id}/delete` | DELETE_ANIMALES | Soft-delete. |
| PATCH | `/animales/{id}/chip` | AUTHORIZED | Chip cascade (LIFECYCLE-04). |
| GET | `/animales/{id}/foto` | READ_ANIMALES | Streaming photo with ETag. |

Status codes: 200 on renders, 303 See Other on success, 404 when the id is missing, 409 on duplicate NCHIP, 422 on validation failure, 304 on If-None-Match for the photo endpoint.

## Service layer

| Function | Purpose |
|---|---|
| `create_animal(client, params)` | INSERT with required-field validation; duplicate NCHIP surfaces as `InsForgeError` 409 to the route. |
| `list_animals(port)` | Hexagonal active-animal route path; currently ordered by NCHIP. |
| `get_animal_by_id(port, animal_id)` | Hexagonal primary-key lookup used by detail and foster assignment. |
| `update_animal(client, animal_id, params)` | UPDATE; returns `None` when the id is missing. |
| `delete_animal(client, animal_id)` | Atomic soft-delete. |
| `record_event(client, *, animal_id, event_type, event_timestamp, created_by, ...)` | Legacy lifecycle-event writer (issue #32, D-23). Mirrored by the hexagonal `record_lifecycle_event` (#609). |
| `search_animals(client, *, q, chip, especie, sexo, estado, fecha_alta_since, fecha_alta_until, limit, offset)` | Paginated search; `limit=0` returns count only. |
| `change_animal_chip(client, *, animal_id, old_chip, new_chip, reason, operador_user_id)` | Saga: updates 6 tables; rolls back on any failure. |
| `record_event(client, ...)` | Append a lifecycle event with causal-pair validation. |
| `validate_causal_pair(client, ...)` | Pre-flight D-23 check that raises `CausalPairViolation`. |
| `resolve_animal_photo(client, animal_id)` | Streaming outcome: `PhotoOutcome` with byte iterator + ETag. |
| `Animal`, `AnimalSearch`, `AnimalSearchResult`, `ChangeChipResult` | Frozen dataclasses. |
| `Especie`, `Sexo`, `LifecycleEventType` | Domain enums. |
| `CausalPairViolation` | Typed exception for D-23 violations. |

The `change_animal_chip` saga lives in `chip_service.py` (extracted from `service.py` to keep that file under the 700-line budget, AGENTS.md rule 21). The lifecycle event log lives in `lifecycle_events.py`. The photo resolver lives in `photo_service.py`.

## Layer type

Transitional mixed layout. `list_animales`, `animal_detail`, and foster assignment use route → application → `AnimalsPort` → adapter. Unmigrated handlers retain route → legacy service → queries.

The eleven `AnimalsPort` methods are landed, including primary-key lookup and paginated search from PR-A.1 of epic #420.

The conversion is not complete. Search/edit remain for PR-A.2b; writes for PR-B; chip/photo for PR-C.

The legacy `service.py` owns `TraeNChip`, `Raza` and the remaining columns until the model widens or an `AnimalCreateRequest` lands.

## Risks and gotchas

- `_validate_required_fields` rejects blank `NCHIP`, `NombreAnimal`, `Especie`, `Sexo`, `FNacimiento`, `Terapia`, `TraeNChip`, `FIMPLANTACIONCHIP`, and `NombreFoto`. The last one is also checked against the storage allow-list (`_validate_storage_key`); path traversal and absolute segments are rejected (issue #224).
- The chip saga is transactional. Any failure in the 6-table UPDATE triggers ROLLBACK and the route renders 422. Two operators running concurrent chip changes on the same animal produce exactly one success and one 409 (UNIQUE on NCHIP).
- The photo contract is fail-closed. An unknown animal returns 404. Missing keys and storage failures return the placeholder PNG with 200. `If-None-Match` returns 304 (issue #285).
- `Situacion` is not persisted. Code that reads or writes it directly is a defect; the derived state comes from the event log.
- The search API uses `ILIKE` with `chr(37)` wildcards and a per-row `LIMIT 100`. The state filter joins `animal_current_state`; a missing row falls back to `pendiente_entrada`.
- The species and sex enums in `service.py` are shadowed by the `Especie` / `Sexo` form fields. The routes import the enums under aliases (`EspecieEnum`, `SexoEnum`) to avoid name shadowing.
- The lifecycle log is append-only by SQL trigger. Corrections are modelled as new events with `caused_by_event_id` pointing at the prior event. The service exposes no UPDATE or DELETE for the log.

## Column constraints

| Column | Constraint | Reason |
|---|---|---|
| `id` | UUID PK | System column. |
| `NCHIP` | NOT NULL, UNIQUE | Microchip; the natural key for the legacy ficha. |
| `NombreAnimal` | NOT NULL TEXT | Required. |
| `Especie` | NOT NULL with CHECK on `Especie` enum | Required. |
| `Sexo` | NOT NULL with CHECK on `Sexo` enum | Required. |
| `FNacimiento` | NOT NULL DATE | Required. |
| 19 optional legacy cols | NULLABLE | `TraeNChip`, `FIMPLANTACIONCHIP`, `Raza`, `Color`, `Pelo`, `Tamano`, `Caracter`, `FDefuncion`, `Terapia`, `Observaciones`, `NombreFoto`, `Cartilla`, `Eutanasia`, `RazaPPP`, `Mestizo`, `EutanasiaOtrasCausas`, `EutanasiaEnfermedad`, `UltimoEstadoAntesDeFallecido`, `ComunicacionARIAC`. |
| `Terapia`, `TraeNChip`, `FIMPLANTACIONCHIP`, `NombreFoto` | NOT NULL by service contract | Issue #129: required by Access + discovery. |
| `NombreFoto` | NOT NULL + allow-list on storage key | Issue #224: rejects path traversal and absolute segments. |
| `fecha_alta`, `updated_at` | TIMESTAMP | System columns. |
| `activo` | BOOLEAN default true | Soft-delete flag. |

## Sub-routers and sub-services

The module is one package with one router and one primary service, plus three orthogonal sub-services:

- `chip_service.py` — the chip cascade saga (LIFECYCLE-04, issue #29). Extracted to keep `service.py` under the 700-line budget.
- `lifecycle_events.py` — the append-only event log writer with the D-23 causal-pair rule (issue #32).
- `photo_service.py` — the streaming photo resolver for the `apap-photos` bucket (issue #285).

The species, sex, and lifecycle event enums live in the corresponding sub-modules to keep the cross-module import surface narrow.

## Acceptance criteria (LIFECYCLE + CHIP + PHOTO + CRUD)

The proposals cover the contracts:

- LIFECYCLE-02 (issue #32): the event log writer and the D-23 causal-pair validator.
- LIFECYCLE-04 (issue #29): the chip cascade updates 6 tables in a single transaction.
- LIFECYCLE-05 (issue #30): the search API with 9 filters, pagination, and the derived-state join.
- HEALTH-03 (issue #52): the `salud/resumen` endpoint delegates to `app/modules/sanidad`.
- The required-field contract is pinned in `_validate_required_fields` and asserted by the `AnimalForm` import-time check.

## Cross-references

- `docs/proceso.md` — end-to-end playbook for the LIFECYCLE workstream.
- `app/modules/salud/` — sibling module for health summary, health actes, and terapias.
- `app/modules/acogidas/README.md`, `app/modules/adopciones/README.md`, `app/modules/entradas/README.md` — slices that consume the chip cascade and lifecycle event log.
- `app/core/domain_animales.py` — DDL, UNIQUE on NCHIP, and CHECK constraints.
- `app/core/domain_lifecycle.py` — DDL for `animal_lifecycle_events` and the append-only trigger.
- `openspec/changes/ux-ui-foundation/proposal.md` — origin proposal for the search UI work.

## Tests pinned

| Test file | Coverage |
|---|---|
| `tests/test_animals.py` | Service-level atoms for CRUD, validation, search. |
| `tests/test_animals_routes.py` | Route-level atoms for auth guards, CSRF, redirects, 404 / 409 / 422. |
| `tests/test_animals_routes_redirects.py` | Redirect-only routes (303 See Other). |
| `tests/test_animals_public_api.py` | Package re-export of the hexagonal primary-key lookup. |
| `tests/test_animal_search.py` | Search query atoms (filters, pagination, count). |
| `tests/test_animals_queries.py` | Query-builder unit tests for the §22 seam. |
| `tests/test_animals_foto_route.py` | Photo streaming contract. |
| `tests/test_animal_photo_resolution.py` | `PhotoOutcome` shape, fail-closed paths. |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: primary-key lookup and DI port surface for sibling modules, plus lifecycle entrypoints. |
| `routes.py` | HTTP layer: 11 endpoints including the search, chip, and photo routes. |
| `service.py` | CRUD orchestration, required-field validation. |
| `domain/animal.py` | Hexagonal `Animal` entity + `Especie` / `Sexo` enums (issue #420 slice). |
| `ports/animals_port.py` | Hexagonal `AnimalsPort` Protocol with the migrated methods. |
| `ports/photo_asset.py` | Transport-neutral photo asset and owned closable-stream contract. |
| `application/get_animal_by_nchip.py` | Hexagonal use case for the NCHIP read. |
| `application/get_animal_by_id.py` | Hexagonal use case for the UUID primary-key read. |
| `application/list_animals.py` | Hexagonal use case for the paginated list. |
| `application/search_animals.py` | Hexagonal use case for paginated filtered search. |
| `application/create_animal.py` | Hexagonal use case for the create flow. |
| `application/update_animal.py` | Hexagonal use case for the partial update. |
| `application/delete_animal.py` | Hexagonal use case for the soft-delete. |
| `application/record_lifecycle_event.py` | Hexagonal use case for the lifecycle-event write (#609). |
| `application/list_lifecycle_events.py` | Hexagonal use case for the chronological timeline read. |
| `application/resolve_animal_photo.py` | Hexagonal use case for photo resolution. |
| `adapters/insforge/animals_insforge_adapter.py` | InsForge-backed `AnimalsPort` implementation. |
| `adapters/insforge/animals_insforge_mappers.py` | Row-to-domain mapping for the InsForge adapter. |
| `adapters/insforge/animals_insforge_photo.py` | Storage adapter for photo download, fallback, safe logging and deterministic stream cleanup. |
| `adapters/insforge/animals_insforge_queries.py` | SQL seam for the InsForge adapter (AGENTS.md §22). |
| `queries.py` | Legacy SQL builder seam (separate from the InsForge adapter; the slice carries two SQL seams until the legacy service is retired). |
| `forms.py` | `AnimalForm` Pydantic v2 model. |
| `chip_service.py` | Chip cascade saga (LIFECYCLE-04). |
| `lifecycle_events.py` | Event log writer + D-23 causal-pair rule (LIFECYCLE-02). |
| `photo_service.py` | Streaming photo resolver (issue #285). |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #30 (LIFECYCLE-05) — search API with 9 filters.
- #29 (LIFECYCLE-04) — chip cascade saga.
- #32 (LIFECYCLE-02) — event log writer + D-23 causal-pair rule.
- #52 (HEALTH-03) — `salud/resumen` endpoint.
- #129 (issue #129) — required-field contract for `Terapia`, `TraeNChip`, `FIMPLANTACIONCHIP`, `NombreFoto`.
- #224 (issue #224) — `NombreFoto` allow-list on storage key.
- #233 (issue #233) — `animal_foto` route thinning (rule §28 ratchet).
- #285 (issue #285) — `PhotoOutcome` streaming contract.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/animales/list.html` | List active animals in the order supplied by the route. |
| `templates/animales/form.html` | Create and edit form (shared by both flows). |
| `templates/animales/detail.html` | Detail view with `AnimalForm`-compatible fields. |

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/animals/routes.py`.
- [ ] Every function name in the Service layer section is exported by `app/modules/animals/service.py`, `chip_service.py`, `lifecycle_events.py`, or `photo_service.py`.
- [ ] Every table and column name matches the queries or DDL that defines it.
- [ ] The Layer type section matches the actual folder shape: `__init__.py`, `routes.py`, `service.py`, `queries.py`, `forms.py`, `chip_service.py`, `lifecycle_events.py`, `photo_service.py`.
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
