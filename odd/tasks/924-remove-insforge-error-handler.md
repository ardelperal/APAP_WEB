# Remove obsolete InsForge error-handler chain (#924)

## Objective and boundary

Remove the unused error translation port, DI provider, and FastAPI registration shim left after the local PostgreSQL migration. Preserve the current `app/main.py` HTTP error behavior. Do not rewrite Git history, archival records, migration transports, or other InsForge aliases.

## Evidence and constraints

- Approved issue: https://github.com/ardelperal/APAP_WEB/issues/924 (`type:refactor`, `status:approved`); claim comment posted.
- CodeGraph and targeted import search show no production registration or consumers of the old handler; `app/main.py` owns the active `BackendError` handler.
- TDD: **on**, from `docs/proceso.md` §4 for `type:refactor`; runner `python3 -m pytest` for focused tests and `make verify` for closure. Observe RED, GREEN, REFACTOR.
- Branch: `refactor/924-remove-insforge-error-handler`; base `origin/main` at `b4f7246`. Root checkout is dirty and must remain untouched.
- Forecast: about 440 authored additions + deletions including this document, tests and baseline updates. Delivery strategy: `ask-on-risk`; user selected `stacked-to-main` on 2026-09-24: T1 and T2 get independently validated PRs to `main`. Budget is a slicing guide, not a reason to compress tests or prose.

## Tasks

- [x] **T1 — Remove stale handler re-export.** Remove only the dead error-handler symbols from `app/core/adapters/insforge/__init__.py` and the matching `scripts/check_layers.py` baseline. Preserve unrelated compatibility aliases. RED: existing layer gate fails after removing stale baseline; GREEN: gate and focused adapter import tests pass. Route: delegated direct (mapping/preparation covered 4+ files; one code file plus mechanical baseline). Check `python3 scripts/check_layers.py`, focused pytest, lint; commit as a coherent slice.
- [ ] **T2 — Remove unregistered handler chain.** Delete `app/core/error_handler.py`, `app/core/ports/insforge_error_handler_port.py`, and `app/core/di/insforge_error_handler_di.py`; remove only their stale `check_crap` and `check_slice_completeness` baseline entries. RED: add or adapt a test/gate proving these obsolete modules are not part of the active contract. GREEN: HTTP error tests, architecture gates, `make verify`, and `python3 -m build`. Route: delegated direct (three non-trivial files). Commit as a second work unit.

## Acceptance and delivery

- No tracked active import or registration of the removed error-handler chain.
- Current `BackendError` response remains non-leaking and covered by tests.
- No quality threshold weakened; stale baselines removed.
- Two independently reviewable PR slices to `main`; record each commit SHA, changed-line count, verification, RDD assessment, and PR boundary here. The user authorized this PR delivery strategy; no red-CI merge or history rewrite is authorized.

## Progress

- Issue approved and claimed; worktree and CodeGraph initialized.
- T1 RED: removing the stale layer baseline exposed exactly one forbidden adapter-to-DI import. GREEN: removing the dead re-export cleared the gate; `tests/test_layers.py` 19 passed; adapter import smoke, targeted Ruff, and `git diff --check` passed. `make verify PYTHON=/home/ubuntu/repos/apap-app/.venv/bin/python`: 4,618 passed, 19 skipped, 1 xfailed, 1 warning (283.48s). The dedicated worktree's system Python 3.14 lacks project tools; project venv is Python 3.12.
- T1 work-unit commit `3fd40da5a12b4dc85b22ceb409f6235652243db5`: 39 authored changed lines. Native committed-only RDD assessment against `origin/main`: `medium`, `review_due=false`, `under_budget`; no review receipt claimed. PR slice 1 contains this commit plus its task-evidence commit (pending).
- Next: deliver PR slice 1 to `main` and verify current-base CI. T2 remains untouched and depends on T1 landing before its independent PR.
