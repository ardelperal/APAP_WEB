# Runbook: live-migration-apply (PR3/M1)

> **Scope**: PR3/M1 forward apply pipeline for the legacy ACCDB → InsForge
> migration. This runbook is the canonical operator reference for every
> apply-time error category surfaced by the CLI (exits 5/6/7) and every
> apply-time evidence file (snapshot, partial-apply). The runbook also
> covers dry-run, pre-flight, and rollback discipline.

> **Audience**: operator running `apap-migrate apply` on a station with
> Microsoft Access Database Engine, the legacy `.accdb`, and the InsForge
> service key. Not for production deployment (separate playbook).

## When to trigger

Run this runbook whenever any of the following surfaces in the
operator's terminal or in CI logs:

- An `apap-migrate apply` command exits with **code 5** (preflight,
  legacy read, or infra bootstrap failure), **code 6** (source drift),
  or **code 7** (partial-apply interruption).
- A `log_safe("apply.preflight_unavailable", reason=…)` event appears
  in the JSON audit stream.
- A `migration.lock_snapshot.json` file appears under
  `<migration_dir>/`.
- A `migration.partial_apply.json` file appears under
  `<migration_dir>/` (this is **always** operator-visible evidence; PR3
  does NOT auto-resume).
- The operator needs to verify a previously-completed apply (drift
  check against the last snapshot).
- The legacy `.accdb` was edited between two apply runs and the
  operator wants to understand the drift.

Do NOT use this runbook for:

- M0 bootstrap / shadow-table / private-bucket infrastructure —
  see `docs/runbooks/live-migration-m0-bootstrap.md` instead.
- Reverse (web → legacy) direction — out of PR3 scope; see follow-up
  PR6.

## Pre-deploy checklist

Before running `apap-migrate apply` for the first time on an
operator box, every item below MUST be verified. Each item is a
hard gate: any failure aborts the apply with a categorical error
and a stable runbook reference.

- [ ] **Python ≥ 3.11** is installed (`python --version`).
- [ ] **`psutil` is installed and importable** (`python -c "import psutil; print(psutil.__version__)"`).
      Without `psutil` the MSACCESS preflight fails closed with
      `reason=psutil_missing`. The runbook documents this as a hard
      requirement, NOT a soft-fail warning.
- [ ] **Microsoft Access Database Engine** (redistributable) is
      installed (`python -c "import pyodbc; print(pyodbc.drivers())"` must list
      `Microsoft Access Driver (*.accdb)`). The executor (`migration/dysflow_client.py`)
      raises `LegacyReaderError` (CLI exit 5, reason
      `legacy_read_failed`) if the driver is missing.
- [ ] **Microsoft Access is CLOSED on the operator box**. The MSACCESS
      preflight (`migration/lock.check_msaccess_running`) raises
      `MsAccessRunningError` (CLI exit 5, reason `msaccess_running`)
      when any `MSACCESS.EXE` process is live. Close the Access
      frontend and retry.
- [ ] **InsForge private bucket `apap-photos` exists** and is private
      (`isPublic=false`). Bootstrap (M0) ran successfully — see
      `docs/runbooks/live-migration-m0-bootstrap.md` for the
      `ensure-bucket` operator checkpoint. A missing or public bucket
      aborts with `infra_bootstrap_failed`.
- [ ] **APAP_MIGRATION_DIR** points to a writable directory for
      `migration.lock`, `migration.lock_snapshot.json`, and
      `migration.partial_apply.json`. Default: `./migration/`.
- [ ] **APAP_INSFORGE_URL** and **APAP_INSFORGE_SERVICE_KEY** are set
      in the operator's environment (or the production config loader
      picks them up). The apply needs service-key privilege to write
      shadow-table rows and bucket operations.
- [ ] **A clean source directory**: the legacy `.accdb` and the photos
      directory are stable (no concurrent edits) for the duration of
      the apply. The snapshot written at apply start pins their
      SHA-256 fingerprints; any change after the snapshot aborts the
      apply (drift detection, see Verification §"Drift").

## Deploy steps

The apply pipeline is a single command. The recommended flow is:

1. **Dry-run first** — count-only, no writes, no lock, no snapshot:

       apap-migrate apply --table animal --voluntario --entrada \
           --legacy-path $APAP_LEGACY_ACCDB \
           --check-only

   The CLI prints per-table `would insert=N skipped=M errors=K` lines.
   Inspect the counts before proceeding. `--check-only` bypasses the
   MSACCESS preflight and the lock entirely (read-only compare).

2. **Resolve partial evidence from prior interrupted run** (if
   present):

       ls $APAP_MIGRATION_DIR/migration.partial_apply.json

   If the file exists, the previous run was interrupted (SIGINT or
   crash). PR3 deliberately does NOT auto-resume. Review the JSON
   payload (`direction`, `table_name`, `progress_applied`,
   `progress_total`, `reason`, `recorded_at`). When ready:

       rm $APAP_MIGRATION_DIR/migration.partial_apply.json

