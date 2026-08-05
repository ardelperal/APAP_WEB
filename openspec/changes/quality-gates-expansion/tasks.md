# Tasks: quality-gates-expansion

## Goal

Add five deterministic quality gates (CRAP score, mutation testing via cosmic-ray, property-based testing via hypothesis, formal DRY detection via stdlib AST, mutation-sites count) plus two refinements (adapter exclusion from coverage floor, QA-through-UI crystallised in AGENTS.md §23) to APAP_WEB. Every new detector ships with a shrink-only baseline so the first CI run cannot break the build. Three chained PRs separate the work into reviewable units.

## Source traceability

- Proposal: `openspec/changes/quality-gates-expansion/proposal.md` (Engram #24074)
- Spec: `openspec/changes/quality-gates-expansion/spec.md` (Engram #24075)
- Design v2: `openspec/changes/quality-gates-expansion/design.md` (Engram #24076)
- Gatekeeper record: same design file, post-BLOCKER-fix (CRAP step moved to `test` job)
- Reviewer WARNINGS encoded as tasks: W-1 (check_jscpd.py docstring), W-2 (pre-push comment rename), W-3 (pytest-randomly dep), W-4 (resolved by BLOCKER fix), W-5 (cosmic-ray determinism via PYTHONHASHSEED + --worker-count=1)

## PR map

| PR | Branch | Deliverable | Lines (approx) | Review lenses |
|----|--------|-------------|----------------|---------------|
| #1 | `feat/quality-gates-foundations` | check_crap.py + check_jscpd.py + check_mutation_sites.py + adapter exclusion + §23 QA-through-UI + pre-commit hook | ~1,400 | code-review-expert (mandatory); judgment-day (mandatory — touches ci.yml, scripts/, git-hooks/, AGENTS.md) |
| #2 | `feat/quality-gates-mutation` | cosmic-ray.toml + diff_cosmic_ray.py + nightly mutation CI job + pre-push hook (advisory) | ~500 | code-review-expert (mandatory); judgment-day (mandatory — touches ci.yml with new scheduled job, git-hooks/) |
| #3 | `feat/quality-gates-property-tests` | hypothesis dev profile + 5 _row_to_* property tests | ~600 | code-review-expert (mandatory); judgment-day NOT mandatory — only tests/ + pyproject.toml dev extras |

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2,500 total (~1,400 + ~500 + ~600 across 3 PRs) |
| 400-line budget risk | High per-commit; each PR is split into multiple work-unit commits (13 + 6 + 4 = 23 commits) |
| Chained PRs recommended | Yes |
| Suggested split | 3 PRs, each with multiple work-unit commits staying under 400 lines per commit |
| Delivery strategy | `exception-ok` (per preflight) |
| Chain strategy | `stacked-to-main` (each PR targets main directly; merge order: #1 → #2 → #3) |

```
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High
```

---

## PR #1: Foundations

### [x] TASK-1.1: Verify context7 dependency floors before pinning
- ID: TASK-1.1
- Files: None (research only)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Query context7 for radon, xenon, cosmic-ray, hypothesis, mutmut current-stable floors. Record each pin rationale. This satisfies REQ-QG-XCUT-2 before any version is written to pyproject.toml.
- Acceptance criteria:
  - Each tool has a context7 query cited in the commit message
  - Each pin is the current stable major.minor floor
  - No deprecated library is pinned
- Tests to add: None (research task)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `chore(deps): verify quality-gates dependency floors via context7`
- Estimated lines: ~30
- Dependency: None

### [x] TASK-1.2: Pin dev dependencies in pyproject.toml
- ID: TASK-1.2
- Files: `pyproject.toml`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? yes
- Description: Add radon>=6.0, xenon>=0.9, cosmic-ray>=8.4, hypothesis>=6.150, mutmut>=2.4 to `[project.optional-dependencies].dev`. Add pytest-randomly>=3.15 (per W-3). Context7 verification from TASK-1.1 is cited in the commit body.
- Acceptance criteria:
  - `pip install -e ".[dev]"` succeeds without DeprecationWarning
  - All five tools are importable in the venv
  - pytest-randomly is importable
- Tests to add: None
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `chore(deps): pin radon xenon cosmic-ray hypothesis mutmut pytest-randomly dev deps`
- Estimated lines: ~15
- Dependency: TASK-1.1

### [x] TASK-1.3: Create scripts/check_crap.py with CRAP ratchet
- ID: TASK-1.3
- Files: `scripts/check_crap.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Implement check_crap.py using radon.complexity and radon.raw to compute per-function CRAP score (CC^2 * (1 - cov/100)^3 + CC). Grade A means CRAP < 6. Mirror scripts/check_module_size.py shape: module docstring, BASELINE_CRAP shrink-only dict, check_tree() returning (violations, notices), main() printing OK/FAIL/NOTE and exit 0/1. Missing coverage.json: exit 0 with NOTE. BASELINE_CRAP starts empty (populated by TASK-1.12 in the same PR).
- Acceptance criteria:
  - `python scripts/check_crap.py` exits 0 on a tree without coverage.json (NOTE printed)
  - `python scripts/check_crap.py` exits 1 when any function exceeds CRAP grade A
  - BASELINE_CRAP is a dict[str, float] shrink-only ratchet
  - Module docstring explains the rule, source observation, and AGENTS.md citation
- Tests to add: None (tests come in TASK-1.4)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(scripts): add check_crap.py CRAP ratchet with shrink-only baseline`
- Estimated lines: ~180
- Dependency: TASK-1.2

### [x] TASK-1.4: Create tests/test_check_crap.py
- ID: TASK-1.4
- Files: `tests/test_check_crap.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Mirror tests/test_module_size.py shape. Test cases: exit 0 on empty baseline (SCN-QG-CRAP-1-1 equivalent), exit 1 when CRAP drops below grade A (SCN-QG-CRAP-1-2), NOTE printed when CRAP improves (SCN-QG-CRAP-1-3), exit 0 with NOTE when coverage.json missing. Includes `test_ci_workflow_lint_job_runs_crap_gate` and `test_ci_workflow_test_job_runs_crap_gate` (CRAP lives in test job per BLOCKER fix). Includes `test_baseline_matches_measured_tree` stub (populated by TASK-1.12).
- Acceptance criteria:
  - All tests pass on the empty-baseline script
  - `test_ci_workflow_test_job_runs_crap_gate` asserts the CRAP step is in the `test` job, not `lint`
  - Missing-coverage scenario exits 0 with NOTE
- Tests to add: `tests/test_check_crap.py`
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `test(check-crap): add tests/test_check_crap.py with ci workflow pins`
- Estimated lines: ~120
- Dependency: TASK-1.3

### [x] TASK-1.5: Create scripts/check_jscpd.py (W-1 docstring clarification)
- ID: TASK-1.5
- Files: `scripts/check_jscpd.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Implement check_jscpd.py as stdlib-only AST walker. Normalise AST (strip identifier names, fold whitespace), cluster identical normalised ASTs as Type-1/2 clones, report project-wide duplicate percentage. BASELINE_JSCPD_PCT = 15.0 (shrink-only). Module docstring MUST open with W-1 clarification: "This script is named check_jscpd.py per the spec (REQ-QG-DRY-1) and the proposal (quality-gates-expansion). It does NOT invoke the jscpd binary — jscpd is a Node.js/Rust tool not pip-installable. This implementation is stdlib-only by construction."
- Acceptance criteria:
  - Module docstring opens with the W-1 clarification paragraph
  - BASELINE_JSCPD_PCT = 15.0
  - check_tree() returns (violations, notices)
  - MIN_CLONE_TOKENS = 50
- Tests to add: None (tests come in TASK-1.6)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(scripts): add check_jscpd.py stdlib AST duplicate detector with shrink-only baseline`
- Estimated lines: ~220
- Dependency: TASK-1.2

### [x] TASK-1.6: Create tests/test_check_jscpd.py
- ID: TASK-1.6
- Files: `tests/test_check_jscpd.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Mirror tests/test_module_size.py shape. Test cases: exit 0 when duplicate pct <= 15.0 (SCN-QG-DRY-1-1), exit 1 when pct > 15.0 (SCN-QG-DRY-1-2), NOTE printed when pct improves (SCN-QG-DRY-1-3). Includes `test_ci_workflow_lint_job_runs_jscpd_gate` and `test_baseline_matches_measured_tree` stub (populated by TASK-1.12).
- Acceptance criteria:
  - All tests pass on the 15.0 baseline
  - `test_ci_workflow_lint_job_runs_jscpd_gate` asserts the step is in the lint job
- Tests to add: `tests/test_check_jscpd.py`
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `test(check-jscpd): add tests/test_check_jscpd.py with ci workflow pins`
- Estimated lines: ~100
- Dependency: TASK-1.5

### [x] TASK-1.7: Create scripts/check_mutation_sites.py
- ID: TASK-1.7
- Files: `scripts/check_mutation_sites.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Implement check_mutation_sites.py as stdlib-only AST walker counting mutation-target nodes per file (BinOp, BoolOp, Compare, If, While, Assert, Raise, Return, Assign with arithmetic, function-call args, literals). BASELINE_MUTATION_SITES is a dict[str, int] shrink-only ratchet. Mirror scripts/check_module_size.py shape exactly.
- Acceptance criteria:
  - BASELINE_MUTATION_SITES is dict[str, int] shrink-only
  - check_tree() returns (violations, notices)
  - Output names the offending file and excess count on violation
  - NOTE printed when a file improves below its baseline
- Tests to add: None (tests come in TASK-1.8)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(scripts): add check_mutation_sites.py AST mutation-site counter with shrink-only baseline`
- Estimated lines: ~200
- Dependency: TASK-1.2

### [x] TASK-1.8: Create tests/test_check_mutation_sites.py
- ID: TASK-1.8
- Files: `tests/test_check_mutation_sites.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Mirror tests/test_module_size.py shape. Test cases: exit 0 on empty baseline (SCN-QG-MSITES-1-1), exit 1 when any file exceeds baseline (SCN-QG-MSITES-1-2), NOTE printed when file improves (SCN-QG-MSITES-1-3). Includes `test_ci_workflow_lint_job_runs_mutation_sites_gate` and `test_baseline_matches_measured_tree` stub.
- Acceptance criteria:
  - All tests pass on the empty-baseline script
  - `test_ci_workflow_lint_job_runs_mutation_sites_gate` asserts the step is in the lint job
- Tests to add: `tests/test_check_mutation_sites.py`
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `test(check-mutation-sites): add tests/test_check_mutation_sites.py with ci workflow pins`
- Estimated lines: ~100
- Dependency: TASK-1.7

### [x] TASK-1.9: Wire 3 new lint-job steps + 1 test-job step into ci.yml
- ID: TASK-1.9
- Files: `.github/workflows/ci.yml`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? yes
- Touches pyproject.toml? no
- Description: Add jscpd step and mutation-sites step to the lint job (after check_vulture_guard.py). Add CRAP step to the test job (after pytest --cov step). CRAP step must be in test job because it reads coverage.json produced by the pytest step. Blockers resolved: CRAP was incorrectly in lint in draft; BLOCKER fix moved it to test job.
- Acceptance criteria:
  - lint job has: `python scripts/check_jscpd.py` and `python scripts/check_mutation_sites.py`
  - test job has: `python scripts/check_crap.py` (AFTER the pytest --cov step)
  - Both new lint steps appear after check_vulture_guard.py in the lint job
  - CRAP step appears after the pytest-cov step in the test job
- Tests to add: pins verified by tests from TASK-1.4, TASK-1.6, TASK-1.8
- Review lenses: code-review-expert (mandatory); judgment-day (mandatory — ci.yml modification)
- Commit strategy: One commit: `feat(ci): wire 3 new lint-job steps + CRAP step in test job per BLOCKER fix`
- Estimated lines: ~40
- Dependency: TASK-1.4, TASK-1.6, TASK-1.8

### [x] TASK-1.10: Exclude app/core/insforge.py from coverage floor
- ID: TASK-1.10
- Files: `pyproject.toml`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? yes
- Description: Add `app/core/insforge.py` to `[tool.coverage.run].omit` in pyproject.toml. fail_under remains unchanged. This satisfies REQ-QG-ADAPT-1.
- Acceptance criteria:
  - `app/core/insforge.py` appears in `[tool.coverage.run].omit`
  - `[tool.coverage.report].fail_under` is unchanged
  - `tests/test_ci_workflow.py::test_ci_workflow_test_job_excludes_insforge_adapter` passes
- Tests to add: None (pin test comes in TASK-1.11)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `chore(coverage): exclude app/core/insforge.py from [tool.coverage.run].omit (REQ-QG-ADAPT-1)`
- Estimated lines: ~5
- Dependency: TASK-1.2

### [x] TASK-1.11: Extend tests/test_ci_workflow.py with adapter exclusion + new lint step assertions
- ID: TASK-1.11
- Files: `tests/test_ci_workflow.py`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Extend `test_ci_workflow_test_job_enforces_global_coverage_floor` with an assertion that `app/core/insforge.py` is in the omit list (REQ-QG-ADAPT-1). Add three new test functions asserting lint job steps: `test_ci_workflow_lint_job_runs_jscpd_gate`, `test_ci_workflow_lint_job_runs_mutation_sites_gate`, `test_ci_workflow_test_job_runs_crap_gate` (CRAP in test job, per BLOCKER fix). Mirror the pattern of `test_ci_workflow_lint_job_runs_module_size_gate`.
- Acceptance criteria:
  - All four new assertions pass
  - Existing tests still pass
- Tests to add: `tests/test_ci_workflow.py` (new methods in existing class)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `test(ci): pin adapter exclusion + 3 new lint/step pins in test_ci_workflow.py`
- Estimated lines: ~50
- Dependency: TASK-1.9, TASK-1.10

### [x] TASK-1.12: Capture CRAP, jscpd, and mutation-sites baselines on main
- ID: TASK-1.12
- Files: `scripts/check_crap.py`, `scripts/check_jscpd.py`, `scripts/check_mutation_sites.py`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Measure the current tree on main: (1) run radon cc + parse coverage.json to produce BASELINE_CRAP entries, (2) run the jscpd detector to confirm BASELINE_JSCPD_PCT = 15.0, (3) run the mutation-sites counter to produce BASELINE_MUTATION_SITES entries. Populate the BASELINE_* constants in the scripts with the measured values. The populated BASELINE values must be committed in the SAME commit as the script introduction (RISK-2: without this the build is red on first run).
- Acceptance criteria:
  - `python scripts/check_crap.py` exits 0 with NOTE on the populated baseline
  - `python scripts/check_jscpd.py` exits 0 with OK: 15.00% <= 15.00%
  - `python scripts/check_mutation_sites.py` exits 0 with NOTE on the populated baseline
  - tests/test_check_crap.py::test_baseline_matches_measured_tree passes
  - tests/test_check_jscpd.py::test_baseline_matches_measured_tree passes
  - tests/test_check_mutation_sites.py::test_baseline_matches_measured_tree passes
- Tests to add: None (baselines drive existing pinning tests)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `chore(baseline): populate BASELINE_CRAP, BASELINE_JSCPD_PCT, BASELINE_MUTATION_SITES on main`
- Estimated lines: ~300
- Dependency: TASK-1.3, TASK-1.5, TASK-1.7

### [x] TASK-1.13: Edit AGENTS.md §23 to add QA-through-UI sentence (per §17.3 feature-branch flow)
- ID: TASK-1.13
- Files: `AGENTS.md`
- Touches AGENTS.md? yes
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Per §17.3, the orchestrator does NOT edit AGENTS.md inline. Delegate to an apply sub-agent on a feature branch that produces the diff from design.md §AGENTS.md §23 edit. The edit adds the QA-through-UI only paragraph to §23 (REQ-QG-QAUI-1). Exact text from design.md: "QA-through-UI only. Verification of any UI-facing feature slice MUST go through the existing Playwright E2E suite under tests/e2e/ (or an equivalent in-tree browser test). QA via the Python shell, direct DB inspection, or curl against a running server is NOT a substitute and MUST NOT be presented as such in PR descriptions, runbooks, or status reports..."
- Acceptance criteria:
  - tests/test_agents_md_section_23.py passes (literal phrase present)
  - The paragraph is appended after the existing §23 paragraph
  - No other §23 text is changed
- Tests to add: `tests/test_agents_md_section_23.py` (in this same commit)
- Review lenses: code-review-expert (mandatory); judgment-day (mandatory — AGENTS.md modification)
- Commit strategy: One commit: `docs(agents): add QA-through-UI only sentence to AGENTS.md §23 (REQ-QG-QAUI-1)`
- Estimated lines: ~25
- Dependency: TASK-1.2 (deps must be pinned first; §17.3 flow applies)

### [x] TASK-1.14: Create git-hooks/pre-commit advisory hook
- ID: TASK-1.14
- Files: `git-hooks/pre-commit` (new), `git-hooks/README.md` (new)
- Touches AGENTS.md? no
- Touches git-hooks? yes
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Create git-hooks/pre-commit as an advisory-only shell script. It runs the three PR #1 detectors (check_crap.py, check_jscpd.py, check_mutation_sites.py) on staged Python files. It MUST exit 0 regardless of findings (per §15.5 advisory contract). Prints ADVISORY: lines on violations. Create git-hooks/README.md with operator instructions: `git config core.hooksPath git-hooks/`.
- Acceptance criteria:
  - Hook exits 0 even when detectors report findings
  - ADVISORY: prefix appears on findings
  - README documents installation command
  - Hook is chmod +x
- Tests to add: `tests/test_git_hooks.py` (advisory exit-0 contract test)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(hooks): add git-hooks/pre-commit advisory script + README`
- Estimated lines: ~60
- Dependency: TASK-1.3, TASK-1.5, TASK-1.7

### [x] TASK-1.15: Open PR #1 against main
- ID: TASK-1.15
- Files: None
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Open PR #1: branch=feat/quality-gates-foundations, target=main. Title: `feat(quality-gates): add CRAP, jscpd, mutation-sites detectors + adapter exclusion + §23 QA-through-UI`. Body cites gatekeeper-driven design v2, BLOCKER fix applied (CRAP in test job), W-1 docstring clarification in check_jscpd.py. CI must be green before merge.
- Acceptance criteria:
  - PR opened and linked to the design artifact
  - CI (lint + test) is green on the branch
  - All 13+ commits are on the branch
- Tests to add: None
- Review lenses: code-review-expert (mandatory); judgment-day (mandatory — ci.yml + git-hooks + AGENTS.md)
- Commit strategy: N/A (PR creation)
- Estimated lines: 0
- Dependency: TASK-1.1 through TASK-1.14

### [x] TASK-1.16: After PR #1 merge — capture CI run evidence
- ID: TASK-1.16
- Files: None
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: After PR #1 merges to main, capture the first green CI run URL as evidence in a follow-up comment on the PR or in the PR description. Verify that the CRAP step ran in the test job (not lint), that the jscpd and mutation-sites steps ran in the lint job, and that the coverage floor is unchanged.
- Acceptance criteria:
  - CI run on main post-merge is green
  - CRAP step appears in test job logs
  - jscpd and mutation-sites steps appear in lint job logs
- Tests to add: None
- Review lenses: None
- Commit strategy: N/A (post-merge verification)
- Estimated lines: 0
- Dependency: TASK-1.15 (merge)

---

## PR #2: Mutation Testing

### TASK-2.1: Verify cosmic-ray determinism + add W-5 mitigations
- ID: TASK-2.1
- Files: None (research + config)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Per W-5: query context7 for cosmic-ray SQLite session determinism. If PYTHONHASHSEED or worker-count affects reproducibility, document the findings. Add `--worker-count=1` and `PYTHONHASHSEED=0` to the mutation job environment in ci.yml (TASK-2.6). This is a forward-dep: findings from context7 inform the YAML.
- Acceptance criteria:
  - W-5 determinism query is cited in the commit body
  - PYTHONHASHSEED=0 and --worker-count=1 are added to ci.yml mutation job environment
- Tests to add: None
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `chore(mutation): add cosmic-ray determinism mitigations (PYTHONHASHSEED=0 --worker-count=1)`
- Estimated lines: ~10
- Dependency: TASK-1.15 (PR #1 must merge first)

### TASK-2.2: Create docs/quality/cosmic-ray.toml
- ID: TASK-2.2
- Files: `docs/quality/cosmic-ray.toml` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Create cosmic-ray configuration: module-path = "app", excluded-modules = ["tests/", "scripts/"], test-command = "python -m pytest -x -q". Per REQ-QG-MUT-1.
- Acceptance criteria:
  - cosmic-ray.toml exists under docs/quality/
  - Module path covers app/ and migration/
  - Test command uses existing pytest -x -q
- Tests to add: None
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `chore(quality): add docs/quality/cosmic-ray.toml config`
- Estimated lines: ~20
- Dependency: TASK-2.1

### TASK-2.3: Run cosmic-ray on main and produce mutation-baseline.json
- ID: TASK-2.3
- Files: `docs/quality/mutation-baseline.json` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Run cosmic-ray init + exec against the merge commit of PR #1. Capture surviving mutants into docs/quality/mutation-baseline.json. Format: {total, killed, survived, skipped, percentage_killed, mutants:[{module, function, mutant_id, operator, line, survived}]}. Per REQ-QG-MUT-1 SCN-QG-MUT-1-1. This is an operator-driven step run locally; the output is committed in this task.
- Acceptance criteria:
  - mutation-baseline.json exists and parses as valid JSON
  - mutants array is non-empty
  - summary contains total/killed/survived/skipped/percentage_killed
- Tests to add: None (verification is SCN-QG-MUT-1-1 manual confirmation)
- Review lenses: None
- Commit strategy: One commit: `docs(quality): capture mutation-baseline.json on main (operator-driven baseline acquisition)`
- Estimated lines: ~500 (the manifest)
- Dependency: TASK-2.2

### TASK-2.4: Create scripts/diff_cosmic_ray.py
- ID: TASK-2.4
- Files: `scripts/diff_cosmic_ray.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Implement diff_cosmic_ray.py as stdlib-only. Reads cr-report --json output (current session) and baseline manifest (mutation-baseline.json). Extracts (module, function, mutant_id, survived) set from each. Exits 0 if current survived <= baseline survived (identical or improvement). Exits 1 if current survived > baseline survived (regression). Prints regression lines for each new survivor. Per REQ-QG-MUT-2 SCN-QG-MUT-2-1/2/3.
- Acceptance criteria:
  - Exit 0 on identical surviving sets (SCN-QG-MUT-2-1)
  - Exit 1 on new survivors with REGRESSION: lines printed (SCN-QG-MUT-2-2)
  - Exit 0 on fewer survivors with IMPROVEMENT: -N printed (SCN-QG-MUT-2-3)
  - Manifest is NOT modified by the script
- Tests to add: None (tests come in TASK-2.5)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(scripts): add diff_cosmic_ray.py regression-only gate`
- Estimated lines: ~120
- Dependency: TASK-2.2

### TASK-2.5: Create tests/test_diff_cosmic_ray.py
- ID: TASK-2.5
- Files: `tests/test_diff_cosmic_ray.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Unit tests for diff_cosmic_ray.py using tmp_path synthetic manifests. Test three cases: identical sets (exit 0), new survivor (exit 1 + REGRESSION: line), fewer survivors (exit 0 + IMPROVEMENT: line). Test that manifest is not modified.
- Acceptance criteria:
  - All three cases produce the correct exit code and output
  - Manifest is not modified after the script runs
- Tests to add: `tests/test_diff_cosmic_ray.py`
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `test(diff-cosmic-ray): add tests/test_diff_cosmic_ray.py`
- Estimated lines: ~80
- Dependency: TASK-2.4

### TASK-2.6: Add mutation CI job to ci.yml (weekly schedule + workflow_dispatch)
- ID: TASK-2.6
- Files: `.github/workflows/ci.yml`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? yes
- Touches pyproject.toml? no
- Description: Add new mutation job: triggered by schedule (weekly, Wednesday 03:00 UTC per design) + workflow_dispatch. Self-hosted runner. 60-minute timeout. Steps: checkout, setup-python, pip install -e ".[dev]", cosmic-ray init + exec + cr-report, diff_cosmic_ray.py. Artifacts: upload .cosmic-ray/ directory (30-day retention). Per REQ-QG-MUT-2. Per W-5: environment section includes PYTHONHASHSEED=0; cosmic-ray exec uses --worker-count=1.
- Acceptance criteria:
  - Job runs on schedule (cron: "17 6 * * 3") and on workflow_dispatch
  - PYTHONHASHSEED=0 is in the job environment
  - cosmic-ray exec uses --worker-count=1
  - Artifact upload is on always() so failed runs still upload
  - Job does NOT fail the deploy job needs chain (per §32.P7)
- Tests to add: pins verified by tests from TASK-2.5
- Review lenses: code-review-expert (mandatory); judgment-day (mandatory — new scheduled CI job)
- Commit strategy: One commit: `feat(ci): add nightly mutation job with weekly schedule + workflow_dispatch`
- Estimated lines: ~60
- Dependency: TASK-2.1, TASK-2.4, TASK-2.5

### TASK-2.7: Update git-hooks/pre-push with advisory mutation scan (W-2 comment rename)
- ID: TASK-2.7
- Files: `git-hooks/pre-push` (new)
- Touches AGENTS.md? no
- Touches git-hooks? yes
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Per W-2: rename the comment block from "mutant inventory scan (advisory)" to "mutant inventory scan (advisory, no mutants evaluated)". The pre-push hook runs a fast cosmic-ray scan on changed files only (scoped via --module-path). 25s timeout. Exit 0 always. ADVISORY output. Per REQ-QG-HOOK-2 SCN-QG-HOOK-2-1.
- Acceptance criteria:
  - Comment block uses the W-2 corrected text
  - Hook exits 0 regardless of scan results
  - timeout 25s is enforced
  - ADVISORY: prefix appears on findings
- Tests to add: `tests/test_git_hooks.py` (pre-push exit-0 contract test)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(hooks): add git-hooks/pre-push advisory mutation scan + W-2 comment correction`
- Estimated lines: ~50
- Dependency: TASK-2.2

### TASK-2.8: Open PR #2 against main
- ID: TASK-2.8
- Files: None
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Open PR #2: branch=feat/quality-gates-mutation, target=main. Title: `feat(quality-gates): cosmic-ray manifest + nightly mutation job + pre-push hook (differential manifest)`. Body explains the baseline acquisition is the main deliverable; nightly job is the enforcement. CI must be green before merge.
- Acceptance criteria:
  - PR opened and linked to the design artifact
  - CI is green on the branch
- Tests to add: None
- Review lenses: code-review-expert (mandatory); judgment-day (mandatory — ci.yml new scheduled job + git-hooks/)
- Commit strategy: N/A (PR creation)
- Estimated lines: 0
- Dependency: TASK-2.1 through TASK-2.7

---

## PR #3: Property Tests

### TASK-3.1: Ensure hypothesis dev profile + pytest-randomly in pyproject.toml
- ID: TASK-3.1
- Files: `pyproject.toml`
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? yes
- Description: Per W-3: verify pytest-randomly>=3.15 is already pinned in [dev] (from TASK-1.2). Verify hypothesis>=6.150 is pinned. No new additions needed if TASK-1.2 was completed. Confirm both are in [project.optional-dependencies].dev.
- Acceptance criteria:
  - pytest-randomly>=3.15 is in [dev]
  - hypothesis>=6.150 is in [dev]
  - pip install -e ".[dev]" succeeds
- Tests to add: None
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit (or确认): `chore(deps): confirm hypothesis and pytest-randomly dev deps (W-3 resolved)`
- Estimated lines: 0 (or ~5)
- Dependency: TASK-1.2 (PR #1 must have merged)

### TASK-3.2: Create tests/property/ directory with conftest.py and hypothesis dev profile
- ID: TASK-3.2
- Files: `tests/property/__init__.py` (new), `tests/property/conftest.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Create tests/property/__init__.py (empty). Create tests/property/conftest.py with: try/except hypothesis import; _HYPOTHESIS_AVAILABLE guard; hypothesis.settings.register_profile("dev", max_examples=50, derandomize=False, deadline=None); settings.load_profile("dev"); pytest_collection_modifyitems hook that skips tests/property/ with a documented reason when hypothesis is absent (SCN-QG-PROP-1-2). Per REQ-QG-PROP-1.
- Acceptance criteria:
  - pytest tests/property/ collects property tests when hypothesis is installed
  - pytest skips (not errors) when hypothesis is absent
  - "hypothesis not installed" skip reason appears in collection output
- Tests to add: `tests/test_property_test_collection.py` (in TASK-3.3)
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `feat(tests): add tests/property/ with custom hypothesis dev profile + skip-if-missing hook`
- Estimated lines: ~50
- Dependency: TASK-3.1

### TASK-3.3: Create first 5 property tests for _row_to_* helpers
- ID: TASK-3.3
- Files: `tests/property/test_row_to_animal.py` (new), `tests/property/test_row_to_voluntario.py` (new), `tests/property/test_row_to_acogida.py` (new), `tests/property/test_row_to_entrada.py` (new), `tests/property/test_row_to_adopcion.py` (new), `tests/test_property_test_collection.py` (new)
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Create 5 property tests targeting the _row_to_* helpers enumerated in design.md §Property test targets. Each test: uses @given() with strategies matching the helper's input shape, calls the helper directly (no FastAPI app), asserts output is a valid model instance with no unexpected exception. Per REQ-QG-PROP-2 and SCN-QG-PROP-2-1. Also create test_property_test_collection.py asserting: (1) pytest collects 5+ property tests when hypothesis is available, (2) pytest skips when hypothesis is absent.
- Acceptance criteria:
  - All 5 property tests are collected by pytest
  - Each test runs 50 examples (dev profile)
  - Property suite completes in under 60 seconds (per SCN-QG-PROP-2-2)
  - pytest-randomly seed is printed on failure (reproducibility)
- Tests to add: `tests/property/test_row_to_*.py` (5 files), `tests/test_property_test_collection.py`
- Review lenses: code-review-expert (mandatory)
- Commit strategy: One commit: `test(property): add 5 _row_to_* property tests + collection pin`
- Estimated lines: ~400
- Dependency: TASK-3.2

### TASK-3.4: Open PR #3 against main
- ID: TASK-3.4
- Files: None
- Touches AGENTS.md? no
- Touches git-hooks? no
- Touches ci.yml? no
- Touches pyproject.toml? no
- Description: Open PR #3: branch=feat/quality-gates-property-tests, target=main. Title: `feat(quality-gates): hypothesis dev profile + 5 _row_to_* property tests`. Body lists the first targets and explains the <60s budget. CI must be green before merge.
- Acceptance criteria:
  - PR opened and linked to the design artifact
  - CI test job includes the property tests
  - All property tests pass
- Tests to add: None
- Review lenses: code-review-expert (mandatory); judgment-day NOT mandatory (only tests/ + pyproject.toml dev extras)
- Commit strategy: N/A (PR creation)
- Estimated lines: 0
- Dependency: TASK-3.1, TASK-3.2, TASK-3.3

---

## Rollback

| PR | Rollback command |
|----|-----------------|
| PR #1 | `git revert <merge-sha>` — removes check_crap.py, check_jscpd.py, check_mutation_sites.py, adapter exclusion, §23 edit, pre-commit hook, CI steps, and all pinning tests atomically |
| PR #2 | `git revert <merge-sha>` — removes cosmic-ray.toml, mutation-baseline.json, diff_cosmic_ray.py, mutation CI job, pre-push hook; also run `gh workflow disable mutation` |
| PR #3 | `git revert <merge-sha>` — removes tests/property/ directory and the hypothesis pytest config |

---

## Requirement traceability

| Requirement | Task(s) |
|-------------|---------|
| REQ-QG-CRAP-1 | TASK-1.3, TASK-1.4, TASK-1.9, TASK-1.12 |
| REQ-QG-MUT-1 | TASK-2.2, TASK-2.3 |
| REQ-QG-MUT-2 | TASK-2.1, TASK-2.4, TASK-2.5, TASK-2.6 |
| REQ-QG-PROP-1 | TASK-3.2, TASK-3.3 |
| REQ-QG-PROP-2 | TASK-3.3 |
| REQ-QG-DRY-1 | TASK-1.5, TASK-1.6, TASK-1.9, TASK-1.12 |
| REQ-QG-MSITES-1 | TASK-1.7, TASK-1.8, TASK-1.9, TASK-1.12 |
| REQ-QG-ADAPT-1 | TASK-1.10, TASK-1.11 |
| REQ-QG-QAUI-1 | TASK-1.13 |
| REQ-QG-HOOK-1 | TASK-1.14 |
| REQ-QG-HOOK-2 | TASK-2.7 |
| REQ-QG-HOOK-3 | TASK-1.14 (pre-commit independence), TASK-2.6 (CI independence) |
| REQ-QG-XCUT-1 | TASK-1.3+TASK-1.4 (CRAP), TASK-1.5+TASK-1.6 (jscpd), TASK-1.7+TASK-1.8 (mutation-sites) |
| REQ-QG-XCUT-2 | TASK-1.1, TASK-1.2 |
| REQ-QG-XCUT-3 | TASK-2.3 (manifest committed by human), TASK-2.6 (CI does not update manifest) |

## Warning (W-*) traceability

| Warning | Task(s) |
|---------|---------|
| W-1: check_jscpd.py docstring clarification | TASK-1.5 (module docstring must open with W-1 paragraph) |
| W-2: pre-push comment block rename | TASK-2.7 (comment text corrected) |
| W-3: pytest-randomly in dev deps | TASK-1.2 (added to pyproject.toml [dev]) |
| W-4: BLOCKER — CRAP in test job | TASK-1.9 (step wired in test job, not lint) |
| W-5: cosmic-ray determinism | TASK-2.1 (PYTHONHASHSEED=0 + --worker-count=1) |
