# Proposal: Intake Entradas CRUD

## Intent

Close issues #87-#89 by exposing a first, minimal intake-entry CRUD workflow over the existing `entradas` table. This creates the service and protected UI surface needed to record an animal entry with a volunteer FK without prematurely rebuilding the full legacy intake domain.

## Scope

### In Scope
- Confirm the current minimal `entradas` schema for #87 unless specs find a strictly required constraint gap.
- Add service-layer CRUD for entries, including validation for animal/volunteer references and duplicate natural key handling.
- Add protected `/entradas` list/detail/create/edit/delete routes and Spanish UI templates following existing app patterns.
- Cover schema/service/routes with strict pytest-first TDD.

### Out of Scope
- Full legacy intake fields, batch intake, owner-surrender details, contracts, RIAC/document flows, veterinary assessment/anamnesis, and lifecycle event/state updates.
- Physical deletion of historical entries.
- Refactoring unrelated direct SQL in existing `voluntarios` routes.

## Capabilities

### New Capabilities
- `intake-entries`: Minimal web CRUD for animal intake entries backed by `entradas`.

### Modified Capabilities
- None.

## Approach

Use incremental CRUD over the existing minimal schema. Routes remain HTTP-only; `app/modules/entradas/service.py` owns SQL, mapping, validation, and domain errors. Route tests use dependency overrides/spies; service tests assert PostgREST SQL through `httpx.MockTransport`. User-facing copy follows existing Spanish templates during implementation.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/core/domain.py` | Modified | Confirm/minimally adjust `entradas` schema. |
| `app/modules/entradas/` | New | Service and route module. |
| `app/templates/entradas/` | New | CRUD pages. |
| `app/main.py`, `app/templates/base.html` | Modified | Router and nav link. |
| `tests/` | Modified/New | Domain, service, route, redirect coverage. |

## Review Slice / PR Plan

1. Schema/spec clarification (#87), under 400 changed lines, with pytest/ruff/build and `code-review-expert` gate.
2. Service + TDD (#88), under 400 changed lines, with `code-review-expert` gate.
3. Routes/templates + route TDD (#89), under 400 changed lines, with `code-review-expert` gate.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Minimal schema misses legacy fields | Med | Explicitly defer; avoid schema expansion without new issue/spec. |
| FK validation leaks into routes | Med | Service-owned validation and tests blocking route SQL. |
| Lifecycle side effects assumed | Med | State out of scope; specs must state CRUD writes `entradas` only. |

## Rollback Plan

Revert the affected slice commit/PR. Schema slice should avoid destructive migration; if a constraint is added, provide a matching rollback SQL note before implementation.

## Dependencies

- Existing `animales`, `voluntarios`, and `entradas` tables.
- Active-volunteer rules from discovery docs.

## Success Criteria

- [ ] Issues #87-#89 have TDD-backed schema/service/route coverage.
- [ ] No route calls `client.execute_sql(...)` directly.
- [ ] `pytest`, `ruff check .`, `python -m build`, and `code-review-expert` pass per implementation slice.
