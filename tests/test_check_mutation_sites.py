"""Tests for the mutation-site density ratchet (REQ-QG-MSITES-1)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_mutation_sites.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_mutation_sites", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _source() -> str:
    return (
        "def choose(value):\n"
        "    if value > 1:\n"
        "        return value + 1\n"
        "    return 0\n"
    )


def _lint_executable(workflow: str) -> str:
    start = workflow.index("\n  lint:")
    section = workflow[start : workflow.index("\n  security:", start)]
    return "\n".join(
        line for line in section.splitlines() if not line.lstrip().startswith("#")
    )


def test_counts_documented_ast_mutation_targets(tmp_path: Path) -> None:
    checker = _load_checker()
    path = _write(tmp_path, "app/sample.py", _source())

    assert checker.count_sites(path) == 8


def test_flags_new_file_over_budget(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/sample.py", _source())

    violations, notices = checker.check_tree(
        tmp_path,
        max_sites=7,
        baseline={},
    )

    assert notices == []
    assert len(violations) == 1
    assert "app/sample.py" in violations[0]
    assert "8 mutation sites" in violations[0]
    assert "check_module_size.py" in violations[0]


def test_ratchet_rejects_baselined_file_growth(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "migration/sample.py", _source())

    violations, notices = checker.check_tree(
        tmp_path,
        max_sites=250,
        baseline={"migration/sample.py": 7},
    )

    assert notices == []
    assert len(violations) == 1
    assert "grew beyond its baseline of 7" in violations[0]


def test_ratchet_reports_file_improvement(tmp_path: Path) -> None:
    checker = _load_checker()
    _write(tmp_path, "migration/sample.py", _source())

    violations, notices = checker.check_tree(
        tmp_path,
        max_sites=250,
        baseline={"migration/sample.py": 9},
    )

    assert violations == []
    assert len(notices) == 1
    assert "migration/sample.py" in notices[0]
    assert "lower BASELINE_MUTATION_SITES" in notices[0]


def test_stale_baseline_entry_is_a_violation(tmp_path: Path) -> None:
    checker = _load_checker()
    (tmp_path / "app").mkdir()

    violations, notices = checker.check_tree(
        tmp_path,
        baseline={"app/gone.py": 300},
    )

    assert notices == []
    assert len(violations) == 1
    assert "stale BASELINE_MUTATION_SITES" in violations[0]


def test_baseline_matches_current_tree_offenders() -> None:
    checker = _load_checker()
    measured = checker.measure_tree(REPO_ROOT)
    offenders = {
        rel: sites
        for rel, sites in measured.items()
        if sites > checker.MAX_MUTATION_SITES_PER_FILE
    }

    assert checker.BASELINE_MUTATION_SITES == offenders
    violations, _notices = checker.check_tree(REPO_ROOT)
    assert violations == []


def test_emit_baseline_prints_current_offenders(
    tmp_path: Path,
    capsys,
) -> None:
    checker = _load_checker()
    _write(tmp_path, "app/sample.py", _source())

    assert checker.main(["--emit-baseline", "--max-sites", "7", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "BASELINE_MUTATION_SITES" in output
    assert '"app/sample.py": 8' in output


def test_ci_workflow_lint_job_runs_mutation_sites_after_jscpd() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    executable = _lint_executable(workflow)

    assert "python scripts/check_mutation_sites.py" in executable
    assert executable.index("python scripts/check_mutation_sites.py") > executable.index(
        "python scripts/check_jscpd.py"
    )
