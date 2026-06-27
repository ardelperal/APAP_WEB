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
