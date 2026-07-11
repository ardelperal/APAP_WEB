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

- Shadow table rollback: `DROP TABLE web_only_feature_shadow` against the intended InsForge database, only after confirming no in-flight migration depends on it.
- Bucket rollback: delete `apap-photos` via the InsForge infrastructure tool (`delete-bucket`). Never replace it with a public bucket.
- Code rollback: revert the PR2 commit. This removes the CLI checkpoint, bucket bootstrap wiring, and tests without touching unrelated migration slices.
