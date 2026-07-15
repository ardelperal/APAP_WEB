# live-migration-runtime-boundary

## Purpose

Contract for the legacy-SQL executor used by `apply_legacy_to_web` and `apply_web_to_legacy`. Defines the testability seam, the prohibition on Dysflow MCP as runtime dependency, source-snapshot identity, dry-run semantics, lock discipline, Access pre-flight detection, and interrupted-apply rollback. Decoupled from any concrete driver (pyodbc / snapshot adapter / subprocess); design selects.

## Requirements

### Requirement: Legacy SQL Executor Testability Seam

`migration.dysflow_client.execute_legacy_sql(path, sql, offset, limit) -> list[dict]` MUST be the only entry point the applier uses to read the legacy `.accdb`. Tests MUST inject a fake via `migration.legacy_reader.set_legacy_query_executor(callable)`. The seam signature MUST NOT change between M0 and M2.

#### Scenario: Tests inject a fake executor

- GIVEN a test sets `set_legacy_query_executor(fake)` with `fake(path, sql, offset, limit) -> [row, ...]`
- WHEN `apply_legacy_to_web` reads legacy rows
- THEN the applier calls `fake` and uses its rows
- AND `set_legacy_query_executor(None)` resets to the default executor

#### Scenario: Missing driver raises LegacyReaderError

- GIVEN no fake injected and the operator box lacks the configured driver
- WHEN `apply_legacy_to_web` reads legacy rows
- THEN `LegacyReaderError` is raised
- AND the CLI exits with code 5

### Requirement: No Dysflow MCP Runtime Dependency

The migration runtime MUST NOT import, register, or invoke any Dysflow MCP tool. Dysflow MCP is agent-only tooling. Production apply MUST run without MCP. Applier MUST depend only on the seam and the chosen driver.

#### Scenario: Static boundary test forbids MCP wiring

- GIVEN `migration/apply.py`, `migration/dysflow_client.py`, and `migration/legacy_reader.py` source on disk
- WHEN a boundary test greps for `mcp__dysflow`, `dysflow_query_execute`, `mcp_dispatch` in `app/` and `migration/` (excluding the stub)
- THEN zero matches are found
- AND the test fails the build on any match

#### Scenario: Operator box without MCP runs apply

- GIVEN an operator box with the configured driver and no Dysflow MCP process
- WHEN `apap-migrate apply --table animal` runs
- THEN the applier completes
- AND no MCP module is imported (verified via `sys.modules` snapshot in fixture)

### Requirement: Source Snapshot Identity

Every apply MUST compute SHA-256 of the `.accdb` file and SHA-256 of the photos directory BEFORE the first legacy read. Both hashes MUST be persisted in `migration.lock_snapshot.json` with `last_apply_at` and `last_apply_direction`.

#### Scenario: First apply writes snapshot

- GIVEN `migration.lock_snapshot.json` does not exist
- WHEN `apply_legacy_to_web --table animal` runs
- THEN the file is written with `accdb_sha256`, `photos_dir_sha256`, `last_apply_at=<UTC ISO>`, `last_apply_direction="legacy->web"`
- AND the snapshot is written BEFORE any `execute_legacy_sql` call

#### Scenario: Drift between runs is detected

- GIVEN snapshot with `accdb_sha256=A` from previous run
- WHEN a new apply runs after the `.accdb` changed (sha `B`)
- THEN pre-flight logs `snapshot_drift: prev=<A8chars> new=<B8chars>` via `log_safe` (no path)
- AND the apply proceeds; drift is informational, recorded in `migration_report.json`

#### Scenario: Empty source is a valid snapshot

- GIVEN a brand-new `.accdb` with 0 rows in `animales`
- WHEN `apply_legacy_to_web --table animal` runs
- THEN snapshot is written with empty-table hashes
- AND the apply completes with `applied=0`, `skipped=0`, `errors=[]`

### Requirement: Dry-Run Mode

`apap-migrate apply --check-only` MUST compute the diff plan and counts but MUST NOT write to web, upload photos, or acquire the apply lock.

#### Scenario: --check-only emits no writes

- GIVEN a fresh web DB (zero rows in `animales`)
- WHEN `apap-migrate apply --table animal --check-only` runs against legacy with 500 rows
- THEN `MigrationReport` reports `would_apply=500`, `applied=0`
- AND `SELECT COUNT(*) FROM animales` is still 0 post-run
- AND no `apap-photos` object is created

