"""Guard: production wheel must NOT ship the test suite.

Regression test for: https://github.com/ardelperal/APAP_WEB/issues/333
audit-2026-07-30 / fix/issue-333-wheel-ships-tests
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def wheel_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the project wheel into a temporary directory and return its path."""
    tmp_dir = tmp_path_factory.mktemp("wheel_output")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(tmp_dir),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Failed to build wheel:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    wheels = list(tmp_dir.glob("*.whl"))
    if not wheels:
        pytest.fail(f"No .whl file produced in {tmp_dir}")
    return wheels[0]


@pytest.fixture(scope="module")
def wheel_members(wheel_file: Path) -> dict[str, zipfile.ZipInfo]:
    """Index the wheel archive members by normalised path."""
    with zipfile.ZipFile(wheel_file) as zf:
        return {zi.filename: zi for zi in zf.infolist()}


def test_wheel_contains_app(wheel_members: dict[str, zipfile.ZipInfo]) -> None:
    """Sanity check: the app package must be present in the wheel."""
    app_entries = [n for n in wheel_members if n.startswith("app/")]
    assert app_entries, "app/ must be present in the wheel"


def test_wheel_excludes_tests(wheel_members: dict[str, zipfile.ZipInfo]) -> None:
    """REGRESSION GUARD (issue #333): tests/ must NOT be shipped in the production wheel.

    The wheel is installed inside the runtime Docker image. Shipping tests exposes:
    - 58k+ LOC of deliberately-malformed fixture modules (tests/_rule_helpers/fixtures/,
      tests/fixtures/query_seam/) whose purpose is to violate static-analysis rules.
    - Test infrastructure that has no place in a production image.
    """
    test_entries = [n for n in wheel_members if n.startswith("tests/")]
    assert not test_entries, (
        f"tests/ must NOT be in the wheel, but found {len(test_entries)} entries: "
        f"{sorted(test_entries)}"
    )
