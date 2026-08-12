"""Tests for ``scripts/measure_mutation_parallelism.py`` (issue #545).

Most of this script's behavior is verified end-to-end on the
``apap-coolify-noble`` runner (Linux only -- cosmic-ray 8.4.6 returns
INCOMPETENT for 100 % of mutants on native Windows, per issue #431,
Finding 1). The parts that can be unit-checked on any platform are:

- the Linux-only fail-fast gate,
- the summary formatter's shape,
- the ``is_session_healthy`` integration on the result.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from scripts.cosmic_ray_run_config import is_session_healthy
from scripts.measure_mutation_parallelism import (
    DEFAULT_SERIAL_BASELINE_S,
    _format_summary,
)

# ---------------------------------------------------------------------------
# Linux fail-fast
# ---------------------------------------------------------------------------


def test_measure_script_refuses_windows() -> None:
    """Run the script on this host; on Windows it must exit 1 with the platform message."""
    if sys.platform.startswith("linux"):
        pytest.skip("script is meant to refuse non-Linux; not exercised on Linux CI")
    completed = subprocess.run(
        [sys.executable, "scripts/measure_mutation_parallelism.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1
    assert "requires Linux" in completed.stderr
    assert sys.platform in completed.stderr


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------


def test_format_summary_renders_serial_baseline_default() -> None:
    """Default serial baseline matches the issue #545 body measurement (3111 s)."""
    assert DEFAULT_SERIAL_BASELINE_S == 3111.0


def test_format_summary_uses_provided_baseline() -> None:
    rendered = _format_summary(
        workers_started=4,
        wall_clock_s=780.0,
        summary={"total": 167, "killed": 129, "survived": 38, "incompetent": 0, "skipped": 0, "pending": 0},
        serial_baseline_s=3111.0,
    )
    # The 3111 s / 780 s ratio is ~3.99 -- enough to flag the speedup is
    # bounded by the slowest single mutant, not a perfect 4x scaling
    # (the issue body explicitly warns that perfect scaling is the
    # wrong mental model).
    assert "workers started:        4" in rendered
    assert "780.0 s" in rendered
    assert "3111 s" in rendered
    assert "3.99x" in rendered or "4.0x" in rendered  # rounding tolerance
    assert "incompetent:            0  (0.0%; ceiling 20%)" in rendered


def test_format_summary_handles_zero_wall_clock() -> None:
    """A degenerate run that finished in 0s must not crash on the speedup calculation."""
    rendered = _format_summary(
        workers_started=4,
        wall_clock_s=0.0,
        summary={"total": 167, "killed": 129, "survived": 38, "incompetent": 0, "skipped": 0, "pending": 0},
        serial_baseline_s=3111.0,
    )
    assert "inf" in rendered  # 3111 / 0 = inf in the formatted text


def test_format_summary_includes_incompetent_ratio() -> None:
    """The incompetent row must surface the actual ratio so the operator can read it off."""
    rendered = _format_summary(
        workers_started=4,
        wall_clock_s=1200.0,
        summary={"total": 100, "killed": 60, "survived": 25, "incompetent": 15, "skipped": 0, "pending": 0},
        serial_baseline_s=3111.0,
    )
    assert "incompetent:            15  (15.0%; ceiling 20%)" in rendered


# ---------------------------------------------------------------------------
# is_session_healthy integration
# ---------------------------------------------------------------------------


def test_healthy_session_marks_run_as_passing() -> None:
    summary = {"total": 167, "killed": 129, "survived": 38, "incompetent": 0, "skipped": 0, "pending": 0}
    assert is_session_healthy(summary) is True


def test_incompetent_over_ceiling_marks_run_as_failing() -> None:
    # The measurement script exits 1 when the summary is unhealthy; that
    # 1 is the gate the operator reads as "do not trust this number".
    summary = {"total": 100, "killed": 60, "survived": 10, "incompetent": 21, "skipped": 0, "pending": 0}
    assert is_session_healthy(summary) is False
