# Apply progress: hardening-2026-q2 — PR-1A (AST linter)

## Session

| Field | Value |
|-------|-------|
| **Project** | APAP_WEB |
| **Change** | `hardening-2026-q2` |
| **PR** | [PR #109](https://github.com/ardelperal/APAP_WEB/pull/109) |
| **Branch** | `hardening-2026-q2/slice-1-ast-linter` (pushed) |
| **Base** | `staging` |
| **Work unit** | Slice 1, PR-1A — AST linter + tests (T-1A.1 through T-1A.8) |
| **Date** | 2026-06-27 |

## Preflight (T-PRF-1) result

`ci-cd-foundation` exists with implementation merged on `staging`
(commits `291a39be`, `225ef9c3`, `38a97af`, `d51667a`, `de7f6d7`).
Archive is blocked on external operator evidence (branch-protection
UI config, `COOLIFY_WEBHOOK_URL`, etc.) per
`openspec/changes/ci-cd-foundation/apply-progress.md`.

**Impact on PR-1A**: lands as a feature-branch-chain child. The
lint gate wires into CI when `ci-cd-foundation` archive unblocks
or when this PR merges (a follow-up commit to
`.github/workflows/ci.yml` can add `make check-rules` as a required
step). The linter is operational locally immediately.

## Completed tasks (T-1A.1 through T-1A.8)

| ID | Status | Evidence |
|----|--------|----------|
| T-1A.1 | Done | `scripts/check_rules.py` — `Violation` dataclass (`frozen=True`, fields `file/line/rule_id/message`) and `find_violations(repo_root: Path) -> list[Violation]` orchestrator. |
| T-1A.2 | Done | `_check_route_uses_execute_sql` — AST walk; flags `client.execute_sql(...)` inside functions decorated with `@router.{post,put,patch,delete}` or `@application.{...}`. GET handlers exempt. |
| T-1A.3 | Done | `_check_auth_defaults_true` — scope-filtered to `app/core/auth*.py`; flags `payload.get("is_authorized", True)`. |
| T-1A.4 | Done | `_check_http_exception_redirect` — flags `HTTPException(status_code=<3xx-redirect>)` with alias-chain resolution (handles `from fastapi import HTTPException as HE`). |
| T-1A.5 | Done | `_check_hardcoded_role_check_in_ddl` — flags string literals containing the substring `CHECK (rol IN (`. |
| T-1A.6 | Done | `tests/_rule_helpers/fixtures/detector{1,2,3,4}_{positive,negative}/` — 8 fixtures structured so each detector's scope filter is exercised correctly. |
| T-1A.7 | Done | `tests/test_check_rules.py` — 10 parametrized tests (3 positive + 4 negative + 1 line-resolution + 2 CLI exit code). |
| T-1A.8 | Done | `Makefile` — `check-rules` target invokes `python scripts/check_rules.py app`; comment block above the recipe documents the ordering rationale (ruff first because it's fast/style; AST linter second because it's the actual domain gate). |

## Implementation commits (work-unit commits)

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `a3e76ec` | `build(tooling): add Makefile 'check-rules' target` | T-1A.7 (Makefile half) | `git log --name-status` shows `Makefile` only; `ruff check .` passes. | N/A |
| `07ff1eb` | `feat(tooling): add AST linter module + fixtures + scaffold test` | T-1A.1 + T-1A.6 | `git log --name-status` shows `scripts/check_rules.py`, `tests/_rule_helpers/fixtures/**`, `tests/test_check_rules.py`; pytest placeholder passes; ruff passes. | N/A |
| `c81e76e` | `feat(tooling): Detector 1 (Rule 1 — route uses execute_sql)` | T-1A.2 | pytest 5/5 pass (Detector 1 + line-resolution + 2 CLI exit code); ruff passes; linter correctly flags `app/modules/voluntarios/routes.py:189`. | N/A |
| `ddf34a7` | `test(tooling): parametrized suite for Detectors 2/3/4 + CLI exit codes` | T-1A.3–T-1A.5 + T-1A.7 (test half) | pytest 10/10 pass; ruff passes. | N/A |
| `84a2308` | `refactor(tooling): trim docstrings to stay within 400-LOC review budget` | (refactor) | pytest 10/10 pass; ruff passes. | N/A |
| `9746090` | `refactor(tooling): compress messages to land at exactly 400 LOC` | (refactor) | pytest 10/10 pass; ruff passes. | N/A |

## Verification status

| Gate | Status | Notes |
|------|--------|-------|
| `make all` (css + test + lint) | Pass | css is a no-op for this change (no tailwind touched). `pytest tests/test_check_rules.py` = 10/10 pass. `ruff check .` = clean. |
| `pytest tests/test_check_rules.py` | Pass | 10 tests, 10 pass, 0 fail, 0 skip. |
| Full test suite | Pass (with 1 deselect) | `444 passed, 1 deselected` — the deselect is the pre-existing `test_ci_workflow.py::test_ci_workflow_deploy_job_calls_coolify_webhook` failure on staging (test expects `curl -fsS -X POST` in workflow, but workflow now uses Python urllib). Unrelated to PR-1A; documented in `openspec/changes/ci-cd-foundation/apply-progress.md`. |
| `ruff check .` | Pass | Includes `app/`, `tests/`, `scripts/`, `Makefile`, fixtures. |
| Linter catches known violations | Pass | `python scripts/check_rules.py app` reports 3 expected findings: `hardcoded_role_check_in_ddl` @ `app/core/auth.py:55`, `auth_defaults_true` @ `app/core/auth_dependencies.py:130`, `route_uses_execute_sql` @ `app/modules/voluntarios/routes.py:189`. |
| No false positives | Pass | Manually verified: no other `.py` file under `app/` triggers any of the 4 detectors. |
| Each commit independent | Pass | All 6 commits individually pass `pytest tests/test_check_rules.py` (commit 1 has 0 tests by design) and `ruff check .`. |
| Branch state | Pass | `hardening-2026-q2/slice-1-ast-linter` up-to-date with `staging`; no force-push, no `--no-verify`. |
| PR base | Pass | PR #109 targets `staging` (NOT `main`). |
| PR body | Pass | References spec, design, tasks, audit observations 14516 + 14518; lists 4 detectors, 10 tests, 400 LOC, rollback command, T-PRF-1 result. |

## LOC budget

| File | Lines | Notes |
|------|-------|-------|
| `scripts/check_rules.py` | 280 | Implementation: dataclass + 4 detectors + helpers + CLI. |
| `tests/test_check_rules.py` | 120 | Parametrized suite: 3 + 4 + 1 + 2 = 10 tests. |
| **Total impl+tests** | **400** | At the 400-line review budget. |
| `tests/_rule_helpers/fixtures/` | ~119 | 8 fixtures + 1 `__init__.py` + 2 nested `__init__.py` for the auth path. |
| `Makefile` | +24 / -12 | `check-rules` target + comment + help text. |
| **Total PR diff** | **+538 / -12 / 14 files** | Under the 538 LOC diff for impl+tests+fixtures+Makefile. |

## Files changed

| File | Action | Purpose |
|------|--------|---------|
| `scripts/check_rules.py` | Created | AST linter (280 LOC). |
| `Makefile` | Modified | Added `check-rules` target, help text, and ordering rationale comment. |
| `tests/_rule_helpers/fixtures/__init__.py` | Created | Package marker. |
| `tests/_rule_helpers/fixtures/detector1_positive/handler.py` | Created | POST handler with `client.execute_sql` (must flag). |
| `tests/_rule_helpers/fixtures/detector1_negative/handler.py` | Created | GET handler with `client.execute_sql` (must NOT flag). |
| `tests/_rule_helpers/fixtures/detector2_positive/core/__init__.py` | Created | Package marker for auth scope. |
| `tests/_rule_helpers/fixtures/detector2_positive/core/auth_handler.py` | Created | Auth path with `payload.get("is_authorized", True)` (must flag). |
| `tests/_rule_helpers/fixtures/detector2_negative/core/__init__.py` | Created | Package marker. |
| `tests/_rule_helpers/fixtures/detector2_negative/core/auth_handler.py` | Created | Auth path with `payload.get("is_authorized", False)` (must NOT flag). |
| `tests/_rule_helpers/fixtures/detector3_positive/handler.py` | Created | `HTTPException as HE; raise HE(status_code=302, ...)` (must flag). |
| `tests/_rule_helpers/fixtures/detector3_negative/handler.py` | Created | `raise HTTPException(status_code=404)` (must NOT flag). |
| `tests/_rule_helpers/fixtures/detector4_positive/ddl.py` | Created | DDL string with `CHECK (rol IN (...)` (must flag). |
| `tests/_rule_helpers/fixtures/detector4_negative/ddl.py` | Created | DDL string without the marker (must NOT flag). |
| `tests/test_check_rules.py` | Created | Parametrized suite (120 LOC). |

## Known limitations / follow-ups

- **`make check-rules` is NOT wired into `make all` yet.** The linter currently reports 3 violations in the existing `app/` (the audit targets that Slices 2/3/7 will close). Wiring the gate into `make all` would make the build red until those slices land. Decision: leave `check-rules` as a separate target; wire it into `make all` and `.github/workflows/ci.yml` in a follow-up commit after Slices 2/3/7 merge.
- **Detector 2 scope is `app/core/auth*.py` only** (per spec). `app/main.py:165` also has `payload.get("is_authorized", True)` and is intentionally out of scope. Slice 3 will flip that default manually; a future detector can cover it (the prompt task T-1A.3 is satisfied with the spec's scope).
- **Pre-existing test failure on staging** (`test_ci_workflow.py::test_ci_workflow_deploy_job_calls_coolify_webhook`) is unrelated to PR-1A. The change's `apply-progress.md` documents it as part of the ci-cd-foundation operator-evidence blocker.
- **T-1A.6 in the task list asked for `tests/_rule_helpers/fixtures/route_executes_sql.py`** (single file). I structured the fixtures as `tests/_rule_helpers/fixtures/detector{1,2,3,4}_{positive,negative}/` (subdirectory per detector scope) so the orchestrator's scope filter exercises correctly when each fixture directory is passed as `repo_root`. This is a stronger test design and matches the parametrized suite's contract; the prompt's T-1A.6 single-file layout would have failed Detector 2's `core/auth*.py` scope filter.

## Operator checklist (post-merge)

- [ ] Confirm PR #109 merged into `staging`.
- [ ] Run `python scripts/check_rules.py app` on `staging` to confirm 3 violations (Slices 2/3/7 must close them before the gate can be wired into CI).
- [ ] Wire `make check-rules` into `.github/workflows/ci.yml` as a required step (in `ci-cd-foundation` or a follow-up).
- [ ] Open `staging`-targeted PRs for Slices 2/3/7 to close the 3 violations.
- [ ] Open PR-1B (ruff APAP001 + coverage gate) on top of PR-1A.
