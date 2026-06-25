# Verification Report: Intake Entradas CRUD

**Change**: `intake-entradas-crud`  
**Version**: 2026-06-25  
**Mode**: Strict TDD  
**Branch**: `staging`  
**Verifier**: `sdd-verify-and`  
**Verdict**: PASS WITH WARNINGS

## Executive Summary

The complete `intake-entradas-crud` SDD change satisfies the proposal, spec, design, and task contract end-to-end. Schema, service, route/UI, and migration-lock follow-up commits are reachable from `staging`; source inspection confirms the layer boundaries and minimal public intake scope; focused tests, full pytest, ruff, and build all pass.

Warnings are non-blocking: the active environment does not have `psutil`, so two optional migration-lock tests are skipped; an informational targeted coverage run failed the global 80% aggregate threshold because it included already-existing low-coverage modules (`app.main`, `app.core.migration.lock`), but all tests in that coverage run passed and strict TDD treats coverage metrics as informational.

## Completeness

| Metric | Value |
|---|---:|
| Tasks total | 10 |
| Tasks complete | 10 |
| Tasks incomplete | 0 |
| Spec requirements | 3 |
| Spec scenarios | 8 |
| Compliant scenarios | 8 |

## Workspace State

| Check | Result | Evidence |
|---|---|---|
| Initial uncommitted changes | ✅ Clean | `git status --short` returned no entries before verification commands. |
| Final uncommitted changes | ✅ Expected artifact only | `git status --short` was clean after verification commands; after persistence it shows only `?? openspec/changes/intake-entradas-crud/verify-report.md`, the intended verify artifact. |
| Commit reachability | ✅ Passed | `git merge-base --is-ancestor` returned `0` for `bb22fa1`, `17cb078`, `1105f57`, `e7331b5`, and `f4d0520` against `staging`. |

## Implementation Commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `bb22fa1` | Schema slice #87 | 1.1-1.3 | Current focused verification includes `tests/test_domain.py`; prior slice evidence records RED/GREEN domain tests, full pytest, ruff, build, and review gate. | N/A |
| `17cb078` | SDD context refresh | Traceability/supporting artifacts | Commit is reachable from `staging`; included in SDD context chain for the service slice. | N/A |
| `1105f57` | Migration-lock Windows liveness follow-up | Supports service-slice verification recovery | Current focused verification includes `tests/test_migration.py`; no Windows `os.kill(pid, 0)` liveness probe remains in the fallback path. | N/A |
| `e7331b5` | Service slice #88 | 2.1-2.4 | Current focused verification includes `tests/test_entradas.py`; service source owns SQL/validation/mapping/errors and exposes minimal public fields. | N/A |
| `f4d0520` | Routes/UI slice #89 | 3.1-3.5 | Current focused verification includes `tests/test_entradas_routes.py`; full pytest, ruff, and build pass. Prior P1 form-action review finding is fixed by explicit form actions. | N/A |

## Build & Test Execution

| Command | Result | Evidence |
|---|---|---|
| `C:\00repos\codigo\APAP_WEB\.venv\Scripts\python.exe -m pytest tests/test_domain.py tests/test_entradas.py tests/test_entradas_routes.py tests/test_migration.py` | ✅ Passed | 195 passed, 2 skipped in 1.13s. Skips require real `psutil`, absent in active venv. |
| `C:\00repos\codigo\APAP_WEB\.venv\Scripts\python.exe -m pytest` | ✅ Passed | 421 passed, 2 skipped in 2.29s. |
| `C:\00repos\codigo\APAP_WEB\.venv\Scripts\python.exe -m ruff check .` | ✅ Passed | `All checks passed!` |
| `C:\00repos\codigo\APAP_WEB\.venv\Scripts\python.exe -m build` | ✅ Passed | Successfully built `apap_web-0.1.0.tar.gz` and `apap_web-0.1.0-py3-none-any.whl`. |
| `C:\00repos\codigo\APAP_WEB\.venv\Scripts\python.exe -m pytest tests/test_domain.py tests/test_entradas.py tests/test_entradas_routes.py tests/test_migration.py --cov=app.core.domain --cov=app.modules.entradas --cov=app.core.migration.lock --cov=app.main --cov-report=term-missing` | ⚠️ Tests passed, coverage threshold failed | 195 passed, 2 skipped; coverage command exited non-zero because aggregate coverage was 70.45% below configured 80% fail-under. Changed intake modules: `domain.py` 100%, `routes.py` 81%, `service.py` 89%. |

