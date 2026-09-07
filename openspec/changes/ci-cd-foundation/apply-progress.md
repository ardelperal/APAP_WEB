# Apply progress: ci-cd-foundation — status reconciliation

## Session

| Field | Value |
|-------|-------|
| **Project** | APAP_WEB |
| **Change** | `ci-cd-foundation` |
| **Branch** | `staging` |
| **Scope of this update** | SDD documentation/status only; no CI/CD implementation, no GitHub settings, no push |
| **Date** | 2026-06-25 |

## Current status

The active change was not archive-ready because `proposal.md` and `specs/ci-cd-pipeline/spec.md` were missing, task `2.3` was documented N/A but still unchecked, task `3.3` had design evidence but was unchecked, and this progress file still reported only the early PR 1/PR 2 state.

This update reconstructs the missing proposal/spec from current `tasks.md` and `design.md` without adding implementation evidence.

## Completed / accepted-by-decision tasks

| ID | Status | Evidence |
|----|--------|----------|
| 0.1–0.6 | Complete | Local quality surface exists and was previously verified. |
| 1.1–1.4 | Complete | `.github/workflows/ci.yml`, `tests/test_ci_workflow.py`, and `.github/branch-protection.md` exist. |
| 2.1, 2.2, 2.4 | Complete | Deploy job, Coolify webhook step, and deploy secret-leak scan exist in `.github/workflows/ci.yml`. |
| 2.3 | N/A / completed by decision | LocalBackend hosting deployment is obsolete for APAP_WEB; app deploys as FastAPI Docker app through Coolify, while LocalBackend is BaaS only. |
| 3.1–3.2 | Complete | Reconstructed spec includes deferred staging/UAT and two-environment Coolify requirements/scenarios. |
| 3.3 | Complete | `design.md § Future work` lists CD-03, ENV-01, CD-04, UAT-01..03, E2E-01..06, E2E-M1..M4, WORKER-01..04 out of scope. |

## Operator-required external acceptance blockers

These remain unchecked in `tasks.md` and block archive readiness until external evidence exists:

- `1.5` — operator enables branch protection for the active protected branch policy (`staging` for normal work; `main` for production if required) and records UI/settings evidence.
- `1.6` — operator opens/verifies a test PR and records the GitHub checks evidence.
- `2.5` — operator confirms `COOLIFY_WEBHOOK_URL` is configured before production deploy.
- `2.6` — operator records first production deploy dry-run evidence; expected-red is acceptable only with an explicit operator comment.

## Deferred future-change tasks

The CD-03, ENV-01, CD-04, UAT, E2E, mobile E2E, and worker items remain unchecked by design. They are not implementation tasks for `ci-cd-foundation`; they are seeds for future SDD changes.

## Verification status

| Gate | Status | Notes |
|------|--------|-------|
| Local tests | Pass (prior verifier evidence) | `pytest` previously reported `421 passed, 2 skipped`. Not rerun in this docs-only update. |
| Lint | Pass (prior verifier evidence) | `ruff check .` previously passed. Not rerun in this docs-only update. |
| Build | Pass (prior verifier evidence) | `python -m build` previously passed. Not rerun in this docs-only update. |
| Spec validation | Unblocked | `proposal.md` and `specs/ci-cd-pipeline/spec.md` now exist. |
| Archive readiness | Blocked | External operator evidence tasks `1.5`, `1.6`, `2.5`, and `2.6` remain unchecked. |

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `d51667a4bf81a232ea6c6f9823a9eb1e4183c0e9` | `chore(ci-cd-foundation): add local test surface` | 0.1–0.6 | `git log --name-status` shows `pyproject.toml`, `Makefile`, `docs/development.md`, `tests/test_smoke.py`, and `openspec/config.yaml`; prior verifier evidence: `pytest` 421 passed/2 skipped, `ruff check .`, `python -m build`. | N/A |
| `291a39be98f15b5b11645e25af49d8e28d387d16` | `ci(ci-cd-foundation): add GitHub Actions workflow` | 1.1–1.4 | `git log --name-status` shows `.github/workflows/ci.yml`, `.github/branch-protection.md`, and `tests/test_ci_workflow.py`; CI workflow is parsed by GitHub Actions on push. | N/A |
| `de7f6d75b4ba2302026f56b2c49ea15bd66c4550` | `fix(ci): make GitHub Actions workflow valid` | 1.1–1.4 | `git log --name-status` shows workflow/test corrections after the initial CI commit; `tests/test_ci_workflow.py` verifies workflow shape and branch-protection doc checks. | N/A |
| `225ef9c33237a7ed00a9bf14de521f79caf290bd` | `feat(ci): add deploy job to CI workflow (CD-01, issue #1)` | 2.1, 2.2, 2.4 | `git log --name-status` shows `.github/workflows/ci.yml` and `tests/test_ci_workflow.py`; current workflow contains deploy gating, Coolify webhook, and deploy secret scan. | N/A |
| `93cfb956f0a0aed5a4a539c212e1bfc382b4a3d3` | `docs(ci-cd): marcar CD-02 (local_backend_create-deployment) como N/A` | 2.3 | `git log --name-status` shows SDD design/tasks decision that LocalBackend hosting deploy is N/A; APAP_WEB deploy target is Coolify. | N/A |

## Files changed by this status update

| File | Action | Purpose |
|------|--------|---------|
| `openspec/changes/ci-cd-foundation/proposal.md` | Created | Minimal reconstructed proposal from current design/tasks. |
| `openspec/changes/ci-cd-foundation/specs/ci-cd-pipeline/spec.md` | Created | Minimal full spec for the new `ci-cd-pipeline` capability. |
| `openspec/changes/ci-cd-foundation/tasks.md` | Updated | Marked `2.3` N/A complete, marked `3.1–3.3` complete from spec/design evidence, preserved operator blockers, and updated stale branch-policy wording. |
| `openspec/changes/ci-cd-foundation/design.md` | Updated | Clarified current `staging` policy and removed obsolete LocalBackend-hosting assumptions. |
| `openspec/changes/ci-cd-foundation/apply-progress.md` | Rewritten | Replaced stale 10/31 status with current archive-blocker status. |
| `docs/development.md` | Updated | Scoped branch/deploy wording to current `staging` normal-work policy and `main` production trigger. |
| `.github/branch-protection.md` | Updated | Scoped branch-protection instructions to the active protected branch policy instead of `main` only. |
| `docs/architecture/architecture-local-backend-stack.md` | Updated | Scoped branch/deploy policy to current `staging` normal-work and `main` production split. |
| `docs/roadmap.md` | Updated | Replaced stale pre-MVC main-only workflow wording with current staging-first policy. |

## Status

Archive is still blocked, but for the right reason: operator-required external acceptance evidence is missing. The missing proposal/spec validation gap has been closed, and local gates remain green based on prior verifier evidence.
