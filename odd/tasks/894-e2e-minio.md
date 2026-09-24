# #894 — Make MinIO E2E evidence trustworthy

## Objective

Fix the MinIO E2E false green before using that suite as a deployment gate. Issue #894 is approved.

## Problem and why

The application-start step passes a literal URL with an unexpanded port to `Minio`, and its step-scoped S3 credentials do not reach pytest. The health test accepts `up`, `down`, or `unconfigured`. A green run therefore does not prove storage works.

## Scope and constraints

- Change only the E2E workflow and its focused regression tests unless a failing test proves a production change necessary.
- Use a digest-pinned MinIO image; do not invent a digest. Registry lookup requires separate remote authorization if no locally verified digest exists.
- Preserve the fail-closed release/manual event matrix and the existing production storage contract.
- Strict TDD: RED → GREEN → REFACTOR (`docs/proceso.md` §4). Runner: `python -m pytest`; CI E2E runner: `python -m pytest tests/e2e_ci/ -v`.
- Branch: `fix/894-e2e-minio` in a dedicated sibling worktree. The root checkout has unrelated changes and remains untouched.

## Acceptance criteria

1. The E2E application receives an expanded, scheme-free `host:port` endpoint.
2. Pytest receives the MinIO credentials and endpoint needed to run the photo test without an implicit skip.
3. With MinIO configured, the health test requires `storage == "up"`; invalid or unreachable storage fails.
4. The MinIO service image is pinned to a verified immutable digest.

## Tasks

- [ ] **WU-1 — Correct E2E wiring and fail-closed assertions.** Route: delegated direct; evidence: preparing a write requires reading 4+ files, and workflow plus tests are non-trivial. Write regression tests first and observe RED, then fix workflow/assertions and observe GREEN, then refactor. Check focused pytest, workflow gate, and applicable E2E runtime. Commit behavior and tests together.
- [ ] **WU-2 — Pin the MinIO service image.** Route: delegated direct if workflow and test both change; evidence: two non-trivial files. Obtain an authoritative digest without guessing, test the pin contract RED/GREEN, and commit separately. If registry access is not authorized, record the blocker and leave this task open.

## Delivery and checks

- Forecast: approximately 180 authored changed lines total; review strategy `ask-on-risk` (default), below the 400-line delivery budget. Running total: 0.
- `make verify` before requesting review; focused checks per task. No PR, push, or merge without separate remote authorization.
- RDD mode is on (global); assess each work-unit commit and follow native transitions when due.

## Progress and evidence

- 2026-09-24: exploration found invalid endpoint, step-scoped credentials, permissive health assertion, and no locally available MinIO image digest. No source edits yet.
- WU-1: code and tests implemented; runtime E2E pending. RED: focused workflow regression failed on the old endpoint. GREEN: focused regression passed, `tests/test_ci_workflow.py` passed (81 tests), Ruff and `git diff --check` passed. `make verify` passed: 4,615 tests passed, 19 skipped, 1 xfailed; the skips were outside E2E. The new storage-health assertion did not have a separate observed RED. No local MinIO image is available, so the real E2E was not run. Commit: pending.
- WU-2: pending. Digest evidence and commit: pending.
- Engram mirror: current after read-back.

## Next step

Commit the bounded WU-1 change, assess its native review risk, then obtain authorization for the MinIO registry lookup and local E2E runtime before closing WU-1 or pinning WU-2.