## Spec Compliance Matrix

| Requirement | Scenario | Covering test/evidence | Result |
|---|---|---|---|
| Migration-compatible `entradas` physical schema with minimal public CRUD scope | Domain schema keeps mapped physical columns | `tests/test_domain.py::test_entradas_create_table_sql_keeps_migration_mapped_physical_columns`; `test_entradas_migration_mapped_columns_are_nullable_and_deferred`; FK/natural-key tests | ✅ COMPLIANT |
| Migration-compatible `entradas` physical schema with minimal public CRUD scope | Duplicate intake is rejected by natural key | `tests/test_domain.py::test_entradas_create_table_sql_unique_natural_key_constraint`; `tests/test_entradas.py::test_create_entrada_rejects_duplicate_natural_key_as_conflict` | ✅ COMPLIANT |
| Service-owned intake entry CRUD | Create entry validates animal and volunteer references | `tests/test_entradas.py::test_create_entrada_validates_references_inserts_minimal_public_fields` | ✅ COMPLIANT |
| Service-owned intake entry CRUD | Invalid volunteer FK is rejected before insert | `tests/test_entradas.py::test_create_entrada_rejects_inactive_volunteer_before_insert` | ✅ COMPLIANT |
| Service-owned intake entry CRUD | Route layer contains no direct SQL | `tests/test_entradas_routes.py::_NoSqlRouteClient`; `test_entradas_route_source_contains_no_direct_execute_sql`; `rg -n "execute_sql\(" app/modules/entradas/routes.py` returned no matches | ✅ COMPLIANT |
| Protected intake entry CRUD UI | Authorized user creates an entry through the UI | `tests/test_entradas_routes.py::test_create_entrada_delegates_to_service_and_redirects_to_detail`; `test_create_form_posts_to_create_route` | ✅ COMPLIANT |
| Protected intake entry CRUD UI | Unauthorized user is redirected | `tests/test_entradas_routes.py::test_entradas_routes_require_authorized_user` | ✅ COMPLIANT |
| Protected intake entry CRUD UI | Delete is soft-delete only | `tests/test_entradas.py::test_delete_entrada_soft_deletes_without_physical_delete`; `tests/test_entradas_routes.py::test_delete_is_soft_delete_service_delegation_and_redirect` | ✅ COMPLIANT |

**Compliance summary**: 8/8 scenarios compliant.

## Correctness (Static Evidence)

