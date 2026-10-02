# 1131 — slice 1: evidence evaluator generalisation + sensitive-path selection

Branch: `chore/1131-release-evidence-paths` (worktree `apap-app-worktrees/1131-release-evidence-paths`), off origin/main 2d5024a.
Issue: #1131 (refs #935, #909, #1073, #1082). Chain: this is slice 1 of 2 and the PR carries label `chain:partial` and NO closing keyword for #1131 (issue-spec, #956). Slice 2 (job, gate wiring, docs) is a separate branch with the same N.

## Objective
Pure, tested logic for the release gate redesign, with no workflow change yet:
1. Generalise `scripts/check_release_evidence.py` so the same fail-closed evaluator can check any commit-status context (default stays `release/e2e-production`; add `--context`), so slice 2 can require `release/smoke-production`.
2. Add a deterministic selector that says whether the authenticated e2e battery is required for a deployed range: it reads a versioned data file of sensitive path patterns and the changed files between two SHAs.

## Scope / surfaces
scripts/check_release_evidence.py, tests/test_check_release_evidence.py, scripts/check_release_e2e_required.py (new), tests/test_check_release_e2e_required.py (new), .github/release-e2e-paths.txt (new data file), odd/tasks/1131-release-evidence-paths.md.
Out: deploy.yml and any workflow, runbook/ci-cd docs (slice 2), the smoke job, #909 invariants, #1073.

## Constraints
- English code/comments/commits; ~400 authored changed lines heuristic; TDD RED then GREEN.
- Existing behaviour of check_release_evidence.py must not change for callers that pass no `--context` (deploy.yml already calls it).
- Must satisfy tests/test_gate_output_encoding.py (pin stdout/stderr through a `_pin_output_encoding` helper called from `main`), ruff, and the full test suite (not a subset).
- Data file: one glob per line, `#` comments, blank lines ignored; deterministic; a test loads the real file and checks every pattern matches at least one tracked path (so it cannot rot silently).

## Tasks
- [x] T1 RED/GREEN: `--context` in check_release_evidence.py with tests (other context ignored, custom context accepted, default unchanged, message names the context and SHA).
- [x] T2 RED/GREEN: check_release_e2e_required.py (patterns file, changed-file list from `git diff --name-only <base>..<head>` or stdin, exit 0 = not required, exit 10 = required, exit 2 = usage/error; fail closed: unreadable data file or git failure means required).
- [x] T3 data file `.github/release-e2e-paths.txt` derived from the real repo layout (auth, session, csrf, secrets/config, migrations, e2e mock route, coolify/deploy config), each pattern justified in a comment.
- [x] T4 full checks: full pytest suite, ruff check/format --check on new files, scripts/check_workflows.py, gate encoding test.
- [x] T5 work-unit commit dc091be; push/PR by the parent.

## Route
Delegated writer (2+ non-trivial files). Delivery: chained (slice 1 of 2), label `chain:partial`.

## Progress / evidence
Commit dc091be (5 files, +508/-15). RED: 4 new evidence tests failed (no --context), selector module import error. GREEN: both test files pass.
Full suite `uv run python -m pytest tests -q -x`: 5092 passed, 19 skipped. ruff check + format --check clean on the 4 py files; check_workflows OK; test_gate_output_encoding and test_ruff_ratchet pass (a first run failed the ratchet on TRY003 +4; fixed by assigning messages to a variable before raising).
Route: delegated writer. Engram mirror: pending (MCP session ambiguity; CLI `engram save --project apap`).

## Next step
Parent: push, open PR (chain:partial, `Refs #1131`, no closing keyword), then slice 2.

## Outcome (2026-09-29)
Slice 1 merged as PR #1132 (merge commit 25998c10), review approved and acknowledged after one correction (2264ae8: stdin read failure now fails closed with exit 10). Follow-ups left by the review, to fold into slice 2: closed allow-list for `--context`, a `git mv` rename test for the selector, shallow-clone behaviour when the selector is called with git diff.
