"""Tests for the AST-based rule linter (scripts/check_rules.py).

Per Slice 1 of hardening-2026-q2/specs/01-dev-tooling-gate/spec.md.
Parametrized suite proves each detector both directions plus the CLI contract.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_rules import (
    Violation,
    _is_client_execute_sql_call,
    find_violations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "_rule_helpers" / "fixtures"
SCRIPT = REPO_ROOT / "scripts" / "check_rules.py"


def _rule_violations(target: Path, rule_id: str) -> list[Violation]:
    return [v for v in find_violations(target) if v.rule_id == rule_id]


# --- per-detector parametrized suite --------------------------------------


@pytest.mark.parametrize(
    "fixture_subdir",
    [
        pytest.param("detector2_positive", id="auth_defaults_true_positive"),
        pytest.param("detector3_positive", id="http_exception_redirect_positive"),
        pytest.param("detector4_positive", id="hardcoded_role_check_positive"),
    ],
)
def test_detector_flags_seeded_violation(fixture_subdir: str) -> None:
    """Each positive fixture must produce a violation with its expected rule_id."""
    rule_id_by_dir = {
        "detector2_positive": "auth_defaults_true",
        "detector3_positive": "http_exception_redirect",
        "detector4_positive": "hardcoded_role_check_in_ddl",
    }
    rule_id = rule_id_by_dir[fixture_subdir]
    target = FIXTURES / fixture_subdir
    matching = _rule_violations(target, rule_id)
    assert matching, f"Expected {rule_id} in {target}; got no matches"
    assert all(isinstance(v, Violation) for v in matching)
    assert all(v.file.suffix == ".py" for v in matching)


@pytest.mark.parametrize(
    "fixture_subdir,forbidden_rule_id",
    [
        pytest.param("detector1_negative", "route_uses_execute_sql", id="rule1_clean"),
        pytest.param("detector2_negative", "auth_defaults_true", id="rule6_clean"),
        pytest.param("detector3_negative", "http_exception_redirect", id="rule7_clean"),
        pytest.param("detector4_negative", "hardcoded_role_check_in_ddl", id="rule4_clean"),
    ],
)
def test_detector_does_not_flag_clean_code(
    fixture_subdir: str, forbidden_rule_id: str
) -> None:
    """Clean fixtures must NOT trigger the corresponding detector."""
    target = FIXTURES / fixture_subdir
    matching = _rule_violations(target, forbidden_rule_id)
    assert not matching, f"False positive {forbidden_rule_id} in {target}: {matching}"


# --- Detector 1 detail: line must point at the call site, not the decorator


def test_detector1_violation_references_correct_line() -> None:
    """Violation's line must point at the execute_sql call inside the body."""
    fixture = FIXTURES / "detector1_positive" / "handler.py"
    expected_lines = {
        node.lineno
        for node in ast.walk(ast.parse(fixture.read_text(encoding="utf-8")))
        if _is_client_execute_sql_call(node)
    }
    assert expected_lines, "fixture must seed a client.execute_sql call"
    violations = _rule_violations(
        FIXTURES / "detector1_positive", "route_uses_execute_sql"
    )
    assert violations
    assert violations[0].line in expected_lines
    assert violations[0].file.name == "handler.py"


# --- CLI exit-code contract ----------------------------------------------


def test_cli_exits_zero_when_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / "detector1_negative")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 on clean fixture; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_cli_exits_one_when_violation_present() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / "detector1_positive")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Expected exit 1 on violation; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "route_uses_execute_sql" in result.stdout


# --- Detector 10 (Rule 25): duplicate_helper_definition -------------------


def test_detector10_flags_new_duplicate_beyond_baseline() -> None:
    """``_opt`` defined in two fixture files (neither in the real repo's
    BASELINE_DUPLICATE_HELPERS) must be flagged in both files."""
    target = FIXTURES / "detector10_violates"
    matching = _rule_violations(target, "duplicate_helper_definition")
    flagged_files = {v.file.name for v in matching}
    assert flagged_files == {"routes.py"}
    # Both the foo/ and bar/ copies must be flagged (2 distinct files).
    assert len({v.file for v in matching}) == 2


