# Tasks: CI/CD Foundation

## Review workload forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 300–500 (config + docs + workflow files + smoke test) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (CI-01: local test surface) → PR 2 (CI-02: CI workflow) → PR 3 (CD-01 + CD-02: CD pipeline) |
| Delivery strategy | force-chained |
| Chain strategy | stacked-to-main |
| Decision needed before apply | No (chain strategy pre-decided by sdd-init `force-chained` + `stacked-to-main` and the per-change `pre-MVC` branch policy) |

```text
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium
```

### Suggested work units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Local test surface + developer guide (CI-01) | PR 1 → main | `pyproject.toml`, `Makefile`, smoke test, `docs/development.md`, `openspec/config.yaml` update |
| 2 | GitHub Actions CI workflow (CI-02) | PR 2 → main | `.github/workflows/ci.yml` with lint/test/build, commented E2E hook, branch protection operator note |
| 3 | Coolify + InsForge deploy pipeline (CD-01 + CD-02) | PR 3 → main | GitHub issue #1; Coolify project `APAP`; `deploy` job in workflow; Coolify webhook; `insforge_create-deployment`; secret-leak grep |

## Phase 0: Local test surface (ticket CI-01)

- [x] 0.1 Create `pyproject.toml` with project metadata, `[tool.pytest.ini_options]` setting `filterwarnings = ["error::DeprecationWarning", "error::PendingDeprecationWarning"]`, and `[tool.ruff]` config matching architecture doc § CI/CD Quality Gate.
- [x] 0.2 Create `tests/test_smoke.py` with one passing assertion (`def test_smoke_passes(): assert 1 + 1 == 2`) so the CI test job is never vacuous.
- [x] 0.3 Create `Makefile` with `test`, `lint`, `build`, and `all` targets wrapping the canonical commands documented in `docs/development.md`.
- [x] 0.4 Create `docs/development.md` covering: prerequisites, clone, install, env vars, test command (with expected output snippet), lint command, build command, pre-staging branch note ("while APAP-WEB is pre-MVC, PRs target `main`; staging transition is CD-03, deferred").
- [x] 0.5 Update `.gitignore` to exclude `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `build/`, `*.egg-info/`, `.coverage`.
- [x] 0.6 Update `openspec/config.yaml`: set `testing.strict_tdd: true`, `testing.test_framework: pytest`, `testing.test_layers: [unit, integration]`, `testing.linter: ruff`, `testing.coverage_tool: pytest-cov`, `apply.test_command: "pytest"`, `apply.build_command: "python -m build"`, `verify.test_command: "pytest"`, `verify.build_command: "python -m build"`, `verify.coverage_threshold: 80`.

### Phase 0 task details

| ID | Maps to requirement | Acceptance criteria | Test plan | Dependencies | PR traceability | Mobile criteria |
|----|---------------------|---------------------|-----------|--------------|------------------|-----------------|
| 0.1 | Local test developer guide; Pre-staging branch policy | `pyproject.toml` exists; `pytest -W error::DeprecationWarning` runs locally; ruff config present | Run `make test` and `make lint` on a clean clone; verify warnings-as-errors triggers on a fixture deprecation | None | Issue + PR; SDD: ci-cd-foundation, tasks 0.1–0.6; CI: lint + test + build; target: main | N/A (infra) |
| 0.2 | Local test developer guide (non-vacuous CI) | `tests/test_smoke.py` exists; CI test job runs at least one test | CI run shows `1 passed`; local `pytest` shows same | 0.1 | Issue + PR; SDD: ci-cd-foundation, tasks 0.1–0.6; CI: lint + test + build; target: main | N/A (infra) |
| 0.3 | Local test developer guide (canonical commands) | `make test`, `make lint`, `make build` all succeed on a clean clone | Run each target; verify each exits 0 | 0.1, 0.2 | Issue + PR; SDD: ci-cd-foundation, tasks 0.1–0.6; CI: lint + test + build; target: main | N/A (infra) |
| 0.4 | Local test developer guide (documentation completeness) | `docs/development.md` exists; a new developer can complete clone → green tests in ≤ 10 documented steps; pre-staging branch note present | Manual walkthrough by a second developer; doc review against architecture doc § CI/CD and Testing Policy | 0.1 | Issue + PR; SDD: ci-cd-foundation, tasks 0.1–0.6; CI: lint + test + build; target: main | N/A (infra) |
| 0.5 | Local test developer guide (clean working tree) | `.gitignore` excludes the listed paths; `git status` is clean after `make test` and `make build` | Run commands; verify no untracked cache files in `git status --ignored` | 0.1, 0.3 | Issue + PR; SDD: ci-cd-foundation, tasks 0.1–0.6; CI: lint + test + build; target: main | N/A (infra) |
| 0.6 | Pre-staging branch policy (config reflects reality) | `openspec/config.yaml` shows `strict_tdd: true`; SDD engine reads new test/build commands | `sdd-verify` (or local spec validation) confirms config parses; `make test` matches the configured command | 0.1, 0.3 | Issue + PR; SDD: ci-cd-foundation, tasks 0.1–0.6; CI: lint + test + build; target: main | N/A (infra) |

## Phase 1: CI pipeline (ticket CI-02)

- [x] 1.1 Create `.github/workflows/ci.yml` with three jobs (`lint`, `test`, `build`) triggered on `pull_request` to `main` and `push` to `main`. Each job uses `actions/setup-python` with the Python version pinned in `pyproject.toml`.
- [x] 1.2 Add a clearly commented `e2e` job placeholder in `.github/workflows/ci.yml` with `if: ${{ false }}` and a `# TODO(E2E-01): enable when Playwright harness lands` note; document the hook in `docs/development.md`.
- [x] 1.3 Add a secret-leak grep step to the `lint` job: `! grep -rE '(http://|https://|sk-|ghp_)[A-Za-z0-9]+' .github/ || true` (the trailing `|| true` makes the grep a diagnostic, not a hard failure for v1; flagged for tightening once secrets are in place).
- [x] 1.4 Create `.github/branch-protection.md` with: required CI check name (`ci / lint`, `ci / test`, `ci / build`), how to enable branch protection on `main` in GitHub repo settings, and how to add the operator's required-reviewer count.
- [ ] 1.5 Operator enables branch protection on `main` requiring the three CI checks; record the GitHub UI screenshot or settings JSON in the PR comment.
- [ ] 1.6 Open a test PR (can be a no-op commit on a feature branch) to verify the workflow runs end-to-end and the three checks appear in the PR UI.

