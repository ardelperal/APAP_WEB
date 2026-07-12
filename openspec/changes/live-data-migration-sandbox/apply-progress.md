## SDD Apply Progress: live-data-migration-sandbox

**Branch**: `feat/live-migration-storage-contract-spike` (from `origin/main` @ PR #186 merge `73bfff4`)
**Work units**: cumulative PR1 / PR2 / PR2-verify / PR3 / PR3 verification remediation / PR3 runbook closure + current PR4a read-only storage contract spike.
**Mode**: Strict TDD (orchestrator-confirmed; global maintainer-approved `size:exception`)
**Delivery**: stacked-to-main with maintainer-approved `size:exception`; target `main` via PR; apply phase does NOT push/open PR/merge (user will auto-merge later)
**Status**: PR1, PR2, PR2-verify, PR3, PR3 verification remediation, PR3 runbook closure, and PR4a complete; PR4b+ untouched. PR4b is **BLOCKED** until the live InsForge storage contract is proven with credentials and the discovery doc verdict changes to PASS.

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
- [x] PR3 3.1 RED — `tests/migration/test_lock_snapshot.py` (42 atoms: snapshot dataclass, compute_accdb_hash, compute_photos_dir_hash, write/read atomic, detect_drift, partial-apply evidence) + `tests/migration/test_apply_safety.py` (12 atoms: MSACCESS pre-flight, snapshot ordering, drift detection, partial-apply lifecycle) + `tests/migration/test_reporting.py` (9 atoms: backward-compat defaults, JSON serialization no-PII, ApplyResult unchanged)
- [x] PR3 3.2 GREEN — `migration/lock_snapshot.py` (Snapshot dataclass + atomic write + drift detection + partial-apply evidence); `migration/apply.py` re-ordered per design D8 (bootstrap → partial-apply entry guard → MSACCESS pre-flight → lock → snapshot write → read+apply loop) with new exception types `MsAccessRunningError` (CLI exit 5), `SourceDriftError` (CLI exit 6), `PartialApplyInterruptedError` (CLI exit 7); `migration/reporting.py` extended `MigrationReport` with `counts` / `source_hashes` / `collisions` via `field(default_factory=dict)` so pre-PR3 callers stay valid; `ApplyResult` UNCHANGED per design D11
- [x] PR3 3.3 VERIFICATION — focused + migration + full local pytest + ruff + check-rules + build all green (real backend mutation not run by design)
- [x] PR3 Rollback — revert the three PR3 commits to drop the snapshot module, the apply-safety wiring, and the new MigrationReport fields; pre-PR3 reports stay valid because of the default-factory pattern
- [x] PR3 verification remediation RED — typed CLI exit-code contract (one closed-vocabulary reason per exception); MSACCESS fail-closed (`MsAccessPreflightUnavailableError`); no traceback / no raw PII / no raw paths in operator stream; `MIGRATION_RUNBOOK_REF` constant; legacy `test_check_msaccess_returns_empty_when_psutil_missing` updated to assert the new fail-closed contract.
- [x] PR3 verification remediation GREEN — `migration.cli.run_apply` handlers for the 6 typed exceptions + `MIGRATION_RUNBOOK_REF` + `_format_apply_error` helper; `migration.lock.check_msaccess_running` raises `MsAccessPreflightUnavailableError` on psutil-missing / iteration-error; `migration.apply.apply_legacy_to_web` catches + emits `log_safe("apply.preflight_unavailable", reason=<cat>)` + re-raises; `migration.apply.MsAccessRunningError` docstring updated to point to the new preflight-unavailable contract.
- [x] PR3 verification remediation verification — focused (5 fail-closed + 44 CLI = 49 atoms) + migration + full local pytest + ruff + check-rules + build all green. Real InsForge / psutil / Access mutation NOT run by design.
- [x] PR3 C-3 dead runbook blocker resolved — repository-level test `tests/test_runbook_links.py` (8 atoms) RED-first captures that every operator-facing migration runbook reference (CLI `MIGRATION_RUNBOOK_REF` + every path named in `migration/dysflow_client.py`) resolves to an authored `docs/runbooks/<name>.md` file with all five AGENTS §13 sections (`## When to trigger`, `## Pre-deploy checklist`, `## Deploy steps`, `## Verification`, `## Rollback`). Authored `docs/runbooks/live-migration-apply.md` with the full closed vocabulary (exits 5/6/7 + all six categorical reasons + psutil prerequisite + check-only + private infra + snapshot/partial files + no auto-resume + no destructive removal + no raw PII/path logging + rollback + escalation). Consolidated the 3 dead `migrate-live-data.md` references in `migration/dysflow_client.py` to the new canonical runbook. Fixed tasks.md drift (`apply.preflight_unlimited` → `apply.preflight_unavailable`). `scripts/check_audit_and_runbook.py` top-level `migration/` detection left as a follow-up (no focused test exists; mechanical change would be a single line in `SENSITIVE_AUDIT_PATHS` but the user's scope-discipline directive says "log follow-up, do not expand" without a RED-first test).
- [x] PR3 final runbook warning closed — `tests/test_runbook_links.py` extended with `TestPyprojectRunbookReferences` (4 atoms, RED-first) that scans `pyproject.toml` for `docs/runbooks/*.md` references and requires each to resolve + carry the AGENTS §13 headings + match the CLI constant. Replaced the stale `docs/runbooks/migrate-live-data.md` reference in `pyproject.toml` (the `pyodbc` install-hint comment) with the canonical `docs/runbooks/live-migration-apply.md`. Updated the PR4b future task spec in `tasks.md` (the only remaining tracked PR3 artifact referencing the stale runbook) to point to the canonical runbook + note that PR4b-specific storage + foto sections will be added on top. Did NOT change `apply-progress.md` historical evidence bullet (past-tense record of the C-3 consolidation work, not a future reference) or any untracked SDD artifacts (proposal / design / specs) per user scope-discipline directive.
- [x] PR3 verification remediation rollback — revert the remediation commit; the underlying PR3 commits (`8aa4ff4`, `6c54931`, `525a461`) remain valid because the new test atoms are GREEN only with the new production code. The legacy `tests/test_migration.py::TestLock::test_check_msaccess_returns_empty_when_psutil_missing` reverts to its pre-remediation `assert lock_mod.check_msaccess_running() == []` assertion.
- [x] PR4a 4.1 RED/GREEN — `tests/migration/test_photo_storage.py` (9 atoms) written first against missing `migration.storage_spike`, then `migration/storage_spike.py` added as a read-only CLI/test seam. Covers 2xx supported shape; 401/403 auth failures; 404 endpoint/sentinel mismatch; 405 and local mutation refusal; redaction; deterministic evidence hash; repeated probes with no writes; timeout/network fail-closed; missing credentials with no network.
- [x] PR4a 4.2 USER OVERRIDE / MUTATION GATE — the prior draft task to probe `POST /api/storage/buckets/apap-photos/upload-strategy` is superseded for PR4a. This batch sends no POST/PUT/PATCH/DELETE, creates no bucket, uploads no object, and reads no object bytes. Upload-strategy behavior is deferred to PR4b MockTransport/fixture tests unless a separate explicit operator mutation gate is created.
- [x] PR4a 4.3 VERIFICATION — live credentials were absent, so the operator probe did not contact InsForge and wrote `docs/discovery/storage-contract-2026-Q3.md` with status `missing_credentials`, evidence hash `8d0f87f79699483014a194d3b787953e1f0fe3353890479d4e41022bd52c559b`, `Verdict: BLOCKED`, and PR4b gate `BLOCKED`. Focused/migration/full pytest, ruff, check-rules, and build passed.
- [ ] PR4b 4.4–4.6 ... PR7 7.x — UNTOUCHED (per orchestrator/user instruction)
- [ ] 9.1 Automatic partial-apply resume — deferred to follow-up PR before M2 fallback-ready; see `tasks.md` 9.1. PR3 deliberately does NOT implement auto-resume.

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
| PR3 3.1 (WU-1) | `tests/migration/test_lock_snapshot.py` | Unit | ✅ `python -m pytest tests/migration/test_lock_snapshot.py -q` failed RED on `ModuleNotFoundError: No module named 'migration.lock_snapshot'` | ✅ 1 collection error | ✅ `python -m pytest tests/migration/test_lock_snapshot.py -q` → 42 passed in 0.42s | ✅ happy (deterministic + write+read roundtrip) / sad (missing file / corrupt JSON / unknown version / missing dir) / edge (empty bytes / empty dir / subdirectories skipped / filename-order independence / inaccessible file) | ✅ test refined to remove false-positive substring match on field-name fragment `photos_dir` (kept the field name `photos_dir_sha256` per design); test refined to use `EMPTY_SHA256` for empty entries (matches empty `.accdb` contract) |
| PR3 3.2 (WU-2) | `tests/migration/test_apply_safety.py` | Unit | ✅ `python -m pytest tests/migration/test_apply_safety.py -q` failed RED on `AttributeError: module 'migration.apply' has no attribute 'check_msaccess_running'` | ✅ 12 collection errors | ✅ `python -m pytest tests/migration/test_apply_safety.py -q` → 12 passed in 0.23s | ✅ happy (no MSACCESS → apply runs) / sad (MSACCESS live → exit-5 abort, drift detected → exit-6 abort, partial-apply exists → exit-7 abort) / edge (dry-run bypasses all pre-flight, SIGINT-before-snapshot leaves no trace, SIGINT-after-snapshot writes partial evidence, empty source still writes snapshot) | ✅ no refactor required |
| PR3 3.3 (WU-3) | `tests/migration/test_reporting.py` | Unit | ✅ `python -m pytest tests/migration/test_reporting.py -q` failed RED on `TypeError: MigrationReport.__init__() got an unexpected keyword argument 'collisions'` | ✅ 6 failures + 3 ApplyResult passes | ✅ `python -m pytest tests/migration/test_reporting.py -q` → 9 passed in 0.18s | ✅ happy (default empty dicts, explicit kwargs, JSON roundtrip) / sad (non-serializable values raise TypeError) / edge (no PII/path leakage in any JSON string value, ApplyResult shape pinned) | ✅ `to_markdown` extended with a `## Source Identity` section that ONLY emits when at least one of the three new fields has content (backward-compat verified by the existing `test_migration_report_to_markdown_contains_summary_table` and `test_reconciliation_summary_to_markdown_omits_when_none` atoms) |
| PR3 verification | full local gate + ruff + check-rules + build | mixed | ✅ focused + migration + full pytest green before full gate | n/a — verification task | ✅ `python -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py` → 2173 passed, 1 skipped (psycopg missing), 2 deselected | ✅ migration + test_migration suite 241 passed | ✅ ruff clean / check-rules silent / build green / coverage gate 17 helpers at 100% |
| PR4a 4.1–4.3 | `tests/migration/test_photo_storage.py` | Unit + CLI harness | N/A (new module/test/doc) | ✅ `python -m pytest tests/migration/test_photo_storage.py -q` → 1 collection error (`ModuleNotFoundError: No module named 'migration.storage_spike'`) | ✅ `python -m pytest tests/migration/test_photo_storage.py -q` → 9 passed in 0.30s | ✅ happy 2xx + bearer HEAD, sad 401/403, 404, 405/refusal, timeout/network, missing credentials, repeated read-only idempotence | ✅ read-only wrapper + deterministic result/document writer; no media/storage PR4b methods/routes added |

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m pytest tests/migration/test_lock_snapshot.py tests/migration/test_apply_safety.py tests/migration/test_reporting.py -q` → `63 passed in 0.83s` (post-PR3); split: `test_lock_snapshot.py -q` → 42 passed, `test_apply_safety.py -q` → 12 passed, `test_reporting.py -q` → 9 passed |
| Runtime harness command/scenario and exact result | `python -m pytest tests/migration -q` → `101 passed in 1.05s`; exercises `apply_legacy_to_web` end-to-end through `FakeInsForge` + injected executor + monkeypatched seams (no real psutil / InsForge / Access touched). Real InsForge mutation: **not run** by design; operator checkpoint documented in `docs/runbooks/live-migration-m0-bootstrap.md` (PR2 runbook remains the operator entry point until PR4 publishes the per-table runbook). |
| Rollback boundary | Revert the three PR3 commits (`8aa4ff4`, `6c54931`, `525a461`) in reverse chronological order to drop the `MigrationReport` extensions, the apply-safety wiring (MSACCESS pre-flight / snapshot write / partial-apply evidence), and the `migration.lock_snapshot` module. The pre-PR3 `MigrationReport` constructor signature stays valid because the new fields use `field(default_factory=dict)` and are added at the end of the dataclass. |

#### Work Unit Evidence (PR4a)

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_photo_storage.py -q` → RED first: 1 collection error (`ModuleNotFoundError: No module named 'migration.storage_spike'`); GREEN after implementation: `9 passed in 0.30s` |
| Runtime harness command/scenario and exact result | `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m migration.storage_spike --probe download_strategy --path apap-photos/0123456789abcdef.jpg --output docs/discovery/storage-contract-2026-Q3.md` with missing `APAP_INSFORGE_URL` / `APAP_INSFORGE_SERVICE_KEY` → process returned 3 (captured as expected blocked operator status), wrote redacted discovery doc, made 0 network calls by construction. Live probe did **not** run; PR4b remains BLOCKED. |
| Rollback boundary | Revert the PR4a commit to remove `migration/storage_spike.py`, `tests/migration/test_photo_storage.py`, `docs/discovery/storage-contract-2026-Q3.md`, and the PR4a-only updates to `openspec/changes/live-data-migration-sandbox/tasks.md` and `apply-progress.md`. No InsForge bucket/object/data rollback exists because PR4a performed no mutation. |

### PR4a Verification Summary

- **RED**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_photo_storage.py -q` → 1 collection error (`ModuleNotFoundError: No module named 'migration.storage_spike'`).
- **GREEN focused**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_photo_storage.py -q` → 9 passed in 0.30s.
- **Runtime/operator harness**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m migration.storage_spike --probe download_strategy --path apap-photos/0123456789abcdef.jpg --output docs/discovery/storage-contract-2026-Q3.md` → status `missing_credentials`, evidence hash `8d0f87f79699483014a194d3b787953e1f0fe3353890479d4e41022bd52c559b`, PR4b gate `BLOCKED`; no live network probe because credentials/env were absent.
- **Migration suite**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration -q` → 168 passed in 1.86s.
- **Full local gate**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` → 2243 passed, 1 skipped (`psycopg` missing), 2 deselected in 22.05s; coverage gate PASS: all 17 helpers at 100%.
- **Ruff**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m ruff check .` → All checks passed.
- **Project rule gate**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe scripts/check_rules.py app` → exit 0, no output.
- **Build**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m build --wheel` → `apap_web-0.1.0-py3-none-any.whl` built.

### Verification Summary (PR3)

- **PR3 RED WU-1 (lock_snapshot)**: `python -m pytest tests/migration/test_lock_snapshot.py -q` → 1 collection error (`ModuleNotFoundError`).
- **PR3 RED WU-2 (apply_safety)**: `python -m pytest tests/migration/test_apply_safety.py -q` → 12 collection errors (`AttributeError` on `migration.apply.check_msaccess_running`).
- **PR3 RED WU-3 (reporting)**: `python -m pytest tests/migration/test_reporting.py -q` → 6 failures + 3 ApplyResult passes (`TypeError: unexpected keyword argument 'collisions'`).
- **PR3 GREEN WU-1**: `python -m pytest tests/migration/test_lock_snapshot.py -q` → 42 passed in 0.42s.
- **PR3 GREEN WU-2**: `python -m pytest tests/migration/test_apply_safety.py -q` → 12 passed in 0.23s.
- **PR3 GREEN WU-3**: `python -m pytest tests/migration/test_reporting.py -q` → 9 passed in 0.18s.
- **Migration suite (post-PR3)**: `python -m pytest tests/migration -q` → 101 passed in 1.05s (47 baseline + 42 lock_snapshot + 12 apply_safety).
- **Migration + test_migration combined (post-PR3)**: `python -m pytest tests/migration tests/test_migration.py -q` → 241 passed in 1.87s.
- **Local full gate without real/shared backend dependency (post-PR3)**: `python -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` → 2173 passed, 1 skipped (psycopg missing), 2 deselected.
- **Ruff**: `ruff check .` → All checks passed.
- **Project rule gate**: `python scripts/check_rules.py app --exclude scripts/check_rules.py --exclude tests/_rule_helpers/fixtures --exclude tests/test_migration_004.py` → exit 0, no output.
- **Coverage gate**: `coverage.json` after pytest → all 17 critical helpers at 100% line coverage (no regressions in the helper list; no new helpers added that require gate inclusion).
- **Build**: `python -m build --wheel` → `apap_web-0.1.0-py3-none-any.whl` built.

### Infrastructure Mutation Status

- No real InsForge bucket/table/object mutation was performed during apply, PR2-verify, PR3, or PR4a.
- PR4a live probe did not contact InsForge because credentials/env were absent; the CLI returned the expected blocked operator status and wrote redacted local evidence only.
- PR4a tests use `httpx.MockTransport` only; no real storage URL, object bytes, bucket creation, upload, delete, or update path is exercised.
- InsForge docs were read via `fetch-sdk-docs(storage, rest-api)` to verify the current bucket management surface.
- Tests use `httpx.MockTransport` or in-memory `FakeInsForge` only.
- Operator work-unit checkpoint is documented in `docs/runbooks/live-migration-m0-bootstrap.md` and remains outside ordinary tests.

### Files Changed (PR2 + PR2-verify + PR3)

| File | Action | What changed |
|---|---|---|
| `app/core/insforge.py` | Modified (PR2) | Added private-only bucket read/ensure helpers using bucket-list/create admin surface; fails closed on public/unknown visibility. |
| `migration/bootstrap.py` | Added (PR2) | Centralized M0 bootstrap helpers for shadow table + private `apap-photos` bucket. |
| `migration/apply.py` | Modified (PR2 + PR3 WU-2) | PR2: apply preflight delegates shadow table to repository contract and runs M0 bootstrap before lock/read. PR3: re-ordered per design D8 (bootstrap → partial-apply entry guard → MSACCESS pre-flight → lock → snapshot write → read+apply loop). New exception types: `MsAccessRunningError` (CLI exit 5), `SourceDriftError` (CLI exit 6), `PartialApplyInterruptedError` (CLI exit 7). New optional params: `snapshot_path`, `partial_path`, `photos_dir_path`. New helpers: `_resolve_default_snapshot_path`, `_resolve_default_partial_path`, `_write_or_check_snapshot`. SIGINT (KeyboardInterrupt) writes partial-apply evidence if the snapshot was already written. |
| `migration/lock_snapshot.py` | Added (PR3 WU-1) | New module: `Snapshot` (versioned JSON, `SCHEMA_VERSION=1`), `PhotosManifest`, `DriftSummary`, `compute_accdb_hash`, `compute_photos_dir_hash`, `write_snapshot` (atomic temp + replace), `read_snapshot`, `detect_drift`, `write_partial_apply`, `read_partial_apply`. Empty / missing sources produce the SHA-256 of zero bytes (deterministic fingerprint, not a crash). No raw paths or PII in the JSON. |
| `migration/reporting.py` | Modified (PR3 WU-3) | `MigrationReport` gains three dict fields at the END: `counts: dict[str, dict[str, int]]`, `source_hashes: dict[str, str]`, `collisions: dict[str, dict[str, int]]`. All use `field(default_factory=dict)` for backward compat with every pre-PR3 caller. `to_json()` round-trips the new fields via the existing `asdict` path. `to_markdown()` gains a `## Source Identity` section that ONLY emits when at least one of the three new fields has content (pre-PR3 markdown shape unchanged). `ApplyResult` is UNCHANGED per design D11. |
| `migration/cli.py` | Modified (PR2) | Added `ensure-bucket` operator checkpoint with `--check-only`; apply converts infrastructure bootstrap failures to exit 5. |
| `tests/migration/conftest.py` | Modified (PR2) | Extended `FakeInsForge` with private bucket fake methods. |
| `tests/migration/test_lock_snapshot.py` | Added (PR3 WU-1) | 42 atoms across `TestSnapshotSerialization`, `TestComputeAccdbHash`, `TestComputePhotosDirHash`, `TestSnapshotReadWrite`, `TestDetectDrift`, `TestPartialApplyEvidence`. Three paths per slice. No PII/path substring leakage in any JSON. |
| `tests/migration/test_apply_safety.py` | Added (PR3 WU-2) | 12 atoms across `TestMsaccessPreflight`, `TestSnapshotOrdering`, `TestDriftDetection`, `TestPartialApplyEvidence`. Monkeypatches every new dependency (no real psutil / InsForge / Access). |
| `tests/migration/test_shadow_state.py` | Added (PR2) | RED/GREEN atoms for repository contract + idempotent DDL replay. |
| `tests/migration/test_bucket_invariant.py` | Added (PR2) + Remediation (PR2-verify) | RED/GREEN atoms for private bucket invariant, public abort, missing create, idempotency, CLI harness, pre-lock order. PR2-verify added `test_bucket_visibility_missing_or_null_fails_closed` (absent + null scenarios) and `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` (lock-file absence + read-absence). |
| `tests/migration/test_reporting.py` | Added (PR3 WU-3) | 9 atoms across `TestDefaultFactories`, `TestJsonSerialization`, `TestApplyResultUnchanged`. Backward-compat defaults, JSON serialization round-trip + no PII/path leakage, `ApplyResult` shape pinned to four fields. |
| `docs/runbooks/live-migration-m0-bootstrap.md` | Modified (PR2) + Remediation (PR2-verify) | Operator runbook for the PR2 infra checkpoint, verification, and rollback. PR2-verify rewrote the Rollback section: non-destructive disable preferred; `DROP TABLE` marked destructive of divergence/audit history; `delete-bucket` marked destructive of uploaded photos; verified backup/export and empty/no-data proof required; `TRUNCATE` explicitly NOT recommended. |
| `migration/storage_spike.py` | Added (PR4a) | Read-only storage contract probe CLI/test seam. Sends only GET/HEAD, refuses POST/PUT/PATCH/DELETE before transport, redacts service keys/URLs/object paths, distinguishes 2xx/401/403/404/405/network/timeout, and writes deterministic machine-readable evidence. |
| `tests/migration/test_photo_storage.py` | Added (PR4a) | 9 strict-TDD atoms for supported shape, auth failures, 404, 405/refusal, redaction, deterministic evidence, repeated no-write probes, timeout fail-closed, and missing-credentials no-network CLI path. |
| `docs/discovery/storage-contract-2026-Q3.md` | Added (PR4a) | Redacted discovery artifact. Current verdict is BLOCKED because live credentials were absent; PR4b must not start until a live operator probe pins the deployed endpoint/header with verdict PASS. |
| `openspec/changes/live-data-migration-sandbox/tasks.md` | Modified (PR2 + PR3 + PR4a) | PR2: marked PR2 tasks complete. PR3: marked PR3 3.1/3.2/3.3/Rollback complete. PR4a: marked storage contract spike complete and recorded the no-mutation override for the former POST upload-strategy spike task. PR4b+ untouched. |
| `openspec/changes/live-data-migration-sandbox/apply-progress.md` | Added (PR2) + Updated (PR2-verify) + Updated (PR3) + Updated (PR4a) | Cumulative PR1+PR2+PR2-verify+PR3+PR4a apply progress with TDD/work-unit evidence for every batch. |

### Deviations from design/tasks

- PR4a user override supersedes the earlier tasks.md line that proposed a live `POST /api/storage/buckets/apap-photos/upload-strategy` probe. This apply batch is read-only by construction: no POST/PUT/PATCH/DELETE, no bucket create/delete/update, no upload, no object-byte fetch. Upload-strategy behavior remains a PR4b MockTransport/fixture concern unless the operator creates a separate explicit mutation gate.
- PR4a live operator probe did not run because `APAP_INSFORGE_URL` / `APAP_INSFORGE_SERVICE_KEY` were absent. The discovery doc is intentionally `Verdict: BLOCKED` rather than pretending Context7/docs are enough proof. PR4b must not start until credentials exist and the live probe records `PASS` evidence.
- The task text referenced a candidate `GET /api/storage/buckets/{bucket}` shape. Current InsForge REST docs fetched during PR2 document `GET /api/storage/buckets` for bucket listing plus `POST /api/storage/buckets` for create. PR2 therefore uses the verified list/create admin surface and fails closed when visibility cannot be verified. This stays inside PR2's bucket-management scope and does **not** implement PR4 upload/download media methods.
- No live InsForge mutation was executed during apply, PR2-verify, or PR3, per the code-vs-real-infrastructure separation requested by the user.
- The new `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` test was originally written with an `assert "ensure_bucket" in events` expectation. The production code short-circuits on the public-bucket check (which fires before `ensure_bucket` is called) so the assertion was removed. The test still exercises the contract that the apply preflight fails before lock acquisition and legacy reads.
- PR3 task spec called for adding three atoms to `tests/migration/test_apply.py`; PR3 WU-2 ships 12 atoms in a NEW `tests/migration/test_apply_safety.py` instead. Reasoning: the existing `test_apply.py` is 460 lines and already covers the apply happy/sad/edge matrix; the new file groups the PR3-specific safety concerns (MSACCESS, ordering, drift, partial-apply) in one place so the reviewer reads a focused module instead of scrolling through mixed concerns. Both files run under the same `tests/migration/` collection; no test atom is lost.
- PR3 task spec named the test `test_drift_detected_and_logged`; PR3 splits that into `test_apply_fails_closed_on_drift` (the abort contract) plus the unit-level drift detector coverage in `test_lock_snapshot.py::TestDetectDrift`. Logging-as-observable-output is not asserted because the apply does not log drift via `log_safe` in PR3 (the drift surface is the raised exception + operator CLI surface; logging lands in a follow-up PR when the operator-facing log line is shaped).
- PR3 task spec named the test `test_partial_apply_json_on_sigint`; PR3 ships `test_apply_writes_partial_apply_on_sigint_after_snapshot` + `test_apply_sigint_before_snapshot_does_not_write_partial`. The two-test split pins both halves of design D8's SIGINT ordering invariant (write-if-after, no-write-if-before).
- PR3 task spec named the test `test_resume_from_partial_apply`; PR3 ships `test_apply_fails_closed_on_existing_partial_evidence` (the operator-resume contract). The actual `apply` resume logic (re-pick-up from `progress_applied`) is out of PR3 scope per the user directive ("no destructive cleanup"); it lands in a follow-up PR alongside the operator runbook update for `migration.partial_apply.json`.
- PR3 task spec named the test `test_snapshot_contains_accdb_sha256_and_photos_dir_sha256`; PR3 covers this at the dataclass level (`TestSnapshotSerialization::test_snapshot_from_json_roundtrip` + `test_snapshot_direction_is_preserved`) and at the compute level (`TestComputeAccdbHash` + `TestComputePhotosDirHash`). The end-to-end "snapshot on disk after apply" assertion lives in `test_snapshot_writes_with_empty_legacy_source` in `test_apply_safety.py`.
- PR3 does NOT add a `psutil` real-process check to the test suite; the `check_msaccess_running()` seam is monkeypatched in every PR3 atom (`monkeypatch.setattr("migration.apply.check_msaccess_running", ...)`). This honors the user directive "Do not kill/compile/access production in tests".

### Issues found

- PR4b material blocker: the deployed InsForge storage download-strategy contract is **not proven** in this environment because live credentials were unavailable. Current discovery verdict is `BLOCKED`; required auth header remains `unknown` and response shape comes only from MockTransport tests, not live evidence.
- `python -m pytest -W error::DeprecationWarning` still collects `tests/test_voluntarios_concurrent.py`, whose first atom hard-fails without `APAP_E2E_BASE_URL`. This is pre-existing and documented in `docs/proceso.md` as requiring deselect/no shared backend for local runs.
- InsForge bucket-list REST docs may return bucket names without visibility in some deployments. PR2 code deliberately fails closed (`bucket_visibility_unknown`) and tells the operator to verify via the InsForge infrastructure tool rather than assuming private state. The PR2-verify atom `test_bucket_visibility_missing_or_null_fails_closed` pins the fail-closed contract for both `isPublic`-absent and `isPublic`-null shapes.
- PR3 does not change the existing `LockActiveError` path; the new apply-safety exceptions (`MsAccessRunningError`, `SourceDriftError`, `PartialApplyInterruptedError`) are sibling exception types in the `MigrationError` hierarchy. The CLI conversion to exit codes 5 / 6 / 7 lands in a follow-up PR alongside the operator runbook (PR3 strict scope is the apply pipeline; the CLI surface for the new exceptions is a thin one-liner each).

### Unrelated-dirt proof

- Untracked `.atl/*` receipts (7 files), `coverage.json`, `coverage_full.json`, `openspec/changes/adopt-03-seguimiento-state-machine/`, `openspec/changes/live-data-migration-sandbox/design.md`, `exploration.md`, `proposal.md`, `specs/` preserved in working tree; not staged, not committed.
- No stash, restore, reset --hard, amend, rebase, force, push, PR open, merge, or GitHub issue/comment performed.
- Apply phase did NOT touch `.github/workflows/ci.yml`, `docs/roadmap.md`, `docs/audits/`, `docs/runbooks/`, `app/core/insforge.py`, `app/modules/animals/routes.py`, `migration/photo_migration.py`, or `migration/mappings/animal.yaml` (per PR4a-only directive: no PR4b media/storage methods/routes).

### PR3 verification remediation — RED / GREEN evidence (2026-07-11)

Per user directive, the PR3 verification surfaced three gaps: (1) the
CLI exception handlers had no deterministic operator contract, (2)
the MSACCESS pre-flight was silently fail-open when psutil was
missing, and (3) the spec did not pin the source-drift fail-closed
behavior, the no-auto-resume contract, or the stale-lock PID-dead
recovery. All three are remediated in a single conventional commit
on the same `feat/live-migration-apply-safety` branch.

| Phase | Command | Result |
|---|---|---|
| RED (CLI exit-code atoms) | `pytest tests/migration/test_cli_apply_safety.py -v` | 1 collection error: `ImportError: cannot import name 'MsAccessPreflightUnavailableError' from 'migration'` |
| RED (fail-closed atoms) | `pytest tests/migration/test_apply_safety.py::TestMsaccessPreflightFailClosed -v` | 4 passed, 1 failed: `test_preflight_failure_does_not_acquire_lock_or_read_legacy` failed because `_patch_apply_seams` set `check_msaccess_running` to its own no-op fake AFTER the test's monkeypatch (test fixed by reordering) |
| RED (legacy test) | `pytest tests/test_migration.py::TestLock::test_check_msaccess_returns_empty_when_psutil_missing -v` | Failed: pre-remediation assertion `lock_mod.check_msaccess_running() == []` no longer holds after fail-closed fix |
| GREEN (fail-closed) | `pytest tests/migration/test_apply_safety.py::TestMsaccessPreflightFailClosed -v` | 5 passed in 0.25s |
| GREEN (CLI exit-code) | `pytest tests/migration/test_cli_apply_safety.py -v` | 44 passed in 0.26s |
| Migration + test_migration | `pytest tests/migration tests/test_migration.py -q` | 290 passed in 2.29s (241 baseline + 5 fail-closed + 44 CLI atoms) |
| Full local gate | `pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` | 2222 passed, 1 skipped (psycopg missing), 2 deselected |
| Ruff | `ruff check .` | All checks passed |
| Project rule gate | `python scripts/check_rules.py app --exclude …` | exit 0, no output |
| Build | `python -m build --wheel` | `apap_web-0.1.0-py3-none-any.whl` built |

#### Work Unit Evidence (PR3 verification remediation)

| Evidence | Required value |
|---|---|
| Focused test command + exact result | `pytest tests/migration/test_apply_safety.py::TestMsaccessPreflightFailClosed tests/migration/test_cli_apply_safety.py -q` → `49 passed in 0.51s` (split: 5 fail-closed + 44 CLI) |
| Runtime harness | `pytest tests/migration tests/test_migration.py -q` → `290 passed in 2.29s`; exercises `apply_legacy_to_web` + `migration.cli.run_apply` end-to-end through `FakeInsForge` + monkeypatched seams (no real InsForge / psutil / Access touched). |
| Rollback boundary | Revert the remediation commit. The underlying PR3 commits (`8aa4ff4`, `6c54931`, `525a461`) remain valid because the new atoms are GREEN only with the new production code. The legacy `tests/test_migration.py::TestLock::test_check_msaccess_returns_empty_when_psutil_missing` reverts to the pre-remediation `assert lock_mod.check_msaccess_running() == []` shape. |

#### CLI categorical contract (post-remediation)

Every typed exception from `apap-migrate apply` produces ONE line:

    apap-migrate apply: status=error reason=<cat> exit=<N> runbook=<ref>

Closed vocabulary:

| Exception                              | Exit | reason                              |
|----------------------------------------|------|-------------------------------------|
| `MsAccessPreflightUnavailableError`    | 5    | `msaccess_preflight_unavailable`     |
| `MsAccessRunningError`                 | 5    | `msaccess_running`                   |
| `LegacyReaderError`                    | 5    | `legacy_read_failed`                 |
| `InsForgeError` (bootstrap path)       | 5    | `infra_bootstrap_failed`            |
| `SourceDriftError`                     | 6    | `source_drift`                       |
| `PartialApplyInterruptedError`         | 7    | `partial_apply_interrupted`          |

`runbook=<ref>` is the stable constant
`MIGRATION_RUNBOOK_REF = "docs/runbooks/live-migration-apply.md"`.
The apply runbook file is scheduled for authoring in a follow-up
PR; the path is the contract the CLI surfaces today so the
operator's docs lookup is deterministic.

#### Spec alignment (artifact updates, in this commit)

- `design.md`: added D17 (drift fail-closed + no auto-resume), D18
  (MSACCESS fail-closed + `psutil` operator prerequisite), D19
  (stale-lock PID-dead recovery contract, implementation untouched).
  Added "Apply exit-code contract" subsection under §8 with the
  closed-vocabulary table above.
- `tasks.md`: marked PR3 3.4 (remediation), 3.5 (remediation tests)
  complete; added 9.1 (automatic partial-apply resume deferred to
  follow-up PR before M2 fallback-ready).
- `apply-progress.md`: cumulative evidence through PR3 verification
  remediation (this section).
- `Engram`: topic `sdd/live-data-migration-sandbox/apply-progress`
  updated (separate save after commit).

#### Deviations / scope discipline

- The remediation does NOT push, open a PR, or merge (per user
  directive).
- The remediation does NOT modify `migration/apply.py`'s public
  contract beyond the preflight catch+log+re-raise (no new params).
- The remediation does NOT change `lock_snapshot.py`'s atomic
  write / drift detection contracts.
- The remediation does NOT change `check_msaccess_running()`'s
  no-arg signature (D9 invariant preserved).
- The remediation does NOT change `MigrationReport`'s default
  factories (D11 invariant preserved).
- The remediation does NOT introduce a new `--accept-drift` flag
  (deferred to a follow-up PR).
- The remediation does NOT introduce automatic partial-apply
  resume (deferred to follow-up PR before M2 fallback-ready).
- The remediation does NOT change the PR2 stale-lock recovery
  behavior (D19 documents the existing safe behavior).

### Next batch

PR1, PR2, PR2-verify, PR3, PR3 verification remediation, PR3 runbook closure, and PR4a complete.
PR4b+ untouched. Next recommended phase: re-run the PR4a live probe with `APAP_INSFORGE_URL` and `APAP_INSFORGE_SERVICE_KEY` in an operator environment containing a safe existing sentinel object; only after `docs/discovery/storage-contract-2026-Q3.md` reaches `Verdict: PASS` may PR4b begin.
