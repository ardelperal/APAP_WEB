# Live Migration M0 Bootstrap Runbook

## When to trigger

Run this before the first live-data migration apply in the `live-data-migration-sandbox` chain, and after any operator rollback that deletes `web_only_feature_shadow` or the `apap-photos` bucket.

## Pre-deploy checklist

- Code tests for PR2 are green; do not run this against InsForge as part of ordinary pytest.
- `APAP_INSFORGE_URL` points to the intended APAP backend.
- `APAP_INSFORGE_SERVICE_KEY` is available only in the operator shell, never committed.
- You are not running a real data import in this work unit; this step only prepares/checks infrastructure.

## Deploy steps

1. Read-only checkpoint:

   ```bash
   python -m migration ensure-bucket apap-photos --check-only
   ```

   Expected private-state output:

   ```text
   bucket=apap-photos status=exists isPublic=false
   ```

2. If the bucket is missing and the operator approves infrastructure mutation, create it private:

   ```bash
   python -m migration ensure-bucket apap-photos
   ```

   Expected output:

   ```text
   bucket=apap-photos status=created isPublic=false
   ```

3. Do not run a real apply in this PR2 work unit. The first later non-check-only `python -m migration apply ...` run will ensure `web_only_feature_shadow` before acquiring the migration lock and before reading legacy rows. If an operator chooses to pre-create the table separately, use the DDL in `migration/shadow_state.py`, record the checkpoint, and keep the rollback below available.

## Verification

- The command output must include `isPublic=false`.
- If the command returns `bucket_public_violation`, stop. Do not apply data. Recreate the bucket as private through the InsForge infrastructure tool and re-run the read-only checkpoint.
- If the command returns `bucket_visibility_unknown`, stop. Use the InsForge MCP `list-buckets` infrastructure tool to verify visibility before continuing.
- `python -m pytest tests/migration/test_shadow_state.py tests/migration/test_bucket_invariant.py -v` must pass locally without real backend access.

## Rollback

> **Destructive actions in this section are last-resort.** They discard
> durable artifacts that the operator and audit trail depend on. Do NOT
> use them as the default rollback path. Prefer the non-destructive
> alternatives first; if a destructive step is unavoidable, the
> preconditions below MUST be met and recorded before the operator
> runs the command.

### Non-destructive alternatives (preferred)

- **Shadow-state disable instead of `DROP TABLE`:** keep the
  `web_only_feature_shadow` table and the divergence/audit history
  intact. Stop future `apply` runs by clearing
  `migration.lock_snapshot.json` (if any) and using
  `APAP_MIGRATION_DIR` overrides to point the next apply at a no-op
  destination; the table continues to record audit history for the
  legacy side. This is the default rollback when the table contains
  rows.
- **Bucket quarantine instead of `delete-bucket`:** keep the bucket
  objects in place and prevent new uploads by removing the InsForge
  service role permission for the bucket. Existing photos stay
  available to authenticated reads; the audit trail stays intact.
- **CLI checkpoint-only mode** (`python -m migration ensure-bucket
  apap-photos --check-only`) is a non-mutating operator tool. Run it
  to verify state without writing.

### Destructive rollback (last resort)

#### `DROP TABLE web_only_feature_shadow`

- **Effect:** destructive of the divergence/audit history for every
  pending `needs_review` row. Once the rows are dropped, the operator
  loses the source/target hash evidence and the manual reconciliation
  workflow that PR5/PR6 rely on.
- **Preconditions (MUST be true before the operator runs the
  command):**
  1. A verified backup/export of the table (e.g. `pg_dump --table
     web_only_feature_shadow`) is stored outside the affected InsForge
     database and the path is recorded in the operator ticket.
  2. `SELECT COUNT(*) FROM web_only_feature_shadow WHERE
     reconciliation_status IN ('pending', 'needs_review')` returns
     `0`, OR the operator has recorded an explicit sign-off in the
     ticket explaining why losing the rows is acceptable.
  3. No in-flight migration depends on the table (no active
     `migration.lock`; no open `apply`/`reconcile` run).
- **Do NOT use `TRUNCATE` as a "safer" alternative.** `TRUNCATE` does
  not call the rollback transaction; it permanently removes all rows
  without per-row logging, which is exactly what the
  verified-backup/empty-proof preconditions are designed to prevent.
  If a destructive reset is required, the operator MUST use `DROP
  TABLE` together with the verified backup.

#### `delete-bucket apap-photos`

- **Effect:** destructive of every uploaded photo currently stored
  under the bucket, including any data already referenced by
  `animales.nombrefoto` in the web DB. The `GET /animales/{animal_id}
  /foto` route will fall back to placeholder bytes for every row
  whose object key disappears.
- **Preconditions (MUST be true before the operator runs the
  command):**
  1. A verified export of the bucket contents (InsForge storage
     download or equivalent) is stored outside the affected InsForge
     deployment and the path is recorded in the operator ticket.
  2. `apap-photos` is empty (`apap-photos` object count = 0) OR the
     operator has recorded an explicit sign-off in the ticket
     explaining why losing the uploaded photos is acceptable.
  3. No in-flight migration depends on the bucket (no active
     `apply`/`reconcile` run referencing the bucket).
- **Never replace the bucket with a public bucket.** The PR2 private
  invariant (`isPublic=false`) is a hard privacy contract; rebuilding
  the bucket as public is rejected by the bootstrap fail-closed check.

### Code rollback (no data effect)

Revert the PR2 commit. This removes the CLI checkpoint, bucket
bootstrap wiring, and tests without touching unrelated migration
slices or any live InsForge state.
