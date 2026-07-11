## SDD Apply Progress: live-data-migration-sandbox

**Branch**: `feat/live-migration-shadow-bootstrap` (from `origin/main` @ PR #178 merge `3ce6132`)
**Work unit**: PR2 / M0 second batch — ShadowStateRepository bootstrap + private bucket ensure
**Mode**: Strict TDD (orchestrator-confirmed)
**Delivery**: stacked-to-main with maintainer-approved `size:exception`; target `main` via PR; apply phase does not push/open PR/merge
**Status**: PR1 and PR2 complete; PR3+ untouched

### Cumulative task state (across batches)

- [x] PR1 1.1 RED — `tests/migration/test_runtime_boundary.py` (14 atoms, fake pyodbc module)
- [x] PR1 1.2 GREEN — `migration/dysflow_client.py` real pyodbc implementation; `pyproject.toml` adds `pyodbc>=5.3`
- [x] PR1 1.3 REFACTOR — `legacy_reader` seam unchanged; boundary test AST-aware (docstring-ignoring)
- [x] PR1 1.4 VERIFICATION — pytest + ruff + check_rules + coverage gate all green
- [x] PR1 Rollback — revert PR1 commit + remove `pyodbc` from operator install if needed
- [x] PR2 2.1 RED — `tests/migration/test_shadow_state.py` + `tests/migration/test_bucket_invariant.py` written first; initial run failed for missing bucket/CLI/apply wiring and repository delegation
- [x] PR2 2.2 GREEN — `ShadowStateRepository.ensure_table()` is the apply bootstrap contract; `InsForgeClient.get_bucket()` / `ensure_bucket()` and `migration.bootstrap` enforce private `apap-photos`; CLI `ensure-bucket` added; apply preflight runs before lock/read
- [x] PR2 2.3 VERIFICATION — focused, migration, local-full pytest gate, ruff, check-rules, build green (real backend mutation not run)
- [x] PR2 Rollback — revert PR2 commit; optional operator rollback `DROP TABLE web_only_feature_shadow` and InsForge infrastructure `delete-bucket apap-photos`
- [ ] PR3 3.x ... PR7 7.x — UNTOUCHED (per orchestrator/user instruction)

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| PR1 1.1–1.4 | `tests/migration/test_runtime_boundary.py` | Unit | ✅ 22/22 existing migration tests | ✅ 11 errors + 2 fails for missing `_pyodbc_module` / `NotImplementedError` stub | ✅ 14 atoms pass | ✅ happy/sad/edge driver paths | ✅ AST boundary detector ignores docstrings |
| PR2 2.1 | `tests/migration/test_shadow_state.py` | Unit | ✅ `python -m pytest tests/migration/test_bootstrap.py tests/migration/test_apply.py tests/migration/test_cli.py tests/test_insforge.py -q` → 36 passed | ✅ `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → 7 failed, 1 passed; failure included `_bootstrap_shadow_state` not delegating to repository | ✅ `python -m pytest tests/migration/test_shadow_state.py -q` → 2 passed | ✅ idempotent DDL replay + repository-delegation path | ✅ `_bootstrap_shadow_state()` delegates to `ShadowStateRepository.ensure_table()` |
| PR2 2.2 | `tests/migration/test_bucket_invariant.py` | Unit + CLI harness | ✅ same 36-test safety net | ✅ same RED run: `InsForgeClient.ensure_bucket` missing, `ensure-bucket` CLI missing, apply preflight lacked bucket event; later micro-RED caught unsafe bucket names escaping as `ValueError` | ✅ `python -m pytest tests/migration/test_bucket_invariant.py -q` → 7 passed | ✅ happy existing-private, sad public-bucket abort, edge missing-bucket auto-create, idempotent replay, unsafe-name fail-before-network, CLI check-only, apply-before-lock order | ✅ extracted `migration/bootstrap.py` (`check_private_bucket`, `ensure_private_bucket`, `bootstrap_m0_infrastructure`) |
| PR2 2.3 | full local gate | Unit/integration mix | ✅ focused + migration suite green before full gate | N/A — verification task | ✅ local full gate with documented no-real-backend deselect green | ✅ `python -m pytest -W error::DeprecationWarning` attempted full run and exposed pre-existing missing `APAP_E2E_BASE_URL`; no product-test failure in PR2 code | ✅ no code refactor after full gate; ruff/check-rules/build green |

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → `9 passed in 0.15s` (latest focused run after implementation); also `test_shadow_state.py -q` → `2 passed`, `test_bucket_invariant.py -q` → `7 passed` |
| Runtime harness command/scenario and exact result | `python -m pytest tests/migration/test_bucket_invariant.py -q` → `7 passed in 0.15s`; exercises operator-facing `apap-migrate ensure-bucket` through `migration.cli.main(...)` with injected clients and verifies apply preflight order before lock/read. Real InsForge mutation: **not run** by design; operator checkpoint documented in `docs/runbooks/live-migration-m0-bootstrap.md`. |
| Rollback boundary | Revert the PR2 commit to remove `migration/bootstrap.py`, `tests/migration/test_shadow_state.py`, `tests/migration/test_bucket_invariant.py`, bucket methods in `app/core/insforge.py`, CLI/apply wiring, FakeInsForge bucket fixtures, PR2 runbook, and tasks/apply-progress marks. Operator rollback is separable: `DROP TABLE web_only_feature_shadow`; InsForge infrastructure `delete-bucket apap-photos`. |

### Verification Summary

- **RED**: `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → 7 failed, 1 passed (expected RED: missing `ensure_bucket`, missing `ensure-bucket` CLI, missing apply bucket preflight, direct DDL instead of repository contract).
- **Focused GREEN**: `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → 9 passed.
- **Focused split**: `python -m pytest tests/migration/test_shadow_state.py -q` → 2 passed; `python -m pytest tests/migration/test_bucket_invariant.py -q` → 7 passed.
- **Migration suite**: `python -m pytest tests/migration -q` → 45 passed.
- **Full pytest attempt**: `python -m pytest -W error::DeprecationWarning` → 2108 passed, 1 skipped, 1 failed due pre-existing `tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner` requiring `APAP_E2E_BASE_URL` (real PostgreSQL row-locking endpoint). This is the documented no-real-backend exception.
- **Local full gate without real/shared backend dependency**: `python -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py` → 2108 passed, 1 skipped, 2 deselected.
- **Ruff**: `ruff check .` → All checks passed.
- **Project rule gate**: `python scripts/check_rules.py app --exclude scripts/check_rules.py --exclude tests/_rule_helpers/fixtures --exclude tests/test_migration_004.py` → exit 0, no output.
- **Build**: `python -m build` → Successfully built `apap_web-0.1.0.tar.gz` and `apap_web-0.1.0-py3-none-any.whl`.

### Infrastructure Mutation Status

- No real InsForge bucket/table mutation was performed during apply.
- InsForge docs were read via `fetch-sdk-docs(storage, rest-api)` to verify the current bucket management surface.
- Tests use `httpx.MockTransport` or in-memory `FakeInsForge` only.
- Operator work-unit checkpoint is documented in `docs/runbooks/live-migration-m0-bootstrap.md` and remains outside ordinary tests.

### Files Changed (PR2)

| File | Action | What changed |
|---|---|---|
| `app/core/insforge.py` | Modified | Added private-only bucket read/ensure helpers using bucket-list/create admin surface; fails closed on public/unknown visibility. |
| `migration/bootstrap.py` | Added | Centralized M0 bootstrap helpers for shadow table + private `apap-photos` bucket. |
| `migration/apply.py` | Modified | Apply preflight delegates shadow table to repository contract and runs M0 bootstrap before lock/read; no Dysflow MCP runtime language remains in touched comments. |
| `migration/cli.py` | Modified | Added `ensure-bucket` operator checkpoint with `--check-only`; apply converts infrastructure bootstrap failures to exit 5. |
| `tests/migration/conftest.py` | Modified | Extended `FakeInsForge` with private bucket fake methods. |
| `tests/migration/test_shadow_state.py` | Added | RED/GREEN atoms for repository contract + idempotent DDL replay. |
| `tests/migration/test_bucket_invariant.py` | Added | RED/GREEN atoms for private bucket invariant, public abort, missing create, idempotency, CLI harness, pre-lock order. |
| `docs/runbooks/live-migration-m0-bootstrap.md` | Added | Operator runbook for the PR2 infra checkpoint, verification, and rollback. |
| `openspec/changes/live-data-migration-sandbox/tasks.md` | Modified | Marked only PR2 tasks complete. |
| `openspec/changes/live-data-migration-sandbox/apply-progress.md` | Added | Cumulative PR1+PR2 apply progress with TDD/work-unit evidence. |

### Deviations from design/tasks

- The task text referenced a candidate `GET /api/storage/buckets/{bucket}` shape. Current InsForge REST docs fetched during PR2 document `GET /api/storage/buckets` for bucket listing plus `POST /api/storage/buckets` for create. PR2 therefore uses the verified list/create admin surface and fails closed when visibility cannot be verified. This stays inside PR2's bucket-management scope and does **not** implement PR4 upload/download media methods.
- No live InsForge mutation was executed during apply, per the code-vs-real-infrastructure separation requested by the user.

### Issues found

- `python -m pytest -W error::DeprecationWarning` still collects `tests/test_voluntarios_concurrent.py`, whose first atom hard-fails without `APAP_E2E_BASE_URL`. This is pre-existing and documented in `docs/proceso.md` as requiring deselect/no shared backend for local runs.
- InsForge bucket-list REST docs may return bucket names without visibility in some deployments. PR2 code deliberately fails closed (`bucket_visibility_unknown`) and tells the operator to verify via the InsForge infrastructure tool rather than assuming private state.

### Next batch

PR2 complete. PR3+ are untouched. Next recommended phase: `sdd-verify` for PR2, then continue with PR3 only when explicitly assigned.
