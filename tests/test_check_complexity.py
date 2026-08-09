"""Tests for the cyclomatic-complexity ceiling (AGENTS.md rule 21).

This gate shipped without tests and, until 2026-08-08, iterated ``BASELINE_CC`` — so it measured
the two functions listed there and nothing else. The first test below is the regression pin for
that defect: a gate that only inspects its own allowlist reports a clean codebase for the 899
functions it never looked at.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_complexity.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_complexity", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _branchy(name: str, branches: int) -> str:
    """A function whose CC is ``branches + 1``."""
    body = "\n".join(
        f"    if value == {index}:\n        return {index}" for index in range(branches)
    )
    return f"def {name}(value):\n{body}\n    return -1\n"


def test_gate_measures_every_function_not_only_the_baseline(tmp_path):
    """Regression pin: the gate must not iterate BASELINE_CC.

    The offender below is absent from BASELINE_CC. A gate scoped to its own allowlist reports
    this tree as clean.
    """
    module = _load_checker()
    module.BASELINE_CC = {}
    _write(tmp_path, "app/routes.py", _branchy("over_budget", module.MAX_CC + 5))

    measured, errors = module.measure(tmp_path)
    assert not errors
    assert ("app/routes.py", "over_budget") in measured

    violations, _ = module.check_complexity(tmp_path)
    assert any("over_budget" in item for item in violations), violations


def test_methods_and_closures_are_measured(tmp_path):
    """Only module-level functions used to be reachable, so methods were invisible."""
    module = _load_checker()
    module.BASELINE_CC = {}
    _write(
        tmp_path,
        "app/service.py",
        "class Service:\n"
        + "\n".join(
            f"    def method_{index}(self, value):\n        return value\n" for index in range(2)
        )
        + "\ndef outer(value):\n    def inner(other):\n        return other\n    return inner\n",
    )
    measured, _ = module.measure(tmp_path)
    assert ("app/service.py", "Service.method_0") in measured
    assert ("app/service.py", "outer.inner") in measured


def test_nested_branches_are_not_double_counted(tmp_path):
    """A closure's branches belong to the closure, not to its parent.

    Otherwise a parent's number depends on its children and the same branch is counted twice.
    """
    module = _load_checker()
    module.BASELINE_CC = {}
    _write(
        tmp_path,
        "app/service.py",
        "def outer(value):\n"
        "    def inner(other):\n"
        "        if other:\n"
        "            return 1\n"
        "        return 2\n"
        "    return inner\n",
    )
    measured, _ = module.measure(tmp_path)
    assert measured[("app/service.py", "outer")] == 1
    assert measured[("app/service.py", "outer.inner")] == 2


def test_function_within_budget_passes(tmp_path):
    module = _load_checker()
    module.BASELINE_CC = {}
    _write(tmp_path, "app/routes.py", _branchy("fine", 3))
    violations, _ = module.check_complexity(tmp_path)
    assert violations == []


def test_baseline_entry_may_not_grow(tmp_path):
    module = _load_checker()
    _write(tmp_path, "app/routes.py", _branchy("tracked", 4))
    module.BASELINE_CC = {("app/routes.py", "tracked"): 3}
    violations, _ = module.check_complexity(tmp_path)
    assert any("may only decrease" in item for item in violations), violations


def test_baseline_entry_below_its_budget_is_a_notice(tmp_path):
    module = _load_checker()
    _write(tmp_path, "app/routes.py", _branchy("tracked", 2))
    module.BASELINE_CC = {("app/routes.py", "tracked"): 9}
    violations, notices = module.check_complexity(tmp_path)
    assert violations == []
    assert any("lock in the improvement" in item for item in notices), notices


def test_stale_baseline_entry_fails(tmp_path):
    """An entry pointing at a function that no longer exists is silent rot."""
    module = _load_checker()
    module.BASELINE_CC = {("app/gone.py", "vanished"): 3}
    _write(tmp_path, "app/routes.py", _branchy("fine", 2))
    violations, _ = module.check_complexity(tmp_path)
    assert any("no such function" in item for item in violations), violations


def test_unparseable_file_is_a_violation_not_a_skip(tmp_path):
    """A file the gate cannot inspect must never count as a clean file."""
    module = _load_checker()
    module.BASELINE_CC = {}
    _write(tmp_path, "app/broken.py", "def oops(:\n    pass\n")
    violations, _ = module.check_complexity(tmp_path)
    assert any("syntax error" in item for item in violations), violations


def test_repository_is_within_its_ratchet():
    """The real tree must stay green, so CI does not go red on an unrelated PR."""
    module = _load_checker()
    violations, _ = module.check_complexity(REPO_ROOT)
    assert violations == [], violations


def test_ci_workflow_runs_the_complexity_gate():
    """Wiring pin: the gate existed in CI but nothing asserted it stayed there."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "python scripts/check_complexity.py" in workflow
