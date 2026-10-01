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

# e2e-local — same pinned images and env contract as the ci.yml `e2e`
# job's service containers (issue #1146). Override the ports if they
# collide with something on the workstation.
E2E_POSTGRES_IMAGE ?= postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193
E2E_MINIO_IMAGE ?= ghcr.io/ardelperal/minio@sha256:6140fe7015bd97e4e6340c9a8ead775c09bc1a226b7c36e41d24852f839dae8f
E2E_MINIO_USER ?= e2e-minio-root
E2E_MINIO_PASSWORD ?= e2e-minio-password
E2E_POSTGRES_PORT ?= 55432
E2E_MINIO_PORT ?= 59000
E2E_APP_PORT ?= 58000
E2E_NETWORK ?= apap-e2e-local
E2E_PG_CONTAINER ?= apap-e2e-local-postgres
E2E_MINIO_CONTAINER ?= apap-e2e-local-minio

.PHONY: help install dev test test-ci lint typecheck verify \
        check-rules check-module-size check-route-size check-layers \
        check-slice-completeness check-migration-boundaries \
        check-docstring-coverage check-complexity check-ruff-ratchet \
        check-vulture-guard check-jscpd check-mutation-sites \
        check-docstring-balance check-import-cycles check-workflows check-test-classification check-crap \
        mutation e2e-local build all clean css css-watch serve run

help:
	@echo "APAP make targets:"
	@echo "  install      - Install runtime + dev deps into the active Python (.venv)"
	@echo "  dev          - Same as install (kept for backwards compat)"
	@echo "  verify       - Run the deterministic CI subset available on a workstation"
	@echo "  test         - Run pytest with deprecation strictness (fast inner loop)"
	@echo "  test-ci      - Run pytest exactly as the CI test job does (coverage floor)"
	@echo "  lint         - Run ruff check on the repo"
	@echo "  typecheck    - Run mypy over app/ + migration/ (scope in pyproject [tool.mypy])"
	@echo "  check-rules  - Run the AST-based AGENTS.md rule linter (scripts/check_rules.py)"
	@echo "  mutation     - Run the cosmic-ray session + ratchet (LINUX ONLY; use WSL)"
	@echo "  e2e-local    - Reproduce the ci.yml e2e job locally (Docker + GHCR login needed; see target docs)"
	@echo "  build        - Build sdist + wheel with python -m build"
	@echo "  css          - Compile Tailwind v4 CSS once (production-style, minified)"
	@echo "  css-watch    - Run Tailwind v4 in watch mode (dev)"
	@echo "  serve        - Run uvicorn against app.main:app on 127.0.0.1:8000"
	@echo "  run          - css + serve (one-shot local preview)"
	@echo "  all          - css + verify (build the bundle, then run the gate)"
	@echo "  clean        - Remove build artifacts and tool caches"
	@echo ""
	@echo "  Run 'make verify' before opening a PR. GitHub's 'ci / required'"
	@echo "  remains authoritative because it also covers service and container jobs."

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

