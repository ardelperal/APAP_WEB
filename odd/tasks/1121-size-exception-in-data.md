# 1121 — size-exception declared in data (PR body), gate parses `size-exception-reason:`

Branch: `chore/1121-size-exception-in-data` (worktree `apap-app-worktrees/1121-size-exception-in-data`). Base was cec3133; origin/main is now ahead and must be merged in.
Issue: #1121 (refs #935 design rule, #941, #896, #926). Single PR, `Closes #1121`; also make #941 and #896 moot (Refs, not Closes, decide in the PR body).

## Situation
The worktree held UNCOMMITTED work from another lane (abandoned 17:12, no live process, no commit, no PR): parser in scripts/check_pr_size.py, body fetch in .github/workflows/pr-size.yml, tests/test_pr_size.py (+122), pins in tests/test_ci_workflow.py, docs. It is adopted, reviewed and corrected here. `.atl/skill-registry.md` is unrelated generated noise: never commit it.

## Defects found in the adopted work (to fix)
1. GITHUB_OUTPUT injection: the PR body (author controlled) is written to `$GITHUB_OUTPUT` with the fixed delimiter `EOF`; a body line `EOF` followed by `key=value` injects step outputs. Fetch the body and enforce in ONE step and hand the body to the script through an env var or a file, never through GITHUB_OUTPUT.
2. Field format: the repo template and existing PR bodies write the field as `` `size-exception-reason:` <text> `` (name wrapped in backticks, text on the same line). The parser only accepts a line that starts with the plain prefix. Accept the documented template shape and the plain shape, keep single-line, non-empty, exactly one occurrence, and keep the "no wrap onto the next line" rule.
3. Body edits: check how editing the PR body re-triggers the required check `pr-size / pr-size` (called from ci.yml). Do NOT add `edited` to ci.yml (it would re-run the whole CI). If a body edit does not re-run it, document that re-running the failed job re-reads the live body.

## Tasks
- [x] T1 commit the adopted work (without .atl/skill-registry.md) and merge origin/main, resolving conflicts (main changed tests/test_ci_workflow.py, CONTRIBUTING.md, PR template and ci-gate-inventory since cec3133).
- [x] T2 RED/GREEN fixes for defects 1 and 2 with tests (parser table incl. backticked template shape, EOF-injection body, empty, duplicate, wrapped; workflow pin: no GITHUB_OUTPUT for the body, same-step enforcement, fail closed on non-200).
- [x] T3 docs (CONTRIBUTING, PR template, gate inventory) consistent with the delivered behaviour, including defect 3.
- [x] T4 full checks: full pytest suite, every lint step of ci.yml locally, ruff, check_workflows.
- [x] T5 one commit for the fixes on top of the adopted-work commit; parent does review/push/PR.

## Evidence
- Commits: fbc48ce adoption (`feat(ci): parse size-exception-reason...`), e206f55 merge of origin/main (clean, no conflicts), 2ce2a35 fixes. Registry noise never staged.
- RED: 5 new tests failed before the fix (template shape x2, template-shaped main run, GITHUB_OUTPUT pin, single-step pin); GREEN after: tests/test_pr_size.py + tests/test_ci_workflow.py 158 passed.
- Extra defect found: the adopted `cast()` in `_pin_output_encoding` broke tests/test_gate_output_encoding.py; restored the plain reconfigure form.
- Defect 3: ci.yml pull_request has default types (no `edited`), so a body edit does not re-run; docs say to re-run the failed ci job (`gh run rerun <id> --failed`), which re-reads the live body. `edited` not added (pinned by a test).
- Real-world check exit codes: template shape 0, plain 0, empty 1, duplicate 1, EOF-injection body with reason 0, 300 lines no reason 0, 900 no reason 1.
- Full suite: 5181 passed, 19 skipped. mypy, ruff check ., every ci.yml lint step: OK.
- Diff vs origin/main: 389 additions, 115 deletions (504 total, over the 400 heuristic; adopted work was ~395 alone, and the fixes' tests/docs add the rest).

## Route
Delegated writer. Engram mirror: pending.

## Outcome (2026-09-30)
Merged as PR #1141 (merge commit ccbeb2b8), issue #1121 closed; #941 and #896 closed as moot. The work adopted from an abandoned lane was corrected before merging (GITHUB_OUTPUT injection, template-shaped field, placeholder rejection). Real proof: a 504-line PR passed `pr-size / pr-size` with no label. Two frictions surfaced on the way: issue #1121 used `##` headings and lacked the acceptance section so `issue-spec` rejected the PR with a misleading "missing or empty section" message, and `strict` invalidated the green state after another agent merged (fixed by merging main and re-waiting). Native review approved without corrections.