| Requirement | Status | Evidence |
|---|---|---|
| Physical schema compatibility | ✅ Implemented | `app/core/domain.py` keeps `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, `donativo_entregador`, FKs, timestamps, `activo`, and natural-key uniqueness. |
| Minimal public CRUD scope | ✅ Implemented | `app/modules/entradas/service.py` `_WRITE_COLUMNS` excludes salida/entrega/donativo fields; templates expose only animal, volunteer, date, origin, motive, and notes. |
| Service owns SQL and validation | ✅ Implemented | SQL calls appear in `app/modules/entradas/service.py`; `app/modules/entradas/routes.py` has no direct `.execute_sql(` call. |
| Duplicate conflict translation | ✅ Implemented | `EntradaConflictError` maps duplicate/unique 409 errors; route create/update handlers render HTTP 409 HTML. |
| Active-volunteer validation | ✅ Implemented | `_CHECK_ACTIVE_VOLUNTEER_SQL` checks `activo = true` and does not enforce `tipo_rol`, matching design. |
| Protected routes/UI | ✅ Implemented | Router is included in `app/main.py`; `/entradas` nav is present; all route handlers use `require_authorized_user` and `return_early_if_response`. |
| Soft delete only | ✅ Implemented | `delete_entrada` executes `UPDATE entradas SET activo = false`; no physical `DELETE FROM` in service test evidence. |

## Coherence (Design)

| Design decision | Followed? | Notes |
|---|---|---|
| Expose only minimal intake fields | ✅ Yes | Service dataclass, write columns, and templates stay within approved public scope. |
| Keep physical schema compatibility columns | ✅ Yes | `ENTRADAS_CREATE_TABLE_SQL` preserves mapped nullable legacy columns. |
| All `entradas` SQL in service layer | ✅ Yes | Routes delegate to `entradas_service`; no route direct SQL. |
| Service-owned validation/errors | ✅ Yes | Required fields, FK checks, duplicate mapping, and soft-delete behavior live in service. |
| Volunteer eligibility is `activo=true` only | ✅ Yes | No `RolVoluntario.INTAKE` / `tipo_rol` enforcement added. |
| Force chained slices under review budget | ✅ Yes | Commits implement schema, service, and routes/UI as separate work units with review gates. |

## Strict TDD Compliance

| Check | Result | Details |
|---|---|---|
| TDD Evidence reported | ✅ | `apply-progress.md` contains a TDD Cycle Evidence table for tasks 1.1-3.5. |
| All tasks have tests | ✅ | 10/10 tasks reference concrete tests or verification commands. |
| RED confirmed (tests exist) | ✅ | `tests/test_domain.py`, `tests/test_entradas.py`, and `tests/test_entradas_routes.py` exist and are executed. |
| GREEN confirmed (tests pass) | ✅ | Focused verification passed: 195 passed, 2 skipped. Full pytest passed: 421 passed, 2 skipped. |
| Triangulation adequate | ✅ | Schema, service, and route layers each cover success, validation/error, duplicate/conflict, auth, and delete paths where applicable. |
| Safety net for modified files | ✅ | Existing schema/migration/app suites were rerun; new service/route files have focused tests. |

**TDD Compliance**: 6/6 checks passed.

## Test Layer Distribution

| Layer | Tests | Files | Tools |
|---|---:|---:|---|
| Unit/schema/service | 58 focused change tests | 2 | pytest + httpx MockTransport |
| Integration/route | 12 focused route tests | 1 | pytest + FastAPI/HTTPX AsyncClient + dependency overrides |
| Migration regression | 127 relevant migration tests | 1 | pytest |
| E2E | 0 in this change | 0 | Not required for this SDD slice |
| **Total focused verification** | **197 collected** | **4** | **pytest** |

## Changed File Coverage

| File | Line % | Branch % | Uncovered Lines | Rating |
|---|---:|---:|---|---|
| `app/core/domain.py` | 100% | N/A | — | ✅ Excellent |
| `app/modules/entradas/service.py` | 89% | Partial | 162, 186, 213-216 | ⚠️ Acceptable |
| `app/modules/entradas/routes.py` | 81% | Partial | 29, 99, 116, 138-139, 160, 164, 179, 206, 220, 239, 251 | ⚠️ Acceptable |
| `app/core/migration/lock.py` | 76% | Partial | Windows/error fallback lines listed by coverage | ⚠️ Low/informational |
| `app/main.py` | 38% | Partial | Existing app routes not exercised by the focused coverage command | ⚠️ Low/informational |

**Coverage note**: Coverage is informational in strict TDD verify. The targeted coverage command failed the configured global fail-under because it included broader existing modules, not because tests failed.

## Assertion Quality

**Assertion quality**: ✅ All inspected assertions verify real behavior. No tautologies, ghost loops, assertion-without-production-code, or smoke-only route tests were found in `tests/test_domain.py`, `tests/test_entradas.py`, or `tests/test_entradas_routes.py`. Source-existence/read assertions in `test_entradas_route_source_contains_no_direct_execute_sql` are paired with the concrete no-direct-SQL contract and are not treated as trivial.

## Code Review / Frontend Review Evidence

| Area | Result | Evidence |
|---|---|---|
| Service slice review | ✅ Passed | Prior final review approved with no P0/P1/P2/P3 findings. |
| Routes/UI review | ✅ Passed | Prior final review approved after P1 form-action fix and P2 form-action test fix. |
| Frontend/UI coherence | ✅ Passed | Templates follow existing APAP Spanish UI patterns and expose only minimal intake fields; explicit form actions prevent the previous broken submission path. |
| Security/reliability scan | ✅ Passed | Auth guard used on all route handlers; no secrets or dynamic SQL introduced; routes delegate writes to service. |

## Issues Found

**CRITICAL**: None.

**WARNING**:
- Optional `psutil` is absent in the active venv, so two migration-lock tests are skipped. This is already represented in pytest output and does not affect the `intake-entradas-crud` CRUD contract.
- Informational coverage command failed the configured aggregate 80% fail-under (`70.45%`) because broader existing modules were included. All tests in that run passed; intake changed modules were 81-100% line-covered.

**SUGGESTION**:
- Tasks and apply-progress now record the routes/UI commit as `f4d0520`.

## Verdict

PASS WITH WARNINGS. The SDD change is implementation-complete and runtime-verified against proposal, spec, design, and tasks. It is ready for the archive phase.
