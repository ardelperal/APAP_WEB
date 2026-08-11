# APAP Makefile — local developer entry points.
#
# See docs/development.md for the full guide and the cross-platform
# PowerShell equivalents for Windows users without GNU make.
# The canonical commands in this file are the source of truth for the
# CI workflow and the deploy job (CD-01 + CD-02, issue #1).

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
PYTEST ?= $(PYTHON) -m pytest
UVICORN ?= $(PYTHON) -m uvicorn

# Tailwind v4 — runs `npx @tailwindcss/cli` against tailwindcss/styles/app.css
# and writes the compiled bundle to app/static/css/output.css.
TAILWIND_DIR ?= tailwindcss
TAILWIND_INPUT ?= $(TAILWIND_DIR)/styles/app.css
TAILWIND_OUTPUT ?= app/static/css/output.css

.PHONY: help install dev test test-ci lint typecheck verify \
        check-rules check-module-size check-route-size check-layers \
        check-slice-completeness check-migration-boundaries \
        check-docstring-coverage check-complexity check-ruff-ratchet \
        check-vulture-guard check-jscpd check-mutation-sites \
        check-import-cycles check-workflows check-crap \
        mutation build all clean css css-watch serve run

help:
	@echo "APAP make targets:"
	@echo "  install      - Install runtime + dev deps into the active Python (.venv)"
	@echo "  dev          - Same as install (kept for backwards compat)"
	@echo "  verify       - THE green-PR gate: every gate ci.yml runs on a pull request"
	@echo "  test         - Run pytest with deprecation strictness (fast inner loop)"
	@echo "  test-ci      - Run pytest exactly as the CI test job does (coverage floor)"
	@echo "  lint         - Run ruff check on the repo"
	@echo "  typecheck    - Run mypy over app/ + migration/ (scope in pyproject [tool.mypy])"
	@echo "  check-rules  - Run the AST-based AGENTS.md rule linter (scripts/check_rules.py)"
	@echo "  mutation     - Run the cosmic-ray session + ratchet (LINUX ONLY; use WSL)"
	@echo "  build        - Build sdist + wheel with python -m build"
	@echo "  css          - Compile Tailwind v4 CSS once (production-style, minified)"
	@echo "  css-watch    - Run Tailwind v4 in watch mode (dev)"
	@echo "  serve        - Run uvicorn against app.main:app on 127.0.0.1:8000"
	@echo "  run          - css + serve (one-shot local preview)"
	@echo "  all          - css + verify (build the bundle, then run the gate)"
	@echo "  clean        - Remove build artifacts and tool caches"
	@echo ""
	@echo "  Run 'make verify' before opening a PR. Its gate list is pinned to"
	@echo "  ci.yml by tests/test_ci_workflow.py::test_make_verify_covers_every_ci_gate."

install:
	$(PIP) install -e ".[dev]"

dev: install

test:
	$(PYTEST)

lint:
	$(RUFF) check .

# typecheck — issue #201, AGENTS.md rule 24. Plain `python -m mypy`:
# the scope (app/ + migration/) and flags live in pyproject.toml
# [tool.mypy] so this target and the CI `typecheck` job can never
# drift. Zero errors is the gate; `# type: ignore` needs its error
# code. Pinned by tests/test_ci_workflow.py::
# test_ci_workflow_defines_typecheck_job_running_mypy.
typecheck:
	$(MYPY)

# check-rules — Slice 1 of hardening-2026-q2 (PR-1A + PR-1B).
# Runs the AST linter that catches the four most common AGENTS.md
# rule violations (rules 1, 4, 6, 7). The linter is intentionally
# ordered AFTER ``ruff check`` because ruff is a fast, style-focused
# binary; the AST linter is slower and is the actual gate that prevents
# the four known regressions from reaching main. Exits non-zero on any
# violation so CI can fail fast.
#
# PR-1B added ``--exclude`` to silence six known false positives in the
# infrastructure layer (linter self-reference, positive fixtures, the
# migration-004 sandbox DDL). The script also accepts ``.check_rulesignore``
# for repo-root-level ignore lists. See:
#   openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md
#   openspec/changes/hardening-2026-q2/apply-progress-pr-1b.md
check-rules:
	$(PYTHON) scripts/check_rules.py .

# check-layers — AGENTS.md rule 33, issue #436. The hexagonal harness:
# dependency direction, inner-layer purity, vertical-slice boundaries.
# The 53 pre-existing violations live in a shrink-only BASELINE measured
# against main @41fbd2a. CI runs it in the lint job.
#
# No positional argument, matching the CI step exactly. The script falls
# back to ``Path(__file__).parents[1]`` (the repo root) when argv is
# empty, so dropping the ``.`` changes nothing about what is scanned and
# removes one more place where local and CI invocations could diverge.
check-layers:
	$(PYTHON) scripts/check_layers.py

# --- Remaining CI lint-job gates (issue #504) -------------------------
#
# One target per gate, in the order ci.yml runs them. They existed only
# as workflow steps until #504: `make all` was documented as "the gate"
# while running four of seventeen, so a green local run said nothing
# about a pull request. Each recipe below is the CI step verbatim.
#
# Adding a gate to ci.yml without adding it here fails
# tests/test_ci_workflow.py::test_make_verify_covers_every_ci_gate.

check-module-size:
	$(PYTHON) scripts/check_module_size.py

check-route-size:
	$(PYTHON) scripts/check_route_size.py

check-slice-completeness:
	$(PYTHON) scripts/check_slice_completeness.py

