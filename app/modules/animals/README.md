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
| Application and port | Public use cases and `AnimalsPort` capabilities. |
| Layer type | How the completed hexagonal slice is wired. |
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
- The photo streaming contract for the `apap-photos` storage bucket, with sentinel detection and deterministic stream cleanup (issue #285).

The `Situacion` legacy column is not persisted: the current state is derived from the event log via `animal_current_state` and exposed through the search API as a snake_case enum. Adding a new derived state means BOTH adding an enum value AND extending the `DB_LABEL_TO_ESTADO` map; the integration test `test_core_event_types_set_matches_strenum_members` pins the contract.

The required-field contract comes from Access `TbFichaAnimal.Required=True` plus the required-animal-data list in `docs/discovery/feature-01-animal-lifecycle.md`. Application validation runs before the port call, so the adapter never writes a row with broken required fields.

## Tables backend

| Table | Key columns | Purpose |
|---|---|---|
| `animales` | `id`, `NCHIP`, `NombreAnimal`, `Especie`, `Sexo`, `FNacimiento`, 19 optional legacy columns, `fecha_alta`, `updated_at`, `activo` | The ficha. UNIQUE on `NCHIP`; `activo` is the soft-delete flag. |
| `animal_lifecycle_events` | `id`, `animal_id`, `event_type`, `event_timestamp`, `caused_by_event_id`, `operador_user_id`, `metadata`, `created_at` | Append-only log. CHECK on `event_type` mirrors the `LifecycleEventType` enum. |
| `animal_current_state` | `animal_id`, `current_state`, `derived_at` | Derived view materialised from the event log. |
| `entradas`, `acogidas`, `adopciones`, `actuaciones_sanitarias`, `terapias` | `NCHIP` columns | Cascade targets of the chip-change saga. |

Read and lifecycle SQL lives in `adapters/local-backend/animals_local_backend_queries.py`; CRUD SQL lives in `animals_local_backend_write_queries.py`; chip SQL lives in `animals_local_backend_chip_cascade.py`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/animales` | READ_ANIMALES | List active animals through `AnimalsPort` (`fecha_alta DESC`, then `NCHIP ASC`). |
| GET | `/animales/search` | AUTHORIZED | JSON search with 9 query filters through `AnimalsPort`. |
| GET | `/animales/new` | READ_ANIMALES | Empty create form. |
| POST | `/animales` | WRITE_ANIMALES | Create animal; renders 409 on duplicate NCHIP. |
| GET | `/animales/{id}` | READ_ANIMALES | Detail view through `AnimalsPort`. |
| GET | `/animales/{id}/salud/resumen` | AUTHORIZED | JSON health summary (HEALTH-03, issue #52). |
| GET | `/animales/{id}/edit` | READ_ANIMALES | Edit form prefilled from the widened hexagonal entity. |
| POST | `/animales/{id}/update` | WRITE_ANIMALES | Update animal. |
| POST | `/animales/{id}/delete` | DELETE_ANIMALES | Soft-delete. |
| PATCH | `/animales/{id}/chip` | AUTHORIZED | Chip cascade (LIFECYCLE-04). |
| GET | `/animales/{id}/foto` | READ_ANIMALES | Streaming photo through `AnimalsPort`. |

Status codes: 200 on renders, 303 See Other on success, 404 when the id is missing, 409 on duplicate NCHIP and 422 on validation failure.

## Application and port

| Function | Purpose |
|---|---|
| `create_animal(port, **fields)` | Hexagonal INSERT; duplicate NCHIP surfaces as `UniqueViolationError` and becomes HTTP 409. |
| `list_animals(port)` | Hexagonal active-animal route path; ordered by newest `fecha_alta`, then NCHIP. |
| `get_animal_by_id(port, animal_id)` | Hexagonal primary-key lookup used by detail and foster assignment. |
| `update_animal(port, animal_id, **fields)` | Hexagonal partial UPDATE; `None` fields are skipped. |
| `delete_animal(port, animal_id)` | Hexagonal atomic soft-delete. |
| `search_animals(port, *, q, chip, especie, sexo, estado, fecha_alta_since, fecha_alta_until, limit, offset)` | Paginated hexagonal search used by the JSON route. |
| `AnimalsPort.change_animal_chip(...)` | Saga: updates 6 tables; rolls back on any failure. |
| `AnimalsPort.record_lifecycle_event(...)` | Append a lifecycle event through the adapter. |
| `AnimalsPort.resolve_animal_photo(animal_id)` | Transport-neutral `PhotoAsset` with an owned closable stream. |
| `Animal`, `AnimalSearchResult`, `ChangeChipResult`, `PhotoAsset` | Domain and port dataclasses. |
| `Especie`, `Sexo`, `LifecycleEventType` | Domain enums. |
| `CausalPairViolation` | Typed exception for D-23 violations. |

The chip saga lives in `adapters/local-backend/animals_local_backend_chip_cascade.py`. The photo resolver lives in `adapters/local-backend/animals_local_backend_photo.py`. The lifecycle event log still exposes its established package API while the port owns persistence.

## Layer type

The slice is 100% hexagonal. Every animal route and the foster integration depend on `AnimalsPort`; no legacy animal service or query shim remains.

The eleven `AnimalsPort` methods are landed. PR-C migrated chip and photo, then removed the four legacy shims to close epic #420.

The hexagonal `Animal` entity carries all 28 application-facing fields. The write port mirrors the 24 operator-writable fields; `id`, `estado`, `activo`, `fecha_alta`, and `updated_at` remain system-owned.

## Risks and gotchas

- `AnimalForm` and the application create/update paths reject invalid required fields before the adapter writes. `NombreFoto` is also checked against the storage allow-list; path traversal and absolute segments are rejected (issue #224).
- The chip saga is transactional. Any failure in the 6-table UPDATE triggers ROLLBACK and the route renders 422. Two operators running concurrent chip changes on the same animal produce exactly one success and one 409 (UNIQUE on NCHIP).
- The photo contract is fail-closed. An unknown animal returns 404. Missing keys and storage failures return the placeholder PNG with 200. The transport-neutral port does not expose ETag or Cache-Control metadata.
- `Situacion` is not persisted. Code that reads or writes it directly is a defect; the derived state comes from the event log.
- The search API uses `ILIKE` with `chr(37)` wildcards and a per-row `LIMIT 100`. The state filter joins `animal_current_state`; a missing row falls back to `pendiente_entrada`.
- The domain species and sex enums are imported under aliases in routes so the `Especie` / `Sexo` form fields do not shadow them.
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

## Adapter components

The module is one package with one router and focused hexagonal components:

- `adapters/local-backend/animals_local_backend_chip_cascade.py` — the chip cascade saga (LIFECYCLE-04, issue #29).
- `lifecycle_events.py` — the append-only event log writer with the D-23 causal-pair rule (issue #32).
- `adapters/local-backend/animals_local_backend_photo.py` — the streaming photo resolver for the `apap-photos` bucket (issue #285).

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
| `tests/test_animals_routes.py` | Route-level atoms for auth guards, CSRF, redirects, 404 / 409 / 422. |
| `tests/test_animals_routes_redirects.py` | Redirect-only routes (303 See Other). |
| `tests/test_animals_public_api.py` | Package re-export of the hexagonal primary-key lookup. |
| `tests/test_animal_search.py` | Search query atoms (filters, pagination, count). |
| `tests/test_animals_foto_route.py` | Photo streaming contract. |
| `tests/test_animals_local_backend_adapter.py` | Adapter CRUD, chip and `PhotoAsset` fail-closed paths. |

## Files inventory

| File | Role |
|---|---|
| `__init__.py` | Public API: primary-key lookup and DI port surface for sibling modules, plus lifecycle entrypoints. |
| `routes.py` | HTTP layer: 11 endpoints including the search, chip, and photo routes. |
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
| `adapters/local-backend/animals_local_backend_adapter.py` | LocalBackend-backed `AnimalsPort` implementation. |
| `adapters/local-backend/animals_local_backend_mappers.py` | Row-to-domain mapping for the LocalBackend adapter. |
| `adapters/local-backend/animals_local_backend_photo.py` | Storage adapter for photo download, fallback, safe logging and deterministic stream cleanup. |
| `adapters/local-backend/animals_local_backend_queries.py` | Read and lifecycle SQL seam for the LocalBackend adapter (AGENTS.md §22). |
| `adapters/local-backend/animals_local_backend_write_queries.py` | CRUD SQL seam, split to satisfy the mutation-site ceiling. |
| `adapters/local-backend/animals_local_backend_lifecycle.py` | Lifecycle persistence orchestration, split to satisfy the mutation-site ceiling. |
| `forms.py` | `AnimalForm` Pydantic v2 model. |
| `lifecycle_events.py` | Event log writer + D-23 causal-pair rule (LIFECYCLE-02). |

## Related issues

The slice is shaped by the following GitHub issues. The README cross-references each one where the implementation lands:

- #30 (LIFECYCLE-05) — search API with 9 filters.
- #29 (LIFECYCLE-04) — chip cascade saga.
- #32 (LIFECYCLE-02) — event log writer + D-23 causal-pair rule.
- #52 (HEALTH-03) — `salud/resumen` endpoint.
- #129 (issue #129) — required-field contract for `Terapia`, `TraeNChip`, `FIMPLANTACIONCHIP`, `NombreFoto`.
- #224 (issue #224) — `NombreFoto` allow-list on storage key.
- #233 (issue #233) — `animal_foto` route thinning (rule §28 ratchet).
- #285 (issue #285) — transport-neutral `PhotoAsset` streaming contract.

The `closes-with-trazability` comment on each merge cites the relevant commit SHA and the test path.

## Related templates

| Template | Role |
|---|---|
| `templates/animales/list.html` | List active animals in the order supplied by the route. |
| `templates/animales/form.html` | Create and edit form (shared by both flows). |
| `templates/animales/detail.html` | Detail view with `AnimalForm`-compatible fields. |

## Verification checklist

- [ ] Every endpoint table entry resolves to a real route in `app/modules/animals/routes.py`.
- [ ] Every function in the Application and port section resolves to an application use case or `AnimalsPort` method.
- [ ] Every table and column name matches the queries or DDL that defines it.
- [ ] The Layer type section matches the hexagonal folder shape: `domain/`, `ports/`, `application/`, `adapters/local-backend/`, `di/`, `routes.py` and `forms.py`.
- [ ] Cross-references resolve to files that exist at the linked paths.
- [ ] No Spanish tuteo or voseo: read once in voice. Castellano peninsular formal in every paragraph.
- [ ] No marketing fluff. No emoji in headings or body.
