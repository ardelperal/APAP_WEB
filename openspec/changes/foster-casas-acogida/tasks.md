# Tasks: FOSTER-01 — Casas de Acogida

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 800-1100 total |
| 400-line budget risk | High (over 400 with tests) |
| Chained PRs recommended | No (pre-MVP single-branch per AGENTS.md §15.2; the project routinely accepts single feature commits in this range — see #41 INTAKE-03, #65 CATALOG-01) |
| Delivery strategy | force-chained |
| Chain strategy | stacked-to-main toward `main` (pre-MVP) |
| Decision needed before apply | No |

## Phase 1: Schema + Service

- [ ] 1.1 RED: add tests in `tests/test_foster.py` covering create/list/get/update/soft-delete, required-field validation, especie_preferente enum check, capacidad positive-int check, coche enum check, search-by-especie.
- [ ] 1.2 GREEN: add `CASAS_ACOGIDA_CREATE_TABLE_SQL` constant to `app/core/domain.py` and ensure `ensure_domain_schema` includes it AFTER `acogidas` (FK dependency: FOSTER-02 will add `casa_acogida_id` FK from `acogidas`).
- [ ] 1.3 GREEN: add `app/modules/foster/service.py` with `CasaAcogida` dataclass, SQL constants, mapping, and CRUD. Validation contract mirrors INTAKE-01: required fields raise `ValueError`; FK / enum errors raise `ValueError`; natural-key duplicates translate to `CasaAcogidaConflictError`.
- [ ] 1.4 REFACTOR: extract shared helpers; ensure service is framework-agnostic.
- [ ] 1.5 Verify: `pytest tests/test_foster.py`, `ruff check .`, `python -m build`.

## Phase 2: Routes + Templates

- [ ] 2.1 RED: create `tests/test_foster_routes.py` for auth guards, service delegation, 404/409/422 handling, redirects, no `client.execute_sql(...)` in routes, CSRF token in forms.
- [ ] 2.2 GREEN: add `app/modules/foster/routes.py` with protected list/new/create/detail/edit/update/delete routes.
- [ ] 2.3 GREEN: add templates `app/templates/casas_acogida/list.html`, `form.html` (shared create/edit), `detail.html` with Spanish copy.
- [ ] 2.4 GREEN: wire router in `app/main.py` and `app/templates/base.html` ("Casas de acogida" nav link).
- [ ] 2.5 Verify: `pytest tests/test_foster_routes.py`, `ruff check .`, `python -m build`.

## Phase 3: Docs + Closeout

- [ ] 3.1 Update `docs/roadmap.md`: remove #43 row from §4, add to §5-bis closed list with SHA + commit, update `Última actualización`.
- [ ] 3.2 Close #43 with traceability comment per `github-issue-closure-traceability` (commit SHA + test path + P1 fidelity note).

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| _TBD_ | FOSTER-01 (schema + service + routes + templates) | 1.1-2.5 | _TBD_ | N/A (InsForge is target; legacy `TbAcogidaCasas` is read-only reference) |