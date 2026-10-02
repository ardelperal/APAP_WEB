# 1082 — release-e2e-gate bound to a revision (post-deploy validation)

Branch: `chore/1082-release-e2e-gate-per-sha` (worktree `apap-app-worktrees/1082-release-e2e-gate`)
Issue: #1082 (refs #1065, #908, #909). Decision by operator: option (a), validation AFTER deploy.

## Objective
Stop blocking every deploy on the global variable `APAP_E2E_GATE_EVIDENCE` and replace it with per-revision evidence recorded after the deploy.

## Problem
`release-e2e-gate` (deploy.yml) fails closed when the repo variable is empty (it does not exist) so every push to main since 2026-09-27 ends with `deploy=skipped`. Once filled it would approve every later release. The contract is circular: the runbook validates production after deploy, the gate demands the evidence before.

## Design (option a)
- `deploy` no longer `needs: release-e2e-gate`; the variable-based job is removed.
- New post-deploy job `release-e2e-record` (needs deploy, success only): sets commit status `release/e2e-production` = `pending` on the deployed SHA ("awaiting runbook validation"). No e2e suite runs in deploy.yml (issue non-goal), no secret held, `statuses: write` only on this job.
- The runbook records the outcome on that same SHA: `success` (run URL), `failure` (=> rollback via the existing digest rollback path), or bypass `success` with description `skipped:<reason>`. A bypass therefore applies to one SHA only and records reason + SHA.
- Evaluation logic lives in `scripts/check_release_evidence.py` (pure function over a statuses payload): evidence for the right SHA, for another SHA, absent, pending, failure, bypass. Fail closed with a message naming the missing SHA. Reusable by a later audit job.

## Scope / surfaces
deploy.yml, new script + its test, runbook, ci-cd.md, hardening-roadmap.md, tests/test_deploy_workflow.py, tests/test_ci_workflow.py. Out: `ui-e2e-gate`, `evidence`, `/e2e/login` (#1073), running e2e inside deploy.yml.

## Constraints
- English in code/comments/commit; Spanish (usted) in docs already written in Spanish.
- ~400 authored changed lines heuristic; issue estimates 150-300.
- Actions pinned by SHA; least-privilege permissions per job.
- Conventional commits, no AI attribution lines beyond repo policy; no push, no PR.

## Tasks
- [x] T1 RED: tests for `check_release_evidence` (correct SHA, other SHA, absent, pending, failure, bypass).
- [x] T2 GREEN: `scripts/check_release_evidence.py`.
- [x] T3 deploy.yml: drop `release-e2e-gate`, add `release-e2e-record`, update `needs`.
- [x] T4 Update workflow tests (`test_deploy_workflow.py`, `test_ci_workflow.py`).
- [x] T5 Runbook + ci-cd.md + hardening-roadmap.md describe order and how to record/bypass per SHA.
- [~] T6 (partial: actionlint unavailable; check_required_jobs needs CI env) Checks green: pytest -k "workflow or release", actionlint, check_workflows/check_required_jobs, ruff.

## Acceptance criteria (from #1082)
- Evidence for one release never approves another revision.
- Bypass applies to one revision and records reason + SHA.
- Missing evidence for the SHA fails with a message naming the SHA; valid evidence lets deploy run.
- Runbook describes the decided order and how to record evidence.

## Routing
Route: delegated (done); delegated writer (2+ non-trivial files; triggers: write rule, preparation rule). Delivery strategy: `ask-on-risk`, single PR.

## Progress / evidence
Commit 1984856 `ci(deploy): bind release e2e evidence to the deployed revision` (8 files, +494/-136, over the 400 heuristic: ~150 lines are tests, ~100 docs).
- RED: test_check_release_evidence import error (module absent); 6 failures in test_deploy_workflow/test_ci_workflow.
- GREEN: pytest (3 files) 145 passed; `-k "workflow or release"` 204 passed; ruff check/format OK; mypy on the script OK; scripts/check_workflows.py OK.
- Not run: actionlint (not installed); scripts/check_required_jobs.py (needs CI_NEEDS_JSON from CI, unrelated).
- Deviation: the record job uses curl+jq, not `gh`, because check_workflows.py rejects `gh` on this runner (issue #533).

Native review (lineage review-63304ddbaabf768c, high risk, 4 lenses, consent granted by the user): 2 CRITICAL candidate-caused findings (R3-1, R4-e2e-gate-removed-no-post-deploy-block): removing `release-e2e-gate` left no enforcement, `release-e2e-record` only wrote `pending`.
- Correction commit 80fa54e `fix(deploy): gate deploys on the previous revision's e2e verdict` (+139/-17 = 156 lines, budget 180/200). Re-added `release-e2e-gate` (no variable): evaluates the previous deployed SHA's `release/e2e-production` status via `scripts/check_release_evidence.py`; `deploy` needs it again. RED (5 failures) then GREEN: pytest 3 files 148 passed, `-k "workflow or release"` 207 passed, check_workflows OK.
- Targeted validation: first attempt hit a provider 529 Overloaded (transient), same slot re-offered, retry approved. Acknowledged; authority burned.
- Non-blocking follow-ups left open (advisory): record job has no curl retry and can clobber an existing verdict, vacuous action-pin test, runbook step numbered 6 vs 7, missing `git fetch` before `git rev-parse origin/main`, same-second status tie-break, error body not printed.
- Bootstrap: the first deploy after merge is blocked until an operator records `success` or `skipped:<reason>` on the last deployed SHA `460c56f1...` (documented in the runbook).
- Route decision recorded: correction delegated to the same writer (resumed).
Mirror: Engram `odd/1082-release-e2e-gate-per-sha/tasks` (pending resync).

## Next step
Push and open the PR (human decision). Do the bootstrap status on 460c56f1 at merge time.

## Outcome (2026-09-29)
Merged as PR #1110; issue #1082 closed. Follow-up commit f2209a6 fixed the UTF-8 output pin required by tests/test_gate_output_encoding.py (the writer had only run a subset of the suite; the full suite caught it in CI). Its native review reached `approved` but was never acknowledged (worktree removed after merge).
- Bootstrap done by the parent: status `release/e2e-production`=success with description `skipped:bootstrap - deployed before the release e2e gate existed (#1082)` recorded on 460c56f1; evaluator accepted it. The gate had failed the deploy run 36603242189 for 2d5024a exactly with "no release/e2e-production status recorded for 460c56f1".
- Failed deploy run 36603242189 re-run (failed jobs) as the live test of the gate; result pending at time of writing.
Engram mirror: pending.
