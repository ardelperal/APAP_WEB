# Apply Progress: Intake Entradas CRUD

## Workload / PR Boundary

| Field | Value |
|---|---|
| Change | `intake-entradas-crud` |
| Current slice | PR 2 / service slice #88 |
| Chain strategy | stacked-to-main toward `staging` |
| Review budget | <400 changed lines for this slice |
| Commit | `pending` |

## Completed Tasks

- [x] 1.1 RED: updated `tests/test_domain.py` to assert migration-compatible physical `entradas` columns required by `entrada.yaml`, while documenting that salida/entrega/donativo remain deferred from public CRUD.
- [x] 1.2 GREEN/REFACTOR: restored nullable mapped physical columns in `ENTRADAS_CREATE_TABLE_SQL` and clarified the physical-schema vs public-contract boundary.
- [x] 1.3 Verify slice: full default pytest, ruff, build, and scoped code-review promotion gate passed after the pytest harness fix.
- [x] 2.1 RED: added `tests/test_entradas.py` covering create/list/get/update/soft-delete, required fields, active-volunteer validation, nullable volunteer, and duplicate conflict.
- [x] 2.2 GREEN: added `app/modules/entradas/__init__.py` and `app/modules/entradas/service.py` with `Entrada`, `EntradaConflictError`, SQL constants, mapping, validation, and CRUD.
- [x] 2.3 REFACTOR: kept the public service contract to minimal intake fields; volunteer eligibility checks `activo = true` only and deliberately does not enforce `RolVoluntario.INTAKE`.
- [x] 2.4 Verify slice: focused tests, migration-lock regression coverage, ruff, full default pytest, build, and fresh review-finding fixes passed for PR 2 promotion readiness.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_domain.py` | Unit/schema | ✅ `pytest tests/test_domain.py` baseline before corrective edit: 44 passed | ✅ Replaced legacy-field exclusion with migration-compatibility assertions; RED failed on missing `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, and `donativo_entregador` | ✅ Passed after 1.2 (`pytest tests/test_domain.py`: 46 passed) | ✅ Required physical columns + nullable/deferred assertions + FK assertion cover distinct compatibility paths | ✅ Test names/comments now distinguish physical schema compatibility from minimal public CRUD scope |
| 1.2 | `tests/test_domain.py` + `app/core/domain.py` | Unit/schema | ✅ Same domain baseline before production edit | ✅ Consumed failing 1.1 compatibility tests | ✅ Restored only mapped nullable physical columns; targeted domain tests passed | ✅ Existing FK/order/unique tests stayed green while new mapped-column checks pass | ✅ Domain comments updated to document deferred salida/entrega/donativo public scope |
| 1.3 | `tests/test_domain.py` + default suite | Verification | ✅ Prior targeted schema safety net retained; default suite now excludes e2e collection by default | N/A | ✅ `pytest` 398 passed; `ruff check .` passed; `python -m build` passed | ✅ Full default suite + explicit e2e collect-only check cover harness boundary | ✅ Scoped code review found no P0/P1/P2 blockers |
| 2.1 | `tests/test_entradas.py` | Unit/service | N/A (new test file) | ✅ Tests written before service module is tracked for create/list/get/update/soft-delete, required fields, active volunteer validation, and duplicate conflict | ✅ `pytest tests/test_entradas.py`: 12 passed after service implementation | ✅ Happy-path create plus null-volunteer, invalid required fields, inactive volunteer, duplicate, missing update/delete, and query-shape assertions cover distinct paths | ✅ Tests assert minimal public fields and no salida/entrega/donativo writes |
| 2.2 | `tests/test_entradas.py` + `app/modules/entradas/service.py` | Unit/service | N/A (new service module) | ✅ Consumed 2.1 RED service contract tests | ✅ `pytest tests/test_entradas.py`: 12 passed | ✅ CRUD methods exercise insert/select/update/soft-delete plus validation and conflict branches | ✅ Service owns SQL/validation/domain error mapping; routes remain untouched |
| 2.3 | `tests/test_entradas.py` + `app/modules/entradas/service.py` | Unit/service | ✅ `pytest tests/test_entradas.py`: 12 passed before final verification | ✅ Existing tests assert minimal public write columns and `activo = true` volunteer lookup with no `tipo_rol` check | ✅ `pytest tests/test_entradas.py`: 12 passed | ✅ Public-field exclusion and role-nonenforcement are asserted alongside valid and invalid volunteer paths | ✅ No deferred salida/entrega/donativo fields are written by create/update SQL |

## Verification

