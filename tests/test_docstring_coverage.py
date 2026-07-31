"""Tests for the docstring-coverage ratchet (issue #339).

``scripts/check_docstring_coverage.py`` enforces that docstring coverage
in ``app/``, ``migration/``, and ``scripts/`` does not fall below
``BASELINE_COVERAGE_FLOOR``. This test module exercises its behavior
against synthetic trees and pins the CI wiring in ``ci.yml``.

Tests use the stdlib ``ast`` module directly so the ratchet's own
measurements are never shadowed by import-time side-effects.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_docstring_coverage.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_docstring_coverage", CHECKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_module(root: Path, rel_posix: str, content: str) -> Path:
    path = root / Path(rel_posix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ── Checker-level tests ─────────────────────────────────────────────────────


def test_checker_loaded_successfully() -> None:
    checker = _load_checker()
    assert hasattr(checker, "BASELINE_COVERAGE_FLOOR")
    assert hasattr(checker, "measure_total_coverage")
    assert callable(checker.measure_total_coverage)


def test_current_tree_passes() -> None:
    """Coverage on the current tree must be at or above the floor.

    The floor is pinned at the measured baseline so the gate is never
    born red.
    """
    checker = _load_checker()
    stats = checker.measure_total_coverage(REPO_ROOT)
    assert stats.is_acceptable(checker.BASELINE_COVERAGE_FLOOR)


def test_floor_is_not_below_73_percent() -> None:
    """The floor must be at least 73.0% — the audit's measured floor.

    This is a belt-and-suspenders check so the ratchet cannot be
    accidentally dropped to a trivially-easy value.
    """
    checker = _load_checker()
    assert checker.BASELINE_COVERAGE_FLOOR >= 73.0


def test_combined_stats_sum_from_parts() -> None:
    """The combined stats.total must equal the sum of module+class+func."""
    checker = _load_checker()
    mod, cls, fn = checker.measure_docstrings(REPO_ROOT)
    total = checker.measure_total_coverage(REPO_ROOT)
    assert total.total == mod.total + cls.total + fn.total
    assert total.documented == mod.documented + cls.documented + fn.documented


def test_no_double_counting() -> None:
    """A file with a module docstring, two classes (one with docstring),
    and three functions (two with docstrings) must be counted correctly."""
    checker = _load_checker()

    content = '''
"""Module docstring."""

class Foo:
    """Class docstring."""
    pass

class Bar:
    pass

def fn1():
    """Function docstring."""
    pass

def fn2():
    pass

def fn3():
    """Another docstring."""
    pass
'''
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_module(root, "app/example.py", content)
        mod, cls, fn = checker.measure_docstrings(root)

        assert mod.total == 1 and mod.documented == 1
        assert cls.total == 2 and cls.documented == 1
        assert fn.total == 3 and fn.documented == 2

        combined = checker.measure_total_coverage(root)
        assert combined.total == 6
        assert combined.documented == 4  # 1+1+2


def test_async_function_is_counted() -> None:
    """AsyncFunctionDef must be counted alongside FunctionDef."""
    checker = _load_checker()

    content = '''
async def async_fn():
    """Async docstring."""
    pass

def sync_fn():
    pass
'''
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_module(root, "app/async_mod.py", content)
        _mod, _cls, fn = checker.measure_docstrings(root)

        assert fn.total == 2
        assert fn.documented == 1


def test_empty_docstring_not_counted() -> None:
    """A docstring that is only whitespace is NOT counted as documented."""
    checker = _load_checker()

    content = '''
"""   """

def fn1():
    """   """
    pass
'''
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_module(root, "app/empty_doc.py", content)
        mod, cls, fn = checker.measure_docstrings(root)

        assert mod.documented == 0
        assert fn.documented == 0


def test_nested_functions_not_counted() -> None:
    """Only top-level definitions are counted (nested ones are stylistic)."""
    checker = _load_checker()

    content = '''
def outer():
    """Outer docstring."""
    def inner():
        """This is nested — should NOT be counted."""
        pass
    return inner
'''
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_module(root, "app/nested.py", content)
        _mod, _cls, fn = checker.measure_docstrings(root)

        # Only top-level FunctionDef is counted
        assert fn.total == 1
        assert fn.documented == 1


def test_ignores_pycache(tmp_path: Path) -> None:
    """Files under __pycache__ must not be scanned."""
    checker = _load_checker()
    pycache_dir = tmp_path / "app" / "__pycache__"
    pycache_dir.mkdir(parents=True)
    bad = pycache_dir / "c692b.py"
    bad.write_text('"""Should not be counted."""\npass\n', encoding="utf-8")

    mod, cls, fn = checker.measure_docstrings(tmp_path)

    assert mod.total == 0
    assert cls.total == 0
    assert fn.total == 0


def test_returns_zero_when_above_floor() -> None:
    """main() exits 0 when coverage is at or above the floor."""
    checker = _load_checker()
    # Current tree is above floor
    assert checker.main([str(REPO_ROOT)]) == 0


def test_returns_nonzero_when_below_floor(tmp_path: Path) -> None:
    """main() exits 1 when coverage drops below the floor."""
    checker = _load_checker()

    # A file with zero docstrings — creates coverage well below 73%
    content = """
def f():
    pass

class C:
    pass
"""
    _write_module(tmp_path, "app/sparse.py", content)
    _write_module(tmp_path, "migration/sparse.py", content)

    assert checker.main([str(tmp_path)]) == 1


# ── CI wiring tests ─────────────────────────────────────────────────────────


def test_ci_workflow_lint_job_runs_docstring_gate() -> None:
    """The CI ``lint`` job must gate on ``scripts/check_docstring_coverage.py``.

    Issue #339: removing this step from ci.yml is a blocked change.
    The docstring-coverage ratchet is only real if CI runs it.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  typecheck:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_docstring_coverage.py" in executable, (
        "The lint job must run the docstring-coverage ratchet "
        "(python scripts/check_docstring_coverage.py) so coverage is "
        "enforced in CI, not just at PR review time."
    )
