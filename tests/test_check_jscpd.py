"""Tests for the stdlib AST duplicate-code ratchet (REQ-QG-DRY-1)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_jscpd.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_jscpd", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _clone(name: str, value_name: str) -> str:
    checks = "\n".join(
        f"    if {value_name} == {index}:\n        return {index}"
        for index in range(1, 9)
    )
    return f"def {name}({value_name}):\n{checks}\n    return 0\n"


def _lint_executable(workflow: str) -> str:
    start = workflow.index("\n  lint:")
    section = workflow[start : workflow.index("\n  security:", start)]
    return "\n".join(
        line for line in section.splitlines() if not line.lstrip().startswith("#")
    )


def test_module_docstring_explains_deliberate_jscpd_name() -> None:
    checker = _load_checker()

    assert checker.__doc__.startswith(
        "This script is named check_jscpd.py per the spec (REQ-QG-DRY-1) "
        "and the proposal (quality-gates-expansion). It does NOT invoke the "
        "jscpd binary"
    )


def test_identical_normalized_functions_exceed_baseline(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/one.py", _clone("first", "value"))
    _write(tmp_path, "migration/two.py", _clone("second", "candidate"))

    violations, notices = checker.check_tree(tmp_path, baseline_pct=15.0)

    assert notices == []
    assert len(violations) == 1
    assert "app/one.py::first" in violations[0]
    assert "migration/two.py::second" in violations[0]
    assert "tokens" in violations[0]


def test_unique_functions_pass(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/one.py", _clone("first", "value"))
    _write(
        tmp_path,
        "migration/two.py",
        "def second(candidate):\n    return candidate * candidate\n",
    )

    violations, notices = checker.check_tree(tmp_path, baseline_pct=15.0)

    assert violations == []
    assert len(notices) == 1
    assert "lower BASELINE_JSCPD_PCT" in notices[0]


def test_tiny_duplicate_functions_are_below_clone_threshold(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/one.py", "def first(value):\n    return value\n")
    _write(tmp_path, "migration/two.py", "def second(candidate):\n    return candidate\n")

    percentage, regions = checker.measure_tree(tmp_path)

    assert percentage == 0.0
    assert regions == []


def test_baseline_improvement_prints_note(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/unique.py", "def unique(value):\n    return value + 1\n")

    violations, notices = checker.check_tree(tmp_path, baseline_pct=15.0)

    assert violations == []
    assert len(notices) == 1
    assert "0.00%" in notices[0]
    assert "15.00%" in notices[0]


def test_current_tree_is_at_or_below_baseline() -> None:
    checker = _load_checker()

    percentage, _regions = checker.measure_tree(REPO_ROOT)
    violations, _notices = checker.check_tree(REPO_ROOT)

    assert percentage <= checker.BASELINE_JSCPD_PCT
    assert violations == []


def test_emit_baseline_reports_measured_percentage(
    tmp_path: Path,
    capsys,
) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/one.py", _clone("first", "value"))
    _write(tmp_path, "migration/two.py", _clone("second", "candidate"))

    assert checker.main(["--emit-baseline", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "BASELINE_JSCPD_PCT" in output
    assert "%" in output


def test_ci_workflow_lint_job_runs_jscpd_gate_after_vulture() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    executable = _lint_executable(workflow)

    assert "python scripts/check_jscpd.py" in executable
    assert executable.index("python scripts/check_jscpd.py") > executable.index(
        "python scripts/check_vulture_guard.py"
    )
