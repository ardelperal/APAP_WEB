# #1309 — Cloudflare R2 as the S3 store; the e2e job drops MinIO

## Goal

Have the `e2e` gate validate the backend production uses (Cloudflare R2,
jurisdiction `eu`) instead of a repo-owned MinIO replica. Issue #1309 carries
the requirements, the evidence and the settled decisions; this file tracks the
work and nothing more.

## Work units

| WU | Description | State |
|---|---|---|
| WU-1 | Tracking doc + `chore/1309-*` branches in the canonical worktree | done |
| WU-2 | `s3.py` endpoint normalization + unit tests | done |
| WU-3 | `healthz.py` bucket-scoped probe + unit tests | done |
| WU-4 | Bucket admin without account-level permissions | done |
| WU-5 | Production `/healthz` through the shared probe | done |
| WU-6 | e2e storage test: no production bucket, no obsolete strict xfail | done |
| WU-7 | `ci.yml` on R2 + workflow contract tests | done |
| WU-8 | Operator runbook and replica scope notes | done |
| WU-9 | Close PR #900 as superseded | done |

Two slices: **1**, the storage client and its tests, verifiable with no R2
credentials; **2**, CI wiring, workflow contracts and operator docs, branched
off slice 1 and closing the issue.

## Gates

`ruff check .`, `scripts/check_rules.py .`, `scripts/check_workflows.py`,
`scripts/check_ruff_ratchet.py`, the focused pytest subset, and — outside the
repository — the operator provisioning the R2 tokens and the lifecycle rule.

## Out of scope

Deleting `minio-replica.yml` or its runbook (they serve `make e2e-local`,
issue #1146, which uses no R2 credentials); provisioning production buckets
from the repository; the restic token; the photos contract; migrating
attachments.
