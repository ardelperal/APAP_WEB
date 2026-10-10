# #1309 — Cloudflare R2 as the S3 store; the e2e job drops MinIO

## Goal

Have the `e2e` gate validate the backend production uses (Cloudflare R2,
jurisdiction `eu`) instead of a repo-owned MinIO replica, and delete the
apparatus that no longer earns its keep. Three verified defects close on the
way:

1. `s3.py` did not normalize the endpoint and swallowed client errors, so a
   scheme-bearing `APAP_S3_ENDPOINT` degraded silently to "no storage".
2. `healthz.py` — and production `/healthz` in `app/main.py`, which registers
   its own handler — probed with `list_buckets()`, an account-level call that a
   bucket-scoped token is denied. A healthy bucket was reported `down`, which
   is a Coolify restart after three failures.
3. `tests/e2e_ci/test_minio_storage.py` hardcoded `PHOTO_BUCKET =
   "apap-photos"` and both put and removed objects there.

## Decisions (settled, not reopened here)

- Production and e2e buckets are separate. CI's token is scoped to `apap-e2e`
  only, so the isolation does not depend on the code being right.
- Test objects land under a per-run prefix that an R2 lifecycle rule expires.
- An R2 outage blocks the release on purpose: the gate measures real
  availability instead of returning a false green.
- Bucket jurisdiction is `eu` and irreversible once created.

## Work units

| WU | Description | State |
|---|---|---|
| WU-1 | Tracking doc + `chore/1309-*` branches in the canonical worktree | done |
| WU-2 | `s3.py` endpoint normalization + unit tests | done |
| WU-3 | `healthz.py` bucket probe + unit tests | done |
| WU-4 | Bucket admin without account-level permissions | done |
| WU-5 | e2e bucket from the environment + per-run prefix | done |
| WU-6 | Production `/healthz` routed through the shared probe | done |
| WU-7 | `ci.yml` on R2 + workflow contract tests | done |
| WU-8 | Operator runbook and replica scope notes | done |
| WU-9 | Close PR #900 as superseded | pending |

## Slices

- **Slice 1** — app-side defect fixes: `s3.py`, `healthz.py`, `storage.py`,
  `app/main.py` and their unit tests. Verifiable entirely on a workstation
  with no R2 credentials, so it merges on its own.
- **Slice 2** — CI wiring, workflow contracts and operator docs. Branches off
  slice 1 and closes the issue.

## Gates

`ruff check .`, `scripts/check_rules.py .`, `scripts/check_workflows.py`,
`scripts/preflight.py`, the focused pytest subset — and, outside the
repository, the operator provisioning the R2 tokens and the `apap-e2e`
lifecycle rule.

## Out of scope

Deleting `.github/workflows/minio-replica.yml` or
`docs/operations/minio-replica.md`: they serve `make e2e-local` (issue #1146),
which must keep working without R2 credentials. Also out: provisioning
production buckets from the repository, touching the restic token, changing
the photos contract, and migrating existing attachments.
