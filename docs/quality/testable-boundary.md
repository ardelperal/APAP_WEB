# Testable / Untestable Boundary

> Single source of truth for what APAP_WEB measures with its static-analysis
> tools, what it deliberately excludes, and why each exclusion exists.

This document closes Rule 14 of `deterministic-quality-harness` v1.5: "the
testable/untestable boundary is a versioned, gated artifact. Modules that
open GUIs, drive external devices, emit system errors, or hang under
automation are declared untestable and excluded from coverage, mutation,
complexity, and duplication tooling. Keep that boundary as thin as possible."

## Scope

This artifact covers every tool in `scripts/` that measures or audits the
codebase: complexity, CRAP, mutation-sites, the extended-ruff ratchet, the
jscpd duplication detector, the vulture dead-code guard, the docstring
coverage gate, the module-size budget, the route-handler size budget, the
import-cycle detector, the layer gate, and the migration-boundary gate.
pytest is also covered because its `--ignore` flags implement the boundary
on the test-collection side.

## Testable scope

The default testable scope is **production code**:

| Tool | Scope | Where in code |
|---|---|---|
| `check_ruff_ratchet.py` | `app/`, `migration/`, `scripts/` | `SCOPE` constant |
| `check_module_size.py` | `app/`, `migration/` | `SCAN_DIRS` constant |
| `check_route_size.py` | `app/**/*.py` + `app/main.py` | `_iter_route_files()` |
| `check_complexity.py` | `app/`, `migration/` | `SCAN_DIRS` constant |
| `check_crap.py` | `app/`, `migration/` | `SCAN_DIRS` constant |
| `check_mutation_sites.py` | `app/`, `migration/` | `SCAN_DIRS` constant |
| `check_docstring_coverage.py` | `app/`, `migration/`, `scripts/` | `SCAN_DIRS` constant |
| `check_jscpd.py` | `app/`, `migration/`, `scripts/` | `SCAN_DIRS` constant |
| `check_vulture_guard.py` | `app/`, `migration/`, `scripts/`, `tests/` | `REFERENCE_SCOPE` constant |
| `check_import_cycles.py` | `app/` | `SCAN_DIRS` constant |
| `check_layers.py` | `app/` | `SCAN_DIRS` constant |
| `check_slice_completeness.py` | `app/` | `SCAN_DIRS` constant |
| `check_migration_boundaries.py` | `migration/` | `SCAN_DIRS` constant (imported from `migration_boundaries_policy.SCAN_DIRS`) |
| `migration_boundaries_policy.py` | `migration/` | `SCAN_DIRS` constant |
| pytest coverage (CI) | `app/`, `migration/` | `--cov=app --cov=migration` in `.github/workflows/ci.yml` |

The scope was last audited 2026-08-10 against `origin/main` at `f016e0b`.
Future scope changes go through a PR that updates this document in the same
commit as the tool change.

## Untestable scope

Six categories of code are deliberately excluded. Each is a documented
decision, not an oversight. Adding a new entry requires updating this list in
the same PR as the exclusion.

### 1. Test fixtures with deliberately malformed code

`tests/_rule_helpers/fixtures/`, `tests/fixtures/query_seam/`, and similar
fixtures contain code that violates static-analysis rules on purpose — they
are the inputs the rule linter and the ratchet scripts need to test their
detection. Excluding them keeps coverage and complexity metrics meaningful
for production code.

- **Excluded from**: `check_module_size.py`, `check_complexity.py`, all
  ratchets that scan `scripts/` or `tests/`.
- **Rationale**: A wrong-positive (flagging a fixture) is a worse failure
  than a wrong-negative (missing a real violation in production).

### 2. The `__pycache__` and `.codegraph-vba` runtime caches

Every tool walks the source tree with `pathlib.Path.rglob`. Both caches are
walked by default. Excluded by an in-script guard:

- `check_module_size.py::_iter_python_files()`: skips any path containing
  `__pycache__`.
- `check_mutation_sites.py::_iter_python_files()`: same.
- `check_route_size.py::_iter_route_files()`: same.

The `.codegraph-vba/` directory is the only other per-tool local cache and
lives outside `app/`, `migration/`, `scripts/`, and `tests/` — it never
appears in any `SCOPE` constant.

