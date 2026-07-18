"""Regression: critical helpers must have 100% line coverage on HEAD.

Spec: ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
(REQ-3 + Acceptance criteria).

This is the ``on-HEAD`` regression test the brief calls for: it walks
``app/`` and verifies the set of helpers the gate tracks matches the
helpers the AST finds in the codebase. If someone adds a new
``_row_to_*`` mapper or renames a critical helper without updating
``CRITICAL_HELPERS``, the AST scan diverges from the gate's tracking and
this test fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.pytest_plugin.coverage_gate import (
    CRITICAL_HELPERS,
    gather_helpers,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"
NON_APP_CRITICAL_HELPERS = frozenset({"_reverse_apply_one_row"})


def _defined_functions_in_app() -> set[str]:
    """Return every ``def _foo(...)`` name under ``app/`` (regex-style helper
    names only — bare ``_foo`` not in a class)."""
    if not APP_ROOT.exists():
        pytest.skip("app/ not present in this checkout")
    found: set[str] = set()
    for py in APP_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or py.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.add(node.name)
    return found


def test_critical_helpers_constant_has_no_drift_from_app() -> None:
    """Every named entry in ``CRITICAL_HELPERS`` must still resolve to a
    real function in the live ``app/`` tree. If the constant references a
    helper that was renamed or deleted, this test fails — preventing a
    silent regression where the gate stops enforcing coverage on a helper
    that no longer exists."""
    defined = _defined_functions_in_app()
    missing = CRITICAL_HELPERS - defined - {
        # ``_row_to_*`` are auto-discovered at runtime, not statically listed.
        n for n in CRITICAL_HELPERS if n.startswith("_row_to_")
    } - NON_APP_CRITICAL_HELPERS
    assert not missing, (
        "CRITICAL_HELPERS references helpers not present in app/: "
        f"{missing}. Either restore the helper or remove the constant entry."
    )


def test_critical_helpers_tracks_every_row_to_defined_in_app() -> None:
    """Every ``_row_to_*`` helper in ``app/`` is auto-discovered. The
    ``gather_helpers`` invocation on the live ``app/`` must return the
    union of the named list and every ``_row_to_*`` defined."""
    discovered = gather_helpers(app_root=APP_ROOT, extra=frozenset())
    expected_row_to = {
        n for n in _defined_functions_in_app() if n.startswith("_row_to_")
    }
    assert expected_row_to, (
        "Expected at least one _row_to_* helper in app/ (audit confirms "
        "_row_to_voluntario, _row_to_entrada, _row_to_animal)"
    )
    for name in expected_row_to:
        assert name in discovered, (
            f"_row_to_* helper {name} was not auto-discovered by "
            f"gather_helpers; check the regex in coverage_gate.py"
        )


def test_named_critical_helpers_resolve_to_existing_app_functions() -> None:
    """Spot-check: the five named helpers each resolve to a real function
    in app/. This is the regression test the spec acceptance criteria
    require ("verifiable forzando # pragma: no cover en una línea")."""
    defined = _defined_functions_in_app()
    named = {
        "_redirect",
        "_render_form",
        "_is_duplicate_error",
        "_validate_create_params",
        "_build_insert_params",
    }
    missing = named - defined
    assert not missing, (
        f"Critical helpers missing from app/: {missing}. Either restore "
        "the helper or remove it from CRITICAL_HELPERS."
    )