### Requirement: Lock Acquisition and Release Discipline

The applier MUST acquire `migration.lock` BEFORE the first legacy read and MUST release it in `try/finally`. The lock file MUST contain the PID; live PID MUST be verified via `psutil.pid_exists()`. Stale lock (dead PID) is removable; live lock MUST abort with exit code 6.

#### Scenario: Lock acquired before reads, released after

- GIVEN no lock held
- WHEN `apply_legacy_to_web --table animal` starts
- THEN `migration.lock` is written before any `execute_legacy_sql` call
- AND on normal completion, the lock is removed

#### Scenario: Stale lock is reported

- GIVEN `migration.lock` PID 12345 and `psutil.pid_exists(12345) == False`
- WHEN `apply_legacy_to_web` starts
- THEN pre-flight aborts with `stale_lock_detected` and exit code 6

#### Scenario: Live lock aborts concurrent apply

- GIVEN `migration.lock` PID 12345 alive
- WHEN a second apply starts
- THEN it aborts with `lock_held_by_live_pid` and exit code 6
- AND no legacy read is attempted

### Requirement: Access Lock Pre-Flight

Before the first legacy read, the applier MUST invoke `check_msaccess_running()` (no-arg; current verified signature at `migration/lock.py:441`). If any MSACCESS.EXE process is alive globally, the apply MUST abort with exit code 5 and a runbook reference.

> **Why the no-arg signature, not path-aware (Correction D).** A path-aware `check_msaccess_running(legacy_path)` would require per-file handle inspection via Windows FD tables / `net file` / lsof — none of which are stable cross-version, and the project has not adopted any. The existing global check (any MSACCESS.EXE PID alive) is conservative: it blocks apply whenever Access is open on any file. That is safer than missing a lock. If a future change adopts a path-aware overload with verified semantics, it can be added without breaking this contract; the no-arg global check remains the safe default.

#### Scenario: Access running globally aborts

- GIVEN ANY `MSACCESS.EXE` process is alive (regardless of which `.accdb` it holds)
- WHEN `apply_legacy_to_web` starts
- THEN pre-flight returns a non-empty PID list and aborts with exit code 5
- AND the message references `docs/runbooks/migrate-live-data.md`
- AND names the PIDs found (operator can verify they're the right process to close)

#### Scenario: Access closed proceeds

- GIVEN no `MSACCESS.EXE` process alive
- WHEN `apply_legacy_to_web` starts
- THEN pre-flight returns `[]` and apply proceeds normally

#### Scenario: psutil missing is a soft fail

- GIVEN `psutil` not installed (CI without Access driver)
- WHEN `check_msaccess_running()` runs
- THEN it returns `[]` (no-op; CI cannot check this; operator-only pre-flight)
- AND a warning is logged via `log_safe("msaccess.preflight.skipped", reason="psutil_missing")`

### Requirement: Interrupted-Apply Rollback Safety

On `KeyboardInterrupt`, `SystemExit`, or uncaught exception, the applier MUST release the lock, persist `partial_apply.json` with the last applied `legacy_pk` and `source_hash` per table, and roll back any partial shadow INSERTs from the failing batch.

#### Scenario: SIGINT mid-batch leaves no orphan

- GIVEN `apply_legacy_to_web` mid-batch (50 of 200 rows applied)
- WHEN the operator sends SIGINT
- THEN the lock is released
- AND `partial_apply.json` records `last_applied_pk=<pk50>`
- AND no partial shadow INSERTs remain (transactional rollback)
- AND `applied=50`, no rows past `pk50`

#### Scenario: Resume after interruption

- GIVEN `partial_apply.json` from previous interrupted run
- WHEN the operator re-runs `apap-migrate apply --table animal`
- THEN the applier resumes from the next batch after `last_applied_pk`
- AND on successful completion, `partial_apply.json` is deleted

## Acceptance Evidence

- `tests/migration/test_runtime_boundary.py` covers the seam, the no-MCP boundary test, snapshot identity, dry-run, lock states, Access pre-flight, and interrupted-apply rollback.
- Counts: `applied + skipped + errors == count_legacy` for the table under test, except `skipped` includes divergence-recorded rows.

## Out of Scope

- Choice of concrete driver (pyodbc vs. snapshot adapter vs. subprocess) — design selects with a TDD spike.
- Web→legacy reverse path runtime contract — covered by `live-migration-bidirectional-completion`.
