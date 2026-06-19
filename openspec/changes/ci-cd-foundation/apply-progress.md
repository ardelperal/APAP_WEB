# Apply progress: ci-cd-foundation — PR 1 + PR 2 slices

## Session

| Field | Value |
|-------|-------|
| **Project** | APAP-WEB |
| **Change** | `ci-cd-foundation` |
| **Scope** | PR 1 + PR 2 of 3 (`stacked-to-main`) — Phase 0 and Phase 1 artifact tasks in `tasks.md` |
| **Topic** | Local test surface + GitHub Actions CI workflow (CI-01, CI-02) |
| **PR** | Work-unit commit pending — orchestrator is the committer |
| **GitHub issue** | [#1](https://github.com/ardelperal/APAP_WEB/issues/1) — `feat(cd): deploy APAP through Coolify and InsForge` |
| **Coolify project** | `APAP` (`mjgxwv4srqlsuww4pfpyo0t7`) with `production` environment (`c7wgl2dmapown2x84f1gbgl9`) |
| **Coolify application** | `apap-web` (`uet2l2h4qequfpi145lnn2ni`) from `ardelperal/APAP_WEB:main`, domain `https://apap.romancaba.com`, deploy not started |
| **Branch policy** | GitHub default branch aligned to `main`; Coolify already points at `main` |
| **Mode** | Strict TDD active; pytest runner declared but not installed in the current shell |
| **Date** | 2026-06-14 |

## Completed tasks

| ID | Title | Status |
|----|-------|--------|
| 0.1 | Create `pyproject.toml` | [x] |
| 0.2 | Create `tests/test_smoke.py` | [x] |
| 0.3 | Create `Makefile` | [x] |
| 0.4 | Create `docs/development.md` | [x] |
| 0.5 | Update `.gitignore` for Python caches | [x] |
| 0.6 | Update `openspec/config.yaml` (strict TDD + tooling) | [x] |
| 1.1 | Create `.github/workflows/ci.yml` with `lint`, `test`, `build` jobs | [x] |
| 1.2 | Add disabled E2E placeholder and document the hook | [x] |
| 1.3 | Add diagnostic secret-leak grep to the lint job | [x] |
| 1.4 | Create `.github/branch-protection.md` operator guide | [x] |

Phase 0 and the file-backed Phase 1 tasks (1.1–1.4) are complete. The operator-only Phase 1 tasks (1.5–1.6) remain unchecked because they require GitHub UI/PR actions outside this local apply slice.

## Files changed

| File | Action | What was done |
|------|--------|---------------|
| `pyproject.toml` | Created | Project metadata, `requires-python = ">=3.11"`, hatchling build backend configured to build from `tests/` until the `apap_web` package lands, `[project.optional-dependencies.dev]` with `build`, `pytest`, `pytest-cov`, `ruff`, `[tool.pytest.ini_options]` with `filterwarnings = ["error::DeprecationWarning", "error::PendingDeprecationWarning"]` per `docs/architecture-insforge-stack.md § CI/CD Quality Gate`, `[tool.ruff]` with `E/F/W/I/UP/B` rule selection and `target-version = "py311"`, baseline `[tool.coverage.*]` config. Runtime dependencies intentionally empty (FastAPI/uvicorn/Jinja2/Pydantic/HTTPX/python-multipart land with the web-app-skeleton PR). |
| `tests/__init__.py` | Created | Empty file so pytest discovers `tests/` as a package and the hatchling wheel can include the directory. |
| `tests/test_smoke.py` | Created | Single passing assertion (`def test_smoke_passes(): assert 1 + 1 == 2`) so the future CI test job is never vacuous. No deprecated API calls, so the strict `filterwarnings` config does not flag the smoke test. |
| `Makefile` | Created | Targets `help`, `install`, `dev`, `test`, `lint`, `build`, `all`, `clean`. `all` runs `test` then `lint`. The canonical commands (`pytest`, `ruff check .`, `python -m build`) match the architecture doc § CI/CD Quality Gate and are the source of truth for the future CI workflow (PR 2) and deploy job (PR 3). |
| `docs/development.md` | Created | 7-step developer walkthrough: prerequisites, clone, venv + `pip install -e ".[dev]"`, MCP setup pointer, test command with expected output snippet, lint command, build command, pre-staging branch note ("while APAP-WEB is pre-MVC, PRs target `main`; staging transition is CD-03, deferred"). Cross-links to `docs/setup.md` and `docs/architecture-insforge-stack.md`. Sentence-case headers per the `docs/setup.md` style. |
| `.gitignore` | Modified (additive) | Appended `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `build/`, `*.egg-info/`, `.coverage` under a new "Python build and test artifacts" section. No existing entry removed. |
| `openspec/config.yaml` | Modified (additive) | `testing.has_test_runner: true`, `testing.strict_tdd: true`, `testing.test_framework: pytest`, `testing.test_layers: [unit, integration]`, `testing.linter: ruff`, `testing.coverage_tool: pytest-cov`, `rules.apply.test_command: "pytest"`, `rules.apply.build_command: "python -m build"`, `rules.verify.test_command: "pytest"`, `rules.verify.build_command: "python -m build"`, `rules.verify.coverage_threshold: 80`. All other fields preserved per the task contract. |
| `tests/test_ci_workflow.py` | Created | Static contract tests for the CI workflow, disabled E2E hook, diagnostic secret-leak scan, branch protection guide, and development-guide hook documentation. |
| `.github/workflows/ci.yml` | Created | GitHub Actions workflow named `ci` with ordered `lint`, `test`, `build` jobs on PRs to `main` and pushes to `main`; setup-python reads `pyproject.toml`; disabled E2E placeholder documents `TODO(E2E-01)`. |
| `.github/branch-protection.md` | Created | Operator-facing branch protection guide with required checks `ci / lint`, `ci / test`, and `ci / build`, GitHub settings path, reviewer-count instruction, and evidence requirements. |
| `docs/development.md` | Modified | Added the CI workflow summary table and the disabled E2E hook note. |
| `openspec/changes/ci-cd-foundation/tasks.md` | Modified | Marked tasks 1.1–1.4 complete; left 1.5–1.6 unchecked. |

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|--------|-----------|-----------|--------------|-------------|
| `(pending — orchestrator commit)` | `chore(ci-cd-foundation): add local test surface (CI-01)` | `tasks.md` 0.1, 0.2, 0.3, 0.4, 0.5, 0.6 | Local `pytest`, `ruff check .`, `python -m build` per the canonical commands in `docs/development.md` | N/A |
| `(pending — orchestrator commit)` | `ci(ci-cd-foundation): add GitHub Actions CI workflow (CI-02)` | `tasks.md` 1.1, 1.2, 1.3, 1.4 | `tests/test_ci_workflow.py` static checks executed directly with Python; pytest/ruff/build blocked by missing tools in current interpreter | N/A |

The orchestrator is the committer per the sdd-apply contract; this artifact does not create the commit. The expected commit body (per `docs/architecture-insforge-stack.md § Delivery Traceability Policy` and the work-unit-commits skill):

```text
chore(ci-cd-foundation): add local test surface (CI-01)

SDD: ci-cd-foundation
Tasks: 0.1, 0.2, 0.3, 0.4, 0.5, 0.6
Issues: <github-issue-number>
Tests: tests/test_smoke.py (pytest with DeprecationWarning-as-error per architecture doc)
Access: N/A (no Access binary touched; greenfield Python web infra)
```

## TDD cycle evidence

Strict TDD mode is active. For PR 2, contract tests were written before creating the CI workflow and branch-protection artifact. Execution through pytest is blocked in the current shell because the active interpreter does not have pytest installed, so the RED/GREEN execution gates are recorded as infrastructure-blocked rather than silently downgraded.

| Task | Test file | Layer | Safety net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_ci_workflow.py` | Unit/static contract | Blocked: `python -m pytest tests/test_smoke.py` → `No module named pytest` | Written first; workflow file absent at test creation | Pytest blocked; direct Python invocation passed after implementation | Multiple assertions cover triggers, jobs, Python version source, and commands | None needed |
| 1.2 | `tests/test_ci_workflow.py` | Unit/static contract | Same blocker as 1.1 | Written first; E2E placeholder absent at test creation | Pytest blocked; direct Python invocation passed after implementation | Assertions cover disabled job and TODO marker plus docs hook | None needed |
| 1.3 | `tests/test_ci_workflow.py` | Unit/static contract | Same blocker as 1.1 | Written first; grep step absent at test creation | Pytest blocked; direct Python invocation passed after implementation | Assertion covers diagnostic step name and exact grep command | None needed |
| 1.4 | `tests/test_ci_workflow.py` | Unit/static contract | Same blocker as 1.1 | Written first; branch protection doc absent at test creation | Pytest blocked; direct Python invocation passed after implementation | Assertions cover required checks and GitHub settings path | None needed |

## Access sync

**N/A — no Access binary touched (this is greenfield Python web infra, no Access/VBA involvement).**

## Verification

All six rows are expected to PASS once the Python build/test dependencies can be installed.

### Current verification run

| Command | Result | Notes |
|---------|--------|-------|
| `python -m pip install -e ".[dev]"` | Not run during repo recovery | The recovery task explicitly forbids installing dependencies or running external test/build tooling. |
| `python -m pytest` | Not run during repo recovery | Requires dependencies that were not installed in this recovery session. |
| `python -m ruff check .` | Not run during repo recovery | Requires dependencies that were not installed in this recovery session. |
| `python -m build` | Not run during repo recovery | Requires dependencies that were not installed in this recovery session. |
| `python -m pytest tests/test_smoke.py` | Failed (tool missing) | `No module named pytest` in `C:\Users\adm1\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`. |
| `python -m pytest tests/test_ci_workflow.py` | Failed (tool missing) | `No module named pytest`; tests were still written before implementation per strict TDD. |
| `python -c "import tests.test_ci_workflow as t; ..."` | Passed | Direct stdlib execution of the five static CI contract test functions printed `static ci workflow checks passed`. |
| `python -m ruff check .` | Failed (tool missing) | `No module named ruff`. |
| `python -m build` | Failed (tool missing) | `No module named build`. |

## Recovery note

These artifacts were migrated from `C:\00repos\codigo\APAP_ACTUAL` to `C:\00repos\codigo\APAP_WEB` on 2026-06-14 after the user clarified that APAP-WEB is the real web repository and APAP_ACTUAL is reference/preparation only. Repo-local clone-path references in migrated docs were updated from `APAP_ACTUAL` to `APAP_WEB`.

## Remaining tasks

PR 1 and the local file-backed PR 2 tasks are complete. Remaining tasks:

- **PR 2 (Phase 1, CI-02)** — operator enables branch protection on `main` (1.5) and opens/verifies a test PR (1.6).
- **PR 3 (Phase 2, CD-01 + CD-02)** — `deploy` job in the same workflow, Coolify webhook step, `insforge_create-deployment` step, operator secret checklist, first dry-run merge.
- **Coolify deployment readiness** — `apap-web` is provisioned but not deployed yet; current repo does not yet contain a runnable web application package/start command.
- **Deferred** (CD-03, CD-04, ENV-01, UAT-01..03, E2E-01..06, E2E-M1..M4, WORKER-01..04) — remain unchecked in `tasks.md` per their trigger conditions.

## Status

**10/31 total tasks complete. Phase 0 plus tasks 1.1–1.4 are complete. Verification is partially blocked until `pytest`, `ruff`, and `build` are installed in the active shell.**

## Next recommended

Complete operator-only tasks 1.5–1.6 after dependencies are installed and GitHub Actions can run the workflow on a test PR.
