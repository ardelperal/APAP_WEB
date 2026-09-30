"""Anti-drift + smoke tests for ``scripts/preflight.py`` (issue #1119).

The first test parses ci.yml independently with PyYAML and compares it
against ``preflight.lint_steps_from_ci`` from the same file — a hardcode
or step drop in preflight.py is detected.

Opt-in heavy smokes run the full pipeline (``RUN_PREFLIGHT_SMOKE=1``).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import preflight

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _lint_run_steps_from_yaml(path: Path) -> list[tuple[str, str]]:
    """Parse ci.yml independently and return the lint job's (name, run) tuples.

    Deliberately does NOT import from ``preflight`` — the whole point is to
    assert that preflight's parser agrees with a fresh PyYAML walk. Mirrors
    the same ``True`` -> ``"on"`` normalization that ``tests/_workflow_yaml``
    applies, so a YAML 1.1 boolean quirk cannot make the comparison diverge.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in doc:
        doc["on"] = doc.pop(True)
    lint_job = doc["jobs"]["lint"]
    steps = lint_job.get("steps") or []
    result: list[tuple[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if not run:
            continue
        name = str(step.get("name", "")).strip()
        result.append((name, str(run)))
    return result


def test_preflight_runs_exactly_lint_job_run_steps() -> None:
    """Issue #1119 anti-drift: preflight's step set must equal ci.yml's.

    Reading the workflow directly yields the same ``(name, run)`` tuples as
    asking preflight to extract them. Adding a step to ci.yml is picked up
    automatically; hardcoding or dropping a step inside ``preflight.py`` is
    detected.
    """
    expected = _lint_run_steps_from_yaml(WORKFLOW_PATH)
    actual = preflight.lint_steps_from_ci(WORKFLOW_PATH)

    assert actual == expected, (
        "preflight step set drifted from ci.yml lint job:\n"
        f"  only in preflight: {sorted(set(actual) - set(expected))}\n"
        f"  only in ci.yml:    {sorted(set(expected) - set(actual))}"
    )
    # Empty would mean ci.yml lost every run step — wrong target.
    assert len(actual) >= 5, (
        f"preflight extracted only {len(actual)} steps from the lint job — "
        "ci.yml or the parser is broken"
    )


def test_preflight_outputs_pass_fail_per_step(capsys: pytest.CaptureFixture[str]) -> None:
    """Each step must be reported as PASS or FAIL with its ci.yml step name.

    The output format is what a contributor sees on a failed run; ambiguous
    output produces ambiguous triage. We feed ``run()`` two fake steps (one
    OK, one exiting 7) and assert the resulting stdout + exit code.
    """
    ok = ("echo-OK-from-preflight-test", "echo OK-from-preflight-test")
    bad = ("echo-FAIL-from-preflight-test", "exit 7")

    exit_code = preflight.run([ok, bad], root=REPO_ROOT)
    captured = capsys.readouterr()

    assert exit_code != 0, "preflight.run must return non-zero when any step fails"
    assert "PASS echo-OK-from-preflight-test" in captured.out, (
        f"expected PASS line for the OK step; got:\n{captured.out!r}"
    )
    assert "FAIL echo-FAIL-from-preflight-test (exit 7)" in captured.out, (
        f"expected FAIL line for the failing step with the step name and "
        f"exit code; got:\n{captured.out!r}"
    )


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


def test_preflight_module_is_importable() -> None:
    """Sanity: scripts/preflight.py imports cleanly and exposes the contract."""
    assert callable(preflight.lint_steps_from_ci)
    assert callable(preflight.run)


@pytest.mark.skipif(
    os.environ.get("RUN_PREFLIGHT_SMOKE") != "1",
    reason="opt-in heavy smoke (RUN_PREFLIGHT_SMOKE=1 to enable)",
)
def test_preflight_exits_zero_in_clean_worktree() -> None:
    """DoD #2: running preflight in the worktree exits 0.

    Heavy — opt-in. Skipped by default to keep the inner loop fast.
    """
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
    """DoD #3: a scratch copy with an induced ruff violation exits non-zero
    and names the failing step.
    """
    # Copy the worktree minus caches. .venv is excluded — the system Python
    # on the runner has dev deps installed.
    skip_names = {".venv", ".git", "node_modules", "build", "dist"}
    skip_patterns = shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".venv", "venv", "node_modules",
    )
    for entry in REPO_ROOT.iterdir():
        if entry.name in skip_names:
            continue
        dest = tmp_path / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest, symlinks=True, ignore=skip_patterns)
        else:
            shutil.copy2(entry, dest)

    # Inject an F401 (unused import) violation into app/ so the ruff step
    # fails while the rest of the project stays coherent.
    (tmp_path / "app" / "_preflight_smoke_violation.py").write_text(
        "import os  # F401 unused import\n", encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/preflight.py"],
        cwd=str(tmp_path), capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0, (
        "preflight must exit non-zero when a ruff violation exists"
    )
    combined = result.stdout + result.stderr
    assert "FAIL Run ruff" in combined, (
        "expected FAIL Run ruff naming the ruff step; "
        f"got:\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
