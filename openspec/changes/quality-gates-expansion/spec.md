# Spec: quality-gates-expansion

## Purpose

This spec translates the `quality-gates-expansion` proposal into a concrete
**requirements + scenarios** layer that `sdd-design` and `sdd-apply` can
consume. It does not pick tools, file paths, or implementation details — it
fixes the **contract** of what each new gate MUST enforce, how each MUST be
verified, and how each MUST behave on first run so the build stays green on
the PR that introduces it. Five new deterministic gates plus two refinements
to existing gates plus advisory git hooks are in scope; no business-domain
code, no service-layer code, no templates, and no route handlers are touched
by this change.

**Source traceability:** proposal
`openspec/changes/quality-gates-expansion/proposal.md` (Engram `#24074`,
topic `sdd/quality-gates-expansion/proposal`); source analysis Engram `#24073`
(topic `sdd/quality-gates-expansion/source`).

## Scope

### In scope (verbatim from proposal §3)

| # | Feature | Tool | Surface |
|---|---------|------|---------|
| 1 | CRAP score threshold = A | `radon cc -s -n A` + `xenon` | CI `lint` job + pre-commit hook |
| 2 | Mutation testing | `cosmic-ray` (baseline + diff) | new nightly CI job + pre-push hook |
| 3 | Property-based testing | `hypothesis` | `tests/property/` + first targets = `_row_to_*` helpers |
| 4 | Formal DRY detection | `jscpd` | new `scripts/check_jscpd.py` (mirrors §21) |
| 5 | Mutation-sites count pre-PR | AST/scan counter | new `scripts/check_mutation_sites.py` |
| Bonus A | Adapter exclusion from coverage floor | `pyproject.toml` + `ci.yml` | `app/core/insforge.py` excluded from `fail_under` |
| Bonus B | "QA-through-UI only" explicit in §23 | AGENTS.md text clarification | feature branch + PR (per §17.3) |
| Hooks | Pre-commit (advisory) + Pre-push (advisory) | git hooks | touches `git-hooks/` (per §15.5; user OK granted this session) |

### Out of scope (verbatim from proposal §3)

- Gherkin/BDD (project uses pytest), Speclj (Clojure only), AI-judgment
  architectural reviews (already covered by `code-review-expert` + `judgment-day`).
- Replacing or relaxing any existing gate (§19, §20, §21, §24, §25–§28).
- Any business-domain change — no routes, services, slices, or templates
  touched.
- Editing `git-hooks/` outside the explicit user-granted scope this session.

## Defaults applied (orchestrator-decided, auto-mode continuity)

These three defaults were open in the proposal §7. The orchestrator resolved
them and they are encoded as concrete requirements below. If `sdd-apply`
discovers evidence any default is wrong, surface it as a RISK in the design
artifact; do NOT silently switch.

1. **Mutation tool = `cosmic-ray`** (built-in differential manifest matches
   "block on regression vs baseline" requirement).