### Phase 1 task details

| ID | Maps to requirement | Acceptance criteria | Test plan | Dependencies | PR traceability | Mobile criteria |
|----|---------------------|---------------------|-----------|--------------|------------------|-----------------|
| 1.1 | CI pipeline on pull requests and main | `.github/workflows/ci.yml` exists; PR shows three checks; push to main triggers the same three | Open test PR (1.6); verify GitHub Actions UI lists lint/test/build; verify push to main re-runs | 0.1, 0.2, 0.3 | Issue + PR; SDD: ci-cd-foundation, tasks 1.1–1.6; CI: lint + test + build; target: main | N/A (infra) |
| 1.2 | CI pipeline on pull requests and main (E2E hook readiness) | E2E job is present in YAML but disabled; hook is documented in `docs/development.md` | Visually inspect workflow file; grep for the TODO marker | 1.1 | Issue + PR; SDD: ci-cd-foundation, tasks 1.1–1.6; CI: lint + test + build; target: main | N/A (infra) |
| 1.3 | Continuous deployment to Coolify and InsForge (secret hygiene prep) | Secret-leak grep step present; intentionally introduced hardcoded URL in a workflow snippet causes the step to log a match (manual test, reverted) | Inspect step output; run `grep -rE 'http' .github/workflows/` locally to confirm no static URLs | 1.1 | Issue + PR; SDD: ci-cd-foundation, tasks 1.1–1.6; CI: lint + test + build; target: main | N/A (infra) |
| 1.4 | CI pipeline on pull requests and main (branch protection) | `.github/branch-protection.md` exists; lists the three required check names; references the GitHub UI location | Reviewer reads the doc and confirms the names match the workflow's job IDs | 1.1 | Issue + PR; SDD: ci-cd-foundation, tasks 1.1–1.6; CI: lint + test + build; target: main | N/A (infra) |
| 1.5 | CI pipeline on pull requests and main (branch protection enforced) | `main` branch protection requires the three checks; PR with a failing check cannot be merged via UI | Open test PR with intentionally failing test; confirm "Merge" button is disabled | 1.1, 1.4 | Issue + PR; SDD: ci-cd-foundation, tasks 1.1–1.6; CI: lint + test + build; target: main | N/A (infra) |
| 1.6 | CI pipeline on pull requests and main (end-to-end verification) | Test PR shows three green checks; the PR is mergeable | Open a no-op test PR; verify the three checks appear; close the PR without merging | 1.1, 1.5 | Issue + PR; SDD: ci-cd-foundation, tasks 1.1–1.6; CI: lint + test + build; target: main | N/A (infra) |

