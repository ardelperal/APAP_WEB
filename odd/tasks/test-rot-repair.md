# #1041 — Reader-403 route tests are order/state-dependent on main

## Goal

Repo-wide reader-403 test rot closes: the conftest default SQL spy hardcodes `rol=key_user` for every auth-revalidation SELECT, and the in-process `auth_cache` keeps a per-email verdict for the worker lifetime. Together they let an earlier test (or the conftest default) prime a rocio@example.com verdict under the wrong rol, after which reader-403 tests observe 200/303/422/404 instead of the contract-pinned 403.

Issue viva: #1041 (estado: **OPEN**, label `bug`).
Referencia: #1019 (el PR que cerró la matriz de permisos de escritura y que originó el hallazgo), #144 (origen del contrato reader-403), #1033 (PR paralelo cerrado como superseded por #1040 — la presente PR reusa su patrón documentado en commit `4a9401b` de la rama `fix/1019-role-guards-audit`).

## Acceptance criteria

- [x] `tests/conftest.py::_clear_settings_cache` autouse fixture calls `auth_cache.invalidate_all()` between tests so a primed verdict for one email cannot leak into the next test.
- [x] The reader-403 contract tests that fail today (`tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403` + 6 parametrized cases; `tests/test_voluntarios_routes.py::test_create_voluntario_rejects_reader_with_403`; `tests/test_voluntarios_routes.py::test_deactivate_voluntario_rejects_reader_with_403`; `tests/test_voluntarios_role_routes.py::test_add_role_rejects_reader`; `tests/test_voluntarios_role_routes.py::test_remove_role_rejects_reader`) have a per-test SQL executor installed that answers the reval with the rol the cookie carries.
- [x] `_AuthRolSqlExecutor` lives next to the reader-403 tests that consume it (each test file owns its copy to keep the seam local; the conftest does NOT host a shared class because the no-SQL contract differs between modules).
- [x] The other reader-403 families (`tests/test_animals_routes.py`, `tests/test_entradas_routes.py`, `tests/test_materiales_routes.py`, `tests/test_foster_routes.py`, `tests/test_acogidas_routes.py`) — which already install a per-test spy with `auth_reval_rol = "reader"` — are protected by the autouse cache invalidation; verified by running the full fast scope in reverse-alphabetical order (salud first).
- [x] `pytest tests/ --no-cov --ignore=tests/e2e --ignore=tests/integration --ignore=tests/e2e_ci` exits 0 under `--randomly-seed` in `{1, 2, 3}` (twice each if flaky) and under the default `addopts` (which sets `--randomly-dont-reorganize`). 4928 passed / 19 skipped across all five runs.

## Hypothesis

Two cooperating defects.

1. **Conftest default spy hardcodes `rol=key_user`.** `tests/conftest.py::_DefaultLocalBackendSpy.execute_sql` always feeds `auth_reval_rows(query, params)` without a rol override, so every auth-revalidation SELECT returns `rol=key_user`. A reader-403 test that signs a session with `rol=reader` therefore observes the route treating the request as `key_user`; the permission check passes; the handler runs (and either returns 422/404 from form-validation/not-found paths that fire before authz, or asserts loudly when a no-SQL spy is in place).

2. **Auth-cache memoization survives across tests.** `app/core/auth_cache.InProcessAuthCache` keeps a `(email, generation) → CachedAuth` for the worker lifetime. The first test that resolves `rocio@example.com` to `rol=key_user` primes the cache; every subsequent test that signs the same email — including the reader-403 test meant to deny — observes the stale verdict via `get_cached_auth(...)`, never reaches the reval SQL, and the spy never gets a chance to correct it.

Compounding effect: even tests that already install a per-test `_NoSqlRouteClient` with `auth_reval_rol = "reader"` are vulnerable when they run AFTER a test that primed the cache via the conftest default spy. The reverse-alphabetical run (salud first) reproduces 25 failures across `test_animals_routes.py`, `test_entradas_routes.py`, `test_materiales_routes.py`, `test_foster_routes.py`, `test_acogidas_routes.py` — none of those families' tests were changed in this PR, yet they all fail because salud primed the cache first.

