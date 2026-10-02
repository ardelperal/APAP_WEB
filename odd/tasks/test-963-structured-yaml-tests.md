# test-963-structured-yaml-tests

Issue: #963 — migrate workflow tests from text-based YAML assertions to
structured access (pyyaml pinned in dev extra). Refs #935, #957.
Estimated 300-600 lines; may need 2 chained PRs (issue guidance).

## Tasks

1. [x] Worktree `apap-app-worktrees/963-pyyaml-structured` + branch
       `test/963-structured-yaml-tests` off origin/main @ f2b6140.
2. [ ] Worker (background): pyyaml pinned in dev + helpers migrated to
       structured access (`on`, `jobs.<id>.steps`, `needs`, `permissions`,
       `concurrency`), handling PyYAML's `on:` → `True` quirk; regression
       test with a sample workflow (innocuous comment/indent changes must
       not break tests).
3. [ ] Verification: same behavioral assertion count, full unit scope green.
4. [ ] Work-unit commit(s), push, PR with `Closes #963` (no merge). If over
       400 lines: split into chained PRs per the issue's guidance.

## Constraints

- No workflow behavior changes. `run:` assertions may stay textual but must
  target the specific step's `run` field.
- Do not rewrite scripts/check_workflows.py unless it shares the helper.

## Evidence log

- Attempt 1 (mul11xc3-f-x1g9) FAILED: orchestrator error — delegated to a worktree path that was never created. Lesson: verify the worktree exists right before delegating (checklist: fetch → worktree add → ls → delegate).
- Attempt 2 (mul1fpwp-g-v6pl) COMPLETED: full migration, no deferred groups. Helper tests/_workflow_yaml.py (163 lines), test_ci_workflow.py +566/-617, pyyaml==6.0.3 pinned in dev (premise stale: already in dev unpinned since #526), uv.lock 1 line. Gates: focused 152→153 passed, full scope 4949/0, ruff/mypy/rules OK, uv frozen dry-run OK. Honest size: 1363 lines.
- 2 deviations documented: python-version-file assert (old substring satisfied only by a comment = false-green, now asserts shared setup action) and job-scoped structure-derived text for negative scans.
- Chaining: worker recommends single PR + size:exception (helper swap atomic; -617 deletions dominate). Alternative split documented. Verify in background: mul3811c-h-f5th — pending.

## Closed — 2026-09-28

- Verify agent timed out (30 min stall on bash); decisive gates re-executed inline by the orchestrator: focused 153 passed, full unit scope 4949/0, ruff/mypy/rules green, helper edge checks on real ci.yml+deploy.yml, python-version-file false-green confirmed (ci.yml:745 comment).
- Commits: 7039c37 (helper + pin), 98ec391 (migration). PR #1059 with size:exception (~1363 lines, single PR per atomicity rationale; alternative split documented for the maintainer).
- Worker note persisted: pyyaml was already an unpinned dev dep since #526 — issue premise stale.