3. **Real apply** — emits `migration.lock_snapshot.json` and runs the
   forward pipeline:

       apap-migrate apply --table animal --voluntario --entrada \
           --legacy-path $APAP_LEGACY_ACCDB

   The CLI exits 0 on success, 1 on per-row errors (diffs continue),
   5/6/7 on categorical failures (see Verification §"Exit codes").

4. **Verify** (see Verification below) before running another apply.

## Verification

### Exit codes (closed vocabulary — matches CLI output)

| Exit | Reason                          | What it means                                                                 | Operator action                                                       |
|------|---------------------------------|--------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| 0    | n/a (success)                    | Apply completed; `migration.lock_snapshot.json` written.                      | Review the per-table counts; reconcile shadow-table divergences.       |
| 1    | n/a (partial errors)             | At least one per-row error (e.g. legacy row missing natural key).            | Read the `errors=` lines; fix data; retry. Snapshot already written. |
| 2    | usage error                      | Bad CLI args (unknown table, malformed timestamp, missing web_client).       | Fix the args; rerun.                                                    |
| 5    | `msaccess_preflight_unavailable` | `psutil` missing or `process_iter` raised mid-iteration.                    | Install `psutil`; rerun. **Do not** proceed without psutil.         |
| 5    | `msaccess_running`               | A live `MSACCESS.EXE` process was detected.                                  | Close Access; rerun.                                                  |
| 5    | `legacy_read_failed`             | pyodbc / dysflow I/O failure (driver missing, .accdb locked, network).     | Install Access Driver / unlock .accdb / check path; rerun.            |
| 5    | `infra_bootstrap_failed`         | Private `apap-photos` bucket missing or public; shadow table broken.         | Re-run M0 bootstrap; verify bucket visibility; rerun apply.          |
| 6    | `source_drift`                   | `migration.lock_snapshot.json` disagrees with current source fingerprints.   | Inspect what changed in `.accdb` or photos; decide and proceed.      |
| 7    | `partial_apply_interrupted`      | `migration.partial_apply.json` exists from a prior interrupted run.          | Review evidence; `rm` the file; rerun. **No auto-resume.**        |

The CLI prints ONE line per error in the canonical format:

    apap-migrate apply: status=error reason=<cat> exit=<N> runbook=docs/runbooks/live-migration-apply.md

No traceback, no raw PII (DNI/Email/Tel1/Tel2), no raw filesystem
paths. The operator reads this runbook for the verbose interpretation.

### Drift detection (exit 6 `source_drift`)

The apply writes `migration.lock_snapshot.json` AFTER acquiring the
lock and BEFORE the first legacy read. The snapshot records the
SHA-256 of the `.accdb` and a deterministic manifest of the photos
directory (filename + size + SHA-256 sorted by filename).

On the next apply run, the pipeline recomputes the fingerprints and
compares them to the on-disk snapshot. **Any** difference (accdb hash
or photos manifest hash) aborts the apply with `source_drift` (exit
6).

To inspect the drift:

    diff <(jq -S . $APAP_MIGRATION_DIR/migration.lock_snapshot.json) \
         <(jq -S . /tmp/current_snapshot.json)

The `accdb_sha256_changed`, `photos_dir_sha256_changed`,
`photos_file_count_delta`, and `photos_total_bytes_delta` fields on
the exception object tell the operator which side changed and by how
much. PR3 fails closed; a future PR may add `--accept-drift` for
explicit acknowledgement.

### `log_safe` audit events (operator-visible via JSON stdout)

- `apply.preflight_unavailable` — emitted when `check_msaccess_running`
  raises. Carries ONLY the categorical `reason` field
  (`psutil_missing` or `process_iteration_failed`). No PIDs, no error
  strings, no path data.
- `sync.applied` — per-row audit (existing PR3 surface).

### Files written by the apply

| Path                                               | Lifecycle                                            |
|----------------------------------------------------|------------------------------------------------------|
| `<migration_dir>/migration.lock`                    | Written at apply start; released on apply end (success OR error). |
| `<migration_dir>/migration.lock_snapshot.json`     | Written AFTER lock, BEFORE first read. Overwritten on each real apply (NOT dry-run). Drift detection reads it on the next run. |
| `<migration_dir>/migration.partial_apply.json`      | Written on SIGINT AFTER the snapshot was already written. NOT auto-cleaned (no destructive cleanup per operator directive). Operator MUST review and `rm` it. |
| `web_only_feature_shadow` rows (per divergence)     | Recorded in the shadow table when a web row disagrees with a legacy row. Operator reconciles via `apap-migrate reconcile --interactive` (out of PR3 scope; pre-existing PR5 surface). |

### What is NOT auto-resumed

- `migration.partial_apply.json` is **never** auto-resumed. PR3 blocks
  the next apply with exit 7 (`partial_apply_interrupted`) until the
  operator removes the file by hand. Automatic resume is a follow-up
  task (per `tasks.md` 9.1; scheduled before the M2 fallback-ready
  gate).
- `migration.lock_snapshot.json` is **never** auto-merged across runs.
  Each apply overwrites the previous snapshot with the new
  fingerprints. Drift is detected on the next run; the operator
  decides.
