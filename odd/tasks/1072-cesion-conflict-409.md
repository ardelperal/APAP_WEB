# #1072 — a second cesión for the same entrada answers 422 instead of 409

## Goal

A second `POST /cesiones` for an entrada that already has one must answer **409**
with the conflict message, not **422** with the generic "No se pudo guardar la
cesion" fallback.

Root cause: the conflict exception is defined twice.

- `app/modules/cesiones/domain/cesion.py` — `CesionConflictError` (the one the
  route imports and catches at `routes.py:51` / `:201`).
- `app/modules/cesiones/service.py:65` — a second, unrelated
  `CesionConflictError` (the one the real code path actually raises at
  `service.py:380`).

Production path: `routes.py` → `application/create_cesion.py` → `CesionesPort` →
`CesionesLocalBackendAdapter` → `service.create_cesion`. The adapter resolves the
service module through `sys.modules`, so the exception that reaches the route is
`service.CesionConflictError`. `except CesionConflictError` does not match it, the
error falls into `except ValueError` (`service.CesionConflictError` subclasses
`ValueError`) and the route renders 422.

The existing route test (`tests/test_cesiones_routes.py:297-324`) never catches
this because its mocked port raises the *domain* class, not the one the real
path raises.

## Fix

`service.py` imports and re-exports the domain `CesionConflictError` instead of
redefining it, so one class travels the whole path. `service.CesionConflictError`
stays importable (backwards compatible) and becomes the very same object.

## Out of scope (recorded deliberately)

- **#1101** — move the cesiones SQL into the adapter, drop the `sys.modules`
  lookup, unify `service.Cesion` / `service.Contrato` with the domain types.
- **#1066** — atomicity of `create_cesion` (already fixed; `service.py` now wraps
  both INSERTs in `transaction()`).
- **#1100** — the shared `_FakeSqlExecutor` double; this task imports the
  canonical one from `tests/test_cesiones.py` instead of adding a 24th copy.

## Test decision (apap-testing-strategy)

`route_integration` in-process, per §3 / Gate-A: the bug is an **error-mapping**
bug in the HTTP contract, not a database-semantics bug. Gate-B (UNIQUE constraint
against real Postgres) is already covered by
`tests/integration/test_cesiones_queries_integration.py::test_cesion_unique_constraint_fires_on_duplicate_entrada`.
The new test wires the **real** `CesionesLocalBackendAdapter` + **real**
`service.create_cesion` and fakes only the `SqlExecutor`, which is exactly the
distance the old mock skipped.

## Tasks

| # | Task | Evidence |
|---|---|---|
| 1 | Worktree `1072-cesion-conflict-409`, branch `fix/1072-cesion-conflict-409` off `origin/main` | `git worktree list` |
| 2 | RED test `test_create_duplicate_through_real_adapter_translates_to_409` in `tests/test_cesiones_routes.py` | observed `assert 422 == 409` on `origin/main` |
| 3 | `service.py` re-exports the domain `CesionConflictError` | `issubclass(service.CesionConflictError, domain.CesionConflictError) is True` |
| 4 | Gates: `pytest -k cesion`, `mypy`, `ruff check .`, `check_rules.py`, `check_module_size.py`, `check_route_size.py` | all green (see below) |
| 5 | Commit, push, PR referencing #1072 | commit `783cf91`, PR #1287 |

## Evidence

```
$ uv run --frozen python -m pytest tests/test_cesiones_routes.py -k duplicate_through_real_adapter -q
origin/main : assert 422 == 409
branch      : 2 passed

$ uv run --frozen python -m pytest tests -k cesion -q
96 passed, 5353 deselected

$ uv run --frozen python -m pytest -q
1 failed, 5427 passed, 21 skipped
  the only failure (tests/test_repository_secrets_ignore.py) is workstation-local:
  an untracked `.atl/.gitignore` containing `*` re-ignores the directory
  (`git check-ignore -v --no-index .atl/skill-registry.md` -> `.atl/.gitignore:1:*`).
  This diff touches neither `.gitignore` nor `.atl/`.

$ uv run --frozen python -m mypy
Success: no issues found in 383 source files

$ uv run --frozen ruff check .
All checks passed!

$ uv run --frozen python scripts/check_rule[REDACTED] 14 baselined notes, none new)
$ uv run --frozen python scripts/check_[REDACTED] baselined, none new)
$ uv run --frozen python scripts/check_module_size.py          -> OK
$ uv run --frozen python scripts/check_route_size.py           -> OK
$ uv run --frozen python scripts/check_import_cycles.py        -> 0 (5 baselined, none new)
$ uv run --frozen python scripts/check_slice_completeness.py   -> OK
$ uv run --frozen python scripts/check_ruff_ratchet.py         -> 0 (438 findings, within baseline)
$ uv run --frozen python scripts/check_docstring_coverage.py   -> 87.53% (floor 73.0%)
```

Independent verification (`gentle-ai-verify`, read-only over the 12-command battery) found
and the branch fixed two self-inflicted reds: the ruff `I001` import block, and the
shrink-only mutation-site ratchet (`362 -> 361`).

ASSESS over the committed range (`origin/main..HEAD`, 4 paths / 160 lines): risk `medium`,
`reviewDue: false`; RDD is off for this clone, so the writer self-verification stands.
An independent verifier ran anyway.

## Acceptance criteria (from the issue)

- [ ] A second cesión for the same entrada answers 409 with the conflict message.
- [ ] `service.py` no longer defines its own `CesionConflictError`.
- [ ] The new route test fails (RED) on current `main` and passes after the fix.
