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

- [x] **WU-1 — Correct E2E wiring and fail-closed assertions.** Route: delegated direct; evidence: preparing a write required reading 4+ files, and workflow plus tests were non-trivial. Regression test RED/GREEN, focused and full checks, work-unit commit `1010057`, and real MinIO-backed E2E 6/6 without skips observed.
- [ ] **WU-2 — Build and pin the E2E MinIO image.** Route: delegated direct; evidence: workflow and regression test are both non-trivial. Build from a fixed upstream commit, obtain the runtime image ID from Docker without guessing, launch by that ID, test the pin contract RED/GREEN, and commit separately. Record the accepted scan findings; do not add a CI claim that the image has no critical CVEs.

## Delivery and checks

- Forecast: approximately 180 authored changed lines total; review strategy `ask-on-risk` (default), below the 400-line delivery budget. Running total: 77 authored lines in work-unit commit `1010057`.
- `make verify` before requesting review; focused checks per task. No PR, push, or merge without separate remote authorization.
- RDD mode is on (global); assess each work-unit commit and follow native transitions when due.

## Progress and evidence

- 2026-09-24: exploration found invalid endpoint, step-scoped credentials, permissive health assertion, and no locally available MinIO image digest. No source edits yet.
- WU-1: code and tests committed as `1010057`. RED: focused workflow regression failed on the old endpoint. GREEN: focused regression passed, `tests/test_ci_workflow.py` passed (81 tests), Ruff and `git diff --check` passed. `make verify` passed: 4,615 tests passed, 19 skipped, 1 xfailed; the skips were outside E2E. The new storage-health assertion did not have a separate observed RED. Real MinIO-backed E2E subsequently passed 6/6 without skips. RDD assessed high risk due workflow shell/process boundary; review was granted, all four lenses returned no findings, and the approved authority was acknowledged for commit `1010057`.
- WU-2: implementation ready, commit and RDD pending. Workflow regression RED (2 focused failures), then GREEN (82 workflow tests); a missing Docker daemon preflight also failed `check_workflows` before correction. The exact extracted source-build/start step succeeded locally and verified the Docker image ID and source-revision label. Real ephemeral PostgreSQL + MinIO + Playwright E2E passed 6/6 without skips. `make verify` passed: 4,616 passed, 19 skipped, 1 xfailed, 86.03% coverage. Ruff, YAML parse, shell syntax, and diff check passed. Hosted GitHub CI has not run.
- 2026-09-24: anonymous Docker Hub manifest inspect and pull for `minio/minio:latest` failed with denied/insufficient-scope, and the Docker Hub latest-tag endpoint returned HTTP 404. The upstream MinIO Compose example names `quay.io/minio/minio:RELEASE.2025-09-06T17-38-46Z`, but Quay availability and digest remain unverified. WU-1 runtime E2E and WU-2 are waiting for explicit authorization to inspect and pull from Quay.
- 2026-09-24: the authorized anonymous Quay manifest lookup, image pull, and tag API request also failed with HTTP 401. The upstream MinIO README states that the community edition is source-only. A source-built image at a fixed upstream commit versus a different object-store distribution is an unresolved product/operations decision; do not invent a digest or mark either task complete.
- 2026-09-24: the user selected the source-built MinIO option, conditional on no detected critical CVEs. Anonymous upstream source inspection found commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` as a candidate only, not a vetted release. The local Go module cache lacks dependencies and no current scanner database is available. Compilation and CVE verification await authorization for the Go module proxy and the scanner database registry. Neither work unit is complete.
- 2026-09-24: the user authorized anonymous read-only downloads from `proxy.golang.org` and `ghcr.io/aquasecurity/trivy-db` for the fixed-source build and vulnerability scan; no credentials, publication, or other destinations were authorized. Build and scan results are pending.
- 2026-09-24: a guarded build and scan did not reach unauthorized hosts. Go module ZIP downloads redirected from `proxy.golang.org` to `storage.googleapis.com`; the Trivy DB blob redirected from GHCR to `pkg-containers.githubusercontent.com`. Both redirects were rejected. No binary, image, or CVE result exists yet.
- 2026-09-24: the user authorized anonymous read-only downloads from both observed redirect hosts. A local scratch image was built from fixed MinIO source commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` (image ID `sha256:81d92457bdedafbbe604c7a6bedffb43cbbeb4ed7ee2e30664e1d9d6bef6eb41`, not published). Trivy v0.73 image scan with DB UpdatedAt `2026-09-24T13:23:01Z` detected seven CRITICAL findings, including two in MinIO itself with no fixed version listed. The candidate fails the user's acceptance condition. The local report is `/tmp/trivy-894-cache/minio-image-scan.json`; no repository source files changed. Scanner findings are not an independent exploitability assessment.
- 2026-09-24: the user removed the no-critical-CVE condition and accepted the scanned MinIO image as-is for E2E only. Keep the seven findings visible; do not publish the image or use it in production. The CI implementation must build from the fixed source SHA and launch by the verified local image ID because hosted Actions starts `services` before build steps.
- 2026-09-24: the real E2E exposed two additional false-green causes: the photo fixture used a nonexistent `animales.nombre` column and a non-UUID ID, then the photo metadata adapter queried nonexistent `"NombreFoto"` rather than physical `nombrefoto`. The failing test returned a 68-byte placeholder instead of the stored 67-byte object. The narrow production query fix aliases `nombrefoto AS "NombreFoto"` to preserve its row contract; real E2E is now green. This production edit is within the task's explicit exception for a failing test that proves it necessary.
- Engram mirror: current after read-back.

## Next step

Commit WU-2 with its tests, then assess that commit through RDD. Hosted GitHub CI, push, PR, and merge remain pending. The accepted seven-critical-CVE risk applies only to this E2E image.
