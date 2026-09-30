"""Behaviour tests for ``scripts/preflight.py`` (issue #1119).

Temporary workflows prove that preflight executes whatever the ``lint``
job declares (so a new step needs no change here), that a red step is
named without hiding the later ones, and that a broken workflow exits 2.

Opt-in heavy smokes run the full pipeline (``RUN_PREFLIGHT_SMOKE=1``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import preflight

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

WORKFLOW_TEMPLATE = """\
name: tmp
on: push
jobs:
  lint:
    runs-on: ubuntu-24.04
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
{steps}
  other:
    runs-on: ubuntu-24.04
    steps:
      - name: Not a lint step
        run: echo other-job-step-must-not-run
"""


def _write_workflow(tmp_path: Path, steps: list[tuple[str, str]]) -> Path:
    """Write a temporary workflow whose lint job holds the given ``run`` steps."""
    blocks = []
    for name, command in steps:
        body = command.replace("\n", "\n          ")
        blocks.append(f"      - name: {name}\n        run: |\n          {body}")
    path = tmp_path / "wf.yml"
    path.write_text(WORKFLOW_TEMPLATE.format(steps="\n".join(blocks)), encoding="utf-8")
    return path


def test_extra_lint_step_in_workflow_is_executed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A step added to the workflow runs without any change to preflight.py."""
    workflow = _write_workflow(
        tmp_path,
        [("first", "true"), ("brand-new-step", "echo marker > ran.txt")],
    )

    code = preflight.main(["--workflow", str(workflow), "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert (tmp_path / "ran.txt").read_text(encoding="utf-8").strip() == "marker"
    assert "PASS brand-new-step" in out
    assert "Not a lint step" not in out
    assert "Check out repository" not in out


def test_failing_step_is_named_and_remaining_steps_still_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One red step does not hide the later ones; the aggregate exit is 1."""
    workflow = _write_workflow(
        tmp_path,
        [("red-step", "exit 3"), ("green-after-red", "echo still > after.txt")],
    )

    code = preflight.main(["--workflow", str(workflow), "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL red-step (exit 3)" in out
    assert "PASS green-after-red" in out
    assert (tmp_path / "after.txt").is_file()


def test_multiline_step_aborts_at_first_failing_command(tmp_path: Path) -> None:
    """GitHub runs ``bash -e``: a failing command must stop the step."""
    workflow = _write_workflow(tmp_path, [("errexit", "false\necho reached > reached.txt")])

    code = preflight.main(["--workflow", str(workflow), "--root", str(tmp_path)])

    assert code == 1
    assert not (tmp_path / "reached.txt").exists()


def test_missing_workflow_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = preflight.main(["--workflow", str(tmp_path / "nope.yml")])

    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_workflow_without_lint_job_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "wf.yml"
    workflow.write_text(
        "on: push\njobs:\n  test:\n    steps:\n      - run: true\n",
        encoding="utf-8",
    )

    code = preflight.main(["--workflow", str(workflow)])

    assert code == 2
    assert "no 'lint' job" in capsys.readouterr().err


def test_malformed_yaml_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workflow = tmp_path / "wf.yml"
    workflow.write_text("jobs: [unclosed\n  - : :", encoding="utf-8")

    code = preflight.main(["--workflow", str(workflow)])

    assert code == 2
    assert "preflight:" in capsys.readouterr().err


def test_step_with_github_expression_is_refused_not_executed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bash cannot evaluate ``${{ }}``: refuse loudly instead of running it."""
    workflow = _write_workflow(
        tmp_path, [("needs-expression", "echo x > ran.txt ${{ github.sha }}")]
    )

    code = preflight.main(["--workflow", str(workflow), "--root", str(tmp_path)])

    assert code == 2
    assert "needs-expression" in capsys.readouterr().err
    assert not (tmp_path / "ran.txt").exists()


def test_list_prints_steps_without_running_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = _write_workflow(tmp_path, [("listed", "echo x > ran.txt")])

    code = preflight.main(["--workflow", str(workflow), "--root", str(tmp_path), "--list"])

    assert code == 0
    assert "listed" in capsys.readouterr().out
    assert not (tmp_path / "ran.txt").exists()


def test_shipped_workflow_lint_job_is_runnable_by_preflight() -> None:
    """The real ci.yml lint job parses, has run steps and no ``${{`` step."""
    steps = preflight.lint_steps_from_ci(WORKFLOW_PATH)

    assert len(steps) >= 5


def test_preflight_outputs_pass_fail_per_step(capsys: pytest.CaptureFixture[str]) -> None:
    """Each step must be reported as PASS or FAIL with its ci.yml step name."""
    ok = ("echo-OK-from-preflight-test", "echo OK-from-preflight-test")
    bad = ("echo-FAIL-from-preflight-test", "exit 7")

    exit_code = preflight.run([ok, bad], root=REPO_ROOT)
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "PASS echo-OK-from-preflight-test" in captured.out
    assert "FAIL echo-FAIL-from-preflight-test (exit 7)" in captured.out


def test_preflight_run_exits_zero_when_all_steps_pass(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sanity: when every fake step exits 0, preflight.run returns 0."""
    steps = [
        ("echo-OK-1-from-preflight-test", "true"),
        ("echo-OK-2-from-preflight-test", "true"),
    ]
    exit_code = preflight.run(steps, root=REPO_ROOT)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "PASS echo-OK-1-from-preflight-test" in captured.out
    assert "PASS echo-OK-2-from-preflight-test" in captured.out
    assert "preflight: PASSED" in captured.out


def test_bash_that_cannot_start_is_an_environment_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A spawn failure (bash missing from PATH) must exit 2 with a message, not a traceback."""

    def _cannot_spawn(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory: 'bash'")

    monkeypatch.setattr(preflight.subprocess, "run", _cannot_spawn)

    exit_code = preflight.run([("any-step", "true")], root=REPO_ROOT)
    captured = capsys.readouterr()

    assert exit_code == preflight.EXIT_ENVIRONMENT == 2
    assert "could not start bash for step 'any-step'" in captured.err
    assert "PASS" not in captured.out
    assert "preflight: PASSED" not in captured.out


@pytest.mark.skipif(
    os.environ.get("RUN_PREFLIGHT_SMOKE") != "1",
    reason="opt-in heavy smoke (RUN_PREFLIGHT_SMOKE=1 to enable)",
)
def test_preflight_exits_zero_in_clean_worktree() -> None:
    """Running preflight in a clean worktree exits 0. Heavy: opt-in."""
    result = subprocess.run(
        [sys.executable, "scripts/preflight.py"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"preflight must exit 0 in a clean worktree; got {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


@pytest.mark.skipif(
    os.environ.get("RUN_PREFLIGHT_SMOKE") != "1",
    reason="opt-in heavy smoke (RUN_PREFLIGHT_SMOKE=1 to enable)",
)
def test_preflight_exits_nonzero_with_induced_ruff_violation(tmp_path: Path) -> None:
    """A scratch copy with an induced ruff violation exits 1 and names the step."""
    skip_names = {".venv", ".git", "node_modules", "build", "dist"}
    skip_patterns = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".venv",
        "venv",
        "node_modules",
    )
    for entry in REPO_ROOT.iterdir():
        if entry.name in skip_names:
            continue
        dest = tmp_path / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest, symlinks=True, ignore=skip_patterns)
        else:
            shutil.copy2(entry, dest)

    (tmp_path / "app" / "_preflight_smoke_violation.py").write_text(
        "import os  # F401 unused import\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/preflight.py"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "FAIL Run ruff" in combined, (
        f"got:\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
