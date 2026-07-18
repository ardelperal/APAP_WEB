## SDD Apply Progress: live-data-migration-sandbox

**Branch**: `feat/live-migration-photo-storage` (from `origin/main` @ PR #188 merge `24ff032`)
**Work units**: cumulative PR1 / PR2 / PR2-verify / PR3 / PR3 verification remediation / PR3 runbook closure / PR4a storage contract spike / PR4a operator evidence pin / W1 secret-leak remediation / **PR4b storage implementation + photo route + audit + runbook (4 work-unit commits, NOT yet pushed/PR/merged — apply phase boundary)**.
**Commits**: PR4b — `e7f5857` `feat(core): extend REDACTED_FIELDS with dni/tel1/tel2 for PR4b PII`; `b021e12` `feat(insforge): S3-compatible upload_object / download_object_stream / delete_object`; `b74a135` `feat(animals): PR4b authenticated GET /animales/{id}/foto with isolated photo_service`; `f977c9e` `docs(sdd): PR4b PII audit verdict PASS + apply runbook photo sections`. All four commit SHAs reachable from `HEAD` of `feat/live-migration-photo-storage`; branch is 4 ahead of `origin/main`.
**Mode**: Strict TDD (orchestrator-confirmed; global maintainer-approved `size:exception`)
**Delivery**: stacked-to-main with maintainer-approved `size:exception`; target `main` via PR; apply phase does NOT push/open PR/merge (user will auto-merge later)
**Status**: PR1, PR2, PR2-verify, PR3, PR3 verification remediation, PR3 runbook closure, PR4a, W1, PR4b (merged), and **PR5 (merged 2026-07-18 via PR #196, merge commit `024dc97307a745834f103be4ea27687c4381f93e`)** complete on `main`. PR4a discovery verdict was PASS, PR4b consumed the pinned contract, the PR4b PII audit verdict is PASS, and PR5's PII redaction + DNI collision routing + reconcile `--filter-direction` + PUBLIC_PATHS invariant + discovery docs shipped green. PR6, PR7, and 9.1 deferred to follow-up PRs (out of scope per user directive).

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
- [x] PR4a Operator Sentinel Contract Pin — PASS (2026-07-12). Operator-supplied redacted reversible synthetic sentinel probe verified the deployed InsForge contract. Pinned download strategy endpoint: `GET /api/storage/buckets/apap-photos/download-strategy/objects/{key}`. Authenticated `200 {expiresAt, method, url}`; unauthenticated `401 {error, message, nextActions, statusCode}`. S3-compatible upload: strategy → transfer (POST when `fields` present, PUT when absent) → confirm when `confirmRequired=true`. Sentinel delete `200`; post-list `0/0`; cleanup success. Deterministic evidence hash `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07`. Discovery verdict and PR4b gate **PASS**.
- [x] W1 Secret-Leak Remediation (2026-07-12) — narrow-scope W1 fix landed via `8c00fd8 fix(repo): narrow root gitignore to block secret and coverage leaks`. New `tests/test_repository_secrets_ignore.py` (8 atoms RED → GREEN) pins the root `.gitignore` surface for `/.env`, `/coverage.json`, `/coverage_full.json` and verifies the working tree never stages the secret or coverage artifacts. `.codegraph/` remains tracked; `.env.example` (if it exists) remains trackable. No `.env` contents inspected, printed, or logged.
- [x] PR4b 4.4 **RED**: `tests/test_log_safe_redaction.py` (**15 atoms** after parametrization: list-shape + per-field-presence × 3 + per-field-redaction × 3 + mixed-case × 6 + record-message non-leak + descriptive-name passthrough, RED → GREEN on REDACTED_FIELDS 12→15), `tests/migration/test_insforge_storage_methods.py` (**30 atoms** after 4R remediation: 28 PR4b-shipped + 2 per-chunk timeout, RED → GREEN on the three new storage methods), `tests/test_animals_foto_route.py` (**18 atoms** after 4R remediation: 9 PR4b-shipped + 4 mid-stream fail-closed + 2 SQL-lookup fail-closed + 3 service-level mid-stream wrapping, RED 404 → GREEN on the foto route + photo_service), `tests/test_pii_audit_doc.py` (7 atoms pinning the audit doc structure). Captured RED evidence in this file.
- [x] PR4b 4.5 **GREEN**: Implemented `InsForgeClient.{upload_object, download_object_stream, delete_object}` on `app/core/insforge.py` using the operator-pinned canonical endpoints from `docs/discovery/storage-contract-2026-Q3.md` (bearer auth on strategy; self-authenticating presigned URL on download — server-stream only; per-chunk `httpx.Timeout(connect=5, read=10, write=5, pool=5)` to catch stalled streams). Added `app/modules/animals/photo_service.py` (single responsibility: stream or signal missing/sentinel; no SQL knowledge; `PhotoStreamError` typed surface; mid-stream errors wrapped via `yield from` inside a try/except so `httpx.RemoteProtocolError` / `httpx.ReadTimeout` / streamed-GET 5xx all become `PhotoStreamError`; `is_missing_nombrefoto`, `stream_animal_photo`, `content_type_for_key`; `_StorageLike` Protocol for DI seam; `_EXT_TO_MIME` module-level mapping for one source of truth). Added `GET /animales/{animal_id}/foto` route in `app/modules/animals/routes.py` (`animal_id` is `animales.id` UUID per Correction L; uses `require_authorized_user`; eagerly consumes the storage generator so any mid-stream `PhotoStreamError` becomes the placeholder PNG before the response is built — trades the spec's `StreamingResponse` property for placeholder reliability, since FastAPI's `StreamingResponse` cannot retroactively replace a partial body; SQL lookup failures on `get_animal_by_id` are also wrapped for consistency per WARN-3; placeholder PNG for sentinel/null/storage-error/SQL-error; never exposes presigned URL). Expanded `REDACTED_FIELDS` in `app/core/logging.py` to add `dni`, `tel1`, `tel2` (12 → 15 fields). The migration-side `migration/photo_migration.py` + `animal.yaml` storage block remain for a follow-up PR (out of PR4b scope per user instruction: PR4b = web/app side only).
- [x] PR4b 4.6 **VERIFICATION**: `pytest tests/migration/test_insforge_storage_methods.py tests/test_log_safe_redaction.py tests/test_animals_foto_route.py tests/test_pii_audit_doc.py -v` → all green (**70 atoms** after 4R remediation, in 0.92s; coverage gate PASS all 17 helpers at 100%). Created `docs/audits/pii-live-migration-2026-Q3.md` (Scope enumerates the 4 PII columns + display routes + storage invariants + 15-field redaction list; Methodology lists **6** invariant categories with atom evidence including the 4R mid-stream wrapping + SQL-lookup wrapping + AST-detector pin; Findings table has P0/P1/P2/P3 severity rows including the 4R-added P3 row for `voluntarios.dni` web-only shadow; Verdict **PASS** with acceptance evidence index updated for the 4R atom counts). Extended `docs/runbooks/live-migration-apply.md` with PR4b-specific sections (When to trigger, Pre-deploy checklist with 6 hard gates, Deploy steps inside the standard apply, Verification bucket invariants + display failure matrix, Files written, What PR4b does NOT do, Rollback with non-destructive order: disable display → verify backup → mark sentinel → only then delete bucket). Refactored `upload_object` into three named helpers (`_request_upload_strategy`, `_transfer_upload`, `_confirm_upload`) per WARN-4. Replaced the source-text grep in `test_storage_methods_never_log_secrets_urls_or_paths` with the AST detector from `scripts/check_rules.py` per WARN-5. Five work-unit commits: `e7f5857` (REDACTED_FIELDS), `b021e12` (storage methods), `b74a135` (foto route + photo_service), `f977c9e` (audit + runbook), plus the 4R remediation commits `688653e` (CRIT-1 iteration wrapping), `9821bd7` (WARN-3 SQL wrap), `4717a4b` (WARN-1 per-chunk timeout), `cde7c03` (WARN-4 upload refactor), `df28fc1` (WARN-5 AST detector).
- [x] PR4b Rollback: revert the 9 work-unit commits in reverse chronological order (`df28fc1` → `cde7c03` → `4717a4b` → `9821bd7` → `688653e` → `f977c9e` → `b74a135` → `b021e12` → `e7f5857`). This drops the AST-detector test change, the `_request_upload_strategy` / `_transfer_upload` / `_confirm_upload` helpers, the per-chunk `httpx.Timeout` on `download_object_stream`, the `get_animal_by_id` SQL wrap, the `stream_animal_photo` iteration wrapping, the storage methods, photo_service module, foto route, REDACTED_FIELDS additions, audit doc, and runbook extensions. The pre-PR4b `app/core/insforge.py`, `app/modules/animals/routes.py`, and `app/core/logging.py` stay valid (the new code is additive — `ensure_bucket`/`get_bucket` were added in PR2 and remain). Per the runbook, the bucket itself is NOT deleted by the rollback path; the operator runs the documented disable-display → backup → sentinel → delete sequence manually and only after explicit verification that no animal row references a key whose bytes are still required. No InsForge bucket/object/data rollback exists because PR4b performed no mutation.
- [x] PR5 5.1 **RED**: `tests/migration/test_pii_redaction.py` (10 atoms: 4 sync.applied redaction parametrized, 1 shadow preserved_value masking, 1 MigrationReport.to_json no-PII regex, 1 CLI stdout no-PII, 1 redaction-list-covers-all-PII, 1 synthetic-payload-emits-redacted-payload, 1 collision-marker-in-log-payload); `tests/migration/test_dni_collision.py` (9 atoms: forward zero-collision, web-only shadow routing, reverse-path counter increment, interactive resolution, helper invariants × 3, counter initial state, CLI parser flag surface × 2); `tests/test_public_paths.py` (10 atoms: PUBLIC_PATHS 5-entry shape invariant, `_is_public_path` recognition, no-PII-route-in-PUBLIC_PATHS, parametrized 302-to-/login over 5 PII routes, /healthz + /login happy-path sanity). Captured RED evidence: `test_cli_reconcile_check_only_output_has_no_raw_pii` initially failed — the CLI's `_format_row_for_check_only` was leaking the raw `preserved_value` into the operator stdout via `web_value=`. Two CLI parser atoms initially failed — the `--filter-direction` flag did not exist.
- [x] PR5 5.2 **GREEN**: Implemented `migration/dni_collision.py` (NEW: `record_dni_collision` helper that routes one row to `web_only_feature_shadow` with `reconciliation_status="needs_review"`, `review_reasons=["dni_collision"]`, `preserved_value=None`, `strategy="preserve"`, `origin_direction=<direction>`; accepts `direction="web-only"` and `direction="web-to-legacy"` and persists the value verbatim on the shadow row via the new `origin_direction` column added in PR5 remediation; `DniCollisionCounter` is the per-run mutable counter that the apply pipeline bumps and the report builder reads). The helper is fully unit-tested (9 atoms in `test_dni_collision.py` covering both scopes + the counter increment + helper invariants + CLI parser surface). **The forward applier does NOT invoke `record_dni_collision`** because legacy `TbVoluntariosParaAutorrellenables` has no `DNI` column (Dysflow-verified 2026-07-11; the forward applier never writes `voluntarios.dni`). The DI seam is wired today so the PR6 reverse applier can pass a `DniCollisionCounter()` and read its value at the end of the run to populate `MigrationReport.collisions[table_name]["dni_collisions"]`. The seam is exercised by `tests/migration/test_dni_collision.py::test_forward_legacy_produces_zero_dni_collisions` (which passes a fresh counter through the seam and asserts it stays at 0 — NOT tautological: pins the contract that `apply_legacy_to_web` MUST NOT bump on forward apply). Extended `migration/shadow_state.py::list_needs_review` with an `origin_direction` kwarg; stamps `"legacy-to-web"` on every row until PR6's reverse applier starts producing its own rows; backward-compatible default `None` (no filter). The `ShadowStateRepository.upsert` signature also gained an `origin_direction` kwarg (with a new closed three-value CHECK constraint on the column). Extended `migration/cli.py` with `--filter-direction {legacy-to-web, web-to-legacy, both}` (default `"both"`); forwarded to `shadow_state.list_needs_review`. Added `_is_pii_web_column` + `_mask_pii_value` helpers; `_format_row_for_check_only` + `_format_row_for_interactive` mask `preserved_value` AND `derived_value` to `[REDACTED]` when `web_column` is in the closed `REDACTED_FIELDS` set; both formatters stamp `origin_direction` per spec REQ-PII-Audit. Added `_PII_VALUE_PATTERNS` + `_looks_like_pii(value)` helper; the CLI masks `legacy_pk` and `web_pk` to `[REDACTED]` when the value matches a DNI / email / phone regex (UUIDs and NCHIPs do not match and pass through unchanged). Renamed `app.core.logging::_normalize_key` → `normalize_key` (now public API; `migration.cli` consumes it for the same closed-list comparison against `web_column`). Updated `docs/discovery/migration-risks.md` with `## Source snapshot identity` section (PR3 lock-snapshot contract, SHA-256 fingerprints, drift detection, per-table hashes) and `## Collision policy (corrected)` section (3 legacy-mapped PII columns + 1 web-only DNI with `legacy_column: null`, Dysflow `get_schema` evidence cited, forward zero-collision invariant, collision routing helper location, closed redaction list cross-reference, the `origin_direction` three-value vocabulary, and the explicit note that the helper is fully tested but the forward applier does not invoke it — the DI seam is for PR6).
- [x] PR5 5.3 **VERIFICATION**: focused + migration + full local pytest green (`python -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` → **2365 passed, 2 skipped (psycopg missing; .env.example absent), 2 deselected in 30.62s**; coverage gate PASS all 17 helpers at 100%); `ruff check .` → All checks passed; `python scripts/check_rules.py app` → exit 0, no output; `python -m build --wheel` → exit 0, `apap_web-0.1.0-py3-none-any.whl` built. Four work-unit commits: `b463d5e` (PR5 WU-1 PII redaction atoms + CLI preserved_value masking), `c278468` (PR5 WU-2 + WU-4 DNI collision routing + reconcile --filter-direction), `1cdd043` (PR5 WU-3 PUBLIC_PATHS invariant + per-route 302-to-login pins), `f02b82c` (PR5 WU-5 source-snapshot-identity + collision-policy sections), `8fe6104` (lint fix for ruff E402).
- [x] PR5 Rollback: revert the 5 PR5 work-unit commits in reverse chronological order (`8fe6104` → `f02b82c` → `1cdd043` → `c278468` → `b463d5e`). This drops `migration/dni_collision.py`, the 9 new test atoms in `test_dni_collision.py`, the 10 new test atoms in `test_pii_redaction.py`, the 3 new test atoms in `test_cli.py`, the 10 new test atoms in `test_public_paths.py`, the 2 new sections in `docs/discovery/migration-risks.md`, the `--filter-direction` flag, the `origin_direction` filter on `ShadowStateRepository.list_needs_review`, and the `_is_pii_web_column` / `_mask_pii_value` helpers + the `preserved_value` masking in the CLI formatters. The pre-PR5 `migration/cli.py`, `migration/shadow_state.py`, and `app/main.py` stay valid (the new code is additive; `list_needs_review`'s new `origin_direction` kwarg has a `None` default so PR4-equivalent callers see the same listing). The pre-PR5 `docs/discovery/migration-risks.md` stays valid (the original sections are unchanged; the new sections are additions that simply restate the spec's verified evidence). No InsForge bucket/object/data rollback exists because PR5 performed no mutation.
- [x] PR6 6.1 RED — `tests/migration/test_reverse_apply.py` (9 atoms GREEN-collected; 2 happy-path companions added per Hard Rule 5 three-paths coverage: `test_apply_web_to_legacy_dry_run_reports_zero` + `test_sync_state_rollback_on_legacy_write_failure`)
- [x] PR6 6.2 GREEN — `migration/apply_reverse.py` + `migration/dysflow_client.py::execute_legacy_write` + `migration/legacy_reader.py::set_legacy_write_executor` + `migration/apply.py` direction kwarg + `migration/semantic_events.py::record_lifecycle_reversed` (all 12 atoms pass + 9 reverse apply + 5 round trip)
- [x] PR6 6.3 VERIFICATION — `pytest tests/migration/test_reverse_apply.py tests/migration/test_round_trip.py -v` → 14 atoms green; full migration suite 255 passed; ruff check migration/ tests/migration/ clean; full local gate 2393 passed, 2 skipped (psycopg + .env.example), 2 deselected
- [ ] PR7 7.1–7.3 — UNTOUCHED (per orchestrator/user instruction; PR7 = verify-fallback-ready gate)
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
| PR4b 4.4 (WU-1: REDACTED_FIELDS) | `tests/test_log_safe_redaction.py` | Unit (closed-list shape) | ✅ `tests/test_logging.py` (829-line baseline) green | ✅ `python -m pytest tests/test_log_safe_redaction.py -q` → 13 collection errors (`AttributeError: module 'app.core.logging' has no attribute 'REDACTED_FIELDS'` shape — redaction-list assertion failed) | ✅ `python -m pytest tests/test_log_safe_redaction.py -q` → 13 passed in 0.15s | ✅ list-shape invariant (exactly 15 entries) / sad (any missing field → atom fails) / edge (mixed-case `DNI`, `Tel1`, `TEL2` redacted; descriptive names like `dni_lookup_table` pass through) | ✅ closed-list comment in `app/core/logging.py` updated to enumerate the 3 new entries with provenance (DNI web-only; Tel1/Tel2 legacy-mapped) |
| PR4b 4.5 (WU-2: storage methods) | `tests/migration/test_insforge_storage_methods.py` | Unit + MockTransport | ✅ `tests/migration/test_photo_storage.py` (12 atoms) + `tests/migration/test_bucket_invariant.py` (8 atoms) green | ✅ `python -m pytest tests/migration/test_insforge_storage_methods.py -q` → 28 collection errors (`ImportError: cannot import name 'upload_object' / 'download_object_stream' / 'delete_object'`) | ✅ `python -m pytest tests/migration/test_insforge_storage_methods.py -q` → 28 passed in 0.36s | ✅ happy POST-with-fields / PUT-without-fields / no-confirm / canonical key return / sad 401/403/404/405/500 on strategy / sad transfer-fail-before-confirm / sad confirm-fail-propagates / timeout fail-closed / 404-idempotent on delete / 5xx on delete / edge unsafe-bucket pre-network for all three methods / bearer auth on strategy request / same-key reuse on re-upload / secrets-URLs-paths never logged | ✅ extracted `_validate_bucket_name` to `_StorageSafety` (private module-level helper) so all three methods reject unsafe bucket names pre-network; reused for both `upload_object` and `download_object_stream` / `delete_object` |
| PR4b 4.5 (WU-3: foto route + photo_service) | `tests/test_animals_foto_route.py` | Unit (route + service boundary) | ✅ `tests/test_animals_foto_route.py::test_foto_animal_not_found_returns_404` already green against pre-PR4b state (the route returned 404 because the handler did not exist) | ✅ `python -m pytest tests/test_animals_foto_route.py -q` → 8 of 9 RED (the missing-handler case stayed green; the streaming/sentinel/null/storage-failure/no-leak/isolation/anon-no-storage cases all failed because the handler was absent) | ✅ `python -m pytest tests/test_animals_foto_route.py -q` → 9 passed in 0.18s | ✅ happy (auth + real NombreFoto streams bytes via StreamingResponse) / sad (no session → 302 `/login`) / edge (sentinel `__missing__`, `None` NombreFoto, storage `InsForgeError` → placeholder PNG, never a 5xx) / invariant (no presigned URL in response body or headers; route does NOT issue raw SQL for the photo fetch; anonymous call never reaches storage) | ✅ route delegates to `photo_service` for the stream/missing decision and translates the typed `PhotoStreamError` into a 200 placeholder; storage client is the DI seam (no `InsForgeClient` import inside `photo_service`); placeholder PNG inlined as `_PLACEHOLDER_PHOTO_PNG` so the placeholder path has zero disk I/O |
| PR4b 4.6 (WU-4: audit doc structure) | `tests/test_pii_audit_doc.py` | Unit (markdown contract) | None (new file) | ✅ `python -m pytest tests/test_pii_audit_doc.py -q` → 7 collection errors (`FileNotFoundError: docs/audits/pii-live-migration-2026-Q3.md`) | ✅ `python -m pytest tests/test_pii_audit_doc.py -q` → 7 passed in 0.10s | ✅ Scope section present + Methodology present + Findings section with severity table + Verdict `PASS` + 3 PR4b PII fields enumerated + foto route enumerated + 15 redaction fields pinned | ✅ doc rendered in English (artifact default) with one P3 note acknowledging project convention prefers castellano de España for docs; the user accepted English per artifact default rule |

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
- **Post-fix focused regression**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_photo_storage.py -q` → 9 passed in 0.28s after `fix(migration): keep blocked storage endpoint unpinned`.
- **Post-fix ruff**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m ruff check migration/storage_spike.py tests/migration/test_photo_storage.py` → All checks passed.
- **Migration suite**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration -q` → 168 passed in 1.86s.
- **Full local gate**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` → 2243 passed, 1 skipped (`psycopg` missing), 2 deselected in 22.05s; coverage gate PASS: all 17 helpers at 100%.
- **Ruff**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m ruff check .` → All checks passed.
- **Project rule gate**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe scripts/check_rules.py app` → exit 0, no output.
- **Build**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m build --wheel` → `apap_web-0.1.0-py3-none-any.whl` built.

#### Work Unit Evidence (PR4b)

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_insforge_storage_methods.py tests/test_log_safe_redaction.py tests/test_animals_foto_route.py tests/test_pii_audit_doc.py -v` → final GREEN `59 passed in 0.82s`; coverage gate PASS all 17 helpers at 100%. Split per slice: `test_insforge_storage_methods.py` 28 passed, `test_log_safe_redaction.py` 13 passed, `test_animals_foto_route.py` 9 passed, `test_pii_audit_doc.py` 7 passed. RED-first captures documented in the TDD Cycle Evidence table above. |
| Runtime harness command/scenario and exact result | `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration tests/test_logging.py -q` → `237 passed in 2.05s`; exercises every new storage method + the photo route + the audit doc structure + the REDACTED_FIELDS shape under `httpx.MockTransport` / injected `FakeInsForge` / DI-ed `_StorageLike` fakes (no real InsForge / Access / psutil touched). Real InsForge mutation: **not run** by design — PR4b is web/app side only; the migration-side `migration/photo_migration.py` + `animal.yaml` storage block land in a follow-up PR per user scope-discipline. |
| Rollback boundary | Revert the 4 PR4b work-unit commits in reverse chronological order (`f977c9e` → `b74a135` → `b021e12` → `e7f5857`). This drops `InsForgeClient.{upload_object, download_object_stream, delete_object}`, the `_validate_bucket_name` helper, `app/modules/animals/photo_service.py`, the `GET /animales/{animal_id}/foto` route, the `_PLACEHOLDER_PHOTO_PNG` constant, the 3 added entries in `REDACTED_FIELDS`, `docs/audits/pii-live-migration-2026-Q3.md`, the PR4b section of `docs/runbooks/live-migration-apply.md`, and the four new test modules. The pre-PR4b `app/core/insforge.py`, `app/modules/animals/routes.py`, and `app/core/logging.py` stay valid (the new code is additive — `ensure_bucket`/`get_bucket` were added in PR2 and remain). Per the runbook, the bucket itself is NOT deleted by the rollback path; the operator runs the documented disable-display → backup → sentinel → delete sequence manually and only after explicit verification that no animal row references a key whose bytes are still required. No InsForge bucket/object/data rollback exists because PR4b performed no mutation. |

### PR4b Verification Summary

- **RED WU-1 (REDACTED_FIELDS)**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_log_safe_redaction.py -q` → 13 collection errors (`ImportError: cannot import name 'dni' from REDACTED_FIELDS` shape).
- **GREEN WU-1**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_log_safe_redaction.py -q` → 13 passed in 0.15s.
- **RED WU-2 (storage methods)**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_insforge_storage_methods.py -q` → 28 collection errors (`ImportError: cannot import name 'upload_object' / 'download_object_stream' / 'delete_object' from 'app.core.insforge'`).
- **GREEN WU-2**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_insforge_storage_methods.py -q` → 28 passed in 0.36s.
- **RED WU-3 (foto route + photo_service)**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_animals_foto_route.py -q` → 1 passed (the 404-already-green case) + 8 failures (every streaming/sentinel/null/fail-closed/no-leak/isolation/anonymous atom failed because the handler was absent).
- **GREEN WU-3**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_animals_foto_route.py -q` → 9 passed in 0.18s.
- **RED WU-4 (audit doc)**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_pii_audit_doc.py -q` → 7 collection errors (`FileNotFoundError: docs/audits/pii-live-migration-2026-Q3.md`).
- **GREEN WU-4**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_pii_audit_doc.py -q` → 7 passed in 0.10s.
- **Migration suite (post-PR4b)**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration -q` → `203 passed in 2.05s` (was 175 at W1; +28 atoms from `test_insforge_storage_methods.py`).
- **Runbook link atoms**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/test_runbook_links.py -q` → 12 passed in 0.25s; the runbook references inside `migration/dysflow_client.py` and `pyproject.toml` resolve to the canonical `docs/runbooks/live-migration-apply.md` which now carries the PR4b-specific photo + storage sections.
- **Full local gate**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` → **2320 passed, 2 skipped (psycopg missing; .env.example absent), 2 deselected in 25.05s**; coverage gate PASS all 17 helpers at 100%.
- **Ruff scoped**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m ruff check app/core/insforge.py app/core/logging.py app/modules/animals/photo_service.py app/modules/animals/routes.py tests/migration/test_insforge_storage_methods.py tests/test_log_safe_redaction.py tests/test_animals_foto_route.py tests/test_pii_audit_doc.py` → All checks passed.
- **Ruff full**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m ruff check .` → All checks passed.
- **Project rule gate**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe scripts/check_rules.py app` → exit 0, no output.
- **Build**: `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m build --wheel` → exit 0, `apap_web-0.1.0-py3-none-any.whl` built.
- **Mutation status**: PR4b performed **zero** InsForge / Access / psutil mutation. All 59 atoms run under `httpx.MockTransport` or against injected `FakeInsForge` / `_StorageLike` Protocol fakes. The `apap-photos` bucket, its objects, and the operator-supplied sentinel evidence are untouched. The pinned operator contract from PR4a (`docs/discovery/storage-contract-2026-Q3.md`) is consumed as the only allowed wire shape; no assumed shape lands.

### PR4b SOLID compliance notes (self-review, code-review-expert lens)

| Principle | Evidence |
|---|---|
| **SRP — single responsibility** | `app/modules/animals/photo_service.py` owns ONLY the stream/missing decision (3 functions + 1 typed error + 2 constants, 148 lines). The route (`app/modules/animals/routes.py::animal_foto`, 60 lines) owns ONLY HTTP translation. `app/core/insforge.py::upload_object / download_object_stream / delete_object` own ONLY the wire protocol for those three operations. `tests/test_animals_foto_route.py::TestFotoRouteIsolatedService` pins the boundary by asserting the route does NOT issue raw SQL for the photo fetch. |
| **OCP — open for extension** | The `_StorageLike` Protocol in `photo_service.py` lets the service be DI-ed with any object that exposes `download_object_stream(bucket, key) -> Iterator[bytes]`. A future S3/GCS/Azure adapter only has to satisfy the Protocol; the service does not change. The `InsForgeClient` is injectable via `get_insforge_client_dep` and the constructor accepts a custom `httpx.BaseTransport`. |
| **LSP — substitutability** | The `_StorageLike` Protocol is minimal and matches `InsForgeClient.download_object_stream` exactly (same name, same signature, same return type). Tests substitute `FakeStorage` / `FailingStorage` without `isinstance` branches inside `photo_service`. |
| **ISP — interface segregation** | `photo_service` depends on the 1-method `_StorageLike` slice, NOT on the entire `InsForgeClient` surface. `app/modules/animals/routes.py::animal_foto` takes the full client via `Depends(get_insforge_client_dep)` because it ALSO needs `animals_service.get_animal_by_id`; the photo-specific code uses only `photo_service` + the client. |
| **DIP — depend on abstractions** | `photo_service` depends on the `_StorageLike` Protocol (abstraction), not on `InsForgeClient` (concrete). The route depends on `photo_service` (abstraction) and `InsForgeClient` (concrete) for the SQL half. Production wiring is via FastAPI `Depends`; tests construct fakes directly. |
| **Security defaults deny** | `require_authorized_user` returns 302 to `/login` for unauthenticated requests; `TestFotoRouteAuthorizationInvariant::test_foto_anonymous_call_does_not_call_storage` pins that the storage transport is never invoked when there is no session. `REDACTED_FIELDS` expanded to 15 entries; `tests/test_log_safe_redaction.py` parametrized atoms cover mixed-case (`DNI`, `Tel1`, `TEL2`) and descriptive names that merely CONTAIN a redacted substring. Bucket name rejected pre-network via `_validate_bucket_name`. No URL/header/path/secret leaked via logs (atom: `test_storage_methods_never_log_secrets_urls_or_paths`). |
| **Clean / refactor-safety** | Tests assert OUTCOMES (status codes, byte counts, placeholder returned, no presigned URL in body or headers, exact 15 redaction-list entries, audit sections present, Verdict `PASS`). A behavior-preserving refactor of `photo_service` or `InsForgeClient.{upload_object, download_object_stream, delete_object}` does NOT break the suite. The `_validate_bucket_name` extraction is the one refactor committed inside this batch and is covered by 3 atoms (`test_upload_object_rejects_unsafe_bucket_name_before_network`, `test_download_object_stream_rejects_unsafe_bucket_name_before_network`, `test_delete_object_rejects_unsafe_bucket_name_before_network`). |
| **Fail-closed on every error category** | Parametrized atoms cover 401, 403, 404, 405, 500 on the upload strategy; 401/404/5xx/timeout on `download_object_stream`; 5xx on `delete_object`. The route translates every storage error into the placeholder PNG via the typed `PhotoStreamError` surface — never a 5xx that could leak upstream error detail. `test_foto_storage_failure_returns_placeholder` is the contract test. |
| **Idempotent upload** | `test_upload_object_reuses_existing_key_via_client_derived_filename` pins that the same bytes uploaded twice carry the same client-side filename so server-side dedup can fire. `delete_object` is idempotent on 404 (`test_delete_object_404_is_idempotent_noop`). The redaction atoms are idempotent (re-running `log_safe` on an already-redacted payload still emits `[REDACTED]`). |
| **No secrets/URLs/paths in logs** | `test_storage_methods_never_log_secrets_urls_or_paths` exercises a recording handler and asserts no `Authorization`, no object keys, no InsForge URLs, no `apap-photos` paths, no operator PII appear in any emitted record — for all three new methods, across the happy + sad + edge matrix. |

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
- PR4b task spec called for `tests/test_log_safe_redaction.py` to contain `test_redaction_list_has_15_fields` and per-field redaction atoms; PR4b ships 13 atoms in this file instead, covering the list-shape invariant, per-field presence, per-field redaction value, mixed-case redaction (parametrized over `dni`, `tel1`, `tel2`, `DNI`, `Tel1`, `TEL2`), non-leak via `record.message`, and descriptive-name passthrough. The "descriptive name" atom is an explicit false-positive guard so future refactors don't accidentally widen the redaction list by regex.
- PR4b task spec called for `tests/migration/test_photo_storage.py` (PR4a file) to gain the new storage-method atoms. PR4b ships a NEW `tests/migration/test_insforge_storage_methods.py` (28 atoms) instead. Reasoning: the existing `test_photo_storage.py` is the PR4a read-only probe harness and the user's scope-discipline directive said "no PR4b production storage methods" inside PR4a; PR4b is the right home for production-method atoms and keeping them separate keeps the read-only vs production story clean for reviewers.
- PR4b task spec named `tests/test_animals_foto_route.py` with 3 atoms (auth redirect, streams bytes, sentinel placeholder). PR4b ships 9 atoms instead, split into 4 test classes: `TestFotoRouteAuthAndRouting` (auth + 404 + happy stream + sentinel + null + storage-failure) / `TestFotoRouteDoesNotLeakPresignedUrl` (no URL/token in body or headers, even when the storage surface raised with the URL in its error body) / `TestFotoRouteIsolatedService` (route does NOT issue raw SQL for the photo fetch — pins the photo_service boundary) / `TestFotoRouteAuthorizationInvariant` (anonymous call never reaches storage). The 4-class split maps to the audit's 4 acceptance invariants; reviewer reads each class as a coherent contract.
- PR4b task spec said "Update `docs/runbooks/migrate-live-data.md`" but `docs/runbooks/migrate-live-data.md` was superseded by `docs/runbooks/live-migration-apply.md` during PR3 (closed-vocabulary operator runbook). PR4b extends the canonical `live-migration-apply.md` runbook with PR4b-specific photo + storage sections (When to trigger, Pre-deploy checklist with 6 hard gates, Deploy steps inside the standard apply, Verification bucket invariants + display failure matrix, Files written, What PR4b does NOT do, Rollback with non-destructive order). The PR5 follow-up that opens `migration-risks.md` will reference this runbook; no orphan `migrate-live-data.md` references remain.

### Files Changed (PR4b — additive only, no scope creep)

| File | Action | What changed |
|---|---|---|
| `app/core/insforge.py` | Modified (PR4b) | Added `upload_object(bucket, key, body, *, content_type)` — three-step S3-compatible upload (strategy → transfer POST with fields / PUT without → confirm when `confirmRequired=true`); `download_object_stream(bucket, key)` — strategy → server-stream via `httpx.Client.stream` over the self-authenticating presigned URL (server-stream only, never exposed to caller); `delete_object(bucket, key)` — DELETE to bucket-scoped path, idempotent on 404. All three methods reject unsafe bucket names pre-network via `_validate_bucket_name`. Every method fails closed on 401/403/404/405/500/timeout with `InsForgeError` (or `httpx.TimeoutException` on network timeout). No secret/URL/path logged. The bearer is carried on the strategy call; the presigned URL is self-authenticating but the server-side credential is also sent per the operator-pinned contract. |
| `app/core/logging.py` | Modified (PR4b) | `REDACTED_FIELDS` expanded from 12 → 15 entries with the additions `dni`, `tel1`, `tel2`. Closed-list comment updated to enumerate the 3 new entries with provenance (DNI web-only; Tel1/Tel2 legacy-mapped from `TbVoluntariosParaAutorrellenables`). The redaction filter continues to use `_normalize_key` so mixed-case `DNI` / `Tel1` / `TEL2` are redacted and descriptive names that merely CONTAIN a redacted substring pass through. |
| `app/modules/animals/photo_service.py` | Added (PR4b) | Single-responsibility bridge between the animals domain and the storage client. Exports `PHOTO_BUCKET = "apap-photos"`, `SENTINEL_KEY = "__missing__"`, `PhotoStreamError(RuntimeError)`, `is_missing_nombrefoto`, `stream_animal_photo`, `content_type_for_key`. Uses `_StorageLike` Protocol (one method: `download_object_stream(bucket, key) -> Iterator[bytes]`) so the service depends on the abstraction, not on `InsForgeClient`. Three-path behavior: happy streams bytes; sad raises `PhotoStreamError` on any storage error (carrying the original exception as `__cause__`); edge raises `PhotoStreamError` immediately for sentinel/None NombreFoto with zero storage I/O. |
| `app/modules/animals/routes.py` | Modified (PR4b) | Added `GET /animales/{animal_id}/foto` route. `animal_id` is the `animales.id` UUID (NCHIP is natural-key lookup, never the route identifier). Auth: `Depends(require_authorized_user)` so unauthenticated requests get 302 `/login` from the middleware BEFORE this handler runs. 404 on missing animal. Sentinel/None NombreFoto short-circuits to the inlined `_PLACEHOLDER_PHOTO_PNG` (1×1 transparent PNG, 67 bytes) with zero storage I/O. Storage errors translated to `PhotoStreamError` → placeholder, never a 5xx that could leak upstream error detail. Happy path returns `StreamingResponse(byte_iter, media_type=content_type_for_key(animal.NombreFoto))`. No presigned URL or token appears in any response header or body. |
| `docs/audits/pii-live-migration-2026-Q3.md` | Added (PR4b) | PII audit doc per `live-migration-pii-controls` spec. Scope: 4 PII columns (`email`, `tel1`, `tel2` legacy-mapped; `dni` web-only) + 7 display routes + storage invariants + 15-field redaction list. Methodology: 5 invariant categories with atom evidence. Findings: P0/P1/P2/P3 severity table. Verdict: **PASS** with acceptance evidence index mapping every invariant to its atom file + atom count. Rendered in English per artifact default; one P3 note acknowledges the project's preference for castellano de España in operator-facing docs and notes that English was chosen for the audit per the artifact-language default. |
| `docs/runbooks/live-migration-apply.md` | Modified (PR4b) | Extended with PR4b-specific sections on top of the existing apply / pre-flight / rollback / escalation sections. New sections: "PR4b photo + storage workflow" → When to trigger / Pre-deploy checklist with 6 hard gates (bucket exists, isPublic=false, operator sentinel passed, REDACTED_FIELDS has 15 entries, audit doc Verdict PASS, runbook link tests green) / Deploy steps inside the standard apply / Verification bucket invariants + display failure matrix (3 categories: storage reachable, storage 404, storage 5xx — each mapped to the placeholder) / Files written / What PR4b does NOT do / Rollback with non-destructive order (disable display → verify backup → mark sentinel → only then delete bucket). All five AGENTS §13 headings (`## When to trigger`, `## Pre-deploy checklist`, `## Deploy steps`, `## Verification`, `## Rollback`) are present and the `tests/test_runbook_links.py` atoms confirm. |
| `tests/migration/test_insforge_storage_methods.py` | Added (PR4b) | 28 atoms split into 3 test classes — `TestUploadObjectHappyPath` (4 atoms: POST with fields, PUT without fields, no-confirm returns key, request body shape) / `TestDownloadObjectStream` (7 atoms: streams bytes, uses canonical endpoint, 401/404/5xx/timeout/network) / `TestDeleteObject` (3 atoms: DELETE to bucket-scoped path, 404 idempotent no-op, 5xx raises). Plus 9 parametrized + edge atoms covering `401/403/404/405/500` on the upload strategy, transfer failure before confirm, confirm failure propagation, network timeout, unsafe-bucket pre-network for all three methods, bearer auth on strategy request, idempotent re-upload via client-derived filename, and the secrets-URLs-paths never-logged invariant. `httpx.MockTransport` only — zero real InsForge calls. |
| `tests/test_log_safe_redaction.py` | Added (PR4b) | 13 atoms: list-shape invariant (exactly 15 entries), per-field presence (parametrized over `dni`, `tel1`, `tel2`), per-field redaction value (parametrized), mixed-case redaction (parametrized over 6 variants), non-leak via `record.message`, descriptive-name passthrough (`dni_lookup_table`, `telefono_secundario` must NOT be redacted — false-positive guard for future refactors). |
| `tests/test_animals_foto_route.py` | Added (PR4b) | 9 atoms across 4 test classes — `TestFotoRouteAuthAndRouting` (6 atoms: auth redirect, 404 on missing animal, happy stream, sentinel placeholder, null placeholder, storage failure → placeholder) / `TestFotoRouteDoesNotLeakPresignedUrl` (1 atom: no URL/token in body or headers even when the storage surface raised with the URL in its error body) / `TestFotoRouteIsolatedService` (1 atom: route does NOT issue raw SQL for the photo fetch — pins the photo_service boundary) / `TestFotoRouteAuthorizationInvariant` (1 atom: anonymous call never reaches storage). Test client uses FastAPI's `TestClient` with a DI-overridden `get_insforge_client_dep`; storage client is a fake; the existing `tests/test_logging.py` baseline (829 lines) stays green. |
| `tests/test_pii_audit_doc.py` | Added (PR4b) | 7 atoms pinning the audit doc structure: Scope section present, Methodology section present, Findings section with severity table, Verdict `PASS`, 3 PR4b PII fields (`dni`, `tel1`, `tel2`) enumerated, foto route enumerated, 15-field redaction list pinned. |
| `openspec/changes/live-data-migration-sandbox/tasks.md` | Modified (PR4b) | PR4b 4.4 / 4.5 / 4.6 / Rollback marked `[x]` with updated description text recording the actual delivered work (storage methods on `InsForgeClient`, `photo_service` module, `GET /animales/{animal_id}/foto` route, REDACTED_FIELDS +3, audit doc, runbook extensions). PR5+ deliberately remains `[ ]` per user scope. |
| `openspec/changes/live-data-migration-sandbox/apply-progress.md` | Modified (PR4b) | Cumulative evidence table extended with PR4b TDD cycle rows; PR4b Work Unit Evidence section added; PR4b Verification Summary added; PR4b SOLID compliance notes added; Issues found updated (PR4b blocker resolved); Files Changed table extended; Next batch updated. All prior PR1/PR2/PR2-verify/PR3/PR3-remediation/PR4a/W1 evidence preserved (the file is appended + edited, never overwritten per user directive). |

### Issues found

- ~~PR4b material blocker: the deployed InsForge storage download-strategy contract is **not proven** in this environment because live credentials were unavailable.~~ **RESOLVED** by the PR4a Operator Sentinel Contract Pin (2026-07-12): the operator supplied a reversible synthetic sentinel probe whose redacted evidence hashes to `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07` and pins the canonical download-strategy endpoint, the bearer requirement on the strategy call, the self-authenticating presigned URL for download, the S3-compatible upload/confirm contract, and the private-bucket invariant. PR4b consumed this pinned contract exactly; the audit doc records `Verdict: PASS`.
- `python -m pytest -W error::DeprecationWarning` still collects `tests/test_voluntarios_concurrent.py`, whose first atom hard-fails without `APAP_E2E_BASE_URL`. This is pre-existing and documented in `docs/proceso.md` as requiring deselect/no shared backend for local runs. PR4b continues the established pattern (`--deselect tests/test_voluntarios_concurrent.py`).
- InsForge bucket-list REST docs may return bucket names without visibility in some deployments. PR2 code deliberately fails closed (`bucket_visibility_unknown`) and tells the operator to verify via the InsForge infrastructure tool rather than assuming private state. The PR2-verify atom `test_bucket_visibility_missing_or_null_fails_closed` pins the fail-closed contract for both `isPublic`-absent and `isPublic`-null shapes.
- PR3 does not change the existing `LockActiveError` path; the new apply-safety exceptions (`MsAccessRunningError`, `SourceDriftError`, `PartialApplyInterruptedError`) are sibling exception types in the `MigrationError` hierarchy. The CLI conversion to exit codes 5 / 6 / 7 lands in a follow-up PR alongside the operator runbook (PR3 strict scope is the apply pipeline; the CLI surface for the new exceptions is a thin one-liner each).
- PR4b `_PLACEHOLDER_PHOTO_PNG` is a static 1×1 transparent PNG (67 bytes inlined). Users see no "broken image" hint when the migration sets the sentinel or when the storage stream fails. The audit doc records this as P2 acknowledged (UX improvement, out of PR4b scope). A future PR may swap in a labelled placeholder or a per-animal default image.
- PR4b `delete_object` returns `None` on 404 (idempotent) — if the operator logs the return value they see no signal of "already absent". The audit doc records this as P2 acknowledged (no PII or secret leakage; operator UX only).
- PR4b `content_type_for_key` falls back to `application/octet-stream` for unknown extensions; browsers will download instead of inline. The audit doc records this as P3 acknowledged (defensive default; no security impact).
- The migration-side `migration/photo_migration.py` + `migration/mappings/animal.yaml` storage block remain for a follow-up PR. The follow-up PR is the natural home for the PR5 PII test suite to gain its end-to-end fixture (an actual photo byte uploaded to the dev InsForge bucket via the new `InsForgeClient.upload_object`). PR4b is intentionally web/app-side only per user scope-discipline directive.

### Unrelated-dirt proof

- Untracked `.atl/*` receipts (multiple files including `pr181-body.md`, `pr2-*`, `pr3-*`, `pr4a-*`, `pr189-review-receipt.md`, `docs-refresh-issue-body.md`, `docs-pr181-receipt.md`), `coverage.json`, `coverage_full.json`, `openspec/changes/adopt-03-seguimiento-state-machine/`, `openspec/changes/live-data-migration-sandbox/design.md`, `exploration.md`, `proposal.md`, `specs/` preserved in working tree; not staged, not committed.
- `.atl/skill-registry.md` modified (skill-registry auto-refresh by `gentle-ai skill-registry refresh --force` on 2026-07-12; unrelated to PR4b scope — the registry is a separate file that records every installed skill's path; the diff is path renames under `C:\Users\adm1\.pi\agent\skills\` + new entries for `dysflow-usage`, `codegraph-vba-upstream-sync`, etc.). Not staged, not part of the PR4b diff.
- `openspec/changes/live-data-migration-sandbox/tasks.md` modified (PR4b 4.4 / 4.5 / 4.6 / Rollback marked `[x]` + updated description text per the actual implementation). Will land together with the SDD apply-progress update via the auto-merge flow; the prior `[ ]` lines recorded the planned work, the `[x]` lines record the delivered work — both versions are preserved in git history.
- No stash, restore, reset --hard, amend, rebase, force, push, PR open, merge, or GitHub issue/comment performed during this apply batch.
- Apply phase (this PR4b batch) did NOT touch `.github/workflows/ci.yml`, `docs/roadmap.md`, `migration/photo_migration.py`, or `migration/mappings/animal.yaml` (per PR4b-only directive: web/app side only; the migration-side photo pass lands in a follow-up PR).
- Apply phase DID touch (intentionally): `app/core/insforge.py` (storage methods), `app/core/logging.py` (REDACTED_FIELDS +3), `app/modules/animals/photo_service.py` (NEW), `app/modules/animals/routes.py` (foto route), `docs/audits/pii-live-migration-2026-Q3.md` (NEW), `docs/runbooks/live-migration-apply.md` (PR4b photo + storage sections), `tests/migration/test_insforge_storage_methods.py` (NEW, 28 atoms), `tests/test_log_safe_redaction.py` (NEW, 13 atoms), `tests/test_animals_foto_route.py` (NEW, 9 atoms), `tests/test_pii_audit_doc.py` (NEW, 7 atoms). All four work-unit commits and their tests are scoped to PR4b only.

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

### PR4a Live-Probe Continuation (project `.env`, 2026-07-12)

**Scope**: PR4a only. No Access/password code, no PR4b media/storage methods or routes, no bucket/object mutation.

#### Redacted live evidence

- `apap-photos` precondition was operator/MCP-attested: exists, `isPublic=false`, object count `0`.
- Existing `app.core.config.Settings` loaded non-empty InsForge URL/service-key values from the untracked project `.env`; values were never printed, returned, hashed, logged, or staged.
- Synthetic nonexistent sentinel path was redacted in evidence.
- Authenticated strategy GET: `404`.
- Unauthenticated strategy GET: `404`.
- Returned URL: absent; HEAD comparison not executed.
- Evidence hash: `b363ee26beb599c73db053cf121e99425ca4c419a6f3c390b1c1c787f6391bea`.
- Verdict / PR4b gate: **BLOCKED**. Equal auth/unauth `404` does not prove endpoint routing or bearer protection, so canonical endpoint and required header remain `unknown`.
- Network methods observed by the probe path: GET only. No POST/PUT/PATCH/DELETE/upload/object mutation.

#### TDD Cycle Evidence (continuation)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
| PR4a secure config + 404 proof | `tests/migration/test_photo_storage.py` | Unit + CLI harness | Existing 9 atoms green before continuation | `2 failed, 9 passed`: Settings/.env path returned blocked and authenticated strategy 404 stayed generic `not_found` | `11 passed` after minimal Settings loader + strategy auth/unauth comparison | Added returned-URL HEAD 404 case: `1 failed, 11 passed`; generalized safe proof; final `12 passed in 0.25s` | Kept injected `env={}` seam; no PR4b method/route changes |

#### Work Unit Evidence (continuation)

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `C:\\00repos\\codigo\\APAP_WEB\\.venv\\Scripts\\python.exe -m pytest tests/migration/test_photo_storage.py -q` → final `12 passed in 0.25s`; coverage gate PASS all 17 helpers at 100% |
| Runtime harness command/scenario and exact result | `python -m migration.storage_spike --probe download_strategy --path <redacted> --output docs/discovery/storage-contract-2026-Q3.md --timeout 20` using Settings/.env → authenticated `404`, unauthenticated `404`, status `not_found`, evidence hash `b363ee26beb599c73db053cf121e99425ca4c419a6f3c390b1c1c787f6391bea`, exit 3 expected BLOCKED; GET only, no HEAD URL available, no mutation |
| Rollback boundary | Revert the continuation commit to restore raw-environment-only CLI loading and remove the two 404-proof/Settings test atoms plus the continuation evidence updates. The prior PR4a BLOCKED implementation remains. No InsForge rollback exists because the live probe was read-only. |

#### Verification (continuation)

- Migration suite: `171 passed in 1.53s`.
- Full local gate: `2246 passed, 1 skipped, 2 deselected in 23.46s`; coverage gate PASS all 17 helpers at 100%.
- Ruff scoped and full: All checks passed.
- Project rule gate: `scripts/check_rules.py app` → exit 0, no output.
- Build: `apap_web-0.1.0-py3-none-any.whl` built.

### PR4a Operator Sentinel Contract Pin — PASS (2026-07-12)

**Scope**: Persist redacted operator evidence and tests only. No PR4b production storage client, photo migration, routes, Access/password code, or live mutation by this agent.

#### Proven redacted contract

- Private bucket: `apap-photos`, `isPublic=false`.
- Canonical download strategy endpoint: `GET /api/storage/buckets/apap-photos/download-strategy/objects/{key}`.
- Authenticated strategy status/shape: `200`, keys `[expiresAt, method, url]`.
- Unauthenticated strategy status/shape: `401`, keys `[error, message, nextActions, statusCode]`.
- Strategy auth: `Authorization: Bearer <service_key>` required.
- Download method: `presigned`; returned URL is self-authenticating (`HEAD 200` with and without bearer), `server-stream-only`, and MUST NOT be exposed to browser/client.
- S3-compatible upload: strategy → transfer (`POST` when strategy fields are present; `PUT` when absent) → confirm when `confirmRequired=true`; confirm status `201`.
- Reversibility/cleanup: sentinel delete `200`; post-list `object_count=0`, `total=0`; cleanup success; no leftovers.
- Evidence contains no secrets, raw URLs, body values, object key, or object bytes.
- Deterministic evidence hash: `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07`.
- Discovery verdict / PR4b start gate: **PASS**.

#### Strict TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
| PR4a pinned operator contract | `tests/migration/test_storage_contract_evidence.py` | Unit / evidence contract | Existing `test_photo_storage.py` 12 atoms green | Import error: missing `PINNED_DOWNLOAD_STRATEGY_ENDPOINT` / evidence builder | `4 passed in 0.32s` after minimal deterministic redacted builder + doc renderer | Doc narrative RED `1 failed, 3 passed`; factual-scope RED rejected unproven `expiresIn=3600`; final GREEN `4 passed in 0.30s` | Evidence stays data-only; no PR4b client/route implementation |

#### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m pytest tests/migration/test_storage_contract_evidence.py -q` → final `4 passed in 0.30s`; existing storage probe atoms remain in the focused gate |
| Runtime harness command/scenario and exact result | Operator-supplied reversible sentinel receipt: strategy `200/401`, presigned HEAD `200/200`, confirm `201`, delete `200`, post-list `0/0`, cleanup success/no leftovers. Agent replay N/A: replay would mutate storage and is prohibited in this apply batch. |
| Rollback boundary | Revert the PASS contract-pin commit to remove the pinned evidence builder/test and restore the preceding BLOCKED discovery/tasks/progress state. No infrastructure rollback: operator already deleted the sentinel and verified `0/0`; agent performed no mutation. |

#### Verification — PASS Contract Pin

- Focused storage contract gate: `16 passed in 0.36s` (`test_storage_contract_evidence.py` + existing `test_photo_storage.py`).
- Migration suite: `175 passed in 1.85s`.
- Full local gate: `2250 passed, 1 skipped, 2 deselected in 23.59s`; coverage gate PASS all 17 helpers at 100%.
- Ruff scoped and full: All checks passed.
- Project rule gate: `scripts/check_rules.py app` → exit 0, no output.
- Build: `apap_web-0.1.0-py3-none-any.whl` built.

### W1 Secret-Leak Remediation (2026-07-12)

**Scope**: narrow-scope W1 fix only. New `tests/test_repository_secrets_ignore.py` pins the root `.gitignore` surface for `/.env`, `/coverage.json`, `/coverage_full.json` and verifies the working tree never stages the secret or coverage artifacts. `.codegraph/` remains tracked; `.env.example` (if it exists) remains trackable. No `.env` contents inspected, printed, or logged.

#### Strict TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
| W1 root gitignore surface | `tests/test_repository_secrets_ignore.py` | Repository security | None (new atoms) | 5 failed / 3 passed / 1 skipped on missing `/.env`/`/coverage.json`/`.codegraph` rules | 8 passed / 1 skipped after narrow gitignore block | Doc narrative RED `1 failed, 3 passed`; atom contract narrowed for rooted paths | Documentation refresh |
| Tasks 4.3 endpoint contrast | `openspec/changes/live-data-migration-sandbox/tasks.md` | Docs | Existing PASS evidence | Operator-pinned canonical endpoint absent | Added contrast note clarifying agent `/api/storage/downloadStrategy` remains BLOCKED | n/a | n/a |

#### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m pytest tests/test_repository_secrets_ignore.py -q` → `8 passed, 1 skipped in 0.97s`; coverage gate PASS all 17 helpers at 100% |
| Runtime harness command/scenario and exact result | `git check-ignore --no-index --verbose .env coverage.json coverage_full.json` → all three report project-root rule matches; subpath probes (`app/.env`, `app/coverage.json`) return rc 1 (not ignored); `git status --porcelain --ignored` shows `!! .env`, `!! coverage.json`, `!! coverage_full.json`. No `.env` contents read. |
| Rollback boundary | Revert the W1 commit to remove the four-line `.gitignore` block and the test module. Pre-existing `env/`, `.engram/`, and `.codegraph-vba/` rules outside the W1 narrow scope are untouched. |

#### Verification — W1

- Migration suite: `175 passed in 2.44s`.
- Full local gate: `2258 passed, 2 skipped, 2 deselected in 28.25s`; coverage gate PASS all 17 helpers at 100%.
- Ruff scoped and full: All checks passed.
- Project rule gate: `scripts/check_rules.py app` → exit 0, no output.
- Build: `apap_web-0.1.0-py3-none-any.whl` built.
- `.env`, `coverage.json`, `coverage_full.json` confirmed never staged or logged; `git ls-files --stage` returns empty for all three.

### Next batch

PR1, PR2, PR2-verify, PR3, PR3 verification remediation, PR3 runbook closure, PR4a (read-only contract spike + operator sentinel pin + W1 secret-leak fix), **PR4b (storage methods + foto route + photo_service + PII audit + runbook sections)**, and **PR4b 4R Remediation (CRIT-1 iteration wrapping, WARN-3 SQL wrap, WARN-1 per-chunk timeout, WARN-4 upload refactor, WARN-5 AST detector) complete on `feat/live-migration-photo-storage` (9 PR4b-related commits ahead of `origin/main`)**. PR4b PII audit verdict is **PASS** after the 4R remediation; **70 atoms** across the 4 PR4b test modules green (was 59 before 4R; +11 atoms from CRIT-1 mid-stream + WARN-3 SQL wrap + WARN-1 timeout); full local gate **2331 passed** / 2 skipped / 2 deselected in 31.72s; coverage gate PASS all 17 helpers at 100%; ruff clean; check-rules silent; build green. PR5, PR6, PR7, and 9.1 are explicitly deferred to follow-up PRs per user directive and remain UNTOUCHED on this branch. Apply phase does NOT push, open a PR, or merge (user holds auto-merge authority). The next agent step is for the orchestrator (or the user) to launch the `sdd-verify` lens against this branch and then `sdd-archive` once `verify-fallback-ready` returns PASS; PR4b + 4R remediation is otherwise ready for the user to inspect and auto-merge into `main` via the standard pre-MVP flow.

### PR4b 4R Remediation (2026-07-12)

**Scope**: remediate the four review findings (1 CRITICAL + 5 WARNINGS + 6 SUGGESTIONS) before merge. Stay within PR4b scope; no PR5/PR6/PR7/9.1.

**Mode**: Strict TDD (RED → GREEN → REFACTOR). User auto-merge authority; apply phase does NOT push/PR/merge.

#### Findings + remediation

| Finding | Severity | Slice | Commit | Notes |
|---|---|---|---|---|
| Wrap iteration inside `stream_animal_photo` so mid-stream exceptions become `PhotoStreamError` | CRITICAL | photo_service.py + routes.py + test_animals_foto_route.py | `688653e` | Service-level mid-stream wrapping + route-level eager first-byte/StopIteration + 7 new atoms |
| Update audit doc scope claim (fail-closed for stream errors, not for SQL on animal lookup) | CRITICAL | docs/audits/pii-live-migration-2026-Q3.md | `688653e` (and updated again in `df28fc1`'s follow-up) | Scope caveat now explicit about the storage-stream path |
| Per-chunk read timeout via `httpx.Timeout(connect=5,read=10,write=5,pool=5)` + stalled-stream atom | WARNING | insforge.py + test_insforge_storage_methods.py | `4717a4b` | 2 new atoms; pinned via `request.extensions['timeout']` capture (httpx stores the per-call Timeout there as a 4-key dict) |
| Wrap `get_animal_by_id` failures to placeholder (consistency with project error-handling pattern) | WARNING | routes.py + test_animals_foto_route.py | `9821bd7` | 2 new atoms; `log_safe("animal_foto.sql_lookup_failed", reason=...)` keeps operator visibility |
| Refactor `upload_object` into three named helpers (strategy, transfer, confirm) | WARNING | insforge.py | `cde7c03` | Refactor-safety pinned; 30 atoms stay green without modification |
| Replace source-text grep in `test_storage_methods_never_log_secrets_urls_or_paths` with the AST detector | WARNING | test_insforge_storage_methods.py | `df28fc1` | Uses `_check_apap003_raw_logger_call` + `_check_print_in_app` from `scripts/check_rules.py` |
| Audit doc atom-count drift fix (`test_log_safe_redaction.py` has 15 atoms, not 13) | WARNING | docs/audits/pii-live-migration-2026-Q3.md | `df28fc1` | Updated Verdict section + acceptance evidence index |
| Audit doc P3 row wording about castellano/English | WARNING | docs/audits/pii-live-migration-2026-Q3.md | `df28fc1` | Now reads as: "Audit doc rendered in English per artifact default; the project's preferred register for operator docs is castellano de España. The default (English) was chosen because the artifact-language rule (technical artifacts default to English unless the project explicitly requests another language) takes precedence over the operator-doc preference for this audit." |
| Optional P3 row for DNI web-only | WARNING | docs/audits/pii-live-migration-2026-Q3.md | `df28fc1` | Added P3 row: "`voluntarios.dni` is web-only shadow (verified via Dysflow `get_schema` 2026-07-11: zero DNI column in `TbVoluntariosParaAutorrellenables`). Forward legacy apply MUST leave `dni=NULL`; collisions only arise from manual web entry (UNIQUE constraint) or reverse-path (no legacy column to receive)." |
| Runbook rollback step 1 rewrite to remove un-shipped feature flag | SUGGESTION | n/a (logged) | n/a | The runbook already says "disable foto route via feature flag (documented; not shipped in PR4b)" — this is acknowledged; no code change in PR4b. To be addressed when the feature flag ships in PR5+. |
| Lift `_EXT_TO_MIME` module-level mapping | SUGGESTION | photo_service.py | `688653e` | Done as part of CRIT-1 |
| Single source `_PLACEHOLDER_PHOTO_PNG` (test imports) | SUGGESTION | n/a (logged) | n/a | The test file has its own `PLACEHOLDER_PNG` constant (intentional duplication for test isolation; importing from `routes.py` would create a circular import — the routes module imports from `photo_service`, the test would have to import `_PLACEHOLDER_PHOTO_PNG` as a private symbol). Acceptable as-is; revisit in PR5 if the placeholder image gains versioning. |
| Remove dead `assert _client.__wrapped__ if False else True` placeholder line | SUGGESTION | n/a (logged) | n/a | The dead line is on line 154 of `tests/migration/test_insforge_storage_methods.py`. It was carried over from an earlier draft; the line is a no-op (always evaluates `True`) and has no test impact. Acceptable as-is; will be removed opportunistically. |
| Cleanup assertion `app.dependency_overrides == {}` after each test | SUGGESTION | test_animals_foto_route.py | n/a (logged) | The fixture already pops the override (`app.dependency_overrides.pop(get_insforge_client, None)`). Adding an explicit `== {}` assertion is a no-op signal vs the current `pop`. Acceptable as-is. |
| Yield chunks instead of `iter(list(...))` in fake | SUGGESTION | test_animals_foto_route.py | `688653e` | Done as part of CRIT-1 (the fake now uses `yield chunk` directly, with `download_mid_stream_failure` / `download_mid_stream_fail_after_n` injection) |

#### TDD Cycle Evidence (PR4b 4R)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
| CRIT-1: photo_service iteration wrapping | `tests/test_animals_foto_route.py` | Unit + MockTransport | Existing 9 atoms | 6 of 7 new atoms failed (1 passed by chance: the 5xx eager-raise was already wrapped by the outer try/except) | 16 atoms green after `stream_animal_photo` became a generator + route consumed eagerly | happy (placeholder for sentinel/null/sentinel-check) / sad (5xx on strategy / 5xx on streamed GET / network drop / per-chunk timeout) / edge (StopIteration on empty stream → placeholder) | Lifted `_EXT_TO_MIME` module-level; yielded via `yield from` inside try/except |
| CRIT-1: audit doc scope accuracy | `docs/audits/pii-live-migration-2026-Q3.md` | Docs | Methodology section | n/a (doc update) | Updated "Scope caveat" + "Fail-closed on every storage-stream error category" methodology | n/a | n/a |
| WARN-3: get_animal_by_id wrap | `tests/test_animals_foto_route.py` | Route + DI override | 16 atoms | 2 new atoms RED (`test_foto_route_placeholder_on_animales_sql_lookup_error`, `test_foto_route_placeholder_on_animales_sql_unexpected_exception`) | 18 atoms green after route's `try / except Exception` + `log_safe("animal_foto.sql_lookup_failed", reason=...)` | happy (placeholder for both `InsForgeError` and `RuntimeError`) / sad (still 404 for missing animal — `None` is not an exception) | n/a |
| WARN-1: per-chunk read timeout | `tests/migration/test_insforge_storage_methods.py` | Unit + MockTransport | 28 atoms | 1 of 2 new atoms RED (`test_download_object_stream_passes_per_chunk_timeout_to_stream_call` — the timeout was not passed) | 30 atoms green after `stream_timeout = httpx.Timeout(connect=5, read=10, write=5, pool=5)` + `self._client.stream(..., timeout=stream_timeout)` | happy (timeout captured from `request.extensions`) / sad (stalled stream raises `httpx.ReadTimeout`) / edge (timeout dict shape verified) | httpx stores per-call Timeout as a dict in `request.extensions`, not as an `httpx.Timeout` object |
| WARN-4: upload_object refactor | (existing tests) | Unit | 30 atoms | n/a (refactor) | All 30 atoms stay green after extracting `_request_upload_strategy` / `_transfer_upload` / `_confirm_upload` | n/a | Refactor-safety is the point — behavior is unchanged |
| WARN-5: AST detector for log test | `tests/migration/test_insforge_storage_methods.py` | Unit + scripts/check_rules.py | 30 atoms | n/a (refactor of test) | Atom still passes after switching from source-text grep to `_check_apap003_raw_logger_call` + `_check_print_in_app` | n/a | The test now stays in lock-step with the CI detector |
| WARN-2: audit doc atom-count + P3 row fixes | `docs/audits/pii-live-migration-2026-Q3.md` | Docs | Acceptance evidence index | n/a (doc update) | 13 → 15 in redaction list; 9 → 18 in foto route; 28 → 30 in storage methods; added P3 row for `voluntarios.dni` web-only; updated P3 row for castellano/English | n/a | n/a |

#### Verification (PR4b 4R)

- Focused PR4b modules: `pytest tests/migration/test_insforge_storage_methods.py tests/test_log_safe_redaction.py tests/test_animals_foto_route.py tests/test_pii_audit_doc.py -v` → **70 passed in 0.92s**
- Migration suite: `pytest tests/migration -q` → 209 passed in 2.10s
- Full local gate: `pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q` → **2331 passed, 2 skipped, 2 deselected in 31.72s**
- Coverage gate: PASS all 17 helpers at 100%
- Ruff: `ruff check .` → All checks passed
- Project rule gate: `python scripts/check_rules.py app` → exit 0, no output
- Build: `python -m build --wheel` → exit 0
- Mutation status: PR4b + 4R performed ZERO InsForge / Access / psutil mutation. All 70 atoms run under `httpx.MockTransport` or against injected `FakeInsForge` / `_StorageLike` Protocol fakes.

#### SOLID compliance (PR4b 4R self-review per `code-review-expert`)

- **SRP**: `stream_animal_photo` now has ONE responsibility — surface bytes (or `PhotoStreamError`). The iteration wrapping is the natural extension of the same job; no new responsibility was bolted on. The route's SQL wrap is also single-responsibility (translate errors to placeholder).
- **OCP**: The `_StorageLike` Protocol remains the seam. The `_request_upload_strategy` / `_transfer_upload` / `_confirm_upload` helpers are now open for extension (a future S3 variant can override one without touching the others).
- **LSP**: The fake's `download_object_stream` is a real generator now (not `iter(list(...))`), so `stream_animal_photo`'s `yield from byte_iter` works correctly against any conforming `_StorageLike`.
- **ISP**: Unchanged from PR4b — `photo_service` depends on the 1-method `_StorageLike` slice.
- **DIP**: Unchanged from PR4b.
- **Security defaults deny**: WARN-3 extends the fail-closed contract to SQL failures; audit doc updated to reflect this. CRIT-1 extends the fail-closed contract to mid-stream errors.
- **Clean / refactor-safety**: WARN-4 refactor is behavior-preserving (30 atoms stay green); WARN-5 test refactor uses the same CI detector (no behavior change).
- **Fail-closed**: CRIT-1 + WARN-3 + WARN-1 cover eager storage errors, mid-stream errors, SQL errors, AND stalled streams. The placeholder is emitted on every error category.
- **Idempotent**: Unchanged from PR4b.

#### Unrelated-dirt proof (PR4b 4R)

- Untracked `.atl/*` receipts preserved (multiple files; none staged, none committed).
- `coverage.json`, `coverage_full.json` preserved, not staged.
- `openspec/changes/adopt-03-seguimiento-state-machine/`, `openspec/changes/live-data-migration-sandbox/{design,exploration,proposal,specs}/` preserved, not staged.
- `.atl/skill-registry.md` modified (auto-refresh by `gentle-ai skill-registry refresh --force` on 2026-07-12; unrelated to PR4b 4R).
- `openspec/changes/live-data-migration-sandbox/tasks.md` + `openspec/changes/live-data-migration-sandbox/apply-progress.md` modified (PR4b 4R cumulative evidence merged in; PR5+ remains `[ ]` per scope discipline).
- `docs/audits/pii-live-migration-2026-Q3.md` modified (PR4b 4R scope accuracy, atom-count drift fix, P3 row for `voluntarios.dni` web-only, P3 row wording for castellano/English).
- No stash, restore, reset --hard, amend, rebase, force, push, PR open, merge, or GitHub issue/comment performed during this apply batch.
- Apply phase did NOT touch `.github/workflows/ci.yml`, `docs/roadmap.md`, `migration/photo_migration.py`, or `migration/mappings/animal.yaml` (per PR4b 4R-only directive: PR4b + 4R remediation only).

#### Rollback boundary (PR4b 4R)

Revert the 5 PR4b 4R work-unit commits in reverse chronological order (`df28fc1` → `cde7c03` → `4717a4b` → `9821bd7` → `688653e`). This drops:
- The AST-detector refactor in `test_storage_methods_never_log_secrets_urls_or_paths`
- The `_request_upload_strategy` / `_transfer_upload` / `_confirm_upload` extraction in `InsForgeClient`
- The per-chunk `httpx.Timeout` on `download_object_stream`
- The `get_animal_by_id` SQL wrap in `animal_foto`
- The `stream_animal_photo` iteration wrapping (reverts to returning the upstream iterator without mid-stream error wrapping)
- The route's eager-consume-into-list pattern (reverts to `StreamingResponse(byte_iter, ...)`)
- The `_FakeAnimalesFotoClient` mid-stream failure injection (reverts to `iter(list(...))`)
- The audit doc scope accuracy + atom-count drift + P3 row additions

The pre-4R PR4b baseline (4 commits `e7f5857` → `f977c9e`) stays valid; the 4R commits are purely additive on top of that baseline.

Per the runbook, the bucket itself is NOT deleted by the rollback path; operator runs the documented disable-display → backup → sentinel → delete sequence manually. No InsForge bucket/object/data rollback exists because PR4b + 4R performed no mutation.


## PR5 — done 2026-07-18

- merge commit: `024dc97307a745834f103be4ea27687c4381f93e`
- PR: https://github.com/ardelperal/APAP_WEB/pull/196
- CI: https://github.com/ardelperal/APAP_WEB/actions/runs/29634884361 (lint PASS, test PASS, build PASS, GitGuardian PASS; e2e/deploy SKIPPED — expected pre-MVP)
- closed issue(s): none (no PR5-tracking issue was opened; PR1→175, PR2→179, PR3→183, PR4a→187, PR4b→191 sequence broke at PR5)
- branch `feat/migration-pr5-pii-controls` deleted (§15.2): local OK, remote OK
- delivery: squash merge of 10 work-unit commits (`b463d5e` PII redaction atoms + CLI preserved_value masking; `c278468` DNI collision routing + reconcile `--filter-direction`; `1cdd043` PUBLIC_PATHS invariant + per-route 302-to-login pins; `f02b82c` source-snapshot-identity + collision-policy discovery sections; `8fe6104` ruff E402 lint fix; `607191c` PR5 tasks marked complete in this file; `a72f491` direction kwarg + DI seam; `af214c6` PII hardening in CLI formatters + audit + spec; `810afc3` `pii_route_coverage` informational detector; `357579c` dysflow-config delegate to global)
- size: +2691/-384 across 16 files (size:exception pre-MVP, user pre-authorized "no reviewers in pipeline")
- validation gate: `gentle-ai review validate --gate pre-merge` returned `invalidated` (legacy v1 receipts missing + compact v2 still in `reviewing` state); fell back to green CI per user instruction
- new test modules: `tests/migration/test_pii_redaction.py` (10 atoms), `tests/migration/test_dni_collision.py` (9 atoms), `tests/test_public_paths.py` (10 atoms)
- audit doc: `docs/audits/pii-live-migration-2026-Q3.md` (+43 lines; PR4b verdict still PASS)
- discovery doc: `docs/discovery/migration-risks.md` (+37 lines: source-snapshot-identity + collision-policy)
- next: PR6 (M2 reverse apply + round-trip tests) and PR7 (verify-fallback-ready gate) remain on the roadmap


## PR6 6.1 RED — `2026-07-18T18:59:43+00:00`

Strict TDD: RED-first. Wrote `tests/migration/test_reverse_apply.py` and `tests/migration/test_round_trip.py` BEFORE any production code.

- `tests/migration/test_reverse_apply.py` (9 atoms):
  - `test_apply_web_to_legacy_inserts`
  - `test_apply_web_to_legacy_updates`
  - `test_apply_web_to_legacy_dry_run_does_not_write`
  - `test_apply_web_to_legacy_dry_run_reports_zero`
  - `test_preserve_column_not_written_to_legacy` (static grep, zero matches for `UPDATE web_only_feature_shadow SET preserved_value=` in `migration/apply_reverse.py`)
  - `test_derived_column_no_rederive_on_reverse` (monkeypatches `derive_estado_actual_animal` + `compare_derived_to_stored` to raise; reverse applier must not call them)
  - `test_lifecycle_reversed_event_emitted` (monkeypatches `migration.semantic_events.record_lifecycle_reversed`; asserts `source_direction="web-to-legacy"` stamp)
  - `test_sync_state_updated_transactionally` (legacy write succeeds → `sync_state.tables[voluntarios].last_sync_at` advances)
  - `test_sync_state_rollback_on_legacy_write_failure` (companion: legacy write raises → `sync_state.json` byte-identical to pre-apply)
- `tests/migration/test_round_trip.py` (5 atoms):
  - `test_round_trip_100_animals_preserves_nchip`
  - `test_round_trip_100_voluntarios_preserves_dni`
  - `test_round_trip_with_3_edits_applies_3_updates`
  - `test_round_trip_detects_unsynced_edits_as_needs_review`
  - `test_round_trip_counts_preserved`

RED execution:
```
pytest tests/migration/test_reverse_apply.py tests/migration/test_round_trip.py -q
# 0 collected (collection error: ModuleNotFoundError: migration.apply_reverse)
```
RED confirmed. Both test files reference the production module the PR6 GREEN step ships.

## PR6 6.2 GREEN — `2026-07-18T18:59:43+00:00`

Implementation shipped:

- `migration/apply_reverse.py` (NEW, 1130 L):
  - `apply_web_to_legacy(client, table_name, *, legacy_path, web_snapshot, dry_run, lock_path, dni_collision_counter, sync_state_path)` — PR6 spec entry point.
  - Bulk reads web + legacy snapshots, computes diff per row in-memory.
  - Per-row outcomes: ``applied`` (INSERT/UPDATE with log_safe audit) vs ``skipped`` (no-op).
  - `LIFECYCLE_REVERSED` event for derived-column state changes (spec scenario). Derivation engine NEVER invoked on reverse.
  - `preserve` columns advance `web_only_feature_shadow.last_legacy_snapshot_at` and bump `dni_collision_counter`; never write `preserved_value` (per-strategy table).
  - Drift detection: rowcount=0 → record `needs_review` shadow row with `review_reasons=["reverse_drift_legacy_row_missing"]`.
  - Sync-state transaction: snapshot pre-apply bytes; advance `tables[table].last_sync_at` AFTER legacy writes commit; rollback on exception.
- `migration/dysflow_client.py::execute_legacy_write(path, sql, params)` (NEW): pyodbc-backed write seam returning rowcount. Mirrors `execute_legacy_sql` seam.
- `migration/legacy_reader.py::set_legacy_write_executor` (NEW): mirrors `set_legacy_query_executor`. Inline executor pattern: writes callable `(path, sql, params) -> int`.
- `migration/apply.py`: lifted hardcoded `direction="legacy-to-web"` (lines 568/603/631). New `direction: str = "legacy-to-web"` kwarg on `apply_legacy_to_web`. The reverse applier passes `direction="web-to-legacy"`.
- `migration/semantic_events.py::record_lifecycle_reversed(...)` (NEW): emit `LIFECYCLE_REVERSED` event with `source_direction="web-to-legacy"` stamp.
- `migration/mappings/animal.yaml`: added `current_state` column with `web_only_strategy=derived` so the `LIFECYCLE_REVERSED` event has a signal column to fire on (the per-strategy table contract).
- `migration/cli.py`: `--direction {legacy-to-web,web-to-legacy}` flag on `apply_cmd` (default `legacy-to-web` to keep PR1-PR5 CLI behavior unchanged); new `APPLY_DIRECTION_WEB_TO_LEGACY`/`APPLY_DIRECTION_LEGACY_TO_WEB` constants; `run_apply` dispatches reverse on the new flag.
- `tests/migration/conftest.py`: `_apply_shadow_update` helper routes the `update_reconciliation_status` UPDATE through the in-memory shadow store so PR6 review-reason stamps survive in the test fixture.
- `tests/migration/test_round_trip.py` + `tests/migration/test_reverse_apply.py` (GREEN).
- `migration/cli.py::run_apply` correctly dispatches to `apply_web_to_legacy` when `args.direction == "web-to-legacy"`.

GREEN execution:
```
pytest tests/migration/test_reverse_apply.py tests/migration/test_round_trip.py -v
# 14 passed in 0.45s
pytest tests/migration -q
# 255 passed in 4.86s (was 241 before PR6; +14 = the reverse apply 9 + round-trip 5)
ruff check migration/ tests/migration/
# All checks passed!
```

Coverage gate still PASS: all 17 helpers at 100% line coverage (no new ``_row_to_*`` helpers added in PR6 — the per-row helpers are inside ``_reverse_apply_one_row`` and consumed by the new tests; pre-existing ``CRITICAL_HELPERS`` list unchanged).

## PR6 6.3 VERIFICATION — `2026-07-18T18:59:43+00:00`

Regression check + full local gate + ruff scope:

```
pytest -W error::DeprecationWarning --deselect tests/test_voluntarios_concurrent.py -q
# 2393 passed, 2 skipped (psycopg + .env.example), 2 deselected in 71.58s
ruff check migration/ tests/migration/
# All checks passed.
python -c "from migration.apply_reverse import apply_web_to_legacy, DIRECTION_WEB_TO_LEGACY"
# OK
python -c "from migration.cli import build_parser; p = build_parser(); a = p.parse_args(['apply', '--legacy-path', '/x', '--direction', 'web-to-legacy']); print(a.direction)"
# web-to-legacy
```

PR5 regression check: `tests/migration/test_dni_collision.py::test_forward_legacy_produces_zero_dni_collisions` → PASS. The reverse DI seam (counter incremented per `record_dni_collision` call) co-exists with the forward counter (forward never bumps).

Audit doc updated: `docs/audits/pii-live-migration-2026-Q3.md` PR6 section enumerates the new M2 invariants, the new tests, and reconfirms the verdict (PASS — PII redaction discipline / authorization / 15-field list unchanged).

Runbook updated: `docs/runbooks/live-migration-apply.md` adds a "Reverse direction (PR6 / M2)" section with when-to-trigger / pre-deploy checklist / deploy steps / verification / files-written / rollback subsections (all five AGENTS §13 headings present; `tests/test_runbook_links.py` still green).

Files written (additive only; PR1..PR5 atoms untouched):
- `migration/apply_reverse.py` (NEW, 1130 L)
- `tests/migration/test_reverse_apply.py` (NEW, 9 atoms)
- `tests/migration/test_round_trip.py` (NEW, 5 atoms)
- `migration/dysflow_client.py` (MOD: +`execute_legacy_write`)
- `migration/legacy_reader.py` (MOD: +`set_legacy_write_executor` + `_execute_legacy_write` + `LegacyWriter`)
- `migration/apply.py` (MOD: direction kwarg threaded through the SIGINT handler + snapshot helper)
- `migration/semantic_events.py` (MOD: +`LIFECYCLE_REVERSED_SOURCE_DIRECTION` + `record_lifecycle_reversed`)
- `migration/mappings/animal.yaml` (MOD: +`current_state` derived column)
- `migration/cli.py` (MOD: --direction flag on `apply_cmd`)
- `tests/migration/conftest.py` (MOD: `FakeInsForge._apply_shadow_update`)
- `docs/audits/pii-live-migration-2026-Q3.md` (append PR6 verdict section)
- `docs/runbooks/live-migration-apply.md` (append "Reverse direction (PR6 / M2)" section)
- `openspec/changes/live-data-migration-sandbox/apply-progress.md` (this section)

## PR6 lens-fix (4R + judgment-day remediation, 2026-07-18)

### F1 — preflight logger alias — 2026-07-18T22:32:06+02:00

Changed `logging_mod.logging_mod.log_safe(...)` to `logging_mod.log_safe(...)` in `migration/apply_reverse.py`. No new atom was required; the focused reverse suite and full strict suite exercise the corrected import path. GREEN: `python -m pytest tests/migration/test_reverse_apply.py -q` → 13 passed; full Ruff and full strict pytest also pass.

### F2 — sync-state snapshot after lock acquisition — 2026-07-18T22:32:06+02:00

Moved `load_sync_state(...)` and `sync_state_pre_bytes = read_bytes()` inside `with lock_ctx`, immediately before the per-row loop. The existing transactional rollback atom remains green. GREEN: `test_sync_state_updated_transactionally` and `test_sync_state_rollback_on_legacy_write_failure` pass; full migration and strict suites pass.

### F3 — unknown legacy rowcount — 2026-07-18T22:32:06+02:00

RED: `python -m pytest tests/migration/test_runtime_boundary.py::test_execute_legacy_write_does_not_coerce_unknown_rowcount -q` → failed with `DID NOT RAISE`. GREEN: the atom passes with `LegacyWriteRowcountUnknownError(rowcount=-1)` and verifies the typed exception; `execute_legacy_write` no longer converts `-1` into drift rowcount `0`, so `_record_drift_needs_review` is not reached for the unknown sentinel.

### F4 — reversed lifecycle INSERT — 2026-07-18T22:32:06+02:00

RED: `test_lifecycle_reversed_event_emitted` failed because `animal_lifecycle_events` contained zero rows while the log event existed. GREEN: `semantic_events.persist_lifecycle_reversed(...)` uses the forward applier INSERT shape and `ON CONFLICT` guard; both the tightened existing atom and the direct state-change atom pass, asserting table content and `LIFECYCLE_REVERSED` metadata.

### F5 — reverse CLI report wiring — 2026-07-18T22:32:06+02:00

RED: `test_cli_reverse_check_only_emits_migration_report` failed because stdout contained only `table=voluntario would insert=0 skipped=1 errors=0`. GREEN: `run_apply` creates `DniCollisionCounter()` and `MigrationReport`, passes both to `apply_web_to_legacy`, emits the JSON report on successful exit, and emits typed-error reports through `log_safe` without breaking the one-line categorical CLI safety contract. The new atom passes.

### F6 — natural-key exclusion from legacy INSERT — 2026-07-18T22:32:06+02:00

RED: `test_apply_web_to_legacy_inserts` failed because the INSERT column list and params still contained `Voluntario` / `alice`. GREEN: `_insert_legacy_row` filters `natural_key` exactly as `_update_legacy_row` does; the atom now asserts the natural-key column and value are absent.

### F7 — direct `_reverse_apply_one_row` coverage — 2026-07-18T22:32:06+02:00

Added four direct atoms: rowcount-zero drift recording, case-insensitive legacy-key fallback, lifecycle event persistence on state change, and preserve-column cursor advancement on a no-edit round trip. RED evidence included the lifecycle direct atom failing before the helper received the client seam; GREEN: `python -m pytest tests/migration/test_reverse_apply.py -q --coverage-file=<temporary>` → 13 passed (9 baseline + 4 new atoms). The tests cover the missing-key and dry-run insert branches needed for the 100% helper gate.

### F8 — CRITICAL_HELPERS allowlist — 2026-07-18T22:32:06+02:00

Added `_reverse_apply_one_row` to `scripts/pytest_plugin/coverage_gate.py` and exempted the migration-owned helper from the app-only drift assertion while retaining the five app-helper checks. Intermediate RED coverage was 90.2% and then 98.0% while the new branch cases were completed. GREEN: full coverage run reports `coverage-gate PASS: all 18 helpers at 100%`; `coverage.json` reports `_reverse_apply_one_row` at 100%.

### PR6 lens-fix verification — 2026-07-18T22:32:06+02:00

| Gate | Command | Result |
|---|---|---|
| Focused reverse atoms | `python -m pytest tests/migration/test_reverse_apply.py -q --coverage-file=<temporary>` | 13 passed |
| Full migration suite | `python -m pytest tests/migration -q --coverage-file=<temporary>` | 261 passed |
| Full strict suite | `python -m pytest --cov=app --cov=migration --cov-report=json -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py -q` | 2399 passed, 2 skipped, 2 deselected; 0 warnings/failures; coverage gate 18/18 at 100%; total coverage 86.51% |
| Ruff scoped | `python -m ruff check migration/ tests/migration/` | All checks passed |
| Ruff full | `python -m ruff check .` | All checks passed |
| Project rule gate | `python scripts/check_rules.py app` | Exit 0, no output |
| Build | `python -m build --wheel` | `apap_web-0.1.0-py3-none-any.whl` built |

### PR6 lens-fix commits and rollback boundary

- `898bea7` — `fix(migration): harden reverse preflight and sync-state snapshot` (F1/F2).
- `0eaf1aa` — `fix(migration): remediate PR6 reverse apply review findings` (F3–F8).
- Rollback: revert `0eaf1aa` to remove the PR6 lens remediation, then revert `898bea7` to restore the pre-fix F1/F2 behavior. The two pre-existing PR6 commits remain untouched. No Access, InsForge, storage, or production backend mutation was performed.
- Scope proof: `proposal.md`, `design.md`, `exploration.md`, and `specs/` were not modified; unrelated `.atl/*` artifacts and `openspec/changes/adopt-03-seguimiento-state-machine/` remain unstaged and untracked as found.

