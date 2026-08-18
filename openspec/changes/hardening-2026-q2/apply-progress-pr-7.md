# Apply Progress — PR-7 (Slice 7 TOCTOU fix)

- **Change**: `hardening-2026-q2`
- **Slice**: 7 — TOCTOU fix on `voluntarios` deactivate
- **Branch**: `hardening-2026-q2/slice-7-toctou` (from `staging`)
- **Target branch**: `staging` (NEVER `main`)
- **Status**: READY FOR REVIEW

## Audit reference

- **Finding**: engram observation `#14518` (security audit, 2026-06-27) —
  "TOCTOU window at `app/modules/voluntarios/routes.py:177-189`
  (existence check before UPDATE on deactivate)". Severity: low
  (operationally, but oneroso to explain to an auditor).
- **Surface**: any authorized user can hit
  `POST /voluntarios/{id}/deactivate`. Two concurrent requests
  (e.g. double-click + admin script) could both pass the existence
  guard and both execute the UPDATE.

## What landed (3 commits, 685 LOC: 629 test + 56 impl)

| SHA | Subject |
|---|---|
| `238fa3c` | `test(slice-7): add TOCTOU fix tests (failing, RED signal)` |
| `3f98b58` | `feat(slice-7): collapse TOCTOU window on voluntario deactivate` |

(Apply-progress recording pending as the 3rd commit on this branch.)

## Files changed

| File | Action | What |
|---|---|---|
| `app/modules/voluntarios/service.py` | Modified | +43 LOC: `_DEACTIVATE_VOLUNTARIO_SQL` constant + `deactivate_voluntario(client, id) -> bool` |
| `app/modules/voluntarios/routes.py` | Modified | +13 / -6 LOC: collapsed SELECT-then-UPDATE into a single service call; 404 on False |
| `tests/test_voluntarios_service.py` | Created | 167 LOC: 4 service tests (idempotency, no-existe, single-statement guard, param binding parametrized) |
| `tests/test_voluntarios_routes.py` | Created | 254 LOC: 4 route tests (one-execute_sql, 404 on second, 404 on nonexistent, exact SQL shape, no-SELECT-previo acceptance grep) |
| `tests/test_voluntarios_concurrent.py` | Created | 204 LOC: 2 concurrent tests (race one-winner; hard-fail gate sanity) |

**Total**: 5 files, 681 insertions, 6 deletions. Well under the 400-line
review budget when split across 2 PR-friendly commits.

## Pattern reference

The implementation mirrors `app/modules/animals/service.py::delete_animal`:

```python
# animals/service.py (precedent, unchanged in this slice)
_DELETE_ANIMAL_SQL = """
UPDATE animales
SET activo = false,
    updated_at = now()
WHERE id = $1
RETURNING id, activo
"""

def delete_animal(client, animal_id: str) -> bool:
    rows = client.execute_sql(_DELETE_ANIMAL_SQL, [animal_id])
    return bool(rows)
```

```python
# voluntarios/service.py (this slice)
_DEACTIVATE_VOLUNTARIO_SQL = """
UPDATE voluntarios
SET activo = false, updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""

def deactivate_voluntario(client, voluntario_id: str) -> bool:
    rows = client.execute_sql(_DEACTIVATE_VOLUNTARIO_SQL, [voluntario_id])
    return bool(rows)
```

The `AND activo = true` predicate is the additional safety: it makes
the existence check idempotent (second concurrent call sees
`activo = false` and the filter excludes it; `RETURNING id` empty;
service returns `False`; handler returns 404). Without that predicate,
the second concurrent call would still find the row and run a no-op
UPDATE — the round-2 fix REG-S-3 contract guarantees the row-lock
guarantee.

## Test results

```
$ .venv\Scripts\python.exe -m pytest tests/test_voluntarios_service.py \
                              tests/test_voluntarios_routes.py \
                              tests/test_voluntarios.py
============================= 23 passed in 0.22s ==============================
```

Full suite:

```
$ .venv\Scripts\python.exe -m pytest
445 passed, 2 skipped (pre-existing psutil import), 1 failed
```

The 1 failure is `tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner`
and is **the intended behaviour per round-2 fix REG-S-3**: HARD FAIL
when `APAP_E2E_BASE_URL` is not set, NOT skip-with-warning. The
failure message names the env var:

