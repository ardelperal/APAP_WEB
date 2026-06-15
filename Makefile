# APAP Makefile — local developer entry points.
#
# See docs/development.md for the full guide and the cross-platform
# PowerShell equivalents for Windows users without GNU make.
# The canonical commands in this file are the source of truth for the
# CI workflow (PR 2) and the deploy job (PR 3).

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
RUFF ?= $(PYTHON) -m ruff
PYTEST ?= $(PYTHON) -m pytest

.PHONY: help install dev test lint build all clean

help:
	@echo "APAP make targets:"
	@echo "  install   - Install runtime deps (no-op until app code lands)"
	@echo "  dev       - Install dev/test/lint deps (pytest, pytest-cov, ruff)"
	@echo "  test      - Run pytest with deprecation strictness"
	@echo "  lint      - Run ruff check on the repo"
	@echo "  build     - Build sdist + wheel with python -m build"
	@echo "  all       - Run test + lint (the green-PR gate)"
	@echo "  clean     - Remove build artifacts and tool caches"

install:
	@echo "Runtime dependencies land with the web-app-skeleton PR. Nothing to install yet."
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST)

lint:
	$(RUFF) check .

build:
	$(PYTHON) -m build

all: test lint

clean:
	rm -rf build/ dist/ .pytest_cache/ .ruff_cache/ .coverage htmlcov/
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