- Public-bucket misconfiguration is **never** auto-recovered.
  `bootstrap_m0_infrastructure` aborts the apply with
  `infra_bootstrap_failed` (exit 5) if the bucket is missing or
  public. The operator must fix the bucket via the InsForge MCP
  before retrying.

### What is NOT logged

- **No raw PII** (DNI / Email / Tel1 / Tel2 column values) ever
  appears in `log_safe` events or CLI output. The PII redaction
  list in `app/core/logging.py` is the closed vocabulary.
- **No raw filesystem paths** (e.g. `C:\Users\…`, `/var/…`,
  `/tmp/…`, `/home/…`) ever appear in the operator stream. The
  exception's `detail` field may contain internal context but the
  CLI emits only the categorical reason.
- **No raw exception payloads** (e.g. full SQL fragments, full
  pyodbc tracebacks) ever appear in the operator stream. Operators
  see a stable categorical line; the verbose detail lives in the
  structured logs at the operator's discretion.

## Rollback

Rollback discipline depends on whether the apply succeeded or aborted.

### Rollback on successful apply (exit 0)

The apply is **idempotent** on the source: the same `.accdb` and
the same photos directory produce the same snapshot fingerprints.
To re-run a successful apply:

1. The destination web DB rows are already inserted; re-running
   re-computes each row's natural-key lookup and skips no-ops.
2. Divergences (existing web rows with a different payload) land in
   `web_only_feature_shadow` as `needs_review` rows. The operator
   reconciles via `apap-migrate reconcile --interactive` (pre-existing
   PR5 surface; out of PR3 scope).
3. `migration.lock_snapshot.json` is overwritten on the next run;
   no manual cleanup required.

### Rollback on partial-apply interruption (exit 7 `partial_apply_interrupted`)

The previous apply was interrupted (SIGINT, crash, OOM, or
operator-initiated abort). The destination may have SOME rows
inserted and OTHERS not. PR3 deliberately does NOT auto-resume.

1. **Do NOT delete the destination rows** without first consulting
   the operator log + `migration.lock_snapshot.json` (to know
   which source fingerprints were current at apply start) and
   `migration.partial_apply.json` (to know how far the apply
   progressed).
2. Review the `migration.partial_apply.json` payload:

       jq . $APAP_MIGRATION_DIR/migration.partial_apply.json

   Fields: `schema_version`, `direction`, `table_name`,
   `progress_applied`, `progress_total` (nullable), `reason`,
   `recorded_at`.
3. Backfill any missing rows **manually** (psql / SQL editor)
   OR run `apap-migrate apply` again AFTER removing the partial
   file (the apply is idempotent on natural-key lookups and skips
   rows already present).
4. Once the destination is consistent with the source, `rm
   $APAP_MIGRATION_DIR/migration.partial_apply.json`.
5. **Never** edit `migration.partial_apply.json` by hand — the file
   is JSON-parseable-only; hand-edits produce drift on the next run.

### Rollback on drift (exit 6 `source_drift`)

The source changed between the previous apply and this one. The
destination may be consistent with the OLD source but inconsistent
with the NEW source. Options, in order of preference:

1. **Investigate the drift first.** Use the `accdb_sha256_changed`,
   `photos_dir_sha256_changed`, `photos_file_count_delta`,
   `photos_total_bytes_delta` fields on the exception to narrow the
   change:

       # Inspect the previous snapshot
       jq . $APAP_MIGRATION_DIR/migration.lock_snapshot.json

       # Compute the current fingerprints manually (see migration/lock_snapshot.py)

   If the change is intentional (e.g. operator edited the source
   intentionally), re-run the apply AFTER backing up the
   destination rows you want to preserve. The apply is idempotent
   on natural-key lookups and skips already-present rows.

2. **If the change is unintentional** (e.g. a partial `.accdb`
   write), STOP. Do NOT re-run. Restore the source from backup, then
   re-run.

### Rollback on preflight / legacy-read / infra-bootstrap failure (exit 5)

These failures occur BEFORE any data is written. There is nothing
to roll back. Fix the underlying issue:

- `msaccess_preflight_unavailable` → `pip install psutil`.
- `msaccess_running` → close Microsoft Access.
- `legacy_read_failed` → install Microsoft Access Database Engine
  redistributable, OR close any held lock on `.accdb`, OR verify
  the legacy path.
- `infra_bootstrap_failed` → re-run M0 bootstrap
  (`apap-migrate ensure-bucket apap-photos --check-only`); verify
  bucket visibility; see `docs/runbooks/live-migration-m0-bootstrap.md`.

After fixing the issue, re-run the apply. The lock + snapshot
files are released / overwritten cleanly.

### Escalation

If the runbook does NOT resolve the issue:

1. Capture the CLI output line(s) — they are the canonical
   categorical contract.
2. Capture `migration.lock_snapshot.json` + `migration.partial_apply.json`
   (if present) and the `apply.preflight_unavailable` (if present)
   JSON event from stdout.
3. File a follow-up issue with `type:bug` and label `migration:apply`.
   Reference the commit SHA of the most recent apply + the SHA of
   `migration.lock_snapshot.json`.