### 3. Browser-driven E2E tests

`tests/e2e/` runs Playwright against a live server at `APAP_E2E_BASE_URL`.
Playwright's sync API initialises an event loop at import time that
poisons `pytest-asyncio`'s loop for every other test in the same process.
The default pytest run excludes them; CI runs them as a dedicated job.

- **Excluded from**: `pytest` (default `addopts` in `pyproject.toml` line 156).
- **CI carve-out**: `.github/workflows/ci.yml` `e2e:` job runs them when
  `APAP_OAUTH_CLIENT_ID` is configured.
- **Why a separate job, not a separate file**: the loop-poisoning only
  happens when Playwright is imported in the same process as the regular
  suite. The dedicated `e2e:` job ships a fresh process per run.

### 4. Real-Postgres integration tests

`tests/integration/` executes every exported query function from
`app/modules/*/queries.py` against a real Postgres engine. The session-scoped
fixture provisions the full domain schema once per test session.

- **Excluded from**: `pytest` (default `addopts` in `pyproject.toml` line 159).
- **CI carve-out**: `.github/workflows/ci.yml` `integration:` job spins up
  a Postgres service container and runs them with
  `APAP_TEST_POSTGRES_DSN=postgresql://postgres@127.0.0.1:5432/apap_test`.
- **Why a separate job**: the integration fixture hard-fails when the DSN is
  absent (issue #329). Silently skipping would erase the regression guard for
  the SQL round-trip contract.

### 5. Concurrent-DB TOCTOU regression test

`tests/test_voluntarios_concurrent.py` runs a real concurrent-session test
that requires a real Postgres backend (not just the queries layer).

- **Excluded from**: `.github/workflows/ci.yml` `test:` job (deselected via
  `--deselect=tests/test_voluntarios_concurrent.py`).
- **Local carve-out**: requires `APAP_E2E_BASE_URL` set so the script can
  provision a volunteer database and run concurrent inserts.
- **Why deselected**: the GitHub Actions pool does not provision Postgres
  in the standard `test` job (only in `integration:` and `e2e:`). A
  hard-failing test in a job that cannot supply its prerequisite would be <!-- alantyle-ignore:ALAN004 -->
  dead code by §32.P6 of AGENTS.md.

### 6. Coverage-line patterns excluded by `pytest-cov`

`pyproject.toml [tool.coverage.report].exclude_lines` removes four idiomatic
patterns from coverage measurement:

- `pragma: no cover` — the explicit opt-out for code that is correct but
  intentionally untested (e.g. defensive `raise NotImplementedError` in
  abstract base classes).
- `if __name__ == .__main__.:` — module entry points, executed via the
  CLI driver, not via pytest.
- `if TYPE_CHECKING:` — type-only imports, stripped at runtime, never
  executable.
- `raise NotImplementedError` — abstract method bodies; the runtime
  contract is enforced by `TypeError` at instantiation, not by tests.

## Enforcement of this artifact

Per Rule 14 the artifact is **versioned and gated**:

- **Versioned**: this file is committed to git. Every PR that touches a
  scope constant (`SCAN_DIRS`, `SCOPE`, `REFERENCE_SCOPE`, etc.) must
  also touch this document in the same commit.
- **Gated**: a follow-up PR will add a `tests/test_testable_boundary.py`
  that parses every tool's scope constant and asserts it matches the
  `Testable scope` table above. Tracked as part of the same compliance
  plan; not in this slice.

## Review cadence

Quarterly (per Rule 6 of the harness): confirm that every entry in the
`Untestable scope` table above is still justified. Justification for
removing an exclusion lives in the PR that removes it.

## References

- `docs/proceso.md` — pre-flight to triage, SDD-or-direct decision,
  local validation, merge.
- `pyproject.toml` `[tool.coverage.report]` (line 308) — coverage
  exclusions.
- `pyproject.toml` `[tool.pytest.ini_options]` (line 151) — pytest
  `--ignore` flags and marker definitions.
- `.github/workflows/ci.yml` — gate boundaries (`integration:` job,
  `e2e:` job, deselected `test_voluntarios_concurrent.py`).
- `deterministic-quality-harness` v1.5 Rule 14 — the rule this artifact
  closes.