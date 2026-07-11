# Tasks: live-data-migration-sandbox

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~3,800 (7 PRs × ~550 avg) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 → PR2 → PR3 → PR4a → PR4b → PR5 → PR6 → PR7 |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | pyodbc executor wired, no-MCP boundary, conftest reset, pyodbc pin | PR1 | `pytest tests/migration/test_runtime_boundary.py -v` | synthetic fixture rows vs real .accdb | drop pyodbc from etl extra |
| 2 | ShadowStateRepository.ensure_table(), bucket MCP create, ensure_bucket wiring | PR2 | `pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -v` | `FakeInsForge` + MCP mock | `DROP TABLE web_only_feature_shadow` |
| 3 | apply.py MOD: lock_snapshot AFTER lock, MSACCESS pre-flight, partial_apply.json, counts/source_hashes/collisions in MigrationReport | PR3 | `pytest tests/migration/test_apply.py tests/migration/test_lock_snapshot.py -v` | `FakeInsForge` + `FakeExecutor` | delete `migration.lock_snapshot.json` |
| 4a | Storage contract spike: live read-only probe against deployed InsForge; pins canonical path + auth header in `docs/discovery/storage-contract-2026-Q3.md` | PR4a | `python -m migration.storage_spike --probe download_strategy` | operator's live InsForge + real .accdb | no-op (read-only) |
| 4b | InsForge storage methods (ensure_bucket/get_bucket/upload_object/download_object_stream/delete_object), animal.yaml storage block, photo_migration.py, GET /animales/{animal_id}/foto StreamingResponse, REDACTED_FIELDS += dni/tel1/tel2 | PR4b | `pytest tests/migration/test_photo_storage.py tests/test_animals_foto_route.py tests/test_log_safe_redaction.py -v` | `httpx.MockTransport` per storage-contract spike | rollback bucket + route |
| 5 | PII tests (log_safe 15 fields, DNI collision web-only+reverse, PUBLIC_PATHS auth), CLI reconcile --filter-direction, docs/discovery/migration-risks.md update | PR5 | `pytest tests/migration/test_pii_redaction.py tests/migration/test_dni_collision.py tests/test_public_paths.py -v` | synthetic fixtures; no real PII | none (tests only) |
| 6 | apply_reverse.py (M2), post_apply_diff symmetric direction, round-trip tests, reverse apply CLI | PR6 | `pytest tests/migration/test_reverse_apply.py tests/migration/test_round_trip.py -v` | `FakeInsForge` + `FakeExecutor` | delete `apply_reverse.py` |
| 7 | verify-fallback-ready CLI, CI job, fallback_ready_gate tests, operator-attest stub | PR7 | `pytest tests/migration/test_fallback_ready_gate.py -v` | CI-runnable subset only | CI job removal |

## Phase 1: M0 — Runtime Boundary + Infrastructure (PR1 + PR2)

### PR1: pyodbc Legacy Executor + No-MCP Boundary (M0)

- [x] 1.1 **RED**: `tests/migration/test_runtime_boundary.py` — write failing tests: `test_execute_legacy_sql_returns_rows`, `test_driver_missing_raises_LegacyReaderError`, `test_fake_executor_injected_via_set_legacy_query_executor`, `test_no_mcp_runtime_dependency` (grep `mcp__dysflow|dysflow_query_execute|mcp_dispatch` in `app/`+`migration/` → 0 matches), `test_reset_executor_seam_restores_default`. Run; confirm red.
- [x] 1.2 **GREEN**: Replace `NotImplementedError` stub in `migration/dysflow_client.py` with pyodbc implementation: `execute_legacy_sql(path, sql, offset, limit) -> list[dict]`. Use `pyodbc.connect()` with `Microsoft Access Driver (*.accdb)`; `Connection.timeout=30`; handle `pyodbc.Error` → `LegacyReaderError`. Add `pyodbc>=5.3` to `[project.optional-dependencies.etl]` in `pyproject.toml`. Confirm green.
- [x] 1.3 **REFACTOR**: Extract `_execute_legacy_query` internal to `legacy_reader.py` unchanged (seam stays stable). Add `py.typed` marker if needed.
- [x] 1.4 **VERIFICATION**: `pytest tests/migration/test_runtime_boundary.py tests/migration/conftest.py -v` — all green. `ruff check migration/dysflow_client.py migration/legacy_reader.py`. Commit: `feat(migration): pyodbc executor for legacy .accdb reads (M0)`.
- [x] Rollback: `pip install '.[etl]'` revert removes pyodbc; seam resets via `set_legacy_query_executor(None)`.

### PR2: ShadowStateRepository + Bucket Infrastructure (M0)