## Reproduce (salud, base 2e514f3 = origin/main 2e514f3)

```bash
.venv/bin/python -m pytest tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403 -v --no-cov
```

Observed:

```
FAILED tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403[POST-/terapias-form_data0]   assert 422 == 403
FAILED tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403[POST-/terapias/terapia-123/update-form_data1]  assert 422 == 403
FAILED tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403[POST-/terapias/terapia-123/delete-None]   assert 404 == 403
FAILED tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403[POST-/terapias/terapia-123/recomendaciones-form_data3]  assert 422 == 403
FAILED tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403[PATCH-/recomendaciones/rec-123-None]  assert 404 == 403
FAILED tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403[DELETE-/recomendaciones/rec-123-None]  assert 404 == 403
6 failed in 0.66s
```

First parametrized case assertion: `assert response.status_code == 403` → `assert 422 == 403`. Form validation fires BEFORE `require_permission` on POST endpoints, so the request never reaches the auth check; PATCH/DELETE on a non-existent `/recomendaciones/rec-123` returns 404 from the handler before authz.

## Reproduce (voluntarios, base 2e514f3 = origin/main 2e514f3)

```bash
.venv/bin/python -m pytest tests/test_voluntarios_routes.py tests/test_voluntarios_role_routes.py -v --no-cov
```

Observed:

```
FAILED tests/test_voluntarios_routes.py::test_create_voluntario_rejects_reader_with_403     assert 303 == 403
FAILED tests/test_voluntarios_routes.py::test_deactivate_voluntario_rejects_reader_with_403  assert 303 == 403
FAILED tests/test_voluntarios_role_routes.py::test_add_role_rejects_reader                   assert 303 == 403
FAILED tests/test_voluntarios_role_routes.py::test_remove_role_rejects_reader                assert 303 == 403
4 failed in 1.33s
```

The two `test_voluntarios_routes.py` reader-403 tests carried a dead `voluntarios_spy.auth_reval_rol = "reader"` setter — the voluntarios port spy never executes SQL, so the rol never reached the auth flow. The two `test_voluntarios_role_routes.py` reader-403 tests had no per-test SQL spy at all.

## Reproduce (cross-test pollution)

```bash
.venv/bin/python -m pytest \
  tests/test_salud_routes.py tests/test_animals_routes.py \
  tests/test_entradas_routes.py tests/test_materiales_routes.py \
  tests/test_foster_routes.py tests/test_acogidas_routes.py \
  --no-cov -q
```

