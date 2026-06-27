# APAP Makefile — local developer entry points.
#
# See docs/development.md for the full guide and the cross-platform
# PowerShell equivalents for Windows users without GNU make.
# The canonical commands in this file are the source of truth for the
# CI workflow and the deploy job (CD-01 + CD-02, issue #1).

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
RUFF ?= $(PYTHON) -m ruff
PYTEST ?= $(PYTHON) -m pytest
UVICORN ?= $(PYTHON) -m uvicorn

# Tailwind v4 — runs `npx @tailwindcss/cli` against tailwindcss/styles/app.css
# and writes the compiled bundle to app/static/css/output.css.
TAILWIND_DIR ?= tailwindcss
TAILWIND_INPUT ?= $(TAILWIND_DIR)/styles/app.css
TAILWIND_OUTPUT ?= app/static/css/output.css

.PHONY: help install dev test lint check-rules build all clean css css-watch serve run

help:
	@echo "APAP make targets:"
	@echo "  install      - Install runtime + dev deps into the active Python (.venv)"
	@echo "  dev          - Same as install (kept for backwards compat)"
	@echo "  test         - Run pytest with deprecation strictness"
	@echo "  lint         - Run ruff check on the repo"
	@echo "  check-rules  - Run the AST-based AGENTS.md rule linter (scripts/check_rules.py)"
	@echo "  build        - Build sdist + wheel with python -m build"
	@echo "  css          - Compile Tailwind v4 CSS once (production-style, minified)"
	@echo "  css-watch    - Run Tailwind v4 in watch mode (dev)"
	@echo "  serve        - Run uvicorn against app.main:app on 127.0.0.1:8000"
	@echo "  run          - css + serve (one-shot local preview)"
	@echo "  all          - css + test + lint (the green-PR gate)"
	@echo "  clean        - Remove build artifacts and tool caches"

install:
	$(PIP) install -e ".[dev]"

dev: install

test:
	$(PYTEST)

lint:
	$(RUFF) check .

# check-rules — Slice 1 of hardening-2026-q2.
# Runs the AST linter that catches the four most common AGENTS.md
# rule violations (rules 1, 4, 6, 7). The linter is intentionally
# ordered AFTER ``ruff check`` because ruff is a fast, style-focused
# binary; the AST linter is slower and is the actual gate that prevents
# the four known regressions from reaching main. Exits non-zero on any
# violation so CI can fail fast. See:
#   openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md
check-rules:
	$(PYTHON) scripts/check_rules.py app

build:
	$(PYTHON) -m build

css:
	cd $(TAILWIND_DIR) && npx tailwindcss -i ./styles/app.css -o ../$(TAILWIND_OUTPUT) --minify

css-watch:
	cd $(TAILWIND_DIR) && npx tailwindcss -i ./styles/app.css -o ../$(TAILWIND_OUTPUT) --watch

serve:
	$(UVICORN) app.main:app --host 127.0.0.1 --port 8000 --reload

run: css serve

all: css test lint

clean:
	rm -rf build/ dist/ .pytest_cache/ .ruff_cache/ .coverage htmlcov/
	rm -rf $(TAILWIND_DIR)/node_modules/ $(TAILWIND_DIR)/package-lock.json
	rm -f $(TAILWIND_OUTPUT)
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
