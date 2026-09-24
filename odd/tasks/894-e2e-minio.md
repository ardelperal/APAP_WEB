# #894 — Make MinIO E2E evidence trustworthy

## Objective

Fix the MinIO E2E false green before using that suite as a deployment gate. Issue #894 is approved.

## Problem and why

The application-start step passes a literal URL with an unexpanded port to `Minio`, and its step-scoped S3 credentials do not reach pytest. The health test accepts `up`, `down`, or `unconfigured`. A green run therefore does not prove storage works.

## Scope and constraints

- Change only the E2E workflow and its focused regression tests unless a failing test proves a production change necessary.
- Use a reproducible MinIO image built from a fixed upstream source commit and launched by its locally verified immutable image ID. The user accepted the seven CRITICAL Trivy findings for this E2E-only image; do not present it as safe or reuse it in production.
- Preserve the fail-closed release/manual event matrix and the existing production storage contract.
- Strict TDD: RED → GREEN → REFACTOR (`docs/proceso.md` §4). Runner: `python -m pytest`; CI E2E runner: `python -m pytest tests/e2e_ci/ -v`.
- Branch: `fix/894-e2e-minio` in a dedicated sibling worktree. The root checkout has unrelated changes and remains untouched.

## Acceptance criteria

1. The E2E application receives an expanded, scheme-free `host:port` endpoint.
2. Pytest receives the MinIO credentials and endpoint needed to run the photo test without an implicit skip.
3. With MinIO configured, the health test requires `storage == "up"`; invalid or unreachable storage fails.
4. The E2E MinIO image is built from a fixed upstream source commit, the scanned risk is documented, and the runner launches it by its verified immutable image ID rather than a floating tag.

## Tasks

- [x] **WU-1 — Correct E2E wiring and fail-closed assertions.** Route: delegated direct; evidence: preparing a write required reading 4+ files, and workflow plus tests were non-trivial. Regression test RED/GREEN, focused and full checks, work-unit commit `8eb2dc2` (rebased from `1010057`), and real MinIO-backed E2E 6/6 without skips observed.
- [x] **WU-2 — Build and pin the E2E MinIO image.** Route: delegated direct; evidence: workflow and regression test were both non-trivial. Fixed upstream source and Go toolchain, verified Docker image ID and revision label, launched by ID, observed regression RED/GREEN and real E2E GREEN. Committed as `487713a` (rebased from `d8677e4`); previous native RDD approval applied to the pre-rebase candidate, so the new combined candidate requires review.

## Delivery and checks

- Forecast: approximately 220 authored changed lines total; review strategy `ask-on-risk` (default), below the 400-line delivery budget. Running total: 220 authored lines across rebased work-unit commits `8eb2dc2` (77) and `487713a` (143).
- `make verify` before requesting review; focused checks per task. Push, PR creation, and manual `ci.yml` dispatch were authorized; merge was not.
- RDD mode is on (global). The latest rebased candidate received four-lens native approval, acknowledged under lineage `review-1f7b9d66dc1c617c`. Earlier approvals covered only their pre-rebase identities.

## Progress and evidence

