## SDD Apply Progress: live-data-migration-sandbox

**Branch**: `feat/live-migration-shadow-bootstrap` (from `origin/main` @ PR #178 merge `3ce6132`)
**Work units**: PR2 / M0 second batch — ShadowStateRepository bootstrap + private bucket ensure, then a narrow PR2 verification remediation
**Mode**: Strict TDD (orchestrator-confirmed)
**Delivery**: stacked-to-main with maintainer-approved `size:exception`; target `main` via PR; apply phase does not push/open PR/merge
**Status**: PR1, PR2, and PR2 verification remediation complete; PR3+ untouched

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
- [x] PR2-verify R1 RED — visibility-missing/null fail-closed atom + bootstrap-failure-does-not-acquire-lock-or-read-legacy atom
- [x] PR2-verify R2 GREEN — only the test atoms needed minimal refactor; no production change required
- [x] PR2-verify R3 VERIFICATION — focused, migration, local full gate, ruff, check-rules, build green
- [x] PR2-verify R4 RUNBOOK — destructive rollback safety: `DROP TABLE` and `delete-bucket` documented as destructive of divergence/audit history and uploaded photos respectively, with verified backup/export and empty/no-data proof; non-destructive disable preferred; `TRUNCATE` explicitly NOT recommended
- [x] PR2-verify Rollback — revert PR2-verify commit; the runbook returns to the prior shape and the new test atoms are removed
- [ ] PR3 3.x ... PR7 7.x — UNTOUCHED (per orchestrator/user instruction)

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| PR1 1.1–1.4 | `tests/migration/test_runtime_boundary.py` | Unit | ✅ 22/22 existing migration tests | ✅ 11 errors + 2 fails for missing `_pyodbc_module` / `NotImplementedError` stub | ✅ 14 atoms pass | ✅ happy/sad/edge driver paths | ✅ AST boundary detector ignores docstrings |
| PR2 2.1 | `tests/migration/test_shadow_state.py` | Unit | ✅ `python -m pytest tests/migration/test_bootstrap.py tests/migration/test_apply.py tests/migration/test_cli.py tests/test_insforge.py -q` → 36 passed | ✅ `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → 7 failed, 1 passed; failure included `_bootstrap_shadow_state` not delegating to repository | ✅ `python -m pytest tests/migration/test_shadow_state.py -q` → 2 passed | ✅ idempotent DDL replay + repository-delegation path | ✅ `_bootstrap_shadow_state()` delegates to `ShadowStateRepository.ensure_table()` |
| PR2 2.2 | `tests/migration/test_bucket_invariant.py` | Unit + CLI harness | ✅ same 36-test safety net | ✅ same RED run: `InsForgeClient.ensure_bucket` missing, `ensure-bucket` CLI missing, apply preflight lacked bucket event | ✅ `python -m pytest tests/migration/test_bucket_invariant.py -q` → 7 passed | ✅ happy existing-private, sad public-bucket abort, edge missing-bucket auto-create, idempotent replay, unsafe-name fail-before-network, CLI check-only, apply-before-lock order | ✅ extracted `migration/bootstrap.py` (`check_private_bucket`, `ensure_private_bucket`, `bootstrap_m0_infrastructure`) |
| PR2 2.3 | full local gate | Unit/integration mix | ✅ focused + migration suite green before full gate | N/A — verification task | ✅ local full gate with documented no-real-backend deselect green | ✅ `python -m pytest -W error::DeprecationWarning` attempted full run and exposed pre-existing missing `APAP_E2E_BASE_URL`; no product-test failure in PR2 code | ✅ no code refactor after full gate; ruff/check-rules/build green |
| PR2-verify R1 | `tests/migration/test_bucket_invariant.py` (`test_bucket_visibility_missing_or_null_fails_closed`, `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy`) | Unit | ✅ `python -m pytest tests/migration/test_bucket_invariant.py -q` → 8 passed (pre-RED baseline) | ✅ `python -m pytest tests/migration/test_bucket_invariant.py -q` → 7 passed, 1 failed; the new `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` failed because the production code already short-circuits before lock — assertion refined to drop the `ensure_bucket` event expectation, RED was logged before that fix | ✅ `python -m pytest tests/migration/test_bucket_invariant.py -q` → 9 passed | ✅ both `isPublic`-absent and `isPublic`-null scenarios; lock- and read-absence assertions on disk as well | ✅ none required — only test atoms + runbook text |
| PR2-verify R2 | n/a — no production code change | n/a | n/a | n/a | n/a | n/a | n/a |
| PR2-verify R3 | full local gate | mixed | ✅ focused + migration suite green before full gate | n/a — verification task | ✅ `python -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py` → 2110 passed, 1 skipped, 2 deselected | ✅ migration suite 47 passed (added 2 atoms) | ✅ ruff/check-rules/build green |
| PR2-verify R4 | runbook `docs/runbooks/live-migration-m0-bootstrap.md` | docs | ✅ runbook text was the safety target | n/a — no test for the runbook text | n/a — operator runbook | n/a | n/a |

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → `11 passed in 0.18s` (post-PR2-verify); split: `test_shadow_state.py -q` → 2 passed, `test_bucket_invariant.py -q` → 9 passed |
| Runtime harness command/scenario and exact result | `python -m pytest tests/migration/test_bucket_invariant.py -q` → `9 passed`; exercises `apap-migrate ensure-bucket` through `migration.cli.main(...)` with injected clients; verifies apply preflight short-circuits on bootstrap failure without acquiring the migration lock or invoking the legacy executor. Real InsForge mutation: **not run** by design; operator checkpoint documented in `docs/runbooks/live-migration-m0-bootstrap.md`. |
| Rollback boundary | Revert the PR2-verify commit to drop the new test atoms (`test_bucket_visibility_missing_or_null_fails_closed`, `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy`) and the runbook rollback-safety rewrite. The PR2 commit on top of which PR2-verify builds remains in place; reverting PR2-verify only reverts the remediation, not the original PR2 code. |

### Verification Summary

- **PR2-verify RED**: `python -m pytest tests/migration/test_bucket_invariant.py -q` → 8 passed, 1 failed; the new `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` failed before the assertion refinement (initial RED expected the `ensure_bucket` event to be in `events`; the production code correctly short-circuits before that call). The new `test_bucket_visibility_missing_or_null_fails_closed` is the canonical privacy fail-closed regression atom.
- **PR2-verify GREEN**: `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -q` → 11 passed.
- **Migration suite**: `python -m pytest tests/migration -q` → 47 passed.
- **Local full gate without real/shared backend dependency**: `python -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py` → 2110 passed, 1 skipped, 2 deselected.
- **Ruff**: `ruff check .` → All checks passed.
- **Project rule gate**: `python scripts/check_rules.py app --exclude scripts/check_rules.py --exclude tests/_rule_helpers/fixtures --exclude tests/test_migration_004.py` → exit 0, no output.
- **Build**: `python -m build` → Successfully built `apap_web-0.1.0.tar.gz` and `apap_web-0.1.0-py3-none-any.whl`.

### Infrastructure Mutation Status

- No real InsForge bucket/table mutation was performed during apply or PR2-verify.
- InsForge docs were read via `fetch-sdk-docs(storage, rest-api)` to verify the current bucket management surface.
- Tests use `httpx.MockTransport` or in-memory `FakeInsForge` only.
- Operator work-unit checkpoint is documented in `docs/runbooks/live-migration-m0-bootstrap.md` and remains outside ordinary tests.

### Files Changed (PR2 + PR2-verify)

| File | Action | What changed |
|---|---|---|
| `app/core/insforge.py` | Modified (PR2) | Added private-only bucket read/ensure helpers using bucket-list/create admin surface; fails closed on public/unknown visibility. |
| `migration/bootstrap.py` | Added (PR2) | Centralized M0 bootstrap helpers for shadow table + private `apap-photos` bucket. |
| `migration/apply.py` | Modified (PR2) | Apply preflight delegates shadow table to repository contract and runs M0 bootstrap before lock/read; no Dysflow MCP runtime language remains in touched comments. |
| `migration/cli.py` | Modified (PR2) | Added `ensure-bucket` operator checkpoint with `--check-only`; apply converts infrastructure bootstrap failures to exit 5. |
| `tests/migration/conftest.py` | Modified (PR2) | Extended `FakeInsForge` with private bucket fake methods. |
| `tests/migration/test_shadow_state.py` | Added (PR2) | RED/GREEN atoms for repository contract + idempotent DDL replay. |
| `tests/migration/test_bucket_invariant.py` | Added (PR2) + Remediation (PR2-verify) | RED/GREEN atoms for private bucket invariant, public abort, missing create, idempotency, CLI harness, pre-lock order. PR2-verify added `test_bucket_visibility_missing_or_null_fails_closed` (absent + null scenarios) and `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` (lock-file absence + read-absence). |
| `docs/runbooks/live-migration-m0-bootstrap.md` | Modified (PR2) + Remediation (PR2-verify) | Operator runbook for the PR2 infra checkpoint, verification, and rollback. PR2-verify rewrote the Rollback section: non-destructive disable preferred; `DROP TABLE` marked destructive of divergence/audit history; `delete-bucket` marked destructive of uploaded photos; verified backup/export and empty/no-data proof required; `TRUNCATE` explicitly NOT recommended. |
| `openspec/changes/live-data-migration-sandbox/tasks.md` | Modified (PR2) | Marked only PR2 tasks complete. |
| `openspec/changes/live-data-migration-sandbox/apply-progress.md` | Added (PR2) + Updated (PR2-verify) | Cumulative PR1+PR2+PR2-verify apply progress with TDD/work-unit evidence. |

### Deviations from design/tasks

- The task text referenced a candidate `GET /api/storage/buckets/{bucket}` shape. Current InsForge REST docs fetched during PR2 document `GET /api/storage/buckets` for bucket listing plus `POST /api/storage/buckets` for create. PR2 therefore uses the verified list/create admin surface and fails closed when visibility cannot be verified. This stays inside PR2's bucket-management scope and does **not** implement PR4 upload/download media methods.
- No live InsForge mutation was executed during apply or PR2-verify, per the code-vs-real-infrastructure separation requested by the user.
- The new `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` test was originally written with an `assert "ensure_bucket" in events` expectation. The production code short-circuits on the public-bucket check (which fires before `ensure_bucket` is called) so the assertion was removed. The test still exercises the contract that the apply preflight fails before lock acquisition and legacy reads.

### Issues found

- `python -m pytest -W error::DeprecationWarning` still collects `tests/test_voluntarios_concurrent.py`, whose first atom hard-fails without `APAP_E2E_BASE_URL`. This is pre-existing and documented in `docs/proceso.md` as requiring deselect/no shared backend for local runs.
- InsForge bucket-list REST docs may return bucket names without visibility in some deployments. PR2 code deliberately fails closed (`bucket_visibility_unknown`) and tells the operator to verify via the InsForge infrastructure tool rather than assuming private state. The PR2-verify atom `test_bucket_visibility_missing_or_null_fails_closed` pins the fail-closed contract for both `isPublic`-absent and `isPublic`-null shapes.

### Unrelated-dirt proof

- Untracked `coverage.json`, `coverage_full.json`, `openspec/changes/adopt-03-seguimiento-state-machine/`, `openspec/changes/live-data-migration-sandbox/design.md`, `exploration.md`, `proposal.md`, `specs/` preserved in working tree; not staged, not committed.
- No stash, restore, reset --hard, amend, rebase, force, push, PR open, merge, or GitHub issue/comment performed.

### Next batch

PR1, PR2, and PR2-verify remediation complete. PR3+ untouched. Next recommended phase: `sdd-verify` for PR2, then continue with PR3 only when explicitly assigned.
