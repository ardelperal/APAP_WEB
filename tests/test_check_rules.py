"""Tests for the AST-based rule linter (scripts/check_rules.py).

Per Slice 1 of ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``.

The parametrized suite proves each detector both directions:

  - **positive**: a seeded fixture must produce a violation with the
    expected ``rule_id``.
  - **negative**: a clean fixture must NOT trigger any detector.

Two additional CLI tests assert the exit-code contract (0 when clean,
1 when violations exist). Detectors 2/3/4 land in commit 4.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_rules import Violation, _is_client_execute_sql_call, find_violations

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "_rule_helpers" / "fixtures"
SCRIPT = REPO_ROOT / "scripts" / "check_rules.py"


# --- Detector 1 (Rule 1): client.execute_sql in route handlers -----------


def test_detector1_flags_post_route_calling_execute_sql() -> None:
    """POST handler with client.execute_sql must be flagged."""
    violations = find_violations(FIXTURES / "detector1_positive")
    matching = [v for v in violations if v.rule_id == "route_uses_execute_sql"]
    assert matching, f"Expected route_uses_execute_sql; got: {violations}"
    assert all(isinstance(v, Violation) for v in matching)


def test_detector1_does_not_flag_get_route_calling_execute_sql() -> None:
    """GET handler with client.execute_sql is allowed (spec REQ-1 scenario 2)."""
    violations = find_violations(FIXTURES / "detector1_negative")
    matching = [v for v in violations if v.rule_id == "route_uses_execute_sql"]
    assert not matching, (
        f"GET handler must be exempt; got false positives: {matching}"
    )


def test_detector1_violation_references_correct_line() -> None:
    """The Violation's line must point at the execute_sql call inside the body."""
    import ast

    fixture = FIXTURES / "detector1_positive" / "handler.py"
    source = fixture.read_text(encoding="utf-8")
    expected_lines = {
        node.lineno
        for node in ast.walk(ast.parse(source))
        if _is_client_execute_sql_call(node)
    }
    assert expected_lines, "fixture must seed a client.execute_sql call"
    violations = find_violations(FIXTURES / "detector1_positive")
    matching = [v for v in violations if v.rule_id == "route_uses_execute_sql"]
    assert matching
    assert matching[0].line in expected_lines
    assert matching[0].file.name == "handler.py"


# --- CLI exit-code contract ----------------------------------------------


def test_cli_exits_zero_when_clean() -> None:
    """The clean fixture directory contains no violations; CLI exits 0."""
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
    """The positive fixture directory has at least one violation; CLI exits 1."""
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