- 2026-09-24: exploration found invalid endpoint, step-scoped credentials, permissive health assertion, and no locally available MinIO image digest. No source edits yet.
- WU-1: code and tests committed as `8eb2dc2` after rebase. RED: focused workflow regression failed on the old endpoint. GREEN: focused regression passed, `tests/test_ci_workflow.py` passed (81 tests), Ruff and `git diff --check` passed. `make verify` passed: 4,615 tests passed, 19 skipped, 1 xfailed; the skips were outside E2E. The new storage-health assertion did not have a separate observed RED. Real MinIO-backed E2E subsequently passed 6/6 without skips. RDD approved and acknowledged the original pre-rebase commit `1010057` only.
- WU-2: committed as `487713a` after rebase. Workflow regression RED (2 focused failures), then GREEN (82 workflow tests); a missing Docker daemon preflight also failed `check_workflows` before correction. The exact extracted source-build/start step succeeded locally and verified the Docker image ID and source-revision label. Real ephemeral PostgreSQL + MinIO + Playwright E2E passed 6/6 without skips. `make verify` passed before rebase: 4,616 passed, 19 skipped, 1 xfailed, 86.03% coverage. Ruff, YAML parse, shell syntax, and diff check passed. Native RDD approved and acknowledged original pre-rebase commit `d8677e4` (lineage `review-705ab459e3702338`); the rebased candidate has no inherited approval. Hosted GitHub CI has not run.
- 2026-09-24: anonymous Docker Hub manifest inspect and pull for `minio/minio:latest` failed with denied/insufficient-scope, and the Docker Hub latest-tag endpoint returned HTTP 404. The upstream MinIO Compose example names `quay.io/minio/minio:RELEASE.2025-09-06T17-38-46Z`, but Quay availability and digest remain unverified. WU-1 runtime E2E and WU-2 are waiting for explicit authorization to inspect and pull from Quay.
- 2026-09-24: the authorized anonymous Quay manifest lookup, image pull, and tag API request also failed with HTTP 401. The upstream MinIO README states that the community edition is source-only. A source-built image at a fixed upstream commit versus a different object-store distribution is an unresolved product/operations decision; do not invent a digest or mark either task complete.
- 2026-09-24: the user selected the source-built MinIO option, conditional on no detected critical CVEs. Anonymous upstream source inspection found commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` as a candidate only, not a vetted release. The local Go module cache lacks dependencies and no current scanner database is available. Compilation and CVE verification await authorization for the Go module proxy and the scanner database registry. Neither work unit is complete.
- 2026-09-24: the user authorized anonymous read-only downloads from `proxy.golang.org` and `ghcr.io/aquasecurity/trivy-db` for the fixed-source build and vulnerability scan; no credentials, publication, or other destinations were authorized. Build and scan results are pending.
- 2026-09-24: a guarded build and scan did not reach unauthorized hosts. Go module ZIP downloads redirected from `proxy.golang.org` to `storage.googleapis.com`; the Trivy DB blob redirected from GHCR to `pkg-containers.githubusercontent.com`. Both redirects were rejected. No binary, image, or CVE result exists yet.
- 2026-09-24: the user authorized anonymous read-only downloads from both observed redirect hosts. A local scratch image was built from fixed MinIO source commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` (image ID `sha256:81d92457bdedafbbe604c7a6bedffb43cbbeb4ed7ee2e30664e1d9d6bef6eb41`, not published). Trivy v0.73 image scan with DB UpdatedAt `2026-09-24T13:23:01Z` detected seven CRITICAL findings, including two in MinIO itself with no fixed version listed. The candidate fails the user's acceptance condition. The local report is `/tmp/trivy-894-cache/minio-image-scan.json`; no repository source files changed. Scanner findings are not an independent exploitability assessment.
- 2026-09-24: the user removed the no-critical-CVE condition and accepted the scanned MinIO image as-is for E2E only. Keep the seven findings visible; do not publish the image or use it in production. The CI implementation must build from the fixed source SHA and launch by the verified local image ID because hosted Actions starts `services` before build steps.
- 2026-09-24: the user confirmed that no further MinIO image hardening is wanted; continue the approved CI/CD issue sequence without an image fork.
- 2026-09-24: the real E2E exposed two additional false-green causes: the photo fixture used a nonexistent `animales.nombre` column and a non-UUID ID, then the photo metadata adapter queried nonexistent `"NombreFoto"` rather than physical `nombrefoto`. The failing test returned a 68-byte placeholder instead of the stored 67-byte object. The narrow production query fix aliases `nombrefoto AS "NombreFoto"` to preserve its row contract; real E2E is now green. This production edit is within the task's explicit exception for a failing test that proves it necessary.
- 2026-09-24: `origin/main` advanced to `3895721` through #821 frontend work. Rebase was conflict-free; the changed base invalidated the old native review target identity. On the rebased tree, `PYTHON=/home/ubuntu/repos/apap-app/.venv/bin/python make verify` passed: 4,616 passed, 19 skipped, 1 xfailed, 86.03% coverage, `check_crap` OK. The earlier 6/6 real E2E run was before rebase; the hosted dispatch remains pending.
- 2026-09-24: `origin/main` advanced again to `b4f7246` before publication. Rebase was conflict-free. `make verify` on the new base passed: 4,620 passed, 19 skipped, 1 xfailed, 85.98% coverage, `check_crap` OK. The exact rebased candidate passed and acknowledged native RDD review.
- 2026-09-24: branch `fix/894-e2e-minio` was pushed using the stored `ardelperal` OAuth credential, and PR [#900](https://github.com/ardelperal/APAP_WEB/pull/900) opened with `type:bug`. PR run [36028817592](https://github.com/ardelperal/APAP_WEB/actions/runs/36028817592) passed, including `ci / required`; E2E was skipped on the PR event by the existing event matrix.
- 2026-09-24: manual `ci.yml` run [36028890804](https://github.com/ardelperal/APAP_WEB/actions/runs/36028890804) passed `build` and the real `e2e` job, but the run and `required` failed: `mutation` found no tests in its unmutated Cosmic Ray baseline, and `security-deep` found 11 full-history Gitleaks findings in older files. These failures are outside the #894 diff. Do not call the manual workflow green or merge while it remains red.
- Engram mirror: current after read-back.

## Next step

Keep PR #900 unmerged. Triage the manual-only `mutation` and `security-deep` failures separately without hiding the red status or widening #894; then continue approved issues #895 and #896 in order. The accepted seven-critical-CVE risk applies only to this E2E image.
