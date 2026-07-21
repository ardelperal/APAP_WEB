"""Tests for the critical-helpers pytest coverage gate (PR-1B).

Spec: ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
(REQ-3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.pytest_plugin import coverage_gate
from scripts.pytest_plugin.coverage_gate import (
    CRITICAL_HELPERS,
    evaluate_coverage,
    gather_helpers,
)

# --- CRITICAL_HELPERS contract -------------------------------------------


def test_critical_helpers_constant_is_frozenset() -> None:
    """The contract: a frozenset so adding a helper is one-line."""
    assert isinstance(CRITICAL_HELPERS, frozenset)


def test_critical_helpers_contains_named_list() -> None:
    """The five named helpers per spec REQ-3 and tasks.md T-1B.4."""
    required = {
        "_redirect",
        "_render_form",
        "_is_duplicate_error",
        "_validate_create_params",
        "_build_insert_params",
    }
    missing = required - CRITICAL_HELPERS
    assert not missing, (
        f"CRITICAL_HELPERS missing required named entries: {missing}"
    )


def test_critical_helpers_discoverable_via_gather(tmp_path: Path) -> None:
    """``gather_helpers`` must auto-discover any ``_row_to_*`` function
    in ``app/`` so adding a new mapper is automatic (T-1B.4 second clause).
    """
    app_root = tmp_path / "app"
    pkg = app_root / "modules" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "service.py").write_text(
        "def _row_to_xyz(row: dict) -> dict:\n"
        "    return row\n"
        "def _row_to_abc(row: dict) -> dict:\n"
        "    return row\n"
        "def not_a_row_to(row: dict) -> dict:\n"
        "    return row\n",
        encoding="utf-8",
    )
    discovered = gather_helpers(app_root=app_root, extra=frozenset())
    assert "_row_to_xyz" in discovered
    assert "_row_to_abc" in discovered
    assert "not_a_row_to" not in discovered


# --- evaluate_coverage contract ------------------------------------------


def _coverage_data(entries: dict[str, float]) -> dict[str, Any]:
    """Build a synthetic coverage.json with ``entries = {func_name: pct}``."""
    return {
        "files": {
            "app/synthetic.py": {
                "functions": {
                    name: {
                        "summary": {"percent_covered": pct},
                        "missing_lines": [] if pct == 100.0 else [1],
                    }
                    for name, pct in entries.items()
                }
            }
        }
    }


def test_evaluate_coverage_passes_when_all_critical_at_100() -> None:
    """Happy path: every CRITICAL_HELPER at 100% → gate passes."""
    data = _coverage_data(
        {name: 100.0 for name in ("_redirect", "_render_form")}
    )
    passed, failed = evaluate_coverage(
        data, frozenset({"_redirect", "_render_form"})
    )
    assert passed is True
    assert failed == []


def test_evaluate_coverage_fails_when_helper_below_100() -> None:
    """REQ-3 Scenario 1: dropping a critical helper to 99% must fail."""
    data = _coverage_data({"_redirect": 99.0, "_render_form": 100.0})
    passed, failed = evaluate_coverage(
        data, frozenset({"_redirect", "_render_form"})
    )
    assert passed is False
    assert len(failed) == 1
    name, pct = failed[0]
    assert name == "_redirect"
    assert pct == pytest.approx(99.0)


def test_evaluate_coverage_warning_when_helpers_empty() -> None:
    """REQ-3 Scenario 2: empty CRITICAL_HELPERS must NOT fail (warning only).

    First-deploy safety: if the constant is empty by misconfiguration the
    suite still passes; the warning surfaces in the pytest summary."""
    data = _coverage_data({})
    passed, failed = evaluate_coverage(data, frozenset())
    assert passed is True, (
        "Empty CRITICAL_HELPERS must return passed=True (warning only)"
    )
    assert failed == []


def test_evaluate_coverage_reports_all_below_threshold() -> None:
    """If multiple helpers drop, all are reported (not just the first)."""
    data = _coverage_data({"_redirect": 50.0, "_render_form": 75.0})
    passed, failed = evaluate_coverage(
        data, frozenset({"_redirect", "_render_form"})
    )
    assert passed is False
    names = {n for n, _ in failed}
    assert names == {"_redirect", "_render_form"}


def test_evaluate_coverage_handles_missing_function() -> None:
    """A helper that does not appear in coverage.json counts as 0%."""
    data = _coverage_data({})  # no functions at all
    passed, failed = evaluate_coverage(
        data, frozenset({"_redirect", "_render_form"})
    )
    assert passed is False
    assert {n for n, _ in failed} == {"_redirect", "_render_form"}


# --- CLI contract --------------------------------------------------------


def test_cli_writes_summary_when_clean(tmp_path: Path, capsys) -> None:
    """``coverage_gate.main`` exits 0 on a passing gate and prints summary."""
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(
        json.dumps(_coverage_data({"_redirect": 100.0})), encoding="utf-8"
    )
    rc = coverage_gate.main(
        [
            "--coverage-file",
            str(cov_path),
            "--helpers",
            "_redirect",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "_redirect" in out
    assert "100" in out


def test_cli_exits_1_when_helper_below_100(tmp_path: Path) -> None:
    """On failure the CLI exits non-zero (CI gate)."""
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(
        json.dumps(_coverage_data({"_redirect": 90.0})), encoding="utf-8"
    )
    with pytest.raises(SystemExit) as exc_info:
        coverage_gate.main(
            [
                "--coverage-file",
                str(cov_path),
                "--helpers",
                "_redirect",
            ]
        )
    assert exc_info.value.code == 1


# --- pytest-plugin hook contract (issue #257) -----------------------------
#
# Regression coverage for issue #257: the pytest-plugin hook printed a red
# "coverage-gate FAIL" banner but the *actual pytest process* still exited
# 0, because ``pytest_terminal_summary`` mutated ``config.exitstatus`` —
# which ``_pytest.main.wrap_session`` never reads back; only
# ``session.exitstatus`` is returned as the process exit code. These tests
# use the ``pytester`` fixture (registered via ``pytest_plugins`` in
# ``tests/conftest.py``) to run a nested, isolated pytest process and
# assert on its real ``result.ret`` — not just banner text in stdout.


def _make_synthetic_project(pytester: pytest.Pytester) -> None:
    """A trivial one-test project that registers the coverage-gate plugin."""
    pytester.makepyfile(
        test_dummy="""
        def test_ok():
            assert True
        """
    )
    pytester.makeini(
        """
        [pytest]
        addopts = -p scripts.pytest_plugin.coverage_gate
        """
    )


def test_pytest_plugin_hook_fails_process_exit_code_on_gate_failure(
    pytester: pytest.Pytester,
) -> None:
    """Issue #257: a gate failure must make the nested pytest PROCESS exit
    non-zero, not just print a red banner.

    ``_redirect`` is a real ``CRITICAL_HELPERS`` entry (hardcoded in the
    module), so reporting it below 100% in a synthetic ``coverage.json``
    exercises the exact same helper set the real CI gate tracks — no
    override mechanism needed.
    """
    _make_synthetic_project(pytester)
    (pytester.path / "coverage.json").write_text(
        json.dumps(_coverage_data({"_redirect": 50.0})), encoding="utf-8"
    )
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)  # the single synthetic test itself passes
    result.stdout.fnmatch_lines(["*coverage-gate FAIL*"])
    assert result.ret != 0, (
        "pytest process must exit non-zero when the coverage gate fails "
        "(issue #257: config.exitstatus is a no-op; session.exitstatus is "
        "what wrap_session() actually returns)"
    )
    assert result.ret == 1


def test_pytest_plugin_hook_exits_zero_when_gate_passes(
    pytester: pytest.Pytester,
) -> None:
    """Companion test: a genuinely passing gate must NOT fail the process.

    Guards against a naive fix that always sets ``session.exitstatus = 1``
    regardless of ``evaluate_coverage``'s verdict.
    """
    _make_synthetic_project(pytester)
    all_at_100 = {name: 100.0 for name in CRITICAL_HELPERS}
    (pytester.path / "coverage.json").write_text(
        json.dumps(_coverage_data(all_at_100)), encoding="utf-8"
    )
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*coverage-gate PASS*"])
    assert result.ret == 0
