# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/Makefile
#
# The portable local entrypoint. `make verify` proves the repository is adopted
# correctly and passes every PR gate that needs only the checkout and installed
# development tools, in CI order (Hard Rules 13 and 19). CI remains the full
# merge gate because PR-context, scheduled, network, and Docker checks are
# explicit capability-scoped exclusions below.
#
# Why this file exists at all: a harness whose gate list lives only in ci.yml
# has no local expression of its own contract. Developers and agents run some
# smaller subset, get a green they did not earn, and discover the real gate on
# the runner. The subset always drifts downward, because nothing measures it.
# `tests/test_ci_workflow.py::test_make_verify_runs_every_local_gate` measures it.
#
# Adjust only the configuration block below. Everything after it is mechanism.

# --- configuration ----------------------------------------------------
PYTHON ?= python
PACKAGE ?= app
POLICY_DATE ?=
# ----------------------------------------------------------------------

RUFF ?= $(PYTHON) -m ruff
MYPY ?= $(PYTHON) -m mypy
PYTEST ?= $(PYTHON) -m pytest

.PHONY: help verify adoption format-check lint typecheck test quality mutation clean

help:
	@echo "verify        - portable local subset of CI; exclusions are listed in this file"
	@echo "adoption      - required configs, lockfile hashes, and scanner image pins"
	@echo "format-check  - ruff format --check (mechanical, fix first)"
	@echo "lint          - ruff check ."
	@echo "typecheck     - mypy over $(PACKAGE)/"
	@echo "test          - pytest with coverage.json, which the CRAP gate consumes"
	@echo "quality       - layers -> complexity -> CRAP -> mutation sites -> DRY, in order"
	@echo "mutation      - the cosmic-ray session + ratchet (slow; CI runs it weekly)"
	@echo ""
	@echo "Run 'make verify' before opening a PR, then rely on CI for excluded gates."
	@echo "Its executable gate identities and exclusions are pinned to ci.yml by"
	@echo "tests/test_ci_workflow.py::test_make_verify_runs_every_local_gate."

# Verification order is Hard Rule 13 and matches CI after capability-scoped
# exclusions: adoption first, then mechanical checks, then tests (which produce
# coverage.json), then code gates that consume it. Never reorder these.
adoption:
	$(PYTHON) scripts/check_adoption.py

format-check:
	$(RUFF) format --check

lint:
	$(RUFF) check .

typecheck:
	$(MYPY) $(PACKAGE)/

test:
	$(PYTEST) --cov --cov-report=json:coverage.json

# quality_report.py runs layers -> complexity -> CRAP -> mutation_sites -> DRY
# in one process because their order is pinned in code (GATES), not in YAML
# where a reviewer can swap two steps without noticing.
quality:
	@test -n "$(POLICY_DATE)" || (echo "POLICY_DATE=YYYY-MM-DD is required" >&2; exit 2)
	$(PYTHON) scripts/quality_report.py --policy-date "$(POLICY_DATE)"

# verify — the portable local evidence boundary (Hard Rule 19).
#
# Deliberately NOT included, each for a reason that is pinned by
# test_make_verify_excludes_what_a_workstation_cannot_run:
#   - check_pr_size / check_branch_name  need CI's PR base/body and head-ref context
#   - check_mutation + cosmic-ray        weekly schedule; far too slow per PR
#   - pip-audit / gitleaks / trivy       Docker- and network-dependent scanners
#
# Adding a gate to ci.yml without adding it here fails the parity test. That is
# the only reason the two lists will still match a year from now.
verify: adoption format-check lint typecheck test quality
	@echo "verify: portable local gates passed; capability-scoped gates still require CI."

# Slow, scheduled, and Linux-only in most setups. Kept out of `verify` on
# purpose (Hard Rule 19's exclusion list), available on demand.
mutation:
	@test -n "$(POLICY_DATE)" || (echo "POLICY_DATE=YYYY-MM-DD is required" >&2; exit 2)
	$(PYTHON) scripts/check_adoption.py
	cosmic-ray baseline cosmic-ray.toml
	cosmic-ray init cosmic-ray.toml mutation-session.sqlite
	cosmic-ray exec cosmic-ray.toml mutation-session.sqlite
	$(PYTHON) scripts/check_mutation.py mutation-session.sqlite --policy-date "$(POLICY_DATE)"

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache coverage.json quality-report.json mutation-session.sqlite