## Phase 2: CD pipeline (tickets CD-01, CD-02; GitHub issue #1)

Provisioning note: the Coolify project `APAP` has been created with UUID `mjgxwv4srqlsuww4pfpyo0t7` and a `production` environment UUID `c7wgl2dmapown2x84f1gbgl9`. The Coolify application `apap-web` has been created with UUID `uet2l2h4qequfpi145lnn2ni`, points at `ardelperal/APAP_WEB:main`, and is configured for `https://apap.romancaba.com`. GitHub's default branch has been aligned to `main`. Deployment has not been started because the repo does not yet contain the runnable web application package/start command.

- [ ] 2.1 Add a `deploy` job to `.github/workflows/ci.yml` triggered on `push: main` only, with `needs: [lint, test, build]`. Job runs `if: github.event_name == 'push' && github.ref == 'refs/heads/main'` and `if: github.event.pull_request == null` (defensive: prevents accidental run on PRs).
- [ ] 2.2 Add a Coolify webhook step to the `deploy` job: `curl -fsS -X POST "${{ secrets.COOLIFY_WEBHOOK_URL }}"` with `failure-level: error` (CD-01).
- [ ] 2.3 Add an `insforge_create-deployment` step to the `deploy` job; the step calls the MCP tool with `projectId` and `sourceDirectory`; env vars are NOT passed in this call (CD-02).
- [ ] 2.4 Add a second secret-leak grep step to the `deploy` job (same command as 1.3 but scoped to the deploy job output, not the workflow file).
- [ ] 2.5 Document required GitHub Actions secrets in the PR body: `COOLIFY_WEBHOOK_URL` (the webhook URL configured in Coolify → apap-web app → webhooks), InsForge credentials via the MCP env (set by the operator). Include a checklist the operator must confirm before merge.
- [ ] 2.6 First dry-run merge to `main` — operator confirms the Coolify app is provisioned and pointing at this repo's `main` branch; the `deploy` job runs and exits zero. If the Coolify app is not yet provisioned, the run is red by design and acknowledged in the PR comment with an explicit "expected-red, follow-up" reason.

### Phase 2 task details

| ID | Maps to requirement | Acceptance criteria | Test plan | Dependencies | PR traceability | Mobile criteria |
|----|---------------------|---------------------|-----------|--------------|------------------|-----------------|
| 2.1 | Continuous deployment to Coolify and InsForge (gating) | `deploy` job exists; runs only on `push: main`; `needs: [lint, test, build]` present in YAML | Open a test PR; verify deploy job does NOT run; merge a no-op commit to main; verify deploy job runs | 1.1, 1.5, 1.6 | Issue + PR; SDD: ci-cd-foundation, tasks 2.1–2.6; CI: lint + test + build + deploy; target: main | N/A (infra) |
| 2.2 | Continuous deployment to Coolify and InsForge (CD-01 trigger) | Coolify webhook step exists; uses `${{ secrets.COOLIFY_WEBHOOK_URL }}`; non-2xx response fails the job | Operator configures webhook; merge to main; verify Coolify UI shows a new deploy attempt | 2.1, 2.5 | Issue + PR; SDD: ci-cd-foundation, tasks 2.1–2.6; CI: lint + test + build + deploy; target: main | N/A (infra) |
| 2.3 | Continuous deployment to Coolify and InsForge (CD-02 step) | `insforge_create-deployment` step exists; uses operator-configured env; no service-role key in the step body | Merge to main; verify InsForge dashboard shows the deployment record | 2.1, 2.5 | Issue + PR; SDD: ci-cd-foundation, tasks 2.1–2.6; CI: lint + test + build + deploy; target: main | N/A (infra) |
| 2.4 | Continuous deployment to Coolify and InsForge (secret hygiene) | Secret-leak grep present in deploy job; uses the same command as 1.3 | Visually inspect job output for the grep step | 2.1, 1.3 | Issue + PR; SDD: ci-cd-foundation, tasks 2.1–2.6; CI: lint + test + build + deploy; target: main | N/A (infra) |
| 2.5 | Continuous deployment to Coolify and InsForge (operator secret checklist) | PR body includes the secret checklist; operator acknowledges in PR comment before merge | Reviewer confirms checklist; operator replies with `secrets configured` before merge | 2.1 | Issue + PR; SDD: ci-cd-foundation, tasks 2.1–2.6; CI: lint + test + build + deploy; target: main | N/A (infra) |
| 2.6 | Continuous deployment to Coolify and InsForge (end-to-end dry-run) | First merge to main exits the `deploy` job with zero; OR run is acknowledged as expected-red with operator comment | Merge a no-op commit; observe run | 2.1, 2.2, 2.3, 2.5 | Issue + PR; SDD: ci-cd-foundation, tasks 2.1–2.6; CI: lint + test + build + deploy; target: main | N/A (infra) |