- [x] 2.1 **RED**: `tests/migration/test_shadow_state.py` — write failing tests for `ShadowStateRepository.ensure_table()`: table created with correct DDL, idempotent replay. Also `tests/migration/test_bucket_invariant.py`: `test_private_bucket_invariant` (isPublic=false), `test_public_bucket_aborts` (exit 5), `test_missing_bucket_auto_create`. Run; confirm red.
- [x] 2.2 **GREEN**: Wire `ShadowStateRepository.ensure_table()` call into `apply.py` bootstrap (before lock). Create `InsForgeClient.ensure_bucket()` and `get_bucket()` in `app/core/insforge.py` using Context7 candidate surface (`POST /api/storage/buckets`, `GET /api/storage/buckets/{bucket}`). Wire `ensure_bucket("apap-photos", is_public=False)` into `apply_legacy_to_web` pre-flight before lock. Add MCP stub in CLI for `apap-migrate ensure-bucket`. Confirm green.
- [x] 2.3 **VERIFICATION**: `pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -v` — all green. Commit: `feat(migration): ShadowStateRepository bootstrap + private bucket ensure (M0)`.
- [x] Rollback: `DROP TABLE web_only_feature_shadow`; bucket deletion via MCP.

## Phase 2: M1 — Forward Apply + Photos + PII (PR3 + PR4a + PR4b + PR5)

### PR3: apply.py Core — Lock Snapshot + MSACCESS Pre-flight + Report Counts (M1)

- [x] 3.1 **RED**: `tests/migration/test_lock_snapshot.py` — write failing tests: `test_snapshot_written_after_lock_before_first_read` (ordering invariant), `test_snapshot_contains_accdb_sha256_and_photos_dir_sha256`, `test_drift_detected_and_logged` (no raw paths in log), `test_partial_apply_json_on_sigint`, `test_resume_from_partial_apply`. `tests/migration/test_apply.py` add: `test_apply_with_msaccess_running_aborts` (exit 5), `test_apply_without_msaccess_proceeds`, `test_counts_source_hashes_collisions_in_report` (MigrationReport gains 3 fields).
- [x] 3.2 **GREEN**: Implement `migration/lock_snapshot.py`: `write_snapshot(path, accdb_sha256, photos_dir_sha256, direction)`, `read_snapshot(path) -> Snapshot`. Wire into `apply_legacy_to_web` after `acquire_lock`, BEFORE first `execute_legacy_sql` call. Implement `partial_apply.json` write on SIGINT + resume logic. Add `check_msaccess_running()` call before lock (exit 5 if non-empty). Add `counts/source_hashes/collisions` fields to `MigrationReport` via `field(default_factory=dict)`. `ApplyResult` unchanged (per design D11). Confirm green.
- [x] 3.3 **VERIFICATION**: `pytest tests/migration/test_lock_snapshot.py tests/migration/test_apply.py -v` — all green. Commit: `feat(migration): lock_snapshot + MSACCESS pre-flight + MigrationReport counts (M1)`.
- [x] Rollback: `rm migration.lock_snapshot.json migration/partial_apply.json`.

### PR4a: Storage Contract Spike (M1 gate — no code changes)

- [ ] 4.1 **SPIKE**: Create `migration/storage_spike.py` CLI command: `python -m migration.storage_spike --probe download_strategy --path apap-photos/<sha256>.jpg`. It reads `APAP_INSFORGE_URL` + `APAP_INSFORGE_SERVICE_KEY`, makes a live read-only `GET /api/storage/downloadStrategy?path=...&expiresIn=3600` call against the deployed instance, records response status, headers, and body shape in `docs/discovery/storage-contract-2026-Q3.md`. Tests: `tests/migration/test_photo_storage.py::test_storage_spike_records_path` (verifies spike ran and doc exists).
- [ ] 4.2 **SPIKE**: Also probe `POST /api/storage/buckets/apap-photos/upload-strategy` with a small synthetic body `{filename:"test.jpg", contentType:"image/jpeg", size:10}` — record the response shape (method, uploadUrl, fields, key, confirmRequired, confirmUrl, expiresAt).
- [ ] 4.3 **SPIKE**: Probe 401 (bad key) and 404 (bad path) to confirm error contract. Tests `test_spike_fails_closed_on_401`, `test_spike_fails_closed_on_404` assert these mark PR4 red until canonical shape recorded.
- [ ] Commit: `feat(migration): storage contract spike — live InsForge probe (PR4a gate)`.

### PR4b: Storage Implementation + Photo Route + Audit + Runbook (M1)

