# Spec: intake-entries

## Purpose

This specification defines the first minimal web CRUD surface for animal intake entries backed by `entradas`. It closes issues #87-#89 without expanding into the full legacy intake domain.

## Requirements

### Requirement: Migration-compatible `entradas` physical schema with minimal public CRUD scope

The system MUST keep the physical `entradas` table compatible with the existing migration mapping while exposing only the minimal intake-entry CRUD contract for this slice. Physical schema compatibility includes UUID primary key, animal FK, optional intake and exit volunteer FKs, intake/exit/owner-delivery dates, source/motive/notes, nullable donor donation value, active/soft-delete fields, timestamps, FK constraints to `animales` and `voluntarios`, and duplicate protection for `(animal_id, fecha_entrada)`. The public service/form contract MUST defer salida/entrega/donativo fields until a dedicated workflow slice exposes them.

#### Scenario: Domain schema keeps mapped physical columns

- GIVEN schema bootstrap is executed in tests
- WHEN the `entradas` DDL is inspected
- THEN it includes animal and intake/exit volunteer FKs, intake/exit/owner-delivery dates, notes, donor donation, active flag, timestamps, and natural-key uniqueness
- AND the salida/entrega/donativo columns are nullable migration-compatibility fields, not mandatory public CRUD fields

#### Scenario: Duplicate intake is rejected by natural key

- GIVEN an existing active entry for one animal and date
- WHEN another entry is created for the same animal and date
- THEN the operation fails with a conflict-equivalent domain error

### Requirement: Service-owned intake entry CRUD

The system MUST provide service-layer CRUD for intake entries. Services MUST own SQL, mapping, validation, duplicate handling, and domain errors. Routes MUST NOT call `client.execute_sql(...)` directly.

#### Scenario: Create entry validates animal and volunteer references

- GIVEN an existing animal and an active volunteer eligible for intake
- WHEN `create_entrada` receives valid intake data
- THEN it persists an `entradas` row with those FK values
- AND returns the created entry contract

#### Scenario: Invalid volunteer FK is rejected before insert

- GIVEN a nonexistent or inactive volunteer id
- WHEN `create_entrada` receives that volunteer id
- THEN the service returns a validation error
- AND no insert into `entradas` is attempted

#### Scenario: Route layer contains no direct SQL

- GIVEN protected CRUD route tests use a spy client
- WHEN list, detail, create, edit, or delete routes are exercised
- THEN SQL execution is observed only through service functions
- AND route code contains no direct `client.execute_sql(...)` calls

### Requirement: Protected intake entry CRUD UI

The system MUST expose protected `/entradas` list, detail, create, edit, and soft-delete workflows using existing FastAPI/Jinja patterns. Unauthenticated or unauthorized users MUST be redirected by shared auth guards.

#### Scenario: Authorized user creates an entry through the UI

- GIVEN an authorized session and valid form data
- WHEN the user submits the create form
- THEN the route delegates to the service and redirects to the created entry detail/list view
- AND Spanish UI copy may follow existing templates during implementation

#### Scenario: Unauthorized user is redirected

- GIVEN a missing or unauthorized session
- WHEN the user requests any `/entradas` CRUD page
- THEN the shared guard redirects to login or unauthorized flow
- AND no service write is attempted

#### Scenario: Delete is soft-delete only

- GIVEN an existing intake entry
- WHEN an authorized user deletes it
- THEN the entry is marked inactive/deleted by the service
- AND the row is not physically removed

## Acceptance Criteria

- Pytest coverage MUST precede implementation for schema, service, routes, redirects, and no-route-direct-SQL.
- `pytest`, `ruff check .`, `python -m build`, and `code-review-expert` MUST pass per implementation slice.
- Work MUST be sliced for the 400-line review budget: schema (#87), service (#88), routes/templates (#89).

## Out of Scope

- Lifecycle event creation, animal state updates, or state-machine side effects.
- Batch intake and multi-animal intake workflows.
- Contracts, RIAC/document flows, anamnesis, veterinary assessment, owner-surrender details.
- Public service/form handling for salida, entrega a propietario, or donativo fields.
- Migration mapping changes for `entrada.yaml`; physical schema compatibility is preserved in this slice.
- Physical deletion of historical entries.
