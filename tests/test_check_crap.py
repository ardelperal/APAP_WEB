"""Tests for the per-function CRAP score ratchet (REQ-QG-CRAP-1)."""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_crap.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_crap", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_module(root: Path, source: str) -> Path:
    path = root / "app" / "sample.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _write_coverage(
    root: Path,
    *,
    executed: list[int],
    missing: list[int],
) -> Path:
    coverage_path = root / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "files": {
                    "app/sample.py": {
                        "executed_lines": executed,
                        "missing_lines": missing,
                        "excluded_lines": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return coverage_path


def _risky_source() -> str:
    return (
        "def risky(value):\n"
        "    if value == 1:\n"
        "        return 1\n"
        "    if value == 2:\n"
        "        return 2\n"
        "    if value == 3:\n"
        "        return 3\n"
        "    if value == 4:\n"
        "        return 4\n"
        "    if value == 5:\n"
        "        return 5\n"
        "    return 0\n"
    )


def _job_executable(workflow: str, start: str, end: str) -> str:
    start_index = workflow.index(start)
    section = workflow[start_index : workflow.index(end, start_index)]
    return "\n".join(
        line for line in section.splitlines() if not line.lstrip().startswith("#")
    )


def test_grade_a_function_passes_without_baseline(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_module(tmp_path, "def simple(value):\n    return value + 1\n")
    _write_coverage(tmp_path, executed=[1, 2], missing=[])

    violations, notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []
    assert notices == []


def test_flags_new_function_outside_grade_a(tmp_path: Path) -> None:
    checker = _load_checker()
    source = _risky_source()
    _write_module(tmp_path, source)
    _write_coverage(tmp_path, executed=[], missing=list(range(1, 13)))

    violations, notices = checker.check_tree(tmp_path, baseline={})

    assert notices == []
    assert len(violations) == 1
    assert "app/sample.py::risky" in violations[0]
    assert "CRAP=" in violations[0]
    assert "grade A" in violations[0]


def test_ratchet_rejects_score_growth(tmp_path: Path) -> None:
    checker = _load_checker()
    source = _risky_source()
    _write_module(tmp_path, source)
    _write_coverage(tmp_path, executed=[], missing=list(range(1, 13)))
    score = checker.measure_tree(tmp_path)["app/sample.py::risky"]

    violations, notices = checker.check_tree(
        tmp_path,
        baseline={"app/sample.py::risky": score - 0.01},
    )

    assert notices == []
    assert len(violations) == 1
    assert "grew beyond its baseline" in violations[0]


def test_ratchet_reports_score_improvement(tmp_path: Path) -> None:
    checker = _load_checker()
    source = _risky_source()
    _write_module(tmp_path, source)
    _write_coverage(tmp_path, executed=list(range(1, 13)), missing=[])
    score = checker.measure_tree(tmp_path)["app/sample.py::risky"]

    violations, notices = checker.check_tree(
        tmp_path,
        baseline={"app/sample.py::risky": score + 1.0},
    )

    # ``_check_measured_scores`` still surfaces the improvement as a NOTICE
    # (informational, "lock in the new score"), but the strict-equality
    # contract promoted by ``check_baseline_exactness`` (issue #540)
    # upgrades it to a VIOLATION — the operator must either refresh the
    # baseline or roll back the improvement.
    assert len(violations) == 1
    assert "app/sample.py::risky" in violations[0]
    assert "improved below its baseline" in violations[0]
    assert len(notices) == 1
    assert "app/sample.py::risky" in notices[0]
    assert "update BASELINE_CRAP" in notices[0]


def test_missing_coverage_json_is_an_advisory_skip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = _load_checker()
    _write_module(tmp_path, _risky_source())

    assert checker.main([str(tmp_path)]) == 0
    assert (
        "NOTE: coverage.json missing — CRAP check skipped (run pytest --cov first)"
        in capsys.readouterr().out
    )


def test_malformed_coverage_json_fails_loudly(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_module(tmp_path, _risky_source())
    (tmp_path / "coverage.json").write_text("not-json", encoding="utf-8")

    violations, notices = checker.check_tree(tmp_path, baseline={})

    assert notices == []
    assert len(violations) == 1
    assert "coverage.json" in violations[0]
    assert "cannot parse" in violations[0]


def test_coverage_omitted_adapter_is_not_measured(tmp_path: Path) -> None:
    checker = _load_checker()
    adapter = tmp_path / "app" / "core" / "insforge.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(_risky_source(), encoding="utf-8")
    (tmp_path / "coverage.json").write_text(
        json.dumps({"files": {}}),
        encoding="utf-8",
    )

    measured = checker.measure_tree(tmp_path)

    assert "app/core/insforge.py::risky" not in measured


def test_baseline_file_without_coverage_record_is_skipped(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    _write_module(tmp_path, _risky_source())
    (tmp_path / "coverage.json").write_text(
        json.dumps({"files": {}}),
        encoding="utf-8",
    )

    violations, notices = checker.check_tree(
        tmp_path,
        baseline={"app/sample.py::risky": 42.0},
    )

    assert violations == []
    assert len(notices) == 1
    assert "no coverage record" in notices[0]


def test_baseline_matches_current_measured_offenders(tmp_path: Path) -> None:
    """``BASELINE_CRAP`` must stay in sync with the measured offenders.

    This test was previously a stand-alone assertion that ran only when
    ``coverage.json`` happened to exist at collection time. Because
    ``pytest --cov-report=json`` writes ``coverage.json`` only at session
    end, the assertion always skipped in CI (issue #540). The contract
    moved into ``scripts.check_crap.check_baseline_exactness``, which the
    CI ``test`` job runs against the freshly-written ``coverage.json``
    immediately after pytest.

    This test exercises the new function directly against a fixture
    ``coverage.json`` + module, so the assertion runs in every pytest
    invocation regardless of whether the real ``coverage.json`` exists.
    """
    checker = _load_checker()

    # Case 1: empty baseline, no offenders → no drift.
    _write_module(tmp_path, "def simple(value):\n    return value + 1\n")
    _write_coverage(tmp_path, executed=[1, 2], missing=[])
    measured = checker.measure_tree(tmp_path)

    violations, notices = checker.check_baseline_exactness(measured, {})
    assert violations == []
    assert notices == []

    # Case 2: a baseline entry references a function whose score improved
    # below its budget → violation. ``_check_measured_scores`` would emit
    # this as a NOTICE; ``check_baseline_exactness`` promotes it to a
    # VIOLATION so the strict-equality invariant can never drift silently.
    _write_module(tmp_path, _risky_source())
    _write_coverage(tmp_path, executed=list(range(1, 13)), missing=[])
    measured = checker.measure_tree(tmp_path)
    improved_score = measured["app/sample.py::risky"]

    violations, notices = checker.check_baseline_exactness(
        measured,
        {"app/sample.py::risky": improved_score + 5.0},
    )
    assert notices == []
    assert len(violations) == 1
    assert "improved below its baseline" in violations[0]
    assert "app/sample.py::risky" in violations[0]

    # Case 3: a baseline entry whose function no longer exists at all →
    # ``check_baseline_exactness`` defers to ``_check_stale_baseline``
    # (which can distinguish "function gone" from "file has no coverage
    # record"), so this function emits no violation on its own.
    _write_module(tmp_path, "def simple(value):\n    return value + 1\n")
    _write_coverage(tmp_path, executed=[1, 2], missing=[])
    measured = checker.measure_tree(tmp_path)

    violations, notices = checker.check_baseline_exactness(
        measured,
        {"app/sample.py::gone_function": 42.0},
    )
    assert violations == []
    assert notices == []

    # Case 4: regression (measured > budget) is also not this function's
    # concern — ``_check_measured_scores`` already catches it as a
    # VIOLATION. ``check_baseline_exactness`` only emits on improvements
    # (measured < budget), so a regression here produces no violation.
    violations, notices = checker.check_baseline_exactness(
        measured,
        {"app/sample.py::simple": measured["app/sample.py::simple"] - 5.0},
    )
    assert violations == []
    assert notices == []


def test_emit_baseline_prints_measured_offenders(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = _load_checker()
    source = _risky_source()
    _write_module(tmp_path, source)
    _write_coverage(tmp_path, executed=[], missing=list(range(1, 13)))

    assert checker.main(["--emit-baseline", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "BASELINE_CRAP" in output
    assert '"app/sample.py::risky"' in output


def test_ci_workflow_test_job_runs_crap_gate_after_pytest() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    test_job = _job_executable(workflow, "\n  test:", "\n  integration:")

    assert "python scripts/check_crap.py" in test_job
    assert test_job.index("python scripts/check_crap.py") > test_job.index(
        "python -m pytest -W error::DeprecationWarning"
    )


def test_ci_workflow_lint_job_does_not_run_crap_gate() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_job = _job_executable(workflow, "\n  lint:", "\n  security:")

    assert "python scripts/check_crap.py" not in lint_job
