"""Tests for scripts/check_spec_drift.py

Verifies the spec-drift detector catches unchecked tasks that use creation
intent but reference file paths that already exist in the codebase.

Per issue #335, the guard should flag:
- hardening-2026-q2: T-6.1 (Create `app/core/logging.py`) is unchecked but the file exists
- foster-gate-capacidad: Añadir `FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL` is unchecked
  but the constant exists in app/core/domain_foster.py:65
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The worktree root (not the worktrees/ parent)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_detector(repo_root: Path | None = None) -> tuple[int, str]:
    """Run the spec drift detector and return (exit_code, stdout+stderr)."""
    root = repo_root or REPO_ROOT
    result = subprocess.run(
        [sys.executable, "scripts/check_spec_drift.py", str(root)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSpecDriftDetector:
    """Test suite for check_spec_drift.py."""

    def test_exit_code_is_1_when_drift_exists(self):
        """The detector must exit 1 when any drift is detected."""
        code, _ = _run_detector()
        assert code == 1, "Expected non-zero exit when drift exists"

    def test_flags_hardening_q2_logging_file(self):
        """T-6.1 (Create app/core/logging.py) unchecked but file exists."""
        _, output = _run_detector()
        assert "app/core/logging.py" in output, (
            "Must flag app/core/logging.py as drift (T-6.1 unchecked)"
        )
        assert "UNDECIDED_CREATION_EXISTS" in output, (
            "Must use UNDECIDED_CREATION_EXISTS label"
        )

    def test_flags_foster_gate_constant(self):
        """Añadir FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL unchecked but exists."""
        _, output = _run_detector()
        # The constant exists at app/core/domain_foster.py:65 — the file
        # app/core/domain.py already imports and invokes it, so the file is
        # definitely present.
        assert "domain_foster.py" in output or "domain.py" in output, (
            "Must flag the foster-gate drift (constant exists but unchecked)"
        )

    def test_no_false_negative_for_doc_examples(self):
        """Both documented drift cases from issue #335 must appear in output."""
        _, output = _run_detector()
        # T-6.1 from hardening-2026-q2
        assert "hardening-2026-q2" in output, (
            "hardening-2026-q2 T-6.1 drift must be detected"
        )
        # foster-gate constant
        assert "foster-gate-capacidad" in output, (
            "foster-gate-capacidad drift must be detected"
        )

    def test_exit_code_is_0_when_no_drift(self, tmp_path: Path):
        """With no tasks.md files, the detector should exit 0 (no drift)."""
        # Create a minimal tasks.md with no creation-intent references
        fake_tasks = tmp_path / "openspec" / "changes" / "test-change" / "tasks.md"
        fake_tasks.parent.mkdir(parents=True, exist_ok=True)
        fake_tasks.write_text(
            "- [ ] Some pending task referencing no files\n",
            encoding="utf-8",
        )
        code, output = _run_detector(tmp_path)
        assert code == 0, f"Expected 0 with no drift, got {code}: {output}"
        assert "no drift detected" in output

    def test_no_drift_for_checked_task(self, tmp_path: Path):
        """Checked tasks must NOT trigger drift (even if file exists)."""
        content = tmp_path / "openspec" / "changes" / "test-change"
        content.mkdir(parents=True, exist_ok=True)
        tasks = content / "tasks.md"
        # File exists AND task is checked — no drift
        app_logging = tmp_path / "app" / "core" / "logging.py"
        app_logging.parent.mkdir(parents=True, exist_ok=True)
        app_logging.write_text("# existing file\n", encoding="utf-8")
        tasks.write_text(
            "- [x] Create `app/core/logging.py` — already done\n",
            encoding="utf-8",
        )
        code, output = _run_detector(tmp_path)
        # Should NOT flag this since the task is checked
        assert "app/core/logging.py" not in output or code == 0

    def test_no_drift_for_non_creation_task(self, tmp_path: Path):
        """Tasks without creation intent should not trigger drift."""
        content = tmp_path / "openspec" / "changes" / "test-change"
        content.mkdir(parents=True, exist_ok=True)
        tasks = content / "tasks.md"
        app_main = tmp_path / "app" / "main.py"
        app_main.parent.mkdir(parents=True, exist_ok=True)
        app_main.write_text("# existing\n", encoding="utf-8")
        # Task mentions app/main.py but does NOT use creation intent
        tasks.write_text(
            "- [ ] Update `app/main.py` with new route\n",
            encoding="utf-8",
        )
        code, output = _run_detector(tmp_path)
        # Should not flag "Update" (not a creation-intent word)
        assert "app/main.py" not in output or code == 0
