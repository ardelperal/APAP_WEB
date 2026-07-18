"""Tests for the module-size ratchet (AGENTS.md rule 21, issue #202).

``scripts/check_module_size.py`` enforces the module-size budget: no
module under ``app/`` or ``migration/`` may exceed ``MAX_LINES`` (700)
lines, and the modules that already exceeded it when the rule landed
live in an explicit ``BASELINE`` that may only shrink (ratchet).

The checker is a stdlib-only script so the CI lint job can run it
without extra dependencies. These tests exercise its behavior against
synthetic trees (``tmp_path``), the real repository tree, and pin the
CI wiring in ``.github/workflows/ci.yml``.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_module_size.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_module_size", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_module(root: Path, rel_posix: str, lines: int) -> Path:
    path = root / Path(rel_posix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"x = {i}" for i in range(lines)) + "\n", encoding="utf-8")
    return path


def test_current_tree_passes_with_baseline() -> None:
    """The checker exits 0 on the repository as it stands.

    Every module over the budget must be in BASELINE at (at least) its
    current size — otherwise the gate would be born red.
    """
    checker = _load_checker()

    assert checker.main([str(REPO_ROOT)]) == 0


def test_baseline_matches_measured_tree() -> None:
    """BASELINE only lists real files, at their real (over-budget) size.

    A baseline entry larger than the file's actual line count would
    leave silent headroom for the module to grow back; an entry at or
    under MAX_LINES should simply not exist.
    """
    checker = _load_checker()

    assert checker.BASELINE, "expected a non-empty baseline of known offenders"
    for rel_posix, budget in checker.BASELINE.items():
        path = REPO_ROOT / Path(rel_posix)
        assert path.is_file(), f"stale BASELINE entry: {rel_posix}"
        actual = checker.count_lines(path)
        assert actual == budget, (
            f"{rel_posix}: BASELINE says {budget} lines but the file has "
            f"{actual} — re-measure and update BASELINE"
        )
        assert budget > checker.MAX_LINES, (
            f"{rel_posix}: baselined at {budget}, which is within the "
            f"{checker.MAX_LINES}-line budget — remove it from BASELINE"
        )


def test_flags_new_over_budget_module(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_module(tmp_path, "app/modules/foo/service.py", 812)
    _write_module(tmp_path, "migration/small.py", 10)

    violations, _notices = checker.check_tree(tmp_path, baseline={})

    assert len(violations) == 1
    assert "app/modules/foo/service.py" in violations[0]
    assert "812" in violations[0]
    assert str(checker.MAX_LINES) in violations[0]
    assert checker.main([str(tmp_path)]) == 1


def test_ratchet_flags_baselined_module_that_grew(tmp_path: Path) -> None:
    checker = _load_checker()
    _write_module(tmp_path, "migration/big.py", 990)

    violations, _notices = checker.check_tree(
        tmp_path, baseline={"migration/big.py": 976}
    )

    assert len(violations) == 1
    assert "migration/big.py" in violations[0]
    assert "990" in violations[0]
    assert "976" in violations[0]


def test_baselined_module_that_shrank_passes_and_suggests_baseline_update(
    tmp_path: Path,
) -> None:
    checker = _load_checker()
    _write_module(tmp_path, "migration/big.py", 940)

    violations, notices = checker.check_tree(
        tmp_path, baseline={"migration/big.py": 976}
    )

    assert violations == []
    assert len(notices) == 1
    assert "migration/big.py" in notices[0]
    assert "BASELINE" in notices[0]


def test_stale_baseline_entry_is_a_violation(tmp_path: Path) -> None:
    """A baseline entry for a deleted/renamed file must fail loudly.

    Otherwise the dict accumulates dead entries and a re-added file
    would inherit stale headroom.
    """
    checker = _load_checker()
    (tmp_path / "app").mkdir()

    violations, _notices = checker.check_tree(
        tmp_path, baseline={"app/gone.py": 800}
    )

    assert len(violations) == 1
    assert "app/gone.py" in violations[0]


def test_ignores_files_outside_app_and_migration(tmp_path: Path) -> None:
    """tests/ and scripts/ are exempt from the budget (only product code)."""
    checker = _load_checker()
    _write_module(tmp_path, "tests/test_huge.py", 900)
    _write_module(tmp_path, "scripts/huge_tool.py", 900)

    violations, notices = checker.check_tree(tmp_path, baseline={})

    assert violations == []
    assert notices == []


def test_ci_workflow_lint_job_runs_module_size_gate() -> None:
    """Issue #202: the CI ``lint`` job must gate on ``scripts/check_module_size.py``.

    The module-size ratchet (AGENTS.md rule 21) is only real if CI runs
    it. Same scoping rationale as
    ``test_ci_workflow_lint_job_runs_check_rules_gate``: slice the lint
    job's section and drop YAML comments so a comment mentioning the
    command can never satisfy the assertion. Removing this step from
    ci.yml is a blocked change.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  test:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_module_size.py" in executable, (
        "The lint job must run the module-size ratchet "
        "(python scripts/check_module_size.py) so the 700-line budget "
        "and the shrink-only baseline gate CI, not just PR review."
    )
