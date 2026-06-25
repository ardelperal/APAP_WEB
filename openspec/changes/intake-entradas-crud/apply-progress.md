# Apply Progress: Intake Entradas CRUD

## Workload / PR Boundary

| Field | Value |
|---|---|
| Change | `intake-entradas-crud` |
| Current slice | PR 1 / schema slice #87 |
| Chain strategy | stacked-to-main toward `staging` |
| Review budget | <400 changed lines for this slice |
| Commit | `pending` |

## Completed Tasks

- [x] 1.1 RED: updated `tests/test_domain.py` to assert migration-compatible physical `entradas` columns required by `entrada.yaml`, while documenting that salida/entrega/donativo remain deferred from public CRUD.
- [x] 1.2 GREEN/REFACTOR: restored nullable mapped physical columns in `ENTRADAS_CREATE_TABLE_SQL` and clarified the physical-schema vs public-contract boundary.
- [x] 1.3 Verify slice: full default pytest, ruff, build, and scoped code-review promotion gate passed after the pytest harness fix.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_domain.py` | Unit/schema | ✅ `pytest tests/test_domain.py` baseline before corrective edit: 44 passed | ✅ Replaced legacy-field exclusion with migration-compatibility assertions; RED failed on missing `voluntario_salida_id`, `fecha_salida`, `fecha_entrega_propietario`, and `donativo_entregador` | ✅ Passed after 1.2 (`pytest tests/test_domain.py`: 46 passed) | ✅ Required physical columns + nullable/deferred assertions + FK assertion cover distinct compatibility paths | ✅ Test names/comments now distinguish physical schema compatibility from minimal public CRUD scope |
| 1.2 | `tests/test_domain.py` + `app/core/domain.py` | Unit/schema | ✅ Same domain baseline before production edit | ✅ Consumed failing 1.1 compatibility tests | ✅ Restored only mapped nullable physical columns; targeted domain tests passed | ✅ Existing FK/order/unique tests stayed green while new mapped-column checks pass | ✅ Domain comments updated to document deferred salida/entrega/donativo public scope |
| 1.3 | `tests/test_domain.py` + default suite | Verification | ✅ Prior targeted schema safety net retained; default suite now excludes e2e collection by default | N/A | ✅ `pytest` 398 passed; `ruff check .` passed; `python -m build` passed | ✅ Full default suite + explicit e2e collect-only check cover harness boundary | ✅ Scoped code review found no P0/P1/P2 blockers |

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

## Code Review Gate Preparation

- Scope reviewed: `app/core/domain.py`, `tests/test_domain.py`, SDD artifacts.
- Architecture: no routes/services/UI added; SQL remains in schema bootstrap only; mapped physical fields stay deferred from public CRUD.
- Security: no user input handling, auth, secrets, network calls, or dynamic SQL introduced.
- Reliability: natural-key uniqueness and FK assertions preserved; no physical deletes or side effects added.
- Blocking review issue found in this corrective diff: none. Formal scoped review completed for task 1.3, including schema slice and pytest harness fix.

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `pending` | Schema slice #87 corrective fix | 1.1-1.3 complete | `pytest tests/test_domain.py` baseline 44 passed; RED 3 expected failures; GREEN 46 passed; final `pytest` 398 passed; `ruff check .` passed; `python -m build` passed; scoped code review passed | N/A |

## Remaining Tasks

- [ ] 2.1-2.4 Service slice #88.
- [ ] 3.1-3.5 Routes/UI slice #89.