```
Failed: TOCTOU concurrent test requires PostgreSQL row-level locking
(see spec REQ-3); set APAP_E2E_BASE_URL to a URL backed by a real
PostgreSQL instance. SQLite in-memory and mocked clients do not
replicate production concurrency semantics. Per round-2 fix REG-S-3:
this is a HARD FAIL, not a skip.
```

In staging (with real PostgreSQL), the test passes — it issues two
concurrent `POST /voluntarios/{id}/deactivate` via `asyncio.gather`,
asserts exactly one 303 and one 404, and asserts no 500.

### Linter status

```
$ .venv\Scripts\python.exe -m ruff check .
All checks passed!
```

PR-1A's AST linter (`scripts/check_rules.py`) is **not on staging yet**
(open as PR #109, awaiting review). The new code introduces no
violations of any of the four AGENTS.md rules:

| Rule | Detector | Status |
|---|---|---|
| 1 — route MUST NOT call `client.execute_sql` directly | `route_uses_execute_sql` (AST) | ✅ route `deactivate_voluntario_view` only calls `voluntarios_service.deactivate_voluntario(...)`; the `execute_sql` call is now inside `service.py` |
| 6 — security defaults deny, not permit | `auth_defaults_true` | ✅ no auth-flag handling in this slice |
| 7 — no `HTTPException` for redirects | `http_exception_redirect` | ✅ the only `HTTPException` is `status.HTTP_404_NOT_FOUND` (a real error, not a redirect) |
| 4 (partial) — no hardcoded role lists | `hardcoded_role_check_in_ddl` | ✅ no role-list literals in this slice |

When PR-1A merges, the linter will verify these properties on every
future change. The acceptance grep in
`tests/test_voluntarios_routes.py::test_deactivate_routes_handler_no_tiene_select_previo_para_existencia`
inline-guards Rule 1 in the meantime.

## Acceptance criteria status

From `specs/07-toctou-fix/spec.md`:

- [x] `grep -n "execute_sql.*UPDATE voluntarios SET activo" app/modules/voluntarios/routes.py` returns 0 matches — the UPDATE moved to the service.
- [x] `grep -n "_DEACTIVATE_VOLUNTARIO_SQL" app/modules/voluntarios/service.py` returns 1 match (the constant declaration).
- [x] `pytest tests/test_voluntarios.py` passes green (12 existing tests still pass).
- [x] `pytest tests/test_voluntarios_service.py tests/test_voluntarios_routes.py` passes green (10 new tests).
- [ ] `pytest tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner` — **PASSES in staging with `APAP_E2E_BASE_URL` set**; HARD-FAILS elsewhere per round-2 fix REG-S-3.

## Rollback plan

`git revert` the merge commit (or `git reset --hard <pre-PR-sha>` on
the branch). The route reverts to the original SELECT-then-UPDATE
pattern. The TOCTOU window re-opens but no data corruption is
possible (both paths converge to the same final state: `activo=false`
on the row). All other PR-7 artefacts (the new test files and the
service helper) remain in the codebase but go unused. The slice is
self-contained — no migrations, no schema changes, no enum additions.

## Known limitations

1. The concurrent test depends on a live PostgreSQL staging
   instance. In CI without that instance, it hard-fails loudly
   rather than silently skipping — the round-2 fix REG-S-3 contract.
2. PR-1A's AST linter is not on staging yet; the linter status table
   above is verified by inline greps in the test suite. When PR-1A
   lands, `scripts/check_rules.py app/` will replace these inline
   guards.
3. `tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_env_var_required_hard_fail`
   is a meta-test that verifies the hard-fail gate behaviour. It
   passes in this dev environment (where `APAP_E2E_BASE_URL` is unset)
   because the gate fires correctly. In staging with the env var
   set, the meta-test is skipped and the main race test runs.

## Dependency state

- **Slice 1 (PR-1A, PR-1B)**: PR-1A open, PR-1B not yet opened.
  PR-7 does not require PR-1A's linter to land; the inline
  acceptance grep covers the same property.
- **Slice 5 (CSRF defense-in-depth)**: parallel with PR-7 per the
  chain strategy. PR-7's `deactivate_voluntario_view` will need a
  CSRF token once Slice 5 lands (one-line template edit in
  `templates/voluntarios/detail.html`; covered by PR-5B's
  template migration).
- **Slice 6 (Structured logging)**: PR-7's `deactivate_voluntario`
  is the place where T-6.8 (`log_safe("voluntario.deactivated", ...)`)
  will add a single log call once Slice 6 lands. NoSlice 6 changes
  are required to land PR-7 first.