- [ ] 4.4 **RED**: `tests/migration/test_photo_storage.py` — write failing tests: `test_upload_object_two_step`, `test_download_object_stream_auth_header`, `test_private_bucket_ispublic_false`, `test_photo_dedup_same_bytes`, `test_photo_upload_sentinel_on_corrupt`, `test_orphan_detection_and_cleanup`. `tests/test_animals_foto_route.py` — `test_animales_foto_requires_auth` (302), `test_animales_foto_streams_bytes`, `test_animales_foto_sentinel_placeholder`. `tests/test_log_safe_redaction.py` — `test_redaction_list_has_15_fields` (dni, tel1, tel2 added). Run; confirm red.
- [ ] 4.5 **GREEN**: Implement `InsForgeClient.{ensure_bucket, get_bucket, upload_object, download_object_stream, delete_object}` in `app/core/insforge.py` using the spike-pinned canonical paths + auth header from `docs/discovery/storage-contract-2026-Q3.md`. Implement `migration/photo_migration.py`: SHA-256 client-derived key, upload via two-step strategy, capture returned canonical key, dedup by SHA-256, sentinel `__missing__` on error, orphan detection. Add `storage` block to `animal.yaml` (`bucket: apap-photos`, `key: <sha256>.<ext>`). Add `GET /animales/{animal_id}/foto` route in `app/modules/animals/routes.py` using `StreamingResponse` from `download_object_stream`; `animal_id` is `animales.id` UUID (NCHIP is lookup, NOT route ID). Expand `REDACTED_FIELDS` in `app/core/logging.py` to add `dni`, `tel1`, `tel2` (12 → 15 fields). Confirm green.
- [ ] 4.6 **VERIFICATION**: `pytest tests/migration/test_photo_storage.py tests/test_animals_foto_route.py tests/test_log_safe_redaction.py -v` — all green. Create `docs/audits/pii-live-migration-2026-Q3.md` (Scope, Methodology, Findings severity table, Verdict PASS). Create `docs/runbooks/migrate-live-data.md` (pre-flight checklist, step-by-step apply, rollback, MSACCESS close, verify commands). Commit: `feat(migration): InsForge storage + authenticated foto route + PII audit (M1)`.
- [ ] Rollback: delete bucket via MCP; `ALTER TABLE animales DROP COLUMN nombrefoto`; revert `REDACTED_FIELDS`.

### PR5: PII Controls + Reconcile CLI + Discovery Docs (M1)

- [ ] 5.1 **RED**: `tests/migration/test_pii_redaction.py` — write failing: `test_sync_applied_log_no_raw_dni`, `test_sync_applied_log_no_raw_email`, `test_sync_applied_log_no_raw_tel1_tel2`, `test_shadow_preserved_value_masked_in_logs`, `test_migration_report_json_no_raw_pii` (regex assert no DNI/email/tel substrings), `test_cli_output_no_raw_pii`. `tests/migration/test_dni_collision.py` — `test_forward_legacy_produces_zero_dni_collisions`, `test_first_web_dni_wins`, `test_reverse_path_collision_recorded`, `test_reconcile_interactive_resolves_dni_collision`. `tests/test_public_paths.py` — `test_public_paths_has_exactly_five_entries` (verified set), `test_pii_routes_require_auth` (302 for /voluntarios, /animales, /entradas). Run; confirm red.
- [ ] 5.2 **GREEN**: Implement all above tests and make green. Add `dni_collisions` / `row_divergences` counters to `MigrationReport.collisions`. Add `--filter-direction {legacy-to-web,web-to-legacy}` flag to CLI reconcile command. Update `docs/discovery/migration-risks.md` with `source-snapshot-identity` section and `collision-policy` section (corrected: DNI only web-only, no legacy column). Confirm green.
- [ ] 5.3 **VERIFICATION**: `pytest tests/migration/test_pii_redaction.py tests/migration/test_dni_collision.py tests/test_public_paths.py -v` — all green. Commit: `feat(migration): PII controls + reconcile CLI + discovery docs (M1)`.
- [ ] Rollback: none (test + doc changes).

## Phase 3: M2 — Reverse Apply + Round-trip + Fallback Gate (PR6 + PR7)

### PR6: Reverse Apply + Round-trip Tests (M2)

