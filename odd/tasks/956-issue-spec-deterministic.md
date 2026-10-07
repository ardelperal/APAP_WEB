# 956 — issue-spec: deterministic traceability (branch + labels + closingIssuesReferences)

Branch: `fix/956-issue-spec-deterministic` (worktree `apap-app-worktrees/956-issue-spec-deterministic`), off origin/main 30f23cc.
Issue: #956 (refs #935, #952, #957, #926). The issue BODY still describes the superseded `Part of #N` proposal; the FINAL design is in the maintainer's third comment (2026-09-25, "Correction to the previous redesign"). The 2026-09-25 claim by the CI-wave agent had no branch, PR or worktree, so it was resumed on 2026-09-29.

## Objective
Make `issue-spec` deterministic and industry-standard so chained PRs are possible: a partial slice can link the parent issue without closing it.

## Final design (maintainer decision)
1. Link from the branch: #N comes from the head branch `<tipo>/<N>-<slug>` (already validated by `scripts/check_branch_name.py`). The gate checks via API that #N exists, is open, has `status:approved` and a complete spec. The gate never parses the PR body.
2. Closing stays GitHub-native (`Closes #N`): the gate reads the PR's structured `closingIssuesReferences` (GraphQL). `REFERENCE_RE` and all body parsing are deleted.
3. Chains via the existing label `chain:partial`: with the label, `closingIssuesReferences` containing #N is a failure (premature close, as #931/#913); without it, `closingIssuesReferences` must contain #N. Any other closed issue must also be approved.
4. No sub-issues, no custom close workflow, no keyword ban. Document in `CONTRIBUTING.md` and the PR template.

## Acceptance criteria
- Result depends only on branch, labels and API fields; editing prose GitHub does not treat as closing never changes it.
- `chain:partial` + closing reference to #N => clear failure; no `chain:partial` and no closing reference to #N => clear failure.
- Unit tests with stubbed API payloads (branch parsing, labels, closingIssuesReferences).
- `REFERENCE_RE` and body parsing removed.
- Real chain of two PRs: validated after merge (not part of this PR's local proof).

## Scope / surfaces
scripts/check_issue_specs.py, tests/test_check_issue_specs.py, .github/workflows/ci.yml (issue-spec job only), .github/PULL_REQUEST_TEMPLATE.md, CONTRIBUTING.md (chained PR section), docs/quality/ci-gate-inventory.md, tests/test_ci_workflow.py (only if it pins the issue-spec job). Out: other gates, deploy, label creation (label exists).

## Parallel-work notes
#933 (PR #962) edits ci.yml `on:` triggers and CONTRIBUTING.md line ~159 (CI bullet); #1110 edits deploy.yml and ci-cd.md. Keep edits to the `Enlace a issue` bullet of CONTRIBUTING.md and to the issue-spec job of ci.yml to avoid conflicts.

## Tasks
- [x] T1 RED: unit tests with stubbed payloads (branch parsing incl. exempt branches and automated actors, chain:partial vs closingIssuesReferences, missing reference, closed approved issue rule).
- [x] T2 GREEN: rewrite the PR validation in scripts/check_issue_specs.py (GraphQL closingIssuesReferences, labels from the API); delete REFERENCE_RE/body parsing.
- [x] T3 ci.yml issue-spec job wiring (token permissions, event data) and workflow tests.
- [x] T4 PR template + CONTRIBUTING.md + ci-gate-inventory.md.
- [x] T5 Checks: pytest -k "issue_spec or workflow", ruff, mypy on the script, scripts/check_workflows.py.
- [x] T6 Work-unit commit done (a21c383); push and PR pending (parent).

## Constraints
English code/comments/commits; Spanish (usted) docs as existing. ~400 line heuristic (issue estimates 100-200; deletions count). Conventional commits, no AI attribution. No push/PR by the writer.

## Route
Delegated writer (2+ non-trivial files; write and preparation triggers). Delivery: single PR, `Closes #956`.

## Progress / evidence
Route: delegated writer (write and preparation triggers). Commit: a21c383.
- RED: 18 failed / 10 passed on the new stubbed tests before implementation; GREEN: 28 passed.
- `uv run python -m pytest tests/test_check_issue_specs.py tests/test_ci_workflow.py -q`: 145 passed.
- `uv run python -m pytest tests -k "issue_spec or workflow or contributing or pr_template" -q`: 214 passed.
- `ruff check` clean; `mypy scripts/check_issue_specs.py` clean; `scripts/check_workflows.py` OK.
- `ruff format --check` on the two touched files fails, but it already failed on the base commit (pre-existing); not reformatted to keep the diff reviewable.
- Not done here: real two-PR chain (validated after merge). CONTRIBUTING.md line ~242 (`fuera de bloques de código`) is now stale but outside the allowed bullet; left for the parent.
- Engram mirror: pending.

## Next step
Parent: push, open PR (`Closes #956`), validate a real chain after merge.

## Outcome (2026-09-29)
Merged as PR #1111; issue #956 closed. Commits a21c383 (gate) and 29821e6 (docs) went through the native review only partially: 3 of 4 lenses completed and `review-readability` failed twice with a provider session-limit error, so the review lineage was never closed; the PR was merged by another actor meanwhile. Real two-PR chain check with `chain:partial` is still to be exercised. Engram mirror: pending.
