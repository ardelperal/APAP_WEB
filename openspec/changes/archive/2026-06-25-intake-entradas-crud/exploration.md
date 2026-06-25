## Exploration: intake-entradas-crud

### Current State
APAP_WEB already has the minimum `entradas` database table in `app/core/domain.py`, created during the migration/lifecycle foundation work. The table is bootstrapped in `ensure_domain_schema()` after `animales`, `voluntarios`, and `roles_voluntario`, with FKs to `animales(id)` and `voluntarios(id)`, soft-delete fields, timestamps, and a natural-key uniqueness constraint on `(animal_id, fecha_entrada)`.

There is no `app/modules/entradas/` module yet, no `/entradas` router included in `app/main.py`, and no `app/templates/entradas/` templates. Current feature modules (`animales`, `voluntarios`) use a thin FastAPI route layer over a service module that owns SQL, validation, and dataclass mapping. Tests use `httpx.MockTransport` for service SQL assertions and `app.dependency_overrides[get_insforge_client]` with route spies for protected route tests.

Relevant existing caveat: `app/modules/voluntarios/routes.py` still contains direct SQL in `deactivate_voluntario_view`; do not copy that pattern. The entries slice must follow the stricter animals pattern: routes delegate all SQL to service methods.

Legacy/product discovery shows intake is broader than the current minimal schema: delivery person data, DNI/contact/address, pickup context, veterinary state, RIAC, contracts, anamnesis, physical assessment, and batch intake are documented but not represented in the current `entradas` table. For this issue block, treat those as explicit out-of-scope follow-ups unless the proposal decides to expand #87 beyond the existing minimal migration table.

### Affected Areas
- `app/core/domain.py` — existing `ENTRADAS_CREATE_TABLE_SQL` is the starting point for #87; proposal must decide whether to keep minimal schema or extend it for product CRUD.
- `tests/test_domain.py` — already covers current `entradas` columns/FKs/natural key; new schema fields or constraints require RED tests here first.
- `app/core/migration/mappings/entrada.yaml` — maps legacy `TbEntradas` to current web columns; any schema expansion must preserve mapping compatibility and web-only strategies.
- `app/modules/animals/service.py` — main pattern for dataclass mapping, service-owned validation, INSERT/LIST/GET/UPDATE/SOFT-DELETE SQL.
- `app/modules/animals/routes.py` — main route pattern for auth guard, form parsing, template rendering, ValueError→422, InsForgeError→409, RedirectResponse 303.
- `app/modules/voluntarios/service.py` — volunteer FK source and role taxonomy (`RolVoluntario.INTAKE`).
- `app/modules/voluntarios/routes.py` — useful UI pattern, but contains direct SQL on deactivate and should not be copied.
- `app/core/auth_dependencies.py` — shared dependency pattern for protected routes; use `Depends(get_insforge_client_dep)` and early-return redirects.
- `app/main.py` — will need to include the future `entradas_router`.
- `app/templates/base.html` — main nav currently links only Inicio/Animales/Voluntarios/Admin; add Entradas only when route exists.
- `app/templates/animales/*`, `app/templates/voluntarios/*` — UI patterns for list/detail/form and APAP visual tokens.
- `tests/conftest.py`, `tests/test_animals.py`, `tests/test_animals_routes.py`, `tests/test_animals_routes_redirects.py`, `tests/test_voluntarios.py` — test patterns for service and protected route coverage.
- `docs/discovery/feature-02-intake-foster-adoption.md` and `docs/legacy-lifecycle-transition-rules.md` — product/legacy rules, especially active-volunteer validation and strict lifecycle state constraints.
- `Makefile`, `pyproject.toml` — verification gate is `pytest`, `ruff check .`, `python -m build`, plus deprecation warnings as test errors.

### Approaches
1. **Incremental CRUD on existing minimal schema** — implement #88/#89 using the current `entradas` columns and service-layer validation, leaving richer legacy fields/batch intake/contracts for later issues.
   - Pros: Smallest safe slice; aligns with existing schema tests; easiest to keep each PR under 400 changed lines; avoids destabilizing migration mappings.
   - Cons: Product CRUD will not capture all legacy intake fields yet; proposal must state the out-of-scope fields clearly.
   - Effort: Medium.

2. **Schema expansion before CRUD** — expand `entradas` now to cover more legacy intake fields from discovery, then implement service/routes/templates.
   - Pros: Closer to full intake product behavior; reduces future schema churn.
   - Cons: Larger diff, higher migration/mapping risk, likely exceeds 400-line review budget unless chained; needs careful legacy field audit before spec.
   - Effort: High.

3. **Read-only/list-first slice** — add list/detail around existing migrated entries before creating entries from UI.
   - Pros: Very small and reviewable; useful if data is already migrated.
   - Cons: Does not close #88 (`create_entrada`) and only partially advances #89; delays core user workflow.
   - Effort: Low.

### Recommendation
Use Approach 1 for the next proposal: build CRUD around the existing minimal `entradas` schema, with strict service-layer validation and explicit follow-up scope for richer intake fields, owner surrender, contracts, and batch intake. This is the best fit for the current issue block (#87-#89), keeps migration compatibility stable, and supports chained review slices under the 400-line budget.

Candidate PR slices:
1. **Schema/spec clarification (#87)** — confirm current `entradas` table as accepted minimal schema or add only strictly necessary constraints/tests. Include `tests/test_domain.py` updates if schema changes.
2. **Service + TDD (#88)** — add `app/modules/entradas/service.py` with `Entrada` dataclass, `create_entrada`, list/get/update/soft-delete helpers if needed by CRUD, active animal/volunteer FK validation where practical, and unit tests using `MockTransport`.
3. **Routes/templates + route TDD (#89)** — add `/entradas` router, templates, nav link, `app.main` include, route-level auth/redirect tests, and no direct `execute_sql` in routes.
4. **Review/verification gate** — run `pytest`, `ruff check .`, `python -m build`, then code-review-expert before promotion. This gate is mandatory for every implementation slice.

### Risks
- Current `entrada.yaml` comments mention a `legacy_id` column, but `ENTRADAS_CREATE_TABLE_SQL` does not define one. Do not expand or rely on `legacy_id` without a dedicated schema/migration decision.
- The current `entradas` schema is intentionally minimal for migration; full product intake fields from discovery are not yet represented.
- FK validation can become N+1 or route-bound if implemented carelessly. Keep validation in service and use focused existence queries.
- Lifecycle/state-machine rules are broader than simple CRUD: a create entry may imply lifecycle events/state updates in later slices. Proposal must state whether this block only writes `entradas` or also updates `animal_lifecycle_events` / `animal_current_state`.
- Duplicate natural key `(animal_id, fecha_entrada)` may be too coarse for multiple same-day intake corrections; use existing constraint for this slice unless product criteria say otherwise.
- Volunteer assignment must reject inactive/nonexistent volunteers for new records per discovery; nullable volunteer FKs must be specified for legacy compatibility.
- Route tests should use the dependency override pattern from current animals tests; avoid the older direct SQL route pattern still present in voluntarios deactivate.
- UI labels in existing templates are Spanish; although this SDD artifact is English per launch contract, generated user-facing APAP templates should follow existing Spanish UI conventions during implementation.

### Ready for Proposal
Yes. The proposal should frame the change as an incremental, TDD-first CRUD slice over the existing minimal `entradas` table, explicitly deferring batch intake, owner surrender, contracts, RIAC/document flows, and richer legacy fields unless the user wants #87 expanded before implementation.