def test_detector10_does_not_flag_single_definition() -> None:
    """A watched name defined in exactly one file must NOT be flagged."""
    target = FIXTURES / "detector10_clean"
    matching = _rule_violations(target, "duplicate_helper_definition")
    assert not matching


def test_detector10_baseline_grandfathers_known_repo_duplication() -> None:
    """The real repo's known (#227) duplication must NOT be flagged —
    only NEW files beyond BASELINE_DUPLICATE_HELPERS would be."""
    matching = _rule_violations(REPO_ROOT, "duplicate_helper_definition")
    assert not matching, (
        "New duplicate_helper_definition violation(s) beyond the tracked "
        f"#227 baseline: {[(str(v.file), v.line) for v in matching]}"
    )


# --- Detector 11 (Rule 26): unjustified_lazy_import ------------------------


def test_detector11_flags_unjustified_lazy_import() -> None:
    target = FIXTURES / "detector11_violates"
    matching = _rule_violations(target, "unjustified_lazy_import")
    assert matching
    assert matching[0].file.name == "violating_handler.py"


def test_detector11_flags_empty_lazy_import_marker() -> None:
    target = FIXTURES / "detector11_empty_marker"
    matching = _rule_violations(target, "unjustified_lazy_import")
    assert matching


def test_detector11_allows_justified_lazy_import() -> None:
    target = FIXTURES / "detector11_clean"
    matching = _rule_violations(target, "unjustified_lazy_import")
    assert not matching


def test_detector11_repo_has_no_unjustified_lazy_imports() -> None:
    """The two known lazy imports (issue #226, config.py + auth_dependencies.py)
    both carry a 'lazy-import:' marker as of this rule landing."""
    matching = _rule_violations(REPO_ROOT, "unjustified_lazy_import")
    assert not matching, (
        f"Unjustified lazy import(s): {[(str(v.file), v.line) for v in matching]}"
    )


# --- Detector 12 (Rule 27): cross_module_submodule_import / _private_import


def test_detector12_flags_submodule_reach() -> None:
    target = FIXTURES / "detector12_violates_submodule"
    matching = _rule_violations(target, "cross_module_submodule_import")
    assert matching
    assert matching[0].file.name == "routes.py"


def test_detector12_flags_plain_import_submodule_reach() -> None:
    target = FIXTURES / "detector12_violates_import"
    matching = _rule_violations(target, "cross_module_submodule_import")
    assert matching
    assert matching[0].file.name == "routes.py"


def test_detector12_flags_private_name_import() -> None:
    target = FIXTURES / "detector12_violates_private"
    matching = _rule_violations(target, "cross_module_private_import")
    assert matching
    assert matching[0].file.name == "routes.py"


def test_detector12_does_not_flag_public_api_import() -> None:
    target = FIXTURES / "detector12_clean"
    matching = _rule_violations(
        target, "cross_module_submodule_import"
    ) + _rule_violations(target, "cross_module_private_import")
    assert not matching


def test_detector12_repo_only_has_the_known_baselined_violation() -> None:
    """The real repo must produce zero NEW cross-module violations beyond
    the single #231 baseline entry (foster/assignment.py -> animals.service).
    The acogidas/routes.py -> foster.assignment instance found by the same
    2026-07-20 review was fixed directly in this PR (import renamed to the
    public ``assignment_service`` alias foster/__init__.py already exports).
    """
    submodule = _rule_violations(REPO_ROOT, "cross_module_submodule_import")
    private = _rule_violations(REPO_ROOT, "cross_module_private_import")
    assert not private, (
        f"New cross_module_private_import violation(s): "
        f"{[(str(v.file), v.line) for v in private]}"
    )
    assert not submodule, (
        f"New cross_module_submodule_import violation(s) beyond the #231 "
        f"baseline: {[(str(v.file), v.line) for v in submodule]}"
    )
