# Tasks: Intake Entradas CRUD

skill_resolution: paths-injected

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 650-900 total; each slice <400 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 schema #87 -> PR 2 service #88 -> PR 3 routes/UI #89 |
| Delivery strategy | force-chained |
| Chain strategy | stacked-to-main toward `staging` |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Confirm migration-compatible physical `entradas` schema and minimal public CRUD scope | PR 1 | Base `staging`; issue #87; pytest/ruff/build/review gate |
| 2 | Add service-owned CRUD/domain errors | PR 2 | Stacked after PR 1; issue #88; tests with code |
| 3 | Add protected routes/templates/nav | PR 3 | Stacked after PR 2; issue #89; route/UI tests with code |

## Phase 1: Schema Slice (#87)

- [x] 1.1 RED: update `tests/test_domain.py` only if needed to assert migration-compatible physical `entradas` columns, FKs, timestamps, `activo`, natural-key uniqueness, and deferred public scope for salida/entrega/donativo.
- [x] 1.2 GREEN/REFACTOR: minimally adjust `app/core/domain.py` only for a proven schema gap; keep mapped physical columns while deferring them from public CRUD.
- [x] 1.3 Verify slice: run `pytest`, `ruff check .`, `python -m build`, then `code-review-expert` before PR 1 promotion.

## Phase 2: Service Slice (#88)

- [x] 2.1 RED: create `tests/test_entradas.py` for create/list/get/update/soft-delete, required fields, active-volunteer validation, and duplicate conflict.
- [x] 2.2 GREEN: create `app/modules/entradas/__init__.py` and `app/modules/entradas/service.py` with `Entrada`, `EntradaConflictError`, SQL constants, mapping, and CRUD.
- [x] 2.3 REFACTOR: keep public fields minimal and ensure volunteer eligibility checks `activo=true`; do not enforce `RolVoluntario.INTAKE`.
- [x] 2.4 Verify slice: run `pytest`, `ruff check .`, `python -m build`, then `code-review-expert` before PR 2 promotion.

## Phase 3: Routes/UI Slice (#89)

- [x] 3.1 RED: create `tests/test_entradas_routes.py` for auth guards, service delegation, 404/409/422 handling, redirects, and no route `client.execute_sql(...)`.
- [x] 3.2 GREEN: create `app/modules/entradas/routes.py` for protected list/detail/new/create/edit/update/delete routes; translate duplicate errors to 409.
- [x] 3.3 GREEN: add `app/templates/entradas/list.html`, `detail.html`, and `form.html` with Spanish copy and only minimal intake fields.
- [x] 3.4 GREEN: wire router/nav in `app/main.py` and `app/templates/base.html`; keep unrelated modules untouched.
- [x] 3.5 Verify slice: run `pytest`, `ruff check .`, `python -m build`, then `code-review-expert` before PR 3 promotion.

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `bb22fa1` | Schema slice #87 | 1.1-1.3 complete | `pytest` 398 passed; `ruff check .` passed; `python -m build` passed; scoped `code-review-expert` review found no P0/P1/P2 blockers; `pytest tests/e2e/ --collect-only` collected 9 explicit e2e tests despite default ignore | N/A |
| `e7331b5` | Service slice #88 | 2.1-2.4 complete | Prior service evidence preserved: `pytest tests/test_entradas.py` 12 passed; `ruff check .` passed; `python -m build` passed; earlier full `pytest` interruption was reproduced outside service slice and later resolved by migration-lock follow-up. Current promotion evidence: `pytest tests/test_entradas.py tests/test_migration.py` 137 passed, 2 skipped; `ruff check .` passed; `pytest` 409 passed, 2 skipped; `python -m build` passed; fresh review findings P2/P3 addressed in SDD artifacts and `app/core/migration/lock.py` | N/A |
| `f4d0520` | Routes/UI slice #89 | 3.1-3.5 complete; review remediation complete | RED: `pytest tests/test_entradas_routes.py` failed 8 expected route/source failures before implementation. GREEN: `pytest tests/test_entradas_routes.py` 10 passed. Fresh review found P1 broken form `action=""` and P2 missing form-action contract tests; fixed by explicit create/update form actions and route tests. Rerun evidence: `pytest tests/test_entradas_routes.py` 12 passed; `ruff check .` passed; `pytest` 423 passed; `python -m build` passed. | N/A |
