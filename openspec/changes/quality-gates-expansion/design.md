# Design: Quality Gates Expansion

## Technical Approach

Add five deterministic quality gates plus two refinements to APAP_WEB's CI/dev
loop. Every new gate ships with a shrink-only baseline (the project-wide
"ratchet" pattern from §21/§25/§28) so the first PR lands on a green tree.
Three chained PRs separate the work into reviewable units.

The technical seam is the existing scripts/* family (`check_module_size.py`,
`check_complexity.py`, `check_route_size.py`, etc.). Each new detector
follows the same shape: a stdlib-only script (or one tightly-scoped extra
dep), a ratchet-shaped baseline dict, a CI step in the `lint` job, and a
pinning test in `tests/`. Mutation testing breaks the stdlib-only pattern
(cosmic-ray is a separate job on a weekly schedule) but keeps the
"ratchet + gate + pin" trio from §32.P3.

Refs: proposal `openspec/changes/quality-gates-expansion/proposal.md`
(Engram `#24074`); spec `openspec/changes/quality-gates-expansion/spec.md`
(Engram `#24075`); source observation `#24073`.

---

## Architecture Decisions

### Decision: CRAP computed by a Python wrapper, not by `radon` or `xenon`

**Choice**: Implement `scripts/check_crap.py` that uses `radon.complexity`
and `radon.raw` as a library to compute per-function CC, then combines
with `coverage.json` to compute CRAP per function
(`CRAP = CC^2 * (1 - cov/100)^3 + CC`). The script enforces grade A
(CRAP < 6) on every function under `app/` + `migration/`.

**Alternatives considered**:
- `xenon --max-absolute=B` only checks CC bands, not CRAP; rejected
  because REQ-QG-CRAP-1 names the CRAP metric specifically.
- A pure-stdlib AST walker was considered (mirroring
  `scripts/check_complexity.py`); rejected because CRAP requires both
  CC and coverage data, and radon already implements CC correctly
  with proper Python grammar coverage.

**Rationale**: radon is a stable, pip-installable library (last release
2023-03-26, status 5-Production/Stable per PyPI). The "ratchet + gate +
pin" pattern is identical to §21. The CRAP formula is a one-liner; the
script is mostly glue around radon's AST walker plus a coverage.json
parser. Context7 query: `/rubik/radon` "radon raw command CRAP score
coverage integration json output" — confirmed `radon cc --json` shape
and `radon.raw.analyze` API.

### Decision: jscpd replaced by a stdlib-only Python AST duplicate detector

**Choice**: `scripts/check_jscpd.py` does NOT invoke the `jscpd`
binary. It is a stdlib-only AST walker that computes a
"duplicate-percentage" metric: for every function under `app/` +
`migration/` + `scripts/`, normalise the AST (strip identifier names,
fold whitespace) and cluster functions whose normalised ASTs are
identical (Type-1/2 clones). Report a project-wide percentage
`(duplicate_lines / total_lines) * 100` and fail when it exceeds
`BASELINE_JSCPD_PCT`.

**Alternatives considered**:
- `pip install jscpd` — REJECTED. jscpd is a Node.js / Rust tool; it
  is NOT pip-installable. Context7 query `/kucherenko/jscpd` install
  section returned only `npm install -g jscpd@5`, `cargo install
  jscpd`, and `brew install jscpd`. Pulling Node.js into the CI
  Python venv violates §33 (clean dependency graph).
- `polydup` / `pychase` / `duplifinder` / `dry4python` (Python
  alternative copy-paste detectors, all released in 2025-2026) —
  REJECTED. None has a stable 1.0 release; pinning to any violates §8
  ("verify current state via context7 before pinning"). Status flags
  are Alpha/Beta across the board.
- Implement under a different name (`check_duplicate_code.py`) —
  REJECTED. The spec (REQ-QG-DRY-1) and proposal (§3 row 4) both
  name `jscpd`; renaming the script after the spec is approved is a
  violation of §17.1. Keeping the script name preserves the
  requirement ID and the orchestrator's intent (formal DRY
  detection with a 15% baseline).

**Rationale**: stdlib-only matches `check_module_size.py` exactly
(mirroring the spec REQ-QG-DRY-1 contract). The metric is "duplicate
lines as % of total lines" — the project wants to track copy-paste
between functions, not token-level similarity in arbitrary text. An
AST-level detector catches Type-1/2 clones (the bulk of issue #227's
known offenders). Type-3 (gap-tolerant) is out of scope for this PR.

RISK surfaced: the script is named `check_jscpd.py` per the spec, but
does not invoke `jscpd`. Reviewers and future contributors may
misunderstand the toolchain. Documented in §10 RISK-8.

### Decision: cosmic-ray over mutmut for the differential manifest pattern

**Choice**: cosmic-ray. Matches the spec default. The differential
manifest pattern is implemented by writing two `cosmic-ray` session
SQLite files (`baseline.sqlite` from the merge commit of PR #2, and
`current.sqlite` from the nightly job) and comparing them
programmatically: extract the `(module_path, function_name, mutant_id,
survived: bool)` set from each via the `cr-report --json` output,
then assert `current_survived <= baseline_survived`.

**Alternatives considered**:
- `mutmut` — REJECTED. mutmut has no built-in differential manifest;
  REQ-QG-HOOK-2 also names `mutmut scan` which does not exist in
  mutmut's CLI (`run`, `results`, `show`, `browse`, `apply`,
  `trampoline` are the documented subcommands per context7 query
  `/websites/mutmut_readthedocs_io_en`). A custom wrapper would have
  to reimplement what cosmic-ray gives for free.

**Rationale**: cosmic-ray's session file is a documented SQLite
schema (per `/websites/cosmic-ray_readthedocs_io` "cr-report"
section); comparing two files is a deterministic diff of the
`mutations` table. The nightly job's "block on regression, succeed
on improvement" semantics is a pure diff against the baseline —
both behaviours are assertions over the diff, not over absolute
counts.

### Decision: hypothesis custom profile named `dev` (matches spec)

**Choice**: Register a custom hypothesis profile named `dev` in
`tests/property/conftest.py` with `max_examples=50`,
`derandomize=False` (fast, non-shrinking). The standard pytest run
loads it via `settings.load_profile("dev")`. CI's `GITHUB_ACTIONS`
env var would normally auto-load the built-in `ci` profile per
hypothesis's `is_in_ci()` detection; we override by explicitly
loading `dev` (per the spec default).

**Alternatives considered**:
- Built-in `ci` profile — REJECTED by spec default.
  `derandomize=True` + `print_blob=True` is better for catching
  bugs but slower; property tests here are *supplements* to the
  atomic suite, not the primary verification, per REQ-QG-PROP-1's
  rationale.

**Rationale**: hypothesis's built-in CI auto-detection would
silently switch to `ci` and contradict the spec. The profile is
registered before `load_profile` so a developer running pytest
locally sees the same behaviour as CI. Source:
context7 query `/hypothesisworks/hypothesis` "Load profiles via
environment variables" + "Built-in CI profile and CI detection".

### Decision: Property tests run inside the standard test job, not a separate CI job

**Choice**: `tests/property/` is added to pytest's discovery path.
The standard `test` job (already runs the full pytest with coverage)
collects and runs the property tests. A separate property job is
NOT created.

**Rationale**: REQ-QG-PROP-1 scenario SCN-QG-PROP-1-2 says the
property tests must be skipped with a documented reason when
hypothesis is not installed, not silently dropped. A separate job
would break that contract: a CI failure in the property job would
not block the test job (and vice versa), and a missing `hypothesis`
import in one job would be silently passed-through while the other
job crashes.

### Decision: Mutation-sites count uses a stdlib AST walker, not a real mutation scan

**Choice**: `scripts/check_mutation_sites.py` counts AST nodes that
are mutation targets (BinOp, BoolOp, Compare, If, While, Assert,
Raise, Return, Assign with arithmetic, function-call arguments,
string/number literals). Per-file count is compared to
`BASELINE_MUTATION_SITES`. This is a static proxy, not a real
mutation scan.

**Rationale**: REQ-QG-MSITES-1 is explicit — the metric is
"mutation sites per file", not "actual mutants produced by cosmic-
ray". The cosmic-ray run (Feature 2) is the real mutation signal;
this detector is a cheap pre-PR smoke that catches files with so
many branches that a mutation scan would be pointless to even
start.

---

## Data Flow

```
                 PR opens on feat/quality-gates-foundations
                                 |
                                 v
    +-------------------------- CI lint job --------------------------+
    |                                                                 |
    |  ruff check .                                                   |
    |  scripts/check_rules.py .                  # APAP001/APAP003     |
    |  scripts/check_module_size.py             # §21 (existing)      |
    |  scripts/check_route_size.py              # §28 (existing)      |
    |  scripts/check_docstring_coverage.py      # issue #339          |
    |  scripts/check_complexity.py              # §21 (existing)      |
    |  scripts/check_ruff_ratchet.py            # issue #380          |
    |  scripts/check_vulture_guard.py           # issues #392, #424   |
    |                                                                 |
    |  +-- NEW in PR #1 ------------------------------------------+   |
    |  | scripts/check_crap.py               # REQ-QG-CRAP-1     |   |
    |  | scripts/check_jscpd.py              # REQ-QG-DRY-1       |   |
    |  | scripts/check_mutation_sites.py     # REQ-QG-MSITES-1   |   |
    |  +---------------------------------------------------------+   |
    |                                                                 |
    +-----------------------------------------------------------------+
                                 |
                                 v
                  Coverage measurement (test job)
                                 |
                                 v
                      coverage.json produced
                                 |
                                 v
            scripts/pytest_plugin/coverage_gate.py
                                 |
                                 v
            CRITICAL_HELPERS 100% gate (§11) — UNCHANGED

            PR #2 (mutation job, weekly schedule only):
              cosmic-ray init -- test-pr.toml session.sqlite
              cosmic-ray exec  -- test-pr.toml session.sqlite
              diff surviving mutants vs docs/quality/mutation-baseline.json

            PR #3 (test job, standard pytest):
              tests/property/test_row_to_*.py  (@given(...) strategies)
```

---

## File Changes

### New files (PR #1 — Foundations)

| File | Action | Description |
|------|--------|-------------|
| `scripts/check_crap.py` | Create | Stdlib + radon. Reads `coverage.json`, computes CRAP per function, fails on grade >= B. Ratchet-shaped `BASELINE_CRAP`. Mirrors `scripts/check_module_size.py`. |
| `scripts/check_jscpd.py` | Create | Stdlib-only AST normaliser + duplicate detector. Reports project-wide duplicate percentage. Shrink-only `BASELINE_JSCPD_PCT`. Mirrors `scripts/check_module_size.py`. |
| `scripts/check_mutation_sites.py` | Create | Stdlib-only AST node counter per file. `BASELINE_MUTATION_SITES` ratchet. Mirrors `scripts/check_module_size.py`. |
| `tests/test_check_crap.py` | Create | Mirrors `tests/test_module_size.py`. Includes `test_ci_workflow_lint_job_runs_crap_gate`. |
| `tests/test_check_jscpd.py` | Create | Mirrors `tests/test_module_size.py`. Includes `test_ci_workflow_lint_job_runs_jscpd_gate`. |
| `tests/test_check_mutation_sites.py` | Create | Mirrors `tests/test_module_size.py`. Includes `test_ci_workflow_lint_job_runs_mutation_sites_gate`. |
| `tests/test_agents_md_section_23.py` | Create | Asserts §23 contains the literal phrase `QA-through-UI only`. Per REQ-QG-QAUI-1 verification. |
| `git-hooks/pre-commit` | Create | Advisory-only shell script. Runs the three PR #1 detectors on staged files. Exit 0 always. (Per §15.5 user-OK-gated.) |
| `git-hooks/pre-push` | Create | Advisory-only shell script. Runs cosmic-ray-style scan on diff. Exit 0 always. Wired in PR #2. |
| `git-hooks/README.md` | Create | Operator-facing instructions: `git config core.hooksPath git-hooks/`. |

### New files (PR #2 — Mutation real)

| File | Action | Description |
|------|--------|-------------|
| `docs/quality/mutation-baseline.json` | Create | Checked-in cosmic-ray manifest. Captured once by the operator on the merge commit of PR #2. Format: `{ total, killed, survived, skipped, percentage_killed, mutants: [{module, function, mutant_id, survived}] }`. |
| `docs/quality/cosmic-ray.toml` | Create | cosmic-ray config: `module-path = "app"`, `excluded-modules = [...]`, `test-command = "python -m pytest -x -q"`. |
| `scripts/diff_cosmic_ray.py` | Create | Stdlib-only. Reads `cr-report --json` output, computes the diff between current session and baseline manifest, exits 0/1 on improvement/regression. |
| `tests/test_diff_cosmic_ray.py` | Create | Unit tests for the diff logic + a CI-workflow pin. |

### New files (PR #3 — Property tests)

| File | Action | Description |
|------|--------|-------------|
| `tests/property/__init__.py` | Create | Empty (pytest discovery). |
| `tests/property/conftest.py` | Create | Hypothesis profile registration (`dev`), plus the `pytest_collection_modifyitems` skip-if-hypothesis-missing hook per REQ-QG-PROP-1 SCN-QG-PROP-1-2. |
| `tests/property/test_row_to_animal.py` | Create | Property tests for `_row_to_animal` (animals/service.py:211). |
| `tests/property/test_row_to_voluntario.py` | Create | Property tests for `_row_to_voluntario` (voluntarios/service.py:105). |
| `tests/property/test_row_to_acogida.py` | Create | Property tests for `_row_to_acogida` (acogidas/service.py:121). |
| `tests/property/test_row_to_entrada.py` | Create | Property tests for `_row_to_entrada` (entradas/service.py:117). |
| `tests/property/test_row_to_adopcion.py` | Create | Property tests for `_row_to_adopcion` (adopciones/service.py:158). |
| `tests/test_property_test_collection.py` | Create | Pin for REQ-QG-PROP-1 SCN-QG-PROP-1-1 + SCN-QG-PROP-1-2. |

### Modified files

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add radon, xenon, cosmic-ray, hypothesis, mutmut to `[project.optional-dependencies].dev`. Add `app/core/local_backend.py` to `[tool.coverage.run].omit`. |
| `.github/workflows/ci.yml` | Modify | PR #1: add 2 new steps in `lint` job (jscpd, mutation-sites — they don't depend on `coverage.json`) and 1 new step in `test` job (CRAP — must run AFTER pytest-cov writes `coverage.json`). PR #2: add new `mutation` job (weekly schedule + workflow_dispatch). PR #3: no CI change (property tests run in existing `test` job). |
| `AGENTS.md` | Modify | PR #1: add the §23 QA-through-UI sentence via the feature-branch + PR flow (§17.3). The orchestrator does NOT edit inline. |
| `openspec/config.yaml` | NO change recommended | Drift flag (RISK-1) — see §10. |

---

## Interfaces / Contracts

### CRAP computation (scripts/check_crap.py)

```python
# Public surface — mirrors scripts/check_module_size.py exactly
MAX_CRAP_GRADE: str = "A"     # strictest; CRAP < 6
SCAN_DIRS: tuple[str, ...] = ("app", "migration")
BASELINE_CRAP: dict[str, float] = {
    # "<path>::<qualname>" -> CRAP score measured on the merge commit
    # of PR #1. Shrink-only ratchet.
    "app/main.py::create_app": 1.0,
    # ...measured per-Function at PR #1 capture time, ~200-400 entries
}

def check_tree(root: Path, *, baseline: Mapping | None = None) -> tuple[list[str], list[str]]:
    """Returns (violations, notices). Stdlib + radon only."""

def main(argv: list[str] | None = None) -> int:
    """Exit 0 on clean, 1 on violation. Notes to stdout regardless."""
```

CRAP formula per function:

```
crap(cc, uncovered_lines, total_lines) =
    cc**2 * (1 - (total_lines - uncovered_lines) / total_lines) ** 3
    + cc
```

Grade mapping (matches radon's CC bands):

| CRAP | Grade |
|------|-------|
| < 6  | A     |
| < 11 | B     |
| < 21 | C     |
| < 31 | D     |
| < 41 | E     |
| >=41 | F     |

### jscpd duplicate detector (scripts/check_jscpd.py)

```python
# Public surface — stdlib only
BASELINE_JSCPD_PCT: float = 15.0   # shrink-only; matches orchestrator default
SCAN_DIRS: tuple[str, ...] = ("app", "migration", "scripts")
MIN_CLONE_TOKENS: int = 50         # don't report sub-50-token matches

def check_tree(root: Path, *, baseline_pct: float = BASELINE_JSCPD_PCT) -> tuple[list[str], list[str]]:
    """Returns (violations, notices). Stdlib only."""

def main(argv: list[str] | None = None) -> int:
    """Exit 0 on clean, 1 on violation. Stdout prints OK/FAIL/NOTE lines."""
```

### Mutation-sites counter (scripts/check_mutation_sites.py)

```python
# Public surface — stdlib only
MAX_MUTATION_SITES_PER_FILE: int = 250   # rough ceiling; baseline is per-file
SCAN_DIRS: tuple[str, ...] = ("app", "migration")
BASELINE_MUTATION_SITES: dict[str, int] = {
    # "<path>" -> site count measured on the merge commit of PR #1
    "app/modules/animals/service.py": 487,
    # ...measured at PR #1 capture time
}
```

Site definition: every AST node that a mutation operator could target
(`BinOp`, `BoolOp`, `Compare`, `If`, `While`, `Assert`, `Raise`,
`Return`, `Assign` with arithmetic right-hand side, `arg` in a
function call, numeric/str/bool literal). The exact node set is
documented in the script's module docstring.

### Mutation baseline manifest (docs/quality/mutation-baseline.json)

```json
{
  "captured_at": "2026-MM-DDTHH:MM:SSZ",
  "captured_on_commit": "<sha>",
  "python_version": "3.11.x",
  "module_path": "app",
  "summary": {
    "total": 0,
    "killed": 0,
    "survived": 0,
    "skipped": 0,
    "percentage_killed": 0.0
  },
  "mutants": [
    {"module": "app.modules.animals.service", "function": "_row_to_animal",
     "mutant_id": "CR-x", "operator": "ReplaceBinaryOperator",
     "line": 215, "survived": true},
    "..."
  ]
}
```

The manifest is checked into the repo, regenerated only by a
human-driven PR (REQ-QG-XCUT-3). CI does NOT mutate it.

### Property test conftest

```python
# tests/property/conftest.py — REQ-QG-PROP-1
import os
try:
    import hypothesis  # noqa: F401
    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    _HYPOTHESIS_AVAILABLE = False

if _HYPOTHESIS_AVAILABLE:
    from hypothesis import settings
    settings.register_profile(
        "dev", max_examples=50, derandomize=False, deadline=None
    )
    settings.load_profile("dev")
```

Collection-modifyitems hook skips when hypothesis is absent
(SCN-QG-PROP-1-2):

```python
def pytest_collection_modifyitems(config, items):
    if _HYPOTHESIS_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="hypothesis not installed (see REQ-QG-PROP-1)")
    for item in items:
        if "tests/property/" in str(item.fspath):
            item.add_marker(skip)
```

### Git hook contracts

Both hooks print an `ADVISORY` block on findings and exit 0
regardless. The exit-0 contract is enforced by a simple test in
`tests/test_git_hooks.py` (PR #2 addition).

---

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit | `scripts/check_crap.py` exit codes, baseline ratchet behaviour, malformed coverage.json | `tests/test_check_crap.py` — mirrors `tests/test_module_size.py`. `tmp_path` synth trees. |
| Unit | `scripts/check_jscpd.py` exit codes, baseline ratchet, MIN_CLONE_TOKENS threshold | `tests/test_check_jscpd.py` — mirrors `tests/test_module_size.py`. |
| Unit | `scripts/check_mutation_sites.py` exit codes, baseline ratchet, AST node selection | `tests/test_check_mutation_sites.py` — mirrors `tests/test_module_size.py`. |
| Unit | `scripts/diff_cosmic_ray.py` improvement/regression/identical cases | `tests/test_diff_cosmic_ray.py`. |
| Unit | Hypothesis property tests — model instantiation invariants | `tests/property/test_row_to_*.py`. Run via the standard pytest. |
| CI pin | Each new lint-job step is present in `ci.yml` | New tests in `tests/test_ci_workflow.py` and the dedicated `tests/test_check_<name>.py`. |
| E2E | (Not applicable — pure tooling change) | N/A per REQ-QG-XCUT-3 + AGENTS.md §23 exemption. |

### New tests in `tests/test_ci_workflow.py`

The spec already pins one: the test that asserts the omit list contains
`app/core/local_backend.py` (REQ-QG-ADAPT-1 verification). The new assertion
goes in the existing
`test_ci_workflow_test_job_enforces_global_coverage_floor`:

```python
def test_ci_workflow_test_job_excludes_local_backend_adapter():
    """REQ-QG-ADAPT-1: the adapter is omitted from coverage.json."""
    cfg = tomllib.loads(PROJECT_FILE.read_text())
    omit = cfg["tool"]["coverage"]["run"]["omit"]
    assert "app/core/local_backend.py" in omit, (
        "Bonus A requires app/core/local_backend.py in [tool.coverage.run].omit"
    )
```

Plus three new tests in `tests/test_check_<name>.py`
(`test_ci_workflow_lint_job_runs_crap_gate`,
`test_ci_workflow_lint_job_runs_jscpd_gate`,
`test_ci_workflow_lint_job_runs_mutation_sites_gate`) — all mirror
`tests/test_module_size.py::test_ci_workflow_lint_job_runs_module_size_gate`.

---

## Threat Matrix

N/A — no routing, shell commands (the hooks are advisory-only shell
that the user explicitly chose per §15.5 this session), subprocesses,
VCS/PR automation, executable-file classification, or process-
integration boundary. The `git-hooks/pre-push` runs `mutmut` (or
cosmic-ray) as a subprocess but is advisory-only (exit 0 always),
so it cannot block the push itself. The CI mutation job runs
cosmic-ray as a subprocess but inside the `lint`/`test` job's
self-hosted runner with the same Python venv; no privileged
boundary.

---

## Migration / Rollout

**Phase 1 (PR #1):** All three new detectors ship with
`mode=warn`-by-construction (empty `BASELINE_*` measured and recorded
in the same PR). The first run after merge sees baselines already
populated, so the build stays green. The `mode=warn` -> `mode=block`
flip happens in PR #1's follow-up commit (same PR) by switching the
script's default from "print + exit 0" to "print + exit 1 on
violation". This is the same pattern `check_module_size.py` already
uses (BASELINE matches measured tree in the PR that adds it).

**Phase 2 (PR #2):** cosmic-ray manifest is captured by the
operator as the last step of the PR #2 merge (manual command run
locally; output checked into `docs/quality/mutation-baseline.json`).
The CI mutation job is added in the same PR and validates
"regression-only" gating via `scripts/diff_cosmic_ray.py`.

**Phase 3 (PR #3):** Hypothesis property tests are added with the
custom `dev` profile. Standard pytest runs them. The collection
hook skips them when hypothesis is missing (REQ-QG-PROP-1 SCN-QG-
PROP-1-2).

**Rollback per PR** (independent):
- PR #1: `git revert <merge-sha>`. Removes the three lint steps
  and the omit-list change. CRITICAL_HELPERS 100% gate (rule 11)
  is untouched.
- PR #2: `git revert <merge-sha>` + `gh workflow disable mutation`.
  Removes the cosmic-ray job, manifest, and config.
- PR #3: `git revert <merge-sha>`. Removes `tests/property/` and
  the dev profile. The conftest hook is reversible in isolation.

---

## Open Questions

- [ ] **jscpd-as-name vs jscpd-as-tool** — RISK-8: the spec names
      `jscpd` but the binary is not pip-installable. The design
      implements an AST-based detector in a script named
      `scripts/check_jscpd.py`. User OK requested before PR #1
      merge if they prefer (a) rename the script to
      `check_duplicate_code.py`, or (b) install Node.js + npm in
      the CI Python venv to use the real jscpd binary.
- [ ] **CRAP baseline measurement time** — RISK-2: PR #1 must
      capture the baseline in the SAME commit that introduces the
      detector, or the build is red on first run. This is the
      same chicken-and-egg solved by `check_module_size.py`. The
      design encodes it; user should confirm the timing.
- [ ] **Cosmic-ray Python deps** — RISK-6: cosmic-ray transitively
      requires `pytest` and `tomli` (the latter via setuptools).
      Both are already in `[dev]`, so no conflict, but the
      `cosmic-ray==8.4.6` line is a hard floor because the API
      changes between majors.

---

## Reference: existing ratchet scripts mirrored

- `scripts/check_module_size.py` — module line count, BASELINE dict.
- `scripts/check_complexity.py` — CC per function, BASELINE_CC.
- `scripts/check_route_size.py` — route-handler line count, BASELINE.
- `scripts/check_ruff_ratchet.py` — ruff rule violation counts,
  BASELINE per-rule.
- `scripts/check_docstring_coverage.py` — BASELINE_COVERAGE_FLOOR.
- `scripts/check_vulture_guard.py` — three-stage AST filter.

Every new detector follows the same shape:

```
1. Module docstring explaining the rule, the source observation, and
   the citation back to AGENTS.md.
2. Stdlib-only (or single-dep) imports.
3. Constants: MAX_*, SCAN_DIRS, BASELINE_* (ratchet-shaped).
4. Pure functions for the checks; main() prints OK/FAIL/NOTE and
   returns int exit code.
5. if __name__ == "__main__": raise SystemExit(main()).
```

---

## Dependency footprint

All new dependencies go in `[project.optional-dependencies].dev`.
None ship in the production wheel (per `[tool.hatch.build.targets.wheel]
only-include = ["app"]`).

| Tool | Floor | Verified via context7 | Compatible w/ pytest 8 / py 3.11? | Notes |
|------|-------|------------------------|----------------------------------|-------|
| `radon` | `>=6.0` | `/rubik/radon` "Radon Python code complexity measurement..."; PyPI page lists 6.0.1 (2023-03-26) | Yes. Radon 6.0.1 supports Python 3.12. Status 5-Production/Stable. | Last release 2023; not deprecated; upstream has not EOL'd. |
| `xenon` | `>=0.9` | `/websites/xenon_readthedocs_io` "xenon is a monitoring tool based on radon"; PyPI lists 0.9.3 (2022-02-24) | Yes (Python 3.6-3.12 supported). Depends on `radon<7,>=4` — pin works with radon 6.0. | Last release 2022; the upstream is silent. Not deprecated. Pinned because nothing newer exists. |
| `cosmic-ray` | `>=8.4` | `/websites/cosmic-ray_readthedocs_io` "Cosmic Ray: mutation testing for Python 3"; PyPI lists 8.4.6 (Python 3.9+) | Yes (Python 3.9+ covers 3.11). MIT license. | Last release in 8.x line. Pins `tomli` (already a dev dep via other tools). |
| `hypothesis` | `>=6.150` | `/hypothesisworks/hypothesis` "Hypothesis property-based testing"; PyPI lists 6.165.x | Yes (Python 3.10+). MPL-2.0. | Pin floor at 6.150 to avoid pulling in pre-2026 APIs. |
| `mutmut` | `>=2.4` | `/boxed/mutmut` "Mutmut is a mutation testing tool"; PyPI current | Yes (Python 3.8+). BSD-3. | Used only for the pre-push hook diff scan (REQ-QG-HOOK-2). The nightly job uses cosmic-ray, not mutmut. |
| `jscpd` | NOT PINNED | `/kucherenko/jscpd` README — only Node.js/Rust installs. | N/A | Decision: see "Architecture Decisions" §jscpd. |

### Transitive dependency audit

- `radon` + `xenon` together: only one radon install (xenon
  depends on `radon<7,>=4`, satisfied by our `radon>=6.0`).
- `cosmic-ray`: requires `pytest` (no version pin documented, but
  the project uses pytest 8.0+; verified compatible per
  context7 query "compatibility").
- `hypothesis`: requires `attrs>=22.2.0` (already pinned implicitly
  via dev tooling).
- `mutmut`: zero relevant transitive deps.

---

## Baseline ratchet shapes

For each detector, the key shape is `dict[str, float]` (CRAP),
`dict[str, float]` (jscpd %), or `dict[str, int]` (mutation sites).
Justification per key choice:

- **CRAP**: `file::qualname` (matches the per-function identity).
  Better than `file::function_name` because it disambiguates
  methods on classes (e.g. `AnimalService.save` vs
  `FosterService.save`). Better than `file::function` with line
  number because the AST node ID is stable across refactors that
  move lines but preserve the function.

- **jscpd**: a single float `BASELINE_JSCPD_PCT` (not a per-file
  dict) because the gate is a project-wide aggregate. Mirrors
  `BASELINE_COVERAGE_FLOOR` in `scripts/check_docstring_coverage.py`.

- **mutation-sites**: `file` (path only) — the metric is too
  coarse to differentiate between functions; a single per-file
  counter is what REQ-QG-MSITES-1 asks for.

```python
# scripts/check_crap.py
BASELINE_CRAP: dict[str, float] = {
    # "<path>::<qualname>" -> CRAP score measured on the merge commit
    # of PR #1. Ratchet: shrink-only. Auto-discovered via radon cc --json
    # at PR #1 capture time (~200-400 entries for the current tree).
    "app/main.py::create_app": 1.0,
    "app/modules/animals/service.py::_row_to_animal": 2.0,
    # ...
}

# scripts/check_jscpd.py
BASELINE_JSCPD_PCT: float = 15.0   # measured at PR #1 capture time

# scripts/check_mutation_sites.py
BASELINE_MUTATION_SITES: dict[str, int] = {
    # "<path>" -> site count measured at PR #1 capture time
    "app/modules/animals/service.py": 487,
    "app/main.py": 95,
    # ...
}
```

Tests that pin baseline-measured-tree parity (mirroring
`tests/test_module_size.py::test_baseline_matches_measured_tree`)
live in each `tests/test_check_*.py`.

---

## CI workflow YAML

### PR #1 — CRAP step in `test` job, two new steps in `lint` job

`scripts/check_crap.py` reads `coverage.json`, which pytest-cov writes
inside the `test` job (after the `python -m pytest ... --cov-report=json`
invocation). The `lint` job has `no needs:` and runs first, with an
independent `actions/checkout@v5` — so a CRAP step in `lint` would
always find `coverage.json` from the LAST merge on `main`, not from the
PR head. The fix is to put CRAP in the `test` job, after pytest, so it
sees per-PR coverage and the gate stays meaningful (REQ-QG-CRAP-1's
"complexity + inverse coverage" rationale).

**Add to `lint` job (after the current last step, e.g. after
`check_vulture_guard.py`)** — 2 new steps:

```yaml
      - name: Run jscpd duplicate-code ratchet (issue quality-gates-expansion #4)
        # REQ-QG-DRY-1: project-wide duplicate-percentage <= 15%.
        # Stdlib-only AST detector (mirrors check_module_size.py shape);
        # see design.md §Architecture Decisions for rationale on not
        # using the jscpd binary directly.
        run: python scripts/check_jscpd.py

      - name: Run mutation-sites count ratchet (issue quality-gates-expansion #5)
        # REQ-QG-MSITES-1: per-file mutation-site count stays under the
        # shrink-only baseline. Cheap AST proxy that runs before cosmic-
        # ray catches files where mutation would be pointless.
        run: python scripts/check_mutation_sites.py
```

**Add to `test` job (after the existing
`python -m pytest ... --cov-report=json` step)** — 1 new step:

```yaml
      - name: Run CRAP score ratchet (issue quality-gates-expansion #1)
        # REQ-QG-CRAP-1: every function in app/ + migration/ stays at
        # CRAP grade A. Reads ./coverage.json written by the pytest
        # step above; this is why the step lives in the test job, not
        # in lint (which has no needs: and runs first). For PR #1,
        # runs in warn-only mode (baselines captured in this PR); the
        # block mode is the default from PR #1's follow-up commit
        # onward.
        run: python scripts/check_crap.py
```

Local fallback (developer runs `scripts/check_crap.py` without pytest
having been run first): the script MUST detect a missing or empty
`coverage.json` and exit 0 with a `NOTE: coverage.json missing —
CRAP check skipped (run pytest --cov first)` message. This keeps the
local pre-commit hook safe even when the developer hasn't generated
coverage yet. Pinned by a unit test
(`tests/test_check_crap.py::test_check_crap_skips_when_coverage_json_missing`).

### PR #2 — new `mutation` job

```yaml
  mutation:
    name: mutation
    # REQ-QG-MUT-2: weekly schedule + manual dispatch; NOT a release
    # gate (per AGENTS.md §15.1 + §32.P7). Same self-hosted runner
    # as lint/test — no GitHub Actions minutes consumed.
    if: >-
      github.event_name == 'schedule' ||
      github.event_name == 'workflow_dispatch'
    runs-on: [self-hosted, Linux, ARM64, apap, oracle]
    timeout-minutes: 60
    steps:
      - name: Check out repository
        uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version-file: pyproject.toml
          cache: pip

      - name: Install mutation testing extras
        run: python -m pip install -e ".[dev]"

      - name: Run cosmic-ray + diff against baseline manifest
        # REQ-QG-MUT-1 + REQ-QG-MUT-2. Cosmic-ray creates a session
        # SQLite under .cosmic-ray/, scripts/diff_cosmic_ray.py reads
        # the surviving-mutant set and compares against
        # docs/quality/mutation-baseline.json. Exits 0 on identical
        # or improvement, non-zero on regression. Improvement does NOT
        # update the manifest (REQ-QG-XCUT-3).
        run: |
          set -euo pipefail
          cosmic-ray init docs/quality/cosmic-ray.toml .cosmic-ray/session.sqlite
          cosmic-ray exec docs/quality/cosmic-ray.toml .cosmic-ray/session.sqlite
          cr-report --json .cosmic-ray/session.sqlite > .cosmic-ray/report.json
          python scripts/diff_cosmic_ray.py \
            --current .cosmic-ray/report.json \
            --baseline docs/quality/mutation-baseline.json

      - name: Upload mutation report artifact
        # 30-day retention so an operator can drill into a regression
        # without re-running the job.
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: cosmic-ray-report
          path: .cosmic-ray/
          retention-days: 30
```

### Schedule update

Update the existing top-level schedule block to add a Wednesday slot
(mutation runs on Wednesday; security-deep stays on Monday):

```yaml
  schedule:
    - cron: "17 6 * * 1"   # security-deep (Monday)
    - cron: "17 6 * * 3"   # mutation (Wednesday)
```

---

## Git hook scripts

### `git-hooks/pre-commit` (PR #1)

```bash
#!/usr/bin/env bash
# git-hooks/pre-commit — APAP_WEB advisory-only pre-commit.
#
# Per AGENTS.md §15.5, this hook MUST exit 0 regardless of findings.
# The CI lint job runs the same detectors independently (REQ-QG-HOOK-3)
# so bypassing this hook with --no-verify is safe; the gate does not
# depend on it.
#
# Installation: git config core.hooksPath git-hooks/
#
# Findings (if any) are printed in an ADVISORY block before the exit-0.

set -e

# Only run if we have staged Python files (cheap guard).
staged=$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.py$' || true)
if [ -z "$staged" ]; then
    exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "ADVISORY: running pre-commit quality gates (advisory only — exit 0 regardless)"

# Run the three lint-job detectors. Each exits 0/1; we ignore the
# exit code by design (§15.5 advisory contract).
findings=0
for detector in scripts/check_crap.py scripts/check_jscpd.py scripts/check_mutation_sites.py; do
    echo "--- $detector ---"
    if ! python "$detector"; then
        findings=$((findings + 1))
    fi
done

if [ "$findings" -gt 0 ]; then
    echo "ADVISORY: $findings detector(s) reported findings — review above and consider tightening before pushing."
fi

echo "ADVISORY: pre-commit checks complete (advisory only, commit allowed)."
exit 0
```

### `git-hooks/pre-push` (PR #2)

```bash
#!/usr/bin/env bash
# git-hooks/pre-push — APAP_WEB advisory-only pre-push.
#
# Runs a fast mutation scan on the diff between the current branch
# tip and the upstream tip. Per REQ-QG-HOOK-2, MUST complete in under
# 30 seconds and MUST exit 0 regardless of findings. §32.P7 forbids
# guards that cancel themselves; the CI mutation job (nightly) is
# the real signal.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "ADVISORY: running pre-push mutation scan (advisory only — exit 0 regardless)"

# Identify changed files vs upstream.
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "")
if [ -z "$upstream" ]; then
    echo "ADVISORY: no upstream branch configured; skipping mutation scan."
    exit 0
fi

changed=$(git diff --name-only "$upstream"...HEAD | grep -E '\.py$' | grep -E '^app/' || true)
if [ -z "$changed" ]; then
    echo "ADVISORY: no changed app/ files; skipping mutation scan."
    exit 0
fi

# Fast scan on the changed files only. mutmut's run mode is not
# designed for partial scans, so we use cosmic-ray's per-module
# init with the diff as the scope. Documented limitation in design.md
# §10 RISK-9.
timeout 25 cosmic-ray init --module-path "$changed" docs/quality/cosmic-ray.toml /tmp/pr-scan.sqlite || true

echo "ADVISORY: pre-push mutation scan complete (advisory only, push allowed)."
exit 0
```

Both files are `chmod +x` on commit.

---

## AGENTS.md §23 edit

The exact diff hunk to add to §23. Per §17.3 the orchestrator MUST NOT
edit this inline; the apply sub-agent commits this on a feature
branch.

```diff
 ### 23. E2E expectation — every UI feature slice grows the E2E net
 
 Every feature slice that adds or changes UI (routes rendering templates, forms, HTMX interactions) MUST add or update at least one Playwright E2E flow under `tests/e2e/`. Backend-only slices (services, migration, scripts) are exempt. The E2E suite is the only net that catches template/route/CSRF wiring regressions that unit tests structurally cannot see.
 
+**QA-through-UI only.** Verification of any UI-facing feature slice MUST go through the existing Playwright E2E suite under `tests/e2e/` (or an equivalent in-tree browser test). QA via the Python shell, direct DB inspection, or `curl` against a running server is NOT a substitute and MUST NOT be presented as such in PR descriptions, runbooks, or status reports. The rationale: §32.P1 — hardening concentrates where the work is interesting while the HTTP edge gets nothing; the E2E suite is the layer that catches the edge regressions the unit suite cannot see. PR descriptions that claim a UI slice "verified by inspecting the DB" or "verified by running curl" are review-blockers and MUST be sent back for E2E coverage.
+
+This rule applies to the **verification step** of a PR, not to the **development loop** (developers may absolutely use shell/curl/DB-inspection to debug while iterating — that is not the subject of this rule). The rule is about what evidence is accepted as "QA passed" when a PR lands.
+
 The CI `e2e` job is currently skipped when `APAP_OAUTH_CLIENT_ID` is not configured (see `.github/workflows/ci.yml`). Once OAuth secrets exist in CI, the job stops being optional and becomes a required check (tracked in issue #206) — do not add new reasons to skip it.
```

Per REQ-QG-QAUI-1 SCN-QG-QAUI-1-1 the literal phrase `QA-through-UI only`
appears. The pin test `tests/test_agents_md_section_23.py` asserts the
phrase survives every future edit.

---

## Property test targets

Per REQ-QG-PROP-2, the first batch targets the `_row_to_*` helpers
auto-discovered by `scripts/pytest_plugin/coverage_gate.py`
(`CRITICAL_HELPERS`). Enumerated via `codegraph_explore` against
`app/modules/**`:

| Helper | File | Invariant the property asserts |
|--------|------|----------------------------------|
| `_row_to_animal` | `app/modules/animals/service.py:211` | "All-None row yields Animal with default scalars (id='None', activo=True)" — model instantiation never raises. |
| `_row_to_voluntario` | `app/modules/voluntarios/service.py:105` | "String fields round-trip: nombre/email/DNI survive whitespace strip without ValueError" — invariant matches the manual case-by-case tests in `tests/test_voluntarios_service.py`. |
| `_row_to_acogida` | `app/modules/acogidas/service.py:121` | "Datetime fields parse ISO 8601 with timezone; None stays None; malformed raises a specific exception class" — narrow the exception class so the test is not a generic no-crash check. |
| `_row_to_entrada` | `app/modules/entradas/service.py:117` | "All-None row yields Entrada with sensible defaults; required fields absent raise ValueError with a message naming the missing field" — encodes the contract documented in the helper's docstring. |
| `_row_to_adopcion` | `app/modules/adopciones/service.py:158` | "Bool fields coerce truthy/falsy strings consistently; fecha_* strings parse without timezone shift" — catches the kind of drift found by property tests in past audits. |

Five property tests per the spec minimum. They use `hypothesis.strategies.dictionaries`,
`hypothesis.strategies.datetimes`, `hypothesis.strategies.booleans`, and
`hypothesis.strategies.text()` to generate 50 examples each (per the
`dev` profile's `max_examples=50`).

Each test:

1. Builds a strategy that mirrors the helper's input shape.
2. Calls the helper directly (no FastAPI app needed — the helper is
   a pure function).
3. Asserts the OUTPUT is a valid instance of the target dataclass
   AND that no unexpected exception was raised.

Per web-tdd-philosophy rule 6 (refactor-safety), tests assert on
OUTCOME (instance creation + key fields) not on the SQL or any
internal flag.

---

## PR slicing

Three chained PRs (per spec; `delivery_strategy = exception-ok`).

### PR #1 — `feat/quality-gates-foundations`

- Branch: `feat/quality-gates-foundations`
- Title: `feat(quality-gates): add CRAP, jscpd, mutation-sites detectors + adapter exclusion + §23 QA-through-UI`
- Commits (one per work unit):
  1. `chore(deps): pin radon>=6.0 xenon>=0.9 cosmic-ray>=8.4 hypothesis>=6.150 mutmut>=2.4 dev deps (context7 verified)`
  2. `feat(scripts): add check_crap.py CRAP ratchet with shrink-only baseline`
  3. `test(check-crap): pin detector behaviour + ci lint-job wiring`
  4. `feat(scripts): add check_jscpd.py AST duplicate detector with shrink-only baseline (stdlib-only)`
  5. `test(check-jscpd): pin detector behaviour + ci lint-job wiring`
  6. `feat(scripts): add check_mutation_sites.py AST site counter with shrink-only baseline`
  7. `test(check-mutation-sites): pin detector behaviour + ci lint-job wiring`
  8. `chore(coverage): exclude app/core/local_backend.py from [tool.coverage.run] omit (REQ-QG-ADAPT-1)`
  9. `test(coverage): pin adapter exclusion in test_ci_workflow.py`
  10. `docs(agents): §23 explicit QA-through-UI only sentence (per §17.3 feature-branch flow)`
  11. `test(agents): pin §23 literal phrase via tests/test_agents_md_section_23.py`
  12. `feat(ci): wire 3 new lint-job steps after check_vulture_guard`
  13. `feat(hooks): add git-hooks/pre-commit advisory script + README`
- Files touched: ~14 new + 3 modified
- Lines added: ~1,400 (split across 13 commits; per-commit ~50-150)
- Review lenses: `code-review-expert` (mandatory), `judgment-day`
  (mandatory — touches `scripts/`, `pyproject.toml`, `ci.yml`,
  `AGENTS.md`, `git-hooks/` per §17.2 trigger list).
- Rollback: `git revert <merge-sha>` — single revert removes all 13
  commits atomically.

### PR #2 — `feat/quality-gates-mutation`

- Branch: `feat/quality-gates-mutation`
- Title: `feat(quality-gates): cosmic-ray manifest + nightly mutation job + pre-push hook (differential manifest)`
- Commits:
  1. `chore(quality): add docs/quality/cosmic-ray.toml config`
  2. `feat(scripts): add diff_cosmic_ray.py regression-only gate`
  3. `test(diff-cosmic-ray): pin identical/improvement/regression cases`
  4. `feat(ci): add nightly mutation job with schedule:cron + workflow_dispatch + report artifact`
  5. `feat(hooks): add git-hooks/pre-push advisory mutation scan + exit-0 contract test`
  6. `docs(quality): capture mutation-baseline.json on the merge commit (operator-driven)`
- Files touched: ~4 new + 1 modified
- Lines added: ~500
- Review lenses: `code-review-expert` (mandatory), `judgment-day`
  (mandatory — touches `scripts/`, `ci.yml`, `git-hooks/`,
  introduces a scheduled job per §17.2).
- Rollback: `git revert <merge-sha>` + `gh workflow disable mutation`.

### PR #3 — `feat/quality-gates-property-tests`

- Branch: `feat/quality-gates-property-tests`
- Title: `feat(quality-gates): hypothesis dev profile + 5 _row_to_* property tests`
- Commits:
  1. `chore(deps): ensure hypothesis>=6.150 dev dep (already pinned in PR #1)`
  2. `feat(tests): add tests/property/conftest.py with custom dev profile + skip-if-missing hook`
  3. `test(property): add tests/test_property_test_collection.py (REQ-QG-PROP-1 pin)`
  4. `test(property): add 5 _row_to_* property tests for the helpers enumerated in design.md §Property test targets`
- Files touched: ~7 new + 0 modified
- Lines added: ~600
- Review lenses: `code-review-expert` (mandatory). `judgment-day`
  is NOT mandatory — the diff does not touch `scripts/`, `ci.yml`,
  or any path on the §17.2 trigger list (only `tests/` + `pyproject.toml`
  dev extras already pinned in PR #1).
- Rollback: `git revert <merge-sha>`.

Total: 3 PRs, ~2,500 added lines across 24 commits, all under the
`review_budget_lines: 400` per-commit threshold per `work-unit-commits`.

---

## Risks

| # | Sev | Mitigation | Trigger condition that would surface a new risk |
|---|-----|------------|--------------------------------------------------|
| RISK-1 | Low | Drift in `pyproject.toml` `fail_under = 85` vs AGENTS.md §19 "80%" vs `openspec/config.yaml` `coverage_threshold: 80`. Spec uses 85 (correct). Design does NOT change the floor. Decision left to user. | User pushes back asking why 85, opens an issue, or merges a doc fix PR. |
| RISK-2 | Med | PR #1 ships CRAP baseline populated in the same commit. Standard ratchet pattern (mirrors §21). If the baseline capture runs AFTER merge the build is red. Documented in the PR description; the sdd-apply sub-agent must commit the populated BASELINE in the detector-introducing commit, not a follow-up. | CI fails on first PR #1 run because BASELINE doesn't match measured values. |
| RISK-3 | Mitigated | CRAP step moved into `test` job, AFTER pytest-cov writes `coverage.json`. Per-PR coverage is now used; the gate sees the actual PR head. Local fallback: script exits 0 with `NOTE: coverage.json missing — CRAP check skipped` when run outside pytest coverage collection (pinned by `test_check_crap_skips_when_coverage_json_missing`). | Future contributor moves the CRAP step back to `lint` and the gate silently regresses to "main coverage" mode. Mitigation: a pinning test asserts the CRAP step is in the `test` job, not `lint`. |
| RISK-4 | High | First cosmic-ray run shows many surviving mutants. Mitigated by the differential-manifest pattern (REQ-QG-MUT-1 captures the baseline). The job blocks only on REGRESSION, not on absolute count. | User expects PR #2 to ship with `percentage_killed > 90` and is surprised by the actual ~40%. |
| RISK-5 | Med | Hypothesis flakes in CI. Mitigated by `dev` profile (deterministic-ish; seeds printed via pytest-randomly) + REQ-QG-PROP-2 SCN-QG-PROP-2-2 budget (<60s). If flakes persist, switch to `ci` profile per spec default justification. | First PR #3 run shows a flake; pytest-randomly seed not reproducible. |
| RISK-6 | Med | Cosmic-ray pins transitive deps (e.g. `tomli`). All already in `[dev]` (via other tools). No conflict, but documented. Cosmic-ray 8.x API is stable. | pip resolver raises a version conflict during PR #2 install step. |
| RISK-7 | Med | Git-hooks touched (§15.5). User OK granted this session. PR body cites the OK. Hooks are advisory (exit 0); no bypass pressure. | User changes their mind and asks to remove the hooks. |
| RISK-8 | High | jscpd is NOT pip-installable (it's Node.js/Rust). Spec names jscpd. Design implements a stdlib AST detector in `scripts/check_jscpd.py` (mirrors the script-name in the spec). Future contributors may be confused. **Decision requested**: (a) keep current design, (b) rename script, (c) install Node.js + npm in CI Python venv to use real jscpd. | A reviewer asks "why doesn't this script use jscpd?". |
| RISK-9 | Med | `mutmut scan` subcommand does not exist. Spec REQ-QG-HOOK-2 names it. The hook uses cosmic-ray's `--module-path` to scope the scan to changed files; documented in the pre-push script as "fast scan on the changed files only" with a 25-second timeout. | The pre-push hook runs longer than 30s on a large PR and times out. |
| RISK-10 | Med | cosmic-ray has not had a release in 2025 or 2026 (last 8.4.6 in 2024). The package is stable but stale. RISK: a future Python release breaks cosmic-ray; the nightly job silently fails or produces wrong results. Mitigated by the weekly schedule + artifact upload so a regression is observable within 7 days. | Next Python release (3.13+) breaks cosmic-ray; the weekly job starts failing. |
| RISK-11 | Low | §32.P8 per-layer gap. Every new detector measures a single dimension. Aggregate could hide layer-specific gaps. Mitigated by the per-detector pinning tests; future PRs SHOULD add per-layer distribution reports. | Aggregate CRAP score looks OK but `app/modules/animals/service.py` is at grade F. |
| RISK-12 | Low | CRAP formula is not part of any standard. Different tools (radon, xenon) compute CC slightly differently (assert count, decorator branches). The design uses radon's CC. Different tools would produce different CRAP values. | A future contributor switches from radon to a different CC tool and the CRAP baseline no longer matches. |

---

## Spec traceability matrix

| Spec requirement | Design section that implements it |
|------------------|----------------------------------|
| REQ-QG-CRAP-1 | §Architecture Decisions (CRAP via radon), §File Changes, §CI workflow YAML |
| REQ-QG-CRAP-1 SCN-QG-CRAP-1-1 | §Baseline ratchet shapes (BASELINE_CRAP), §Testing Strategy |
| REQ-QG-CRAP-1 SCN-QG-CRAP-1-2 | §Baseline ratchet shapes, §CRAP computation contract |
| REQ-QG-CRAP-1 SCN-QG-CRAP-1-3 | §Baseline ratchet shapes (ratchet contract) |
| REQ-QG-MUT-1 | §Architecture Decisions (cosmic-ray), §File Changes, §Interfaces / Contracts (manifest schema) |
| REQ-QG-MUT-1 SCN-QG-MUT-1-1 | §Interfaces / Contracts (mutation-baseline.json) |
| REQ-QG-MUT-1 SCN-QG-MUT-1-2 | §Architecture Decisions (deterministic session file diff) |
| REQ-QG-MUT-2 | §CI workflow YAML (mutation job) |
| REQ-QG-MUT-2 SCN-QG-MUT-2-1 | §CI workflow YAML (diff_cosmic_ray.py exit 0 on identical) |
| REQ-QG-MUT-2 SCN-QG-MUT-2-2 | §CI workflow YAML (diff_cosmic_ray.py exit 1 on regression) |
| REQ-QG-MUT-2 SCN-QG-MUT-2-3 | §CI workflow YAML (improvement logged but manifest untouched), REQ-QG-XCUT-3 |
| REQ-QG-PROP-1 | §File Changes (tests/property/), §Interfaces / Contracts (conftest) |
| REQ-QG-PROP-1 SCN-QG-PROP-1-1 | §Interfaces / Contracts (standard pytest collection) |
| REQ-QG-PROP-1 SCN-QG-PROP-1-2 | §Interfaces / Contracts (pytest_collection_modifyitems skip) |
| REQ-QG-PROP-2 | §Property test targets (5 _row_to_* helpers enumerated) |
| REQ-QG-PROP-2 SCN-QG-PROP-2-1 | §Property test targets (per-helper invariant) |
| REQ-QG-PROP-2 SCN-QG-PROP-2-2 | §Architecture Decisions (dev profile max_examples=50, <60s budget) |
| REQ-QG-DRY-1 | §Architecture Decisions (jscpd → stdlib AST), §File Changes, §Interfaces / Contracts |
| REQ-QG-DRY-1 SCN-QG-DRY-1-1 | §Baseline ratchet shapes (BASELINE_JSCPD_PCT=15.0) |
| REQ-QG-DRY-1 SCN-QG-DRY-1-2 | §Interfaces / Contracts (check_tree exit 1 on violation) |
| REQ-QG-DRY-1 SCN-QG-DRY-1-3 | §Baseline ratchet shapes (shrink-only contract) |
| REQ-QG-MSITES-1 | §File Changes (check_mutation_sites.py), §Interfaces / Contracts |
| REQ-QG-MSITES-1 SCN-QG-MSITES-1-1 | §Baseline ratchet shapes (BASELINE_MUTATION_SITES) |
| REQ-QG-MSITES-1 SCN-QG-MSITES-1-2 | §Interfaces / Contracts (check_tree exit 1, hint to module-size ratchet) |
| REQ-QG-MSITES-1 SCN-QG-MSITES-1-3 | §Baseline ratchet shapes (shrink-only contract) |
| REQ-QG-ADAPT-1 | §File Changes (pyproject.toml omit list), §Testing Strategy (test_ci_workflow pin) |
| REQ-QG-ADAPT-1 SCN-QG-ADAPT-1-1 | §Testing Strategy |
| REQ-QG-ADAPT-1 SCN-QG-ADAPT-1-2 | §Testing Strategy |
| REQ-QG-ADAPT-1 SCN-QG-ADAPT-1-3 | §Testing Strategy (negative test that proves exclusion is load-bearing) |
| REQ-QG-QAUI-1 | §AGENTS.md §23 edit (literal phrase + verbatim paragraph) |
| REQ-QG-QAUI-1 SCN-QG-QAUI-1-1 | §Testing Strategy (test_agents_md_section_23.py) |
| REQ-QG-QAUI-1 SCN-QG-QAUI-1-2 | §AGENTS.md §23 edit (review-time enforcement) |
| REQ-QG-HOOK-1 | §Git hook scripts (pre-commit, exit 0 advisory) |
| REQ-QG-HOOK-1 SCN-QG-HOOK-1-1 | §Git hook scripts (three detectors invoked) |
| REQ-QG-HOOK-1 SCN-QG-HOOK-1-2 | §Git hook scripts (ADVISORY label) |
| REQ-QG-HOOK-2 | §Git hook scripts (pre-push, 30s budget) |
| REQ-QG-HOOK-2 SCN-QG-HOOK-2-1 | §Git hook scripts (timeout 25s + exit 0) |
| REQ-QG-HOOK-3 | §Git hook scripts (CI independence) |
| REQ-QG-HOOK-3 SCN-QG-HOOK-3-1 | §CI workflow YAML (CI lint-job runs same detectors independently) |
| REQ-QG-XCUT-1 | §File Changes (every detector has script + CI step + pin test), §Testing Strategy |
| REQ-QG-XCUT-2 | §Dependency footprint (every dev dep cited with context7 query) |
| REQ-QG-XCUT-3 | §File Changes (manifest only updated by human PR) |

Every requirement from the spec is traced. The matrix also surfaces
that REQ-QG-MUT-2 SCN-QG-MUT-2-3's "manifest SHALL NOT be updated by
CI" is explicitly encoded by the absence of any `git add` /
`git commit` in the mutation job's YAML (§CI workflow YAML PR #2).