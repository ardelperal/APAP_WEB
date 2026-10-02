# 914 — Atomic create_adopcion / create_acogida

- Issue: #914 (finding A-02 of epic #911)
- Branch: `fix/914-atomic-adopcion-acogida-create`
- Worktree: `../apap-app-worktrees/914-atomic-adopcion-acogida-create`
- Base: `origin/main` @ `b15004d` (includes `TransactionalSqlExecutor.transaction()` from #913)

## Objective

Run every write of `create_adopcion` and `create_acogida` (row INSERT, `record_event`,
`close_previous_situation`, `actualizar_estado_animal`) inside one `transaction()` so a
mid-way failure persists nothing.

## TDD

- Mode: strict (user global config). Runner: `uv run pytest`; integration tests need `APAP_TEST_POSTGRES_DSN`.
- CRAP gate reads coverage only from the `test` job (no integration) — see #929.

## Tasks

- [ ] T1 — Integration RED tests (forced mid-way failure) + wrap both flows in `transaction()` + fix comments; unit coverage for the CRAP gate (route: delegated writer; trigger: 2+ non-trivial files).
- [ ] T2 — PR (`Closes #914`, `Refs #911`, `Hallazgo: A-02`), ≤400 lines or chained.

## Progress / evidence

_none yet_

## Next step

T1.