2. **`jscpd` initial threshold = 15%** (matches current measurement; does not
   force unrelated #227 cleanup inside this change).
3. **Hypothesis CI profile = `dev`** (fast default; property tests
   supplement, do not replace, atomic tests).

---

## Requirements

The requirement IDs use the form `REQ-QG-<FEATURE>-<NN>` and scenario IDs
use `SCN-QG-<FEATURE>-<N>-<M>` so each requirement is independently
testable, locatable, and traceable to the proposal row it derives from.

### Feature 1: CRAP score threshold = A

**Source:** Proposal §3 row 1 / Observation #24073 (Source analysis §2)
**Modifies:** new gate; extends CI `lint` job (rule §20) — does not modify
any AGENTS.md rule text.
**Defaults applied:** none of the three orchestrator defaults affect CRAP.

#### Requirement: REQ-QG-CRAP-1 — CRAP score per function MUST stay at grade A

The system MUST provide a deterministic check that fails when any function in
`app/` and `migration/` exceeds cyclomatic-complexity-adjusted CRAP score A
(strictest band). The check SHALL be implemented as `scripts/check_crap.py`
(mirrors `scripts/check_module_size.py`'s shape) and SHALL be wired as a step
in the CI `lint` job. Coverage input for CRAP MUST come from
`coverage.json` already produced by the existing `--cov-report=json` flag in
the CI `test` job (§19).

**Rationale:** 80% line coverage proves lines were executed; it does NOT
prove assertions exist. CRAP combines complexity with the inverse of
coverage — a function with CC=20 and 50% coverage has CRAP≈40 (grade F).
Catching that surface proves the existing test net actually exercises the
hard paths.

**Scenarios:**

- **SCN-QG-CRAP-1-1** — Given `app/` + `migration/` with the baseline
  measured on the merge commit before PR #1 lands, WHEN the new check runs
  on that tree, THEN it SHALL print `OK` and exit 0; the baseline values
  are recorded in a shrink-only `BASELINE_CRAP` ratchet inside the script.

- **SCN-QG-CRAP-1-2** — Given a function whose complexity OR uncovered-line
  count changes such that CRAP drops below grade A, WHEN the check runs on
  the PR that introduced the change, THEN it SHALL exit non-zero with a
  message naming the offending function, file, and line.

- **SCN-QG-CRAP-1-3** — Given a function whose CRAP score improves (shrinks)
  versus its baseline entry, WHEN the check runs, THEN it SHALL exit 0 and
  print a `NOTE` reminding the operator to lower the corresponding
  `BASELINE_CRAP` entry in the same PR (mirrors §21/§28 contract).

**Verification:** `python scripts/check_crap.py` exits 0 on a clean tree;
new step in `.github/workflows/ci.yml` `lint` job (pinned by a test in
`tests/test_check_crap.py::test_ci_workflow_lint_job_runs_crap_gate`).

**Failure mode:** block (exit 1) — first PR runs in `mode=warn` against an
empty baseline so the build stays green while baseline values are captured
in the same PR; the second PR flips `mode=block`.

**Baseline behavior:** shrink-only ratchet. Entries may shrink or
disappear, never grow. New entries require a measured CRAP value plus the
exact path; same shape as `BASELINE` in `scripts/check_module_size.py`.

#### Out of scope for Feature 1

- CRAP on `tests/` or `scripts/` (test code is exercised by the suite
  itself; gating it would re-create §32.P8's per-layer gap).
- Per-function CC reports from `xenon` outside the A-grade band — those
  come from `scripts/check_complexity.py` already.
- HTML report rendering (CI sees stdout only).

---

### Feature 2: Mutation testing (cosmic-ray)

**Source:** Proposal §3 row 2 / Observation #24073 (Source analysis §1)
**Modifies:** new gate; new nightly CI job; does not modify any AGENTS.md
rule text.
**Defaults applied:** mutation tool = `cosmic-ray`; differential-manifest
pattern.

#### Requirement: REQ-QG-MUT-1 — A checked-in cosmic-ray manifest captures the surviving-mutant baseline

The system MUST run a one-time cosmic-ray session against the merge commit
that introduces this requirement, capture the list of surviving mutants
(those NOT killed by the existing atomic suite), and check the resulting
manifest into the repository as `docs/quality/mutation-baseline.json`. The
manifest format MUST record `(module_path, function_name, mutant_id,
survived: bool)` for every mutation cosmic-ray explored, plus the
aggregate `{ total, killed, survived, skipped, percentage_killed }` summary.
Re-running cosmic-ray on the same commit MUST be deterministic and MUST
reproduce the manifest bit-for-bit.

**Rationale:** mutation testing on a mature codebase shows many surviving
mutants out of the gate (proposal §6 row 2). Gating on the absolute count
would block PR #2 from merging. The differential-manifest pattern — block
only on **regression vs the manifest** — turns the gate into "no new
mutants survive" instead of "kill all mutants on day one".

**Scenarios:**

- **SCN-QG-MUT-1-1** — Given a clean checkout of the merge commit of PR #2,
  WHEN the operator runs the documented cosmic-ray session, THEN the
  resulting `docs/quality/mutation-baseline.json` SHALL exist, SHALL parse
  as valid JSON, and SHALL contain a non-empty `mutants[]` array.

- **SCN-QG-MUT-1-2** — Given the manifest produced in SCN-QG-MUT-1-1, WHEN
  cosmic-ray is re-run on the same commit with the same Python and the
  same dependency versions, THEN the new manifest SHALL equal the checked-in
  one byte-for-byte (manifest diff = 0).

#### Requirement: REQ-QG-MUT-2 — Nightly CI job blocks on surviving-mutant regression, not on absolute count

The system MUST add a new `mutation` job to `.github/workflows/ci.yml`
triggered by `schedule:` (cron, weekly at minimum) and by
`workflow_dispatch:`. The job MUST run cosmic-ray against `app/` and
`migration/`, diff the resulting surviving-mutant set against
`docs/quality/mutation-baseline.json`, and exit non-zero iff the new
set is NOT a subset of the baseline (regression detected). The job
MUST NOT fail when the surviving count drops (improvement). The job
MUST NOT block the `deploy` job's `needs:` chain — mutation testing is a
separate signal, not a release gate in pre-MVP.

**Rationale:** §32.P7 forbids guards that cancel themselves. Per the
pre-MVP gate (§15.1), only `lint`/`test`/`build` are blocking; the
existing `security-deep` job follows the same schedule-only pattern.

**Scenarios:**

- **SCN-QG-MUT-2-1** — Given the manifest from REQ-QG-MUT-1 and a commit
  whose surviving-mutant set is identical to the manifest, WHEN the
  nightly job runs, THEN it SHALL exit 0 and print `OK: 0 regressions`.

- **SCN-QG-MUT-2-2** — Given the manifest from REQ-QG-MUT-1 and a commit
  that introduces a NEW surviving mutant (function changed in a way the
  atomic suite does not assert against), WHEN the nightly job runs, THEN
  it SHALL exit non-zero and print a `REGRESSION: <module>.<func>
  mutant_id=<id>` line for each new survivor.

- **SCN-QG-MUT-2-3** — Given a commit that REDUCES the surviving-mutant
  count (test atoms added that kill previously-surviving mutants), WHEN
  the nightly job runs, THEN it SHALL exit 0 AND print `IMPROVEMENT:
  -N survivors` AND the manifest SHALL NOT be updated by CI (the operator
  decides when to lock the improvement into the checked-in baseline).

#### Out of scope for Feature 2

- Mutation testing on `tests/` or `scripts/` — same rationale as Feature 1.
- Per-PR mutation runs — too slow for the pre-MVP gate loop; nightly only.
- Replacing cosmic-ray with mutmut — orchestrator default is cosmic-ray;
  switching is out of scope for this change.

---

### Feature 3: Property-based testing (hypothesis)

**Source:** Proposal §3 row 3 / Observation #24073 (Source analysis §3)
**Modifies:** new test directory + new dev dep; does not modify any
AGENTS.md rule text.
**Defaults applied:** Hypothesis CI profile = `dev`; first targets =
`_row_to_*` helpers in `CRITICAL_HELPERS` (§11).

#### Requirement: REQ-QG-PROP-1 — `tests/property/` directory hosts hypothesis-driven property tests

The system MUST add `tests/property/` as a new top-level test directory
covered by the project's pytest discovery. The directory MUST be excluded
from default pytest collection only when the `hypothesis` dev-dep is not
installed (so a clean `pip install -e ".[dev]"` on a machine without
hypothesis does not break the suite); this exclusion SHALL be implemented
as a `pytest_collection_modifyitems` hook gated on
`pytestconfig.getini("apap_property_available")` set by
`conftest.py` when `hypothesis` imports succeed. When hypothesis IS
available, the directory SHALL be collected and run by the standard CI
`test` job (no separate job).

**Rationale:** the standard CI suite is the cheapest reliable signal —
adding a separate property job creates the §32.P6 risk (test that exists
but never runs). Property tests must run alongside atomic tests or the
gate is decorative.

**Scenarios:**

- **SCN-QG-PROP-1-1** — Given a developer venv with `hypothesis`
  installed, WHEN `pytest tests/property/` runs, THEN at least one
  property test SHALL be collected and executed.

- **SCN-QG-PROP-1-2** — Given a developer venv WITHOUT `hypothesis`
  installed, WHEN the default `pytest` run executes, THEN the property
  tests SHALL be skipped with a documented `skip` reason naming the
  missing dep, NOT a hard `collection error`.

#### Requirement: REQ-QG-PROP-2 — First property targets are the `_row_to_*` helpers

The system MUST add at least 5 property tests under `tests/property/`
covering the `_row_to_*` helpers currently in `CRITICAL_HELPERS`
(`scripts/pytest_plugin/coverage_gate.py`). Each property MUST encode
an invariant the existing example-based tests verify case-by-case
(e.g. "an all-None row yields a model with default scalars", "string
fields round-trip without whitespace regression", "datetime fields
parse ISO 8601 with timezone"). Hypothesis MUST be configured with
profile `dev` (matches `pytest-randomly` seed control) and MUST use
`@given(...)` strategies that exercise the helper's actual contract —
not mock-only tests.

**Rationale:** the proposal §4 row 3 names `_row_to_*` as the first
target set because each is a mini-parser whose contracts the existing
suite proves one example at a time. Hypothesis shrinks to the smallest
failing input, exposing edge cases the example suite cannot enumerate.

**Scenarios:**

- **SCN-QG-PROP-2-1** — Given `_row_to_animal` in
  `app/modules/animals/service.py`, WHEN the corresponding property test
  in `tests/property/test_row_to_animal.py` runs against 200 generated
  rows, THEN every generated row SHALL produce a valid `Animal` instance
  (no `ValueError`, no `KeyError`, no `AttributeError`).

- **SCN-QG-PROP-2-2** — Given the hypothesis profile configuration,
  WHEN the property suite runs in CI, THEN it SHALL complete in under
  60 seconds (the `dev` profile caps example counts); flakes SHALL be
  reproducible by the `pytest-randomly` seed printed in the failure
  output (§32.P6 — test exists and runs).

#### Out of scope for Feature 3

- Property tests for non-`CRITICAL_HELPERS` modules — first slice is the
  helpers; additional targets land in follow-up changes.
- Stateful property tests (`hypothesis.stateful.RuleBasedStateMachine`)
  — overkill for the row-to-model parsers.
- Custom `hypothesis` strategies beyond the built-in ones.

---

### Feature 4: Formal DRY detection (jscpd)

**Source:** Proposal §3 row 4 / Observation #24073 (Source analysis §4)
**Modifies:** new detector; extends CI `lint` job; does not modify any
AGENTS.md rule text.
**Defaults applied:** initial threshold = 15% (matches current measurement;
does not force issue #227 cleanup inside this change).

#### Requirement: REQ-QG-DRY-1 — jscpd runs as a deterministic CI gate with a shrink-only baseline

The system MUST add `scripts/check_jscpd.py` (mirrors
`scripts/check_module_size.py`'s shape) that invokes `jscpd` against the
source tree, parses the resulting JSON/XML output, and fails when the
duplicate-percentage metric exceeds the recorded baseline. The threshold
MUST live in a shrink-only `BASELINE_JSCPD_PCT` constant inside the
script (init = 15.0). The detector MUST scan the same directories
covered by other ratchets (`app/`, `migration/`, `scripts/`) and MUST
ignore `tests/`, generated files, and vendored code (mirroring the
exclude pattern documented in `scripts/check_module_size.py`).

**Rationale:** §25's `WATCHED_DUPLICATE_HELPERS` watch-list covers three
helper names; a general duplication detector fills the rest. jscpd's
default 5% threshold would fail on the current tree (issue #227 has not
landed), so the first PR must run in `mode=warn` against the measured
15% baseline; the threshold may only shrink.

**Scenarios:**

- **SCN-QG-DRY-1-1** — Given the merge commit of PR #1 with the
  baseline measured at 15.0%, WHEN `python scripts/check_jscpd.py` runs
  on that tree, THEN it SHALL print `OK: 15.00% <= 15.00% baseline`
  and exit 0.

- **SCN-QG-DRY-1-2** — Given a PR whose duplicate-percentage exceeds
  `BASELINE_JSCPD_PCT`, WHEN the check runs, THEN it SHALL exit non-zero
  with a message naming the top duplicated regions (file pairs + token
  count) so the operator can decide whether to refactor or to lower the
  baseline.

- **SCN-QG-DRY-1-3** — Given a PR that reduces duplication below the
  baseline, WHEN the check runs, THEN it SHALL exit 0 AND print a `NOTE`
  reminding the operator to lower `BASELINE_JSCPD_PCT` in the same PR.

**Verification:** pinned by `tests/test_check_jscpd.py`. The CI `lint`
job step is pinned by
`tests/test_ci_workflow.py::test_ci_workflow_lint_job_runs_jscpd_gate`.

**Failure mode:** block (exit 1) from PR #2 onwards; `mode=warn` for PR #1.

**Baseline behavior:** shrink-only. `BASELINE_JSCPD_PCT` may only
decrease.

#### Out of scope for Feature 4

- Refactoring the existing duplication tracked by issue #227 — separate
  change.
- Per-line jscpd diff (only the project-level percentage is gated; file-
  pair detail is informational).
- Switching jscpd to a different token model (current default).

---

### Feature 5: Mutation-sites count pre-PR

**Source:** Proposal §3 row 5 / Observation #24073 (Source analysis §5)
**Modifies:** new detector; does NOT modify any AGENTS.md rule text.
**Defaults applied:** none of the three orchestrator defaults affect this
feature.

#### Requirement: REQ-QG-MSITES-1 — A PR introducing more than N mutation sites per file fails pre-push

The system MUST add `scripts/check_mutation_sites.py` (mirrors the
shape of `scripts/check_module_size.py`) that counts mutation sites per
file using AST analysis (function bodies, class bodies, top-level
statements) and fails when ANY single file in `app/` or `migration/`
exceeds a recorded baseline in `BASELINE_MUTATION_SITES`. The detector
MUST operate as a pre-push hook and as a step in the CI `lint` job.

**Rationale:** mutation-sites count is a cheap proxy for testability
density: a file with too many branches is hard to mutate well and is
the strongest signal that the file should be split. Catching it
**before** mutation runs saves the 5-30 minute cosmic-ray run on
unmistakable trouble.

**Scenarios:**

- **SCN-QG-MSITES-1-1** — Given the merge commit of PR #1 with baseline
  measurements recorded, WHEN the detector runs on that tree, THEN it
  SHALL print `OK` and exit 0.

- **SCN-QG-MSITES-1-2** — Given a PR whose single-file mutation-site
  count exceeds `BASELINE_MUTATION_SITES`, WHEN the detector runs, THEN
  it SHALL exit non-zero with a message naming the file and the excess
  count, AND SHALL print a hint pointing to the module-size ratchet
  (Feature 1's sibling detector).

- **SCN-QG-MSITES-1-3** — Given a PR that lowers a file's mutation-site
  count below its baseline entry, WHEN the detector runs, THEN it
  SHALL print a `NOTE` reminding the operator to lower the baseline.

**Verification:** pinned by `tests/test_check_mutation_sites.py`; CI
lint-job step pinned by
`tests/test_ci_workflow.py::test_ci_workflow_lint_job_runs_mutation_sites_gate`.

**Failure mode:** block (exit 1) from PR #2 onwards; `mode=warn` for
PR #1 (mirrors Features 1 and 4).

**Baseline behavior:** shrink-only ratchet. Same shape as
`BASELINE` in `scripts/check_module_size.py`.

#### Out of scope for Feature 5

- Per-function mutation-site breakdowns (only the per-file total is
  gated; finer detail is informational in stdout).
- Cross-file mutation-site sum gating (file-level is the unit).
- Replacing AST counting with a `mutmut`-based actual scan (the
  detector is cheap-by-construction; a real scan would duplicate
  Feature 2).

---

### Bonus A: Adapter exclusion from coverage floor

**Source:** Proposal §3 Bonus A / Observation #24073 (Source analysis
"Bonuses")
**Modifies:** `pyproject.toml [tool.coverage.run]` + `.github/workflows/ci.yml`
test job; does NOT change `fail_under` and does NOT touch any AGENTS.md
rule text.
**Defaults applied:** none.

#### Requirement: REQ-QG-ADAPT-1 — `app/core/insforge.py` is excluded from the coverage floor without lowering the floor

The system MUST add `app/core/insforge.py` to the `omit` list under
`[tool.coverage.run]` in `pyproject.toml`. The `fail_under` value under
`[tool.coverage.report]` SHALL remain unchanged (currently 85, per the
combined `app` + `migration` measurement). The `--cov-fail-under=85`
flag in `.github/workflows/ci.yml`'s `test` job SHALL remain unchanged.
The `scripts/pytest_plugin/coverage_gate.py` plugin SHALL continue to
enforce 100% line coverage on `CRITICAL_HELPERS` (§11) — Bonus A does
NOT weaken that gate, it only removes one transport-layer file from the
global percentage.

**Rationale:** `app/core/insforge.py` is the transport-layer adapter to
InsForge. Per §33.4 and §18.4, it is the only place allowed to talk
to InsForge. Per the legacy-vs-web exclusion principle, an adapter is
exactly the kind of module that should not count toward the production-
logic floor — its tests run under `httpx.MockTransport` and contribute
to branch coverage without exercising real product semantics.

**Scenarios:**

- **SCN-QG-ADAPT-1-1** — Given a fresh `pytest --cov=app --cov=migration
  --cov-report=json` run on `main`, WHEN `coverage.json` is parsed, THEN
  the file entry for `app/core/insforge.py` SHALL appear with
  `summary.excluded = true` (or equivalent marker under the omit list).

- **SCN-QG-ADAPT-1-2** — Given the same run, WHEN the `--cov-fail-under=85`
  flag is enforced, THEN the global floor SHALL be 85 (not the
  pre-exclusion value) AND the post-exclusion measured percentage SHALL
  remain at or above 85.

- **SCN-QG-ADAPT-1-3** — Given `app/core/insforge.py` removed from the
  omit list, WHEN the test job runs, THEN the global coverage
  percentage SHALL drop by some measurable amount AND `fail_under` SHALL
  fail — proving the exclusion is load-bearing for the global number.

**Verification:** pinned by
`tests/test_ci_workflow.py::test_ci_workflow_test_job_enforces_global_coverage_floor`
(which reads `fail_under` from `pyproject.toml` and asserts the CI flag
matches); plus a new assertion in the same test class that the omit
list contains the adapter path.

**Failure mode:** block (exit 1) when the floor is breached, same as
today; the exclusion is a measurement change, not a floor relaxation.

**Baseline behavior:** N/A — this is a measurement-config change, not
a gate-introducing change.

#### Out of scope for Bonus A

- Excluding `migration/` from the coverage floor — migration code is
  exercised by the integration job (§18.4), not the unit-test job; the
  current measurement already covers it correctly.
- Lowering `fail_under` to compensate — explicitly forbidden by §19.
- Excluding other transport files (`app/core/csrf.py`, etc.) — those
  are security-sensitive and must stay in the measurement.

---

### Bonus B: "QA-through-UI only" crystallised in AGENTS.md §23

**Source:** Proposal §3 Bonus B / Observation #24073 (Source analysis
"Bonuses")
**Modifies:** AGENTS.md §23 only.
**Defaults applied:** none.

#### Requirement: REQ-QG-QAUI-1 — AGENTS.md §23 explicitly states QA is verified through the UI only

The system MUST edit AGENTS.md §23 to add an unambiguous sentence that
states: verification of any UI-facing feature slice MUST go through
the existing Playwright E2E suite under `tests/e2e/` (or an equivalent
in-tree browser test); QA via the Python shell, direct DB inspection, or
`curl` against a running server is NOT a substitute. The edit SHALL
follow the feature-branch + PR flow required by §17.3 (orchestrator does
not edit AGENTS.md inline). The edit SHALL preserve every other part of
§23 and SHALL NOT change the existing exemption for backend-only slices.

**Rationale:** §23 already requires E2E for UI feature slices, but the
"QA-through-UI only" discipline is implicit. Crystallising it in the
rule text closes the audit-2026-07-25 §32.P1 perimeter gap — the
project has hardening for internal mechanisms (CSRF, PII redaction,
session lifecycle) but no explicit boundary-layer QA rule.

**Scenarios:**

- **SCN-QG-QAUI-1-1** — Given the post-edit AGENTS.md §23, WHEN the rule
  text is read, THEN it SHALL contain the literal substring
  `QA-through-UI only` OR an unambiguous paraphrase that names
  Playwright + `tests/e2e/` as the verification path AND names shell/
  curl/DB-inspection as non-substitutes.

- **SCN-QG-QAUI-1-2** — Given a PR that introduces a new UI feature
  slice WITHOUT a `tests/e2e/` flow, WHEN the PR review applies §23, THEN
  the reviewer SHALL block the PR with a comment citing the new
  sentence in §23.

**Verification:** PR-level only — there is no CI gate for prose
content. `tests/test_agents_md_section_23.py` (new test) asserts the
literal phrase is present in §23 so a future edit cannot silently drop
it. Per §17.3 the orchestrator delegates this change to a subagent.

**Failure mode:** review-only (no CI block). The change goes through
the §17.3 feature-branch flow.

**Baseline behavior:** N/A — this is a rule-text clarification, not a
new gate.

#### Out of scope for Bonus B

- Adding new E2E flows to `tests/e2e/` for existing features — Bonus B
  crystallises the rule; filling the E2E gap is a separate change.
- Renumbering or restructuring §23.
- Modifying any other section of AGENTS.md.

---

### Feature 8: Advisory git hooks (pre-commit + pre-push)

**Source:** Proposal §3 "Hooks" row / Observation #24073 (Source
analysis "Git hooks")
**Modifies:** `git-hooks/` directory (per §15.5; user OK granted this
session).
**Defaults applied:** none of the three orchestrator defaults affect
this feature, but the ADVISORY semantics below encode the proposal's
guidance that hooks must never block a push.

#### Requirement: REQ-QG-HOOK-1 — Pre-commit hook runs CRAP, jscpd, and mutation-sites checks on staged files, advisory only

The system MUST add a pre-commit hook under `git-hooks/pre-commit` (or
the existing equivalent path the project uses) that invokes the CRAP,
jscpd, and mutation-sites detectors (Features 1, 4, 5) on the set of
staged files only, MUST complete in under 5 seconds on the current
tree, and MUST exit 0 even when findings exist. Findings SHALL be
printed to stdout in a clearly-labelled `ADVISORY` block before the
exit-0.

**Rationale:** §15.5 forbids hooks that block by default — pre-commit
hooks that fail force the developer to bypass with `--no-verify`, which
silently trains the team to skip gates. The advisory-only contract
preserves the signal without the bypass-pressure.

**Scenarios:**

- **SCN-QG-HOOK-1-1** — Given staged Python files, WHEN the pre-commit
  hook runs, THEN it SHALL invoke CRAP, jscpd, and mutation-sites
  detectors against the staged set AND SHALL exit 0 regardless of
  findings.

- **SCN-QG-HOOK-1-2** — Given the hook invocation above, WHEN any
  detector reports a finding, THEN the output SHALL contain the literal
  `ADVISORY` token AND SHALL name the offending file and detector.

#### Requirement: REQ-QG-HOOK-2 — Pre-push hook runs a fast mutation scan on the diff, advisory only

The system MUST add a pre-push hook under `git-hooks/pre-push` that
runs `mutmut scan` (or the equivalent mutation-tool scan mode) on the
diff between the current branch tip and the upstream tip. The hook
MUST complete in under 30 seconds, MUST exit 0 regardless of findings,
and MUST print ADVISORY output as in REQ-QG-HOOK-1.

**Rationale:** same rationale as REQ-QG-HOOK-1. The pre-push hook is
where developers have already invested 30 seconds+ of context; asking
for a fast mutation signal there pays the highest dividend.

**Scenarios:**

- **SCN-QG-HOOK-2-1** — Given a push to a branch, WHEN the pre-push
  hook runs, THEN it SHALL complete in under 30 seconds on the current
  tree AND SHALL exit 0.

#### Requirement: REQ-QG-HOOK-3 — Hooks are independent of CI gate status

The system MUST NOT couple hook exit status to CI gate status. If a
developer bypasses a hook with `--no-verify`, the CI lint job SHALL
still run the same detectors independently. Hooks are a developer-
experience signal; CI is the release gate. This encodes §32.P7
explicitly: the hooks and the CI gate are two guards that cover the
same surface, neither cancels the other.

**Rationale:** §32.P7 forbids guards that cancel themselves. A hook
that exits non-zero on a push would be cancelled by `--no-verify`; a
CI step that depends on the hook would be cancelled by GitHub-hosted
runners that do not run hooks at all (per the §15.3 staging-only
pre-push contract). Independence is the only design that survives both
cancellation paths.

**Scenarios:**

- **SCN-QG-HOOK-3-1** — Given a commit pushed with `--no-verify` to
  skip the pre-commit hook, WHEN the CI `lint` job runs, THEN the CRAP,
  jscpd, and mutation-sites detectors SHALL run as independent CI steps
  AND SHALL fail the build per their respective `mode=block` policy.

#### Out of scope for Feature 8

- `core.hooksPath` setting in `.git/config` — the hook files land in
  `git-hooks/` but installation is the operator's choice (per §15.5,
  `git-hooks/` touches are user-OK-gated).
- Blocking pre-commit hooks (`--no-verify` MUST always be available).
- Pre-receive or post-receive hooks — pre-commit + pre-push are the
  scope.

---

## Cross-cutting requirements

These requirements govern HOW the eight features above are wired into
the project. They are not separate features; they encode the project's
"every detector ships with three things" contract from §32.P3.

#### Requirement: REQ-QG-XCUT-1 — Every new detector ships with script + CI step + pinning test

For each of Features 1, 4, and 5 (the three new AST/line-based
detectors), the change MUST ship:

1. The detector script under `scripts/check_<name>.py`, stdlib-only
   where possible, exit-code-1-on-violation.
2. A new step in `.github/workflows/ci.yml` `lint` job that invokes the
   script after the existing module-size and route-size ratchets (in
   that order).
3. A pinning test under `tests/test_check_<name>.py` AND a CI-workflow
   pin in `tests/test_ci_workflow.py` whose name matches the pattern
   `test_ci_workflow_lint_job_runs_<name>_gate` (mirrors the existing
   `test_ci_workflow_lint_job_runs_module_size_gate` contract).

This encodes §32.P3: a rule whose only enforcement is "PR review" does
not change behaviour.

#### Requirement: REQ-QG-XCUT-2 — New dev dependencies are verified via context7 per §8

For each new dev dependency introduced by Features 1, 2, 3, 4
(`radon`, `xenon`, `cosmic-ray`, `hypothesis`, `jscpd`), the change MUST
verify the pinned floor via the `context7` MCP before the version is
written to `pyproject.toml [project.optional-dependencies].dev`. The
PR body MUST cite the context7 query and the current-stable line that
backed the pin (mirrors the psutil pin in §8).

#### Requirement: REQ-QG-XCUT-3 — Mutation manifest is updated only via explicit PR

The `docs/quality/mutation-baseline.json` manifest MUST be updated ONLY
by a human-driven PR (the "lock the improvement" workflow from
REQ-QG-MUT-2). The nightly CI job MUST NOT commit to the manifest. This
encodes §17.1 (orchestrator coordinates, humans decide policy) and
prevents the auto-update loop where CI silently accepts regressions.

---

## Out of scope (overall)

- **Gherkin/BDD, Speclj, AI-judgment architectural reviews** — already
  covered or non-applicable (proposal §3).
- **Replacing or relaxing** any existing gate (§19, §20, §21, §24,
  §25–§28) — proposal §3 + §6 row 2.
- **Any business-domain change** — no routes, services, slices, or
  templates touched (proposal §3).
- **Editing `git-hooks/` outside the explicit user-granted scope this
  session** — proposal §3 + §15.5.
- **Refactoring the duplication tracked by issue #227** — separate
  change (proposal §7 question 2 context).
- **Switching cosmic-ray for mutmut** — orchestrator default is cosmic-ray;
  switching is a future decision.
- **Per-PR mutation runs** — nightly only by orchestrator decision
  (proposal §4 PR #2 description).
- **Stateful hypothesis property tests** — overkill for the row-to-model
  helpers (Feature 3 out-of-scope).
- **Per-function CRAP / mutation-site breakdowns** — file-level only.

---

## Risks surfaced (and NOT silently resolved by switching defaults)

These risks come from the orchestrator's three resolved defaults. If
`sdd-design` discovers evidence any of them is wrong, surface the
evidence in the design artifact and request a user decision — do not
silently switch.

1. **`cosmic-ray` over `mutmut`** — cosmic-ray has the differential
   manifest built in; mutmut would require a custom baseline wrapper
   (per observation #24073 §1). If the cosmic-ray setup cost exceeds
   1 engineer-day in PR #2, mutmut becomes a candidate.
2. **`jscpd` initial threshold = 15%** — risks masking real business-
   module duplication until issue #227 lands. Mitigated by the
   shrink-only baseline ratchet (a future PR can lower it).
3. **Hypothesis CI profile = `dev`** — fast but with fewer examples.
   If property tests prove flaky in CI without seeded
   `pytest-randomly`, switch to `ci` (slower, with shrinking).
4. **§32.P7 interaction** — hooks are advisory AND new CI jobs are
   independent. Explicitly encoded in REQ-QG-HOOK-3.
5. **§32.P8 per-layer gap** — every new detector measures a single
   dimension. Future PRs SHOULD add per-layer distribution reports so
   the aggregate does not hide layer-specific gaps.
6. **§8 dependency drift** — `cosmic-ray`/`hypothesis`/`radon`/`xenon`/
   `jscpd` floors must be verified via context7 at PR-creation time,
   not at spec-time (REQs encode this as REQ-QG-XCUT-2).