check-migration-boundaries:
	$(PYTHON) scripts/check_migration_boundaries.py

check-docstring-coverage:
	$(PYTHON) scripts/check_docstring_coverage.py

check-complexity:
	$(PYTHON) scripts/check_complexity.py

check-ruff-ratchet:
	$(PYTHON) scripts/check_ruff_ratchet.py

check-vulture-guard:
	$(PYTHON) scripts/check_vulture_guard.py

check-jscpd:
	$(PYTHON) scripts/check_jscpd.py

check-mutation-sites:
	$(PYTHON) scripts/check_mutation_sites.py

check-import-cycles:
	$(PYTHON) scripts/check_import_cycles.py

# check-workflows — issue #523. Protects the gates themselves: a workflow
# whose YAML does not parse vanishes from the PR rollup instead of failing.
check-workflows:
	$(PYTHON) scripts/check_workflows.py

# check-crap — runs in the CI `test` job, not `lint`: the CRAP score is
# a function of complexity AND coverage, so it needs coverage.json from
# the pytest run above it. Depends on test-ci for exactly that reason.
check-crap: test-ci
	$(PYTHON) scripts/check_crap.py

# test-ci — the CI `test` job's pytest invocation, verbatim. Separate
# from `test` on purpose: `test` stays the fast inner loop (no coverage
# instrumentation), `test-ci` is what a pull request is actually judged
# by. The e2e and integration suites are excluded here exactly as they
# are in CI; integration has its own job with a Postgres service.
test-ci:
	$(PYTEST) -W error::DeprecationWarning \
		--ignore=tests/e2e \
		--ignore=tests/integration \
		--cov=app \
		--cov=migration \
		--cov-report=json \
		--cov-report=term \
		--cov-fail-under=85

# verify — THE definition of green (issue #504).
#
# One command that runs every gate ci.yml applies to a pull request, in
# CI's order: the lint job, then typecheck, then test + the CRAP ratchet
# that consumes its coverage.json. If this passes locally and the branch
# is up to date with main, CI has nothing left to discover.
#
# Deliberately NOT included, because they cannot run on a developer
# workstation and are not per-PR gates:
#   - `mutation`   weekly schedule, Linux-only (cosmic-ray), own job
#   - `security`   Docker-based scanners (gitleaks, trivy)
#   - `integration` needs a live Postgres service container
#   - `e2e`        needs Playwright + configured OAuth
#
# Pinned by tests/test_ci_workflow.py::test_make_verify_covers_every_ci_gate.
verify: lint check-rules check-module-size check-route-size check-layers \
        check-slice-completeness check-migration-boundaries \
        check-docstring-coverage check-complexity check-ruff-ratchet \
        check-vulture-guard check-jscpd check-mutation-sites \
        check-import-cycles check-workflows typecheck check-crap
	@echo "verify: all CI pull-request gates passed."

# mutation — issue #431. Runs the cosmic-ray session for the curated target
# set in docs/quality/cosmic-ray.toml and gates it with the ratchet.
#
# LINUX ONLY. cosmic-ray 8.4.6 returns INCOMPETENT for 100% of mutants on
# native Windows while `cr-rate` still reports a passing 0.00, so a session
# produced there is worse than no session at all. The guard below refuses to
# run rather than let that happen; on a Windows workstation use WSL, per
# docs/runbooks/mutation-testing.md. PYTHONHASHSEED=0 is the TASK-2.1 (W-5)
# determinism mitigation; its companion `--worker-count=1` does not exist in
# cosmic-ray 8.4.6 and the local distributor is already sequential.
mutation:
	@case "$$(uname -s)" in \
	  Linux*) ;; \
	  *) echo "make mutation: refusing to run on $$(uname -s)."; \
	     echo "cosmic-ray does not execute mutants outside Linux and reports"; \
	     echo "a passing 0.00 anyway. Use WSL — see docs/runbooks/mutation-testing.md."; \
	     exit 1 ;; \
	esac
	rm -f mutation.sqlite
	PYTHONHASHSEED=0 cosmic-ray baseline docs/quality/cosmic-ray.toml
	PYTHONHASHSEED=0 cosmic-ray init docs/quality/cosmic-ray.toml mutation.sqlite
	cr-filter-operators mutation.sqlite docs/quality/cosmic-ray.toml
	PYTHONHASHSEED=0 cosmic-ray exec docs/quality/cosmic-ray.toml mutation.sqlite
	$(PYTHON) scripts/check_mutation.py mutation.sqlite

build:
	$(PYTHON) -m build

css:
	cd $(TAILWIND_DIR) && npx tailwindcss -i ./styles/app.css -o ../$(TAILWIND_OUTPUT) --minify

css-watch:
	cd $(TAILWIND_DIR) && npx tailwindcss -i ./styles/app.css -o ../$(TAILWIND_OUTPUT) --watch

serve:
	$(UVICORN) app.main:app --host 127.0.0.1 --port 8000 --reload

run: css serve

# all — kept for backwards compatibility with docs and muscle memory.
# It used to be `css test lint typecheck`, which was documented as "the
# green-PR gate" while running four of the seventeen gates CI applies
# (issue #504). It now delegates to `verify`, so the promise the name
# always made is finally true.
all: css verify

clean:
	rm -rf build/ dist/ .pytest_cache/ .ruff_cache/ .coverage htmlcov/
	rm -rf $(TAILWIND_DIR)/node_modules/ $(TAILWIND_DIR)/package-lock.json
	rm -f $(TAILWIND_OUTPUT)
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
