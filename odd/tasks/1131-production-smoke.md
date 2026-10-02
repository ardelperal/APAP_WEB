# 1131 — slice 2: production smoke job, gate wiring, docs

Branch: `chore/1131-production-smoke` (worktree `apap-app-worktrees/1131-production-smoke`), off origin/main 25998c1 (slice 1 = PR #1132 merged).
Issue: #1131 (refs #935, #909, #1073, #1082). This is the FINAL slice: the PR closes #1131 (`Closes #1131`, no `chain:partial`).

## Objective
Replace the manual attestation with automatic evidence: after a deploy the workflow itself proves the unauthenticated smoke and records it; the authenticated battery is demanded only for sensitive ranges.

## Design (decided)
1. `scripts/production_smoke.py` (+ tests): no secrets, no auth, stdlib HTTP only. Checks `/healthz` reports the deployed SHA (reuse scripts/verify_deployment.py helpers if clean), public routes answer (e.g. `/login` 200), a protected route redirects to `/login` without a 5xx. Exit 0 ok, 1 failed check, 2 usage. Bounded retries for the revision check (deploy finishes just before). Pin output encoding (`_pin_output_encoding` helper called from `main`).
2. deploy.yml:
   - `release-e2e-gate` (pre-deploy): finds the previous deployed SHA (already does), exposes it as a job output, and now requires BOTH statuses of that revision: `release/smoke-production` (`check_release_evidence.py --context release/smoke-production`) and `release/e2e-production` (default context). Fail closed.
   - `production-smoke` (new, needs `deploy`, runs only when deploy succeeded): hosted runner, no secrets, `permissions: contents: read, statuses: write`, runs the smoke script against the base URL derived from the existing repo variable `APAP_DEPLOY_HEALTH_URL`, then ALWAYS posts `release/smoke-production` on `$GITHUB_SHA` (success or failure, target_url = the run URL, curl+jq, no `gh`), and fails the job if the smoke failed.
   - `release-e2e-record` (existing, needs the gate for `previous_sha` and `deploy`): decides with `scripts/check_release_e2e_required.py --base <previous_sha> --head $GITHUB_SHA` (needs full history: fetch-depth 0). Exit 10 (required) => post `release/e2e-production=pending` ("awaiting runbook validation: e2e-sensitive paths changed"); exit 0 => post `release/e2e-production=success` with description `not-required: no e2e-sensitive path changed since <prev8>`; any other exit => fail the job. First deploy (no previous SHA) => required.
3. Follow-ups from the slice-1 review: closed allow-list for `--context` in check_release_evidence.py (only the two contexts) with a test; a `git mv` rename test in tests/test_check_release_e2e_required.py asserting both old and new paths are reported.
4. Docs (Spanish, formal usted): runbook (who writes each status, what each covers, limits of the smoke, one-time bootstrap: run the smoke against production and record the real result on the last deployed SHA), ci-cd.md (job inventory names in backticks), hardening-roadmap row.

## Scope / surfaces
.github/workflows/deploy.yml, scripts/production_smoke.py (new), tests/test_production_smoke.py (new), scripts/check_release_evidence.py, tests/test_check_release_evidence.py, tests/test_check_release_e2e_required.py, tests/test_deploy_workflow.py, tests/test_ci_workflow.py, docs/runbooks/e2e-production.md, docs/codebase/ci-cd.md, docs/quality/hardening-roadmap.md, this doc.
Out: authenticated e2e in CI (#909), #1073, rollback automation, pre-existing statuses.

## Constraints
English code/comments/commits; TDD RED then GREEN; FULL test suite before finishing (lesson from #1082: a subset missed a convention test); actions pinned by SHA; least-privilege permissions per job; no `gh` in workflows (check_workflows.py rejects it); ~400 line heuristic, may exceed with reason.

## Tasks
- [x] T1 smoke script + tests.
- [x] T2 `--context` allow-list + tests; rename test for the selector.
- [x] T3 deploy.yml: gate (two statuses, previous_sha output), production-smoke, release-e2e-record decision.
- [x] T4 workflow tests (structured YAML pins).
- [x] T5 docs.
- [x] T6 full checks and one work-unit commit (native review, push and PR remain with the parent).

## Route
Delegated writer (2+ non-trivial files). Delivery: final slice, `Closes #1131`.

## Progress / evidence
Work-unit commit 4c45f84 `feat(ci): automate the production smoke and gate deploys on it` (~950 changed lines: 248 script, 244 smoke tests, ~150 workflow, ~150 workflow tests, docs; exceeds the ~400 heuristic because tests and Spanish docs dominate, not split to keep the gate wiring, its pins and docs in one reviewable unit).
- RED: 2 allow-list tests failed (no ALLOWED_CONTEXTS); 10 workflow pin tests failed against the old deploy.yml; smoke tests failed at import (module absent). The rename test passes immediately (locks in the existing --no-renames behaviour).
- GREEN: `uv run python -m pytest tests -q` = 5141 passed, 19 skipped (3m20s); ruff check and format --check clean on all touched python; scripts/check_workflows.py OK; test_ruff_ratchet and test_gate_output_encoding pass (PLR0913 solved with a Retry dataclass, PLR2004 with constants).
- Manual: smoke run against a local stub server: exit 0 on match, exit 1 on wrong revision.
- Not exercisable by tests: the first real run of the workflow shell logic (previous_sha output, selector exit mapping, statuses POST, job.status in the always() step). Engram mirror: pending.

## Next step
Parent: native review, push, PR body with `Closes #1131`; after merge, run the one-time bootstrap in the runbook (real smoke against production, record release/smoke-production on the last deployed SHA) BEFORE the next deploy or it will be blocked by release-e2e-gate.