# check-alantyle — issue #559, ADR d-42. Stdlib detector of the nine
# §10 anti-patterns from the documentation-alan-style skill. Scans
# the canonical doc trees (docs/, specs, and change delta-specs) plus root files
# referenced from the hub-and-spoke guide. The paths match the CI step
# verbatim, so local and remote verdicts see the same set of files.
check-alantyle:
	$(PYTHON) scripts/check_alantyle.py docs/ openspec/specs/ openspec/changes/*/specs/ README.md AGENTS.md DOCS.md CONTRIBUTING.md

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
# Adding a locally reproducible script gate to ci.yml without adding it here
# fails test_make_verify_covers_locally_runnable_script_gates.

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

# check-docstring-balance -- guards against unclosed triple-quoted strings.
# When a """ opens but never closes, Python consumes the class body as
# string content; methods "disappear" and tests fail with NameError at
# runtime. ruff/mypy do not catch this because py_compile succeeds.
check-docstring-balance:
	$(PYTHON) scripts/check_docstring_balance.py .

check-import-cycles:
	$(PYTHON) scripts/check_import_cycles.py

# check-workflows — issue #523. Protects the gates themselves: a workflow
# whose YAML does not parse vanishes from the PR rollup instead of failing.
check-workflows:
	$(PYTHON) scripts/check_workflows.py

# check-issue-specs — issue #723. GitHub forms are the authoring boundary;
# this local gate proves every supported work type exposes the same required
# issue-as-spec contract. Live PR linkage is checked by issue-spec.yml because
# it requires the GitHub event and issue API.
check-issue-specs:
	$(PYTHON) scripts/check_issue_specs.py forms

# check-test-classification -- issue #631. Companion to the test audit
# docs/quality/test-audit.md (2026-08-31). Every domain whose unit tests
# mock SQL via httpx.MockTransport must have a matching
# tests/integration/test_<module>_queries_integration.py when the flow
# involves FK enforcement, triggers, CTE rollback, or ON CONFLICT.
check-test-classification:
	$(PYTHON) scripts/check_test_classification.py

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
		--ignore=tests/e2e_ci \
		--ignore=tests/integration \
		--cov=app \
		--cov=migration \
		--cov-report=json \
		--cov-report=term \
		--cov-fail-under=85

# verify — deterministic local pre-push subset (issue #504).
#
# One command for the CI checks that are deterministic and practical on a
# developer workstation: lint/meta-gates, typecheck, pytest with coverage,
# and the CRAP ratchet that consumes coverage.json. A green result is useful
# pre-push evidence, not proof that the complete remote pipeline is green.
#
# Deliberately NOT included because they require CI services, containers,
# browsers, credentials, or release-only capacity:
#   - `mutation`   release-tag/manual-dispatch only, Linux-only (cosmic-ray), own job
#   - `security` / `security-deep` Docker-based scanners and audits
#   - `integration` needs a live Postgres service container
#   - `verify-fallback-ready` needs an isolated Postgres service container
#   - `build`       validates the production container image
#   - `e2e`         starts Postgres, the real app, and Chromium
#
# The locally reproducible script list is pinned by
# tests/test_ci_workflow.py::test_make_verify_covers_locally_runnable_script_gates.
verify: lint check-rules check-alantyle check-module-size check-route-size check-layers \
        check-test-classification check-slice-completeness check-migration-boundaries \
        check-docstring-coverage check-complexity check-ruff-ratchet \
        check-vulture-guard check-jscpd check-mutation-sites \
        check-docstring-balance check-import-cycles check-workflows check-issue-specs typecheck check-crap
	@echo "verify: deterministic local CI subset passed; await GitHub 'ci / required'."

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

# e2e-local — reproduce the ci.yml `e2e` job on a workstation (issue #1146).
#
# Boots the same pinned Postgres and MinIO-replica service containers CI
# uses, creates the apap-photos bucket, starts the real application with
# lifespan enabled and the same APAP_* env the workflow sets, and runs
# tests/e2e_ci against it. Everything tears down automatically, even on
# failure.
#
# Honest requirements (what is NOT free):
#   - Docker daemon running (checked; fails fast like the CI preflight).
#   - The MinIO replica image lives on ghcr.io and is pinned by digest to
#     the same digest ci.yml uses. If the pull is denied (the package is
#     private — CI authenticates with the ephemeral GITHUB_TOKEN), run
#     `docker login ghcr.io` with a PAT granted read:packages first (see
#     docs/operations/minio-replica.md). There is no public mirror to
#     fall back on (issue #973).
#   - amd64 workstations run the pinned replica as-is. On arm64 hosts
#     (Apple Silicon etc.) the image is amd64-only and needs qemu binfmt
#     (e.g. `docker run --privileged tonistiigi/binfmt --install amd64`);
#     without it the MinIO container dies with `exec format error` and
#     this target fails at the health gate — that failure is the honest
#     signal, not a target bug. CI runs on amd64 hosted runners.
#   - Playwright Chromium: `make install` then
#     `python -m playwright install --with-deps chromium`.
#   - bash + openssl + curl (Linux/macOS; no Windows path in this target).
#   - No repository secrets needed: the auth secret is generated per run
#     and MinIO uses the local root credentials below, not the MINIO_E2E_*
#     organization secrets CI reads.
e2e-local:
	@bash -euo pipefail -c '\
	echo "== e2e-local: reproducing the ci.yml e2e job (issue #1146) =="; \
	docker info >/dev/null 2>&1 || { echo "FAIL: Docker daemon is not reachable; start Docker and retry." >&2; exit 1; }; \
	cleanup() { if [ -n "$${SERVER_PID:-}" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi; docker rm -f $(E2E_PG_CONTAINER) $(E2E_MINIO_CONTAINER) >/dev/null 2>&1 || true; docker network rm $(E2E_NETWORK) >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT INT TERM; \
	cleanup >/dev/null 2>&1 || true; \
	if ! docker image inspect $(E2E_MINIO_IMAGE) >/dev/null 2>&1; then \
	  echo "Pulling the MinIO replica (private GHCR image; requires docker login ghcr.io with read:packages — docs/operations/minio-replica.md)..."; \
	  docker pull $(E2E_MINIO_IMAGE); \
	fi; \
	docker network create $(E2E_NETWORK) >/dev/null 2>&1 || true; \
	docker run -d --name $(E2E_PG_CONTAINER) --network $(E2E_NETWORK) \
	  -e POSTGRES_USER=postgres -e POSTGRES_DB=apap_e2e -e POSTGRES_HOST_AUTH_METHOD=trust \
	  -p $(E2E_POSTGRES_PORT):5432 $(E2E_POSTGRES_IMAGE) >/dev/null; \
	docker run -d --name $(E2E_MINIO_CONTAINER) --network $(E2E_NETWORK) \
	  -e MINIO_ROOT_USER=$(E2E_MINIO_USER) -e MINIO_ROOT_PASSWORD=$(E2E_MINIO_PASSWORD) \
	  -p $(E2E_MINIO_PORT):9000 $(E2E_MINIO_IMAGE) server /data --console-address :9001 >/dev/null; \
	echo "Waiting for Postgres readiness (30s cap)..."; \
	for i in $$(seq 1 30); do docker exec $(E2E_PG_CONTAINER) pg_isready -U postgres -d apap_e2e >/dev/null 2>&1 && break; sleep 1; done; \
	docker exec $(E2E_PG_CONTAINER) pg_isready -U postgres -d apap_e2e >/dev/null || { echo "FAIL: Postgres did not become ready within 30s." >&2; exit 1; }; \
	echo "Waiting for MinIO health (60s cap)..."; \
	for i in $$(seq 1 60); do curl -fsS http://127.0.0.1:$(E2E_MINIO_PORT)/minio/health/live >/dev/null 2>&1 && break; sleep 1; done; \
	curl -fsS http://127.0.0.1:$(E2E_MINIO_PORT)/minio/health/live >/dev/null || { echo "FAIL: MinIO did not become healthy within 60s." >&2; exit 1; }; \
	MINIO_HOST_PORT=$(E2E_MINIO_PORT) S3_ACCESS_KEY=$(E2E_MINIO_USER) S3_SECRET_KEY=$(E2E_MINIO_PASSWORD) \
	  $(PYTHON) scripts/create_minio_bucket.py; \
	export APAP_LOCAL_DB_URL=postgresql://postgres@127.0.0.1:$(E2E_POSTGRES_PORT)/apap_e2e \
	  APAP_E2E_AUTH_SECRET=$$(openssl rand -hex 32) \
	  APAP_DEBUG=true APAP_MODE=test \
	  APAP_AUTH_ENABLE_MAGIC_LINK=true \
	  APAP_E2E_AUTH_ENABLED=true APAP_E2E_AUTH_DEFAULT_EMAIL=e2e@apap.local \
	  APAP_S3_ENDPOINT=http://127.0.0.1:$(E2E_MINIO_PORT) \
	  APAP_S3_ACCESS_KEY=$(E2E_MINIO_USER) APAP_S3_SECRET_KEY=$(E2E_MINIO_PASSWORD) \
	  APAP_S3_BUCKET=apap-photos APAP_S3_SECURE=false; \
	echo "Starting the application on 127.0.0.1:$(E2E_APP_PORT)..."; \
	$(UVICORN) app.main:app --host 127.0.0.1 --port $(E2E_APP_PORT) --lifespan on & SERVER_PID=$$!; \
	for i in $$(seq 1 45); do curl -fsS http://127.0.0.1:$(E2E_APP_PORT)/healthz >/dev/null 2>&1 && break; sleep 1; done; \
	curl -fsS http://127.0.0.1:$(E2E_APP_PORT)/healthz >/dev/null || { echo "FAIL: the application did not become healthy within 45s (check the uvicorn output above)." >&2; exit 1; }; \
	APAP_E2E_BASE_URL=http://127.0.0.1:$(E2E_APP_PORT) $(PYTEST) tests/e2e_ci/ -v; \
	echo "e2e-local: PASSED"'

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
# (issue #504). It now delegates to the documented deterministic local
# verification subset.
all: css verify

clean:
	rm -rf build/ dist/ .pytest_cache/ .ruff_cache/ .coverage htmlcov/
	rm -rf $(TAILWIND_DIR)/node_modules/
	rm -f $(TAILWIND_OUTPUT)
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
