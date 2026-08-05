"""Tests for the advisory-only repository pre-commit hook."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "git-hooks" / "pre-commit"
README_PATH = REPO_ROOT / "git-hooks" / "README.md"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_pre_commit_is_advisory_when_all_detectors_fail(tmp_path: Path) -> None:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("Git-compatible sh is unavailable")

    _git(tmp_path, "init")
    staged = tmp_path / "sample.py"
    staged.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "sample.py")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/usr/bin/env sh\necho FAKE-DETECTOR:$1\nexit 1\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [sh, str(HOOK_PATH)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ADVISORY" in result.stdout
    assert "scripts/check_crap.py" in result.stdout
    assert "scripts/check_jscpd.py" in result.stdout
    assert "scripts/check_mutation_sites.py" in result.stdout
    assert "3 detector(s) reported findings" in result.stdout


def test_pre_commit_skips_when_no_python_file_is_staged(tmp_path: Path) -> None:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("Git-compatible sh is unavailable")

    _git(tmp_path, "init")
    staged = tmp_path / "README.txt"
    staged.write_text("docs only\n", encoding="utf-8")
    _git(tmp_path, "add", "README.txt")

    result = subprocess.run(
        [sh, str(HOOK_PATH)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_installation_is_documented() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert "git config core.hooksPath git-hooks/" in readme
    assert "advisory" in readme.lower()


def test_ci_runs_hook_detectors_independently() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    for command in (
        "python scripts/check_crap.py",
        "python scripts/check_jscpd.py",
        "python scripts/check_mutation_sites.py",
    ):
        assert command in workflow
