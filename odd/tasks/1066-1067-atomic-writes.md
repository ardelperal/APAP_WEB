# #1066 + #1067 — non-atomic multi-write lifecycles (cluster 1 of the 2026-09-28 audit)

## Goal

One root, three functions, two issues: services that emit several writes through
separate `execute_sql` calls without `transaction()`, so a mid-flow failure leaves
half-written state:

- **#1066** `cesiones/service.py::create_cesion` — the cesion INSERT commits alone; a
  contrato INSERT failure left a cesion row WITHOUT its contract.
- **#1067** `adopciones/service.py::update_adopcion` — the UPDATE commits alone; an
  event-INSERT or cache-refresh failure left the adoption persisted without its
  `ADOPTION_RETURNED` event and with a stale state cache.
- **#1067** `acogidas/service.py::close_acogida` — same shape: the close UPDATE
  committed alone before `FOSTER_RETURNED` and the refresh.

## Fix

Adopt the established #913/#914 (A-02) pattern already used by `create_adopcion` and
`create_acogida`: depend on `TransactionalSqlExecutor`, wrap the whole read/write unit
in `with client.transaction() as tx:` and issue every statement through `tx`. All three
commit together or roll back together.

Out of scope, recorded deliberately:

- **#1071** (deterministic gate for multi-write functions outside `transaction()`) —
  gate machinery belongs to the governance carril the team-skills export owns; not
  implemented here.
- **#1101** (cesiones SQL → adapter, single `CesionConflictError`, 422→409) and
  **#1072** — refactor of the same subsystem tracked separately; the atomicity fix
  here does not preclude it.

## Evidence

- RED first: 6 new tests across `tests/test_cesiones.py`,
  `tests/test_adopciones_lifecycle_events.py`, `tests/test_acogidas_lifecycle_events.py`
  — the fakes gained the `_FakeBoundExecutor`/`tx_queries`/commit-rollback recording
  pattern of `tests/test_animals_chip_cascade_saga.py` plus a `fail_on` fault-injection
  hook; all 25 pre-existing tests in those files kept passing untouched.
- GREEN after the service changes; routes/actor-flow annotations widened to
  `TransactionalSqlExecutor` (same pattern as the #914 create routes).
- Full suite: 5338 passed, 21 skipped, 0 failed. mypy 0 errors (377 files), ruff
  clean, ruff-ratchet green, `check_rules`/module/route-size/docstring/import-cycle
  ratchets green.

## Status

Implemented 2026-10-03/04. PR closes #1066 and #1067.