| Command | Result | Notes |
|---|---|---|
| `pytest tests/test_domain.py` (baseline before corrective edit) | ✅ 44 passed | Safety net before modifying existing schema/test files. |
| `pytest tests/test_domain.py` (RED corrective test) | ✅ Failed as expected | 3 failures proved the physical mapped columns and `voluntario_salida_id` FK were missing. |
| `pytest tests/test_domain.py` (GREEN corrective fix) | ✅ 46 passed | Confirms physical schema compatibility and minimal public-scope documentation. |
| `ruff check .` | ✅ Passed | No lint issues after corrective fix. |
| `python -m build` | ✅ Passed | Built sdist and wheel after corrective fix. |
| `pytest` | ✅ 398 passed | Full default suite passes after `pyproject.toml` excludes `tests/e2e/` collection by default. |
| `pytest tests/e2e/ --collect-only` | ✅ 9 collected | Confirms the default ignore does not prevent explicit e2e collection for the dedicated job/local live-server workflow. |
| Scoped `code-review-expert` review | ✅ Passed | Reviewed `app/core/domain.py`, `tests/test_domain.py`, `pyproject.toml`, and SDD artifacts. No P0/P1/P2 blockers found. |
| `pytest tests/test_entradas.py` | ✅ 12 passed | Focused PR 2 service-slice tests passed. |
| `pytest` | ❌ Interrupted | 300 passed before `KeyboardInterrupt` in pre-existing `tests/test_migration.py::TestLock::test_acquire_lock_recovers_from_stale_lock` at `app/core/migration/lock.py:214` (`lock_path.unlink()` on a temp lock). |
| `pytest tests/test_migration.py -x --full-trace` | ❌ Interrupted | Reproduced the same unrelated migration-lock interruption after 114 passed; failure is outside service slice files. |
| `ruff check .` | ✅ Passed | No lint issues after service slice files. |
| `python -m build` | ✅ Passed | Built sdist and wheel after service slice files. |
| `pytest tests/test_entradas.py tests/test_migration.py` | ✅ 137 passed, 2 skipped | Focused service slice plus migration-lock regression checks after fresh review fixes. |
| `ruff check .` | ✅ Passed | No lint issues after SDD refresh and migration-lock doc/prototype fix. |
| `pytest` | ✅ 409 passed, 2 skipped | Full default suite now completes; skipped tests require real `psutil`, which is not installed in the active venv. |
| `python -m build` | ✅ Passed | Built sdist and wheel after fresh review fixes. |

## Code Review Gate Preparation

- Scope reviewed: `app/core/domain.py`, `tests/test_domain.py`, SDD artifacts.
- Architecture: no routes/services/UI added; SQL remains in schema bootstrap only; mapped physical fields stay deferred from public CRUD.
- Security: no user input handling, auth, secrets, network calls, or dynamic SQL introduced.
- Reliability: natural-key uniqueness and FK assertions preserved; no physical deletes or side effects added.
- Blocking review issue found in this corrective diff: none. Formal scoped review completed for task 1.3, including schema slice and pytest harness fix.
- PR 2 service review scope prepared: `app/modules/entradas/service.py`, `app/modules/entradas/__init__.py`, `tests/test_entradas.py`, and SDD progress artifacts.
- Architecture: service owns all `entradas` SQL/validation/mapping/errors; routes/templates/UI were not implemented in this slice.
- Security: SQL is parameterized through `execute_sql`; no route/auth surface or secrets introduced; duplicate infrastructure errors are translated to `EntradaConflictError`.
- Reliability: deletes are soft (`activo=false`); volunteer eligibility checks `activo=true`; no role enforcement is added for this slice.
- Fresh review findings addressed: task 2.4 and service-slice verification evidence refreshed after full-suite green; migration-lock docstring now matches the Windows kernel-query fallback; Win32 ctypes calls now declare explicit prototypes for 64-bit HANDLE clarity.
- Blocking review issue found locally: none after current focused tests, full pytest, ruff, and build passed.

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `pending` | Schema slice #87 corrective fix | 1.1-1.3 complete | `pytest tests/test_domain.py` baseline 44 passed; RED 3 expected failures; GREEN 46 passed; final `pytest` 398 passed; `ruff check .` passed; `python -m build` passed; scoped code review passed | N/A |
| `pending` | Service slice #88 | 2.1-2.4 complete | Prior evidence preserved: `pytest tests/test_entradas.py` 12 passed; `ruff check .` passed; `python -m build` passed; earlier full `pytest` interruption classified outside service slice. Current evidence: `pytest tests/test_entradas.py tests/test_migration.py` 137 passed, 2 skipped; `ruff check .` passed; `pytest` 409 passed, 2 skipped; `python -m build` passed; fresh review findings addressed | N/A |

## Remaining Tasks

- [ ] 3.1-3.5 Routes/UI slice #89.