## Phase 3: Forward-planning validation (no implementation)

These tasks validate that the spec, design, and this `tasks.md` correctly capture the deferred CD-03 and ENV-01 work, but they do NOT implement it. The implementation of CD-03 and ENV-01 lives in a future change triggered by "Virginia MVC/MVP adoption".

- [ ] 3.1 Validate that `specs/ci-cd-pipeline/spec.md` contains the "Staging branch and UAT channel (deferred — implementation pending Virginia MVC/MVP adoption)" requirement with three scenarios.
- [ ] 3.2 Validate that `specs/ci-cd-pipeline/spec.md` contains the "Staging and production Coolify environments (deferred — implementation pending CD-03)" requirement with three scenarios.
- [ ] 3.3 Validate that `design.md § Future work` lists CD-03, ENV-01, CD-04, UAT-01..03, E2E-01..06, E2E-M1..M4, WORKER-01..04 as out-of-scope, and that none of those ticket IDs appears as a checked Phase 0–2 task.

## DEFERRED — CD-03 implementation (trigger: Virginia MVC/MVP adoption)

The following tasks are NOT in scope for this change. They are tracked here as the contract for the future SDD change that will implement CD-03. Do NOT check these boxes in the current change; copy them into a new `openspec/changes/staging-transition/` change when the trigger fires.

- [ ] D1.1 Create `staging` branch in the repository with branch protection requiring the CI workflow to pass.
- [ ] D1.2 Update the `deploy` job in `.github/workflows/ci.yml` to gate production merge on `uat_releases.production_gate_status = passed` (or explicit override with reviewer identity).
- [ ] D1.3 Update `docs/development.md` to describe the new flow: PR to staging → UAT → merge to main; include the technical/internal-skip clause.
- [ ] D1.4 Update `docs/architecture-insforge-stack.md § Branch and deployment policy` to mark the transition as complete and reflect the post-staging state.

## DEFERRED — ENV-01 implementation (trigger: CD-03 complete)

The following tasks are NOT in scope for this change. They are tracked here as the contract for the future SDD change that will implement ENV-01. Do NOT check these boxes in the current change.

- [ ] D2.1 Provision `apap-staging` Coolify application on the project VPS; configure to deploy from the `staging` branch.
- [ ] D2.2 Provision `apap-production` Coolify application on the project VPS; configure to deploy from the `main` branch.
- [ ] D2.3 Configure separate environment variable sets per environment via the Coolify dashboard.
- [ ] D2.4 Configure domain or subdomain routing for both environments.
- [ ] D2.5 Add a health check step to the `deploy` job; the job reports success only when the health check endpoint returns 2xx.
- [ ] D2.6 Update the `deploy` job to deploy to `apap-staging` on push to `staging` and to `apap-production` on push to `main`.

## Implementation order and PR chain

PR 1 (CI-01) lands first; PR 2 (CI-02) requires PR 1; PR 3 (CD-01 + CD-02) requires PR 2. Each PR targets `main` (stacked-to-main). The chain is a true stack: PR 1's branch is `feat/ci-01-local-tests`, PR 2's branch is `feat/ci-02-github-actions` rebased on `main` after PR 1 merges, PR 3's branch is `feat/cd-01-coolify-insforge` rebased on `main` after PR 2 merges. The three PRs are independent slices: each merges cleanly on its own and the deploy job in PR 3 is the only one that touches production state.