Observed: 25 failures (salud's 6 + 4 animales + 3 entradas + 5 materiales + 3 foster + 4 acogidas). Alphabetical order passes 182/182 because the per-test spy families prime rocio → reader before salud runs and the cache HIT short-circuits the reval. Reverse-alphabetical fails because salud primes rocio → key_user first.

## Root-cause family

Identical shape to the closed PR #1033 / commit `4a9401b` precedent (root cause documented in the commit message of branch `fix/1019-role-guards-audit`):

> The conftest default SQL spy (`_DefaultLocalBackendSpy`) hardcodes `rol=key_user` for every auth revalidation SELECT. The two reader-403 tests in `test_voluntarios_routes.py` carried a dead `voluntarios_spy.auth_reval_rol = "reader"` setter — the voluntarios port spy never executes SQL, so the rol never reached the auth flow and the request was treated as key_user, hitting 303 (deactivate) instead of 403.
>
> `app.core.auth_cache.InProcessAuthCache` keeps a per-email verdict for the worker lifetime. Once a test (any test, any order) primes `rocio@example.com` to `rol=key_user`, later reader-403 tests would see `rol=key_user` until the worker restarts.

The current PR applies that same two-layer fix to every reader-403 family in the route suite (salud + voluntarios role_routes) that lacked it, and reuses the `_AuthRolSqlExecutor` pattern verbatim from the closed PR #1033.

## Work-unit commits

| WU | Commit | Description |
|---|---|---|
| WU-1 | `fix(tests): invalidate auth_cache between tests` | `tests/conftest.py::_clear_settings_cache` autouse also calls `auth_cache.invalidate_all()`. Foundation for every reader-403 test (closes the order-dependence on the worker-local cache). |
| WU-2 | `fix(tests): install per-test auth-reval seam for reader-403 tests` | `tests/test_salud_routes.py` — `_NoSqlRouteClient.auth_reval_rol` attribute + `route_client` fixture parameter on `test_salud_write_routes_reject_reader_with_403`. `tests/test_voluntarios_routes.py` — drop dead `self.auth_reval_rol` from `_VoluntariosPortSpy`, add `_AuthRolSqlExecutor` + `auth_rol_spy` fixture, wire the two reader-403 tests through it. `tests/test_voluntarios_role_routes.py` — add `_AuthRolSqlExecutor` + `auth_rol_spy` fixture, wire the two reader-403 tests through it. |

Se planeó consolidar las dos families (WU-2) en un único commit porque comparten el mismo patrón (`_AuthRolSqlExecutor` mirroring PR #1033) y la PR queda por debajo del presupuesto de 400 líneas. El split por familia quedaría en el cuerpo del commit como bullets.

## Verification matrix

```
$ .venv/bin/python -m pytest tests/ --no-cov \
    --ignore=tests/e2e --ignore=tests/integration --ignore=tests/e2e_ci \
    --randomly-seed=1 -q
4928 passed, 19 skipped, 1 warning in 206.95s (0:03:26)

$ .venv/bin/python -m pytest tests/ --no-cov \
    --ignore=tests/e2e --ignore=tests/integration --ignore=tests/e2e_ci \
    --randomly-seed=2 -q
4928 passed, 19 skipped, 1 warning in 234.95s (0:03:54)

$ .venv/bin/python -m pytest tests/ --no-cov \
    --ignore=tests/e2e --ignore=tests/integration --ignore=tests/e2e_ci \
    --randomly-seed=3 -q
4928 passed, 19 skipped, 1 warning in 238.05s (0:03:58)
```

Focused (touched files only, all orders):

```
$ .venv/bin/python -m pytest \
    tests/test_salud_routes.py tests/test_voluntarios_routes.py \
    tests/test_voluntarios_role_routes.py tests/test_animals_routes.py \
    tests/test_entradas_routes.py tests/test_materiales_routes.py \
    tests/test_foster_routes.py tests/test_acogidas_routes.py \
    --no-cov -q
194 passed in 7.43s   # alphabetical

$ .venv/bin/python -m pytest \
    tests/test_voluntarios_role_routes.py tests/test_voluntarios_routes.py \
    tests/test_salud_routes.py tests/test_acogidas_routes.py \
    tests/test_foster_routes.py tests/test_materiales_routes.py \
    tests/test_entradas_routes.py tests/test_animals_routes.py \
    --no-cov -q
194 passed in 7.85s   # reverse alphabetical (the rot-exposing order)
```

Focused reader-403 tests (the 29 parametrized cases from all 7 families):

```
$ .venv/bin/python -m pytest \
    tests/test_salud_routes.py::test_salud_write_routes_reject_reader_with_403 \
    tests/test_voluntarios_routes.py::test_create_voluntario_rejects_reader_with_403 \
    tests/test_voluntarios_routes.py::test_deactivate_voluntario_rejects_reader_with_403 \
    tests/test_voluntarios_role_routes.py::test_add_role_rejects_reader \
    tests/test_voluntarios_role_routes.py::test_remove_role_rejects_reader \
    tests/test_animals_routes.py::test_write_route_rejects_reader_with_403 \
    tests/test_animals_routes.py::test_change_chip_route_rejects_reader_with_403 \
    tests/test_entradas_routes.py::test_entradas_write_routes_reject_reader_with_403 \
    tests/test_materiales_routes.py::test_materiales_write_routes_reject_reader_with_403 \
    tests/test_foster_routes.py::test_foster_write_routes_reject_reader_with_403 \
    tests/test_acogidas_routes.py::test_acogidas_write_routes_reject_reader_with_403 \
    --no-cov -v
29 passed in 1.36s
```

Ratchets:

```
$ .venv/bin/python -m ruff check \
    tests/conftest.py tests/test_salud_routes.py \
    tests/test_voluntarios_routes.py tests/test_voluntarios_role_routes.py
All checks passed!

$ .venv/bin/python scripts/check_ruff_ratchet.py
check_ruff_ratchet: OK (433 finding(s), all within baseline)

$ .venv/bin/python scripts/check_mutation_sites.py
check_mutation_sites: OK

$ .venv/bin/python scripts/check_route_size.py
check_route_size: OK
```

`check_route_size.py` is `OK` because no `app/modules/**` route file is touched — the contract is already correct, the tests just didn't observe it.

## Out of scope (not touched in this PR)

- `app/modules/**` route files: the contract is correct, the tests just didn't observe it. The surface rule from the mission applies — diagnosis proved the root cause lives in the tests.
- The other 5 reader-403 families (`tests/test_animals_routes.py`, `tests/test_entradas_routes.py`, `tests/test_materiales_routes.py`, `tests/test_foster_routes.py`, `tests/test_acogidas_routes.py`): they already install a per-test `_NoSqlRouteClient` with `auth_reval_rol = "reader"` BEFORE installing the reader cookie, and the autouse cache invalidation (WU-1) protects them from prior-test pollution. Verified by running the full file set in reverse-alphabetical order (salud first, the rot-exposing order) and observing 194/194 passes.
- The mutation-sites baseline (`scripts/check_mutation_sites.py`): no movement. The reader-403 contract is observed via `auth_reval_rows` (already in the baseline); this PR adds new call sites but they mirror existing reader/role tests that the baseline already counts.
- `tests/test_rbac.py` and the `#1019` audit tests added by PR #1040: already in `origin/main`, not in this PR's surface.

## Implementation notes

- The `_AuthRolSqlExecutor` class is defined per test file (not in conftest) because the no-SQL contract differs (`tests/test_voluntarios_routes.py` raises `f"voluntarios routes MUST NOT execute SQL directly: ..."` because the routes go through the hexagonal `voluntarios_port`; `tests/test_voluntarios_role_routes.py` raises `f"voluntarios role routes MUST NOT execute SQL directly: ..."` for the same reason with a slightly different message). A shared conftest class would either weaken the message or couple unrelated test files.
- `tests/test_salud_routes.py` already had `_NoSqlRouteClient` and `route_client` fixture in place; the fix is a single attribute (`self.auth_reval_rol = "key_user"` default, flipped to `"reader"` by the reader-403 test) plus the `route_client` fixture parameter on `test_salud_write_routes_reject_reader_with_403`.
- The `close()` method is added to `_NoSqlRouteClient` (salud) and the two `_AuthRolSqlExecutor` classes (voluntarios + voluntarios role) so the executor satisfies the `LocalPostgresExecutor` Protocol — `LocalPostgresExecutor` is an abstract base that requires `close()`. `app.state.sql_executor` may be inspected by middleware that calls `close()` between requests; without the method, the autouse fixture's `app.state.__dict__.pop("sql_executor", None)` would race against middleware teardown.

## Riesgos identificados

1. **`addopts --randomly-dont-reorganize`**: conftest sets this so the existing suite's fixture order stays stable. The rot was only exposed when reverse-alphabetical ran salud first; alphabetical (the default) passed by accident because other families primed rocio → reader before salud ran. The fix removes the dependence on alphabetical luck.
2. **`auth_cache.invalidate_all()` is worker-local**: with multiple Uvicorn workers, a verdict primed in worker A does not propagate to worker B. Out of scope here (no production multi-worker deployment yet; `docs/runbooks/auth-cache-multi-worker.md` covers the multi-worker remediation playbook).
3. **Other auth-dep-using routes not yet audited**: this PR fixes every reader-403 test known to fail today. A future PR may surface additional families (e.g. tests that sign a session with `rol=developer` or `rol=ghost_role` and pin a contract); the `_AuthRolSqlExecutor` pattern is reusable for those.