- [ ] 6.1 **RED**: `tests/migration/test_reverse_apply.py` — write failing: `test_apply_web_to_legacy_inserts`, `test_apply_web_to_legacy_updates`, `test_apply_web_to_legacy_dry_run`, `test_preserve_column_not_written_to_legacy` (grep assertion: zero matches for `UPDATE web_only_feature_shadow SET preserved_value=` in reverse branches), `test_derived_column_no_rederive_on_reverse`, `test_lifecycle_reversed_event_emitted`, `test_sync_state_updated_transactionally`. `tests/migration/test_round_trip.py` — `test_round_trip_100_animals_preserves_nchip`, `test_round_trip_100_voluntarios_preserves_dni`, `test_round_trip_with_3_edits_applies_3_updates`, `test_round_trip_detects_unsynced_edits_as_needs_review`, `test_round_trip_counts_preserved`. Run; confirm red.
- [ ] 6.2 **GREEN**: Implement `migration/apply_reverse.py`: `apply_web_to_legacy(client, table_name, *, web_snapshot, dry_run, lock_path)`. Reuse same executor seam, same lock discipline. Implement symmetric `post_apply_diff` hook with `direction="web-to-legacy"` handling per `web-only-feature-preservation` spec: `preserve` never writes `preserved_value`, `derived` does not re-derive, `fixed` never writes. Add `LIFECYCLE_REVERSED` event emission. Implement `sync_state.json` transactional update. Implement reverse-direction CLI: `apap-migrate apply --direction web-to-legacy`. Confirm green.
- [ ] 6.3 **VERIFICATION**: `pytest tests/migration/test_reverse_apply.py tests/migration/test_round_trip.py -v` — all green. Commit: `feat(migration): reverse apply + round-trip tests (M2)`.
- [ ] Rollback: `rm migration/apply_reverse.py`.

### PR7: verify-fallback-ready Gate + CI Wiring (M2)

- [ ] 7.1 **RED**: `tests/migration/test_fallback_ready_gate.py` — write failing: `test_verify_fallback_ready_ci_only_passes_when_all_green`, `test_verify_fallback_ready_ci_only_exits_1_when_round_trip_fails`, `test_verify_fallback_ready_full_exits_1_without_operator_attestation`, `test_verify_fallback_ready_full_exits_0_with_full_receipt`. Run; confirm red.
- [ ] 7.2 **GREEN**: Implement `migration/cli.py` `verify-fallback-ready` command: `--ci-only` flag runs CI-runnable conditions (round-trip test import + run, `apply_web_to_legacy --check-only`, audit doc verdict parse) and exits 0/1. Without flag, requires `migration_report_signature.json` with `operator_id` + `sha256_of_report` + `signed_at`. Add `migration_report_signature.json` operator-attest stub generation (`apap-migrate apply --operator-attest`). Update `.github/workflows/ci.yml`: add `verify_fallback_ready` job (`needs: [test]`, `python -m migration verify-fallback-ready --ci-only`). Confirm green.
- [ ] 7.3 **VERIFICATION**: `pytest tests/migration/test_fallback_ready_gate.py -v` — all green. `ruff check migration/cli.py`. Commit: `feat(migration): verify-fallback-ready gate + CI job (M2 final)`.
- [ ] Rollback: remove CI job from `ci.yml`; delete `verify-fallback-ready` command.

## Phase 4: M1 + M2 Integration — Real Data Execution (Operator Work Unit)

> **Code vs. Real Data Separation**: All PRs above ship code + synthetic tests. The real-data migration requires an operator work unit NOT merged via PR:

- [ ] Operator work unit: `python -m migration ensure-bucket apap-photos --check-only` → confirm `isPublic=false`.
- [ ] Operator work unit: `python -m migration apply --table animal --voluntario --entrada --check-only` → review counts + source_hashes.
- [ ] Operator work unit: `python -m migration apply --table animal --voluntario --entrada` → apply with real data.
- [ ] Operator work unit: `python -m migration reconcile --check-only` → review `needs_review` cases.
- [ ] Operator work unit: `python -m migration status --photos` → verify orphan count.
- [ ] Operator work unit: M2 gate — `apap-migrate verify-fallback-ready` (full) requires `migration_report_signature.json` operator attestation.
- [ ] Rollback operator work unit: `python -m migration rollback --table animal` (deletes by NCHIP range from legacy_ids captured in pre-flight).

## Phase 5: E2E Playwright Tests (CI — Canonical Repo Tests)

- [ ] 8.1 **RED**: `tests/e2e/test_animals_foto_auth.py` — write failing fixture-first tests: `test_foto_authenticated_returns_200_plus_bytes` (creates `apap-photos-test-<8hex>` bucket, seeds 1×1 synthetic PNG, asserts 200 + Content-Type + bytes > 0), `test_foto_no_session_returns_302_to_login` (no session cookie, asserts 302 Location=/login), `test_foto_sentinel_returns_placeholder` (nombrefoto=__missing__, asserts 200 placeholder). Each test has its own ephemeral bucket, cleaned up via fixture teardown. Playwright MCP is diagnostic only (operator sign-off), NOT in CI. Run; confirm red.
- [ ] 8.2 **GREEN**: Implement all three paths. Use `page.goto()` pattern. Confirm green.
- [ ] 8.3 **VERIFICATION**: `pytest tests/e2e/test_animals_foto_auth.py -v` — all green. Commit: `test(e2e): Playwright foto auth three-path (canonical CI tests)`.
