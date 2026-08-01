"""Tests for the extended-ruff shrink-only ratchet.

Issue #380: the extended rulesets are not in ``[tool.ruff.lint] select``
because 802 pre-existing violations would fail ``ruff check .``. The ratchet
freezes the per-rule counts so they may only shrink. These tests cover:

1. Behavioural: ``compare()`` fails on an increase and on an unknown rule.
2. Behavioural: ``compare()`` reports an improvement without failing.
3. Integration: the ratchet passes against the real tree.
4. Wiring: the CI ``lint`` job runs the gate.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_ruff_ratchet import (  # noqa: E402
    BASELINE,
    SCOPE,
    SELECT,
    compare,
    main,
    run_ruff,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_baseline_is_non_empty_and_positive() -> None:
    """Every baseline entry must be a positive count.

    A zero entry is meaningless: a rule with no violations should simply be
    absent, so that any future violation trips the unknown-rule branch.
    """
    assert BASELINE, "BASELINE must not be empty"
    zero_or_negative = {code: n for code, n in BASELINE.items() if n <= 0}
    assert not zero_or_negative, (
        f"BASELINE entries must be positive; remove these instead: {zero_or_negative}"
    )


def test_compare_is_clean_when_counts_match_baseline() -> None:
    """Measuring exactly the baseline is the steady state — no output."""
    violations, notices = compare(Counter(BASELINE))
    assert violations == []
    assert notices == []


def test_compare_fails_when_a_count_increases() -> None:
    """One extra violation of a tracked rule must fail the ratchet."""
    counts = Counter(BASELINE)
    counts["FAST002"] += 1

    violations, _ = compare(counts)

    assert len(violations) == 1
    assert "FAST002" in violations[0]
    assert "may only decrease" in violations[0]


def test_compare_fails_on_a_rule_absent_from_baseline() -> None:
    """A rule with no baseline entry must report zero, not creep in silently."""
    counts = Counter(BASELINE)
    counts["S602"] = 1

    violations, _ = compare(counts)

    assert len(violations) == 1
    assert "S602" in violations[0]
    assert "not in BASELINE" in violations[0]


def test_compare_notices_an_improvement_without_failing() -> None:
    """Dropping below baseline is a NOTE, so the win can be locked in."""
    counts = Counter(BASELINE)
    counts["FAST002"] -= 10

    violations, notices = compare(counts)

    assert violations == []
    assert len(notices) == 1
    assert "below baseline" in notices[0]
    assert "lock in the improvement" in notices[0]


def test_compare_treats_a_rule_dropping_to_zero_as_an_improvement() -> None:
    """A tracked rule reaching zero is an improvement, not an error."""
    counts = Counter(BASELINE)
    del counts["ERA001"]

    violations, notices = compare(counts)

    assert violations == []
    assert any("ERA001" in n for n in notices)


def test_run_ruff_reports_an_error_for_a_missing_scope() -> None:
    """A root with no scope directories is an error, not a silent zero.

    Without this branch a mis-invoked ratchet would report "OK, 0 findings"
    and pass CI while checking nothing.
    """
    counts, error = run_ruff(REPO_ROOT / "does-not-exist", scope=SCOPE)

    assert counts == Counter()
    assert error is not None
    assert "no scope directories" in error


def test_ratchet_passes_against_the_real_tree() -> None:
    """The committed BASELINE must match the tree it was measured against."""
    assert main([str(REPO_ROOT)]) == 0


def test_select_covers_the_documented_rulesets() -> None:
    """The select string is the contract with issue #380 — pin it."""
    for ruleset in ("S", "ERA", "ARG", "FAST", "N", "C901", "PLR", "SIM", "RET", "TRY", "PTH"):
        assert ruleset in SELECT.split(","), f"{ruleset} missing from SELECT"


def test_existing_ruff_gate_still_passes() -> None:
    """``ruff check .`` must stay green — this issue adds a gate, not noise.

    The extended rulesets deliberately live in the ratchet rather than in
    ``select``, so the pre-existing lint step is unaffected.
    """
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"ruff check . regressed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(not WORKFLOW_PATH.exists(), reason="ci.yml not present")
def test_ci_workflow_lint_job_runs_ruff_ratchet_gate() -> None:
    """The CI ``lint`` job must gate on ``scripts/check_ruff_ratchet.py``.

    Issue #380: removing this step from ci.yml is a blocked change.
    The ratchet is only real if CI runs it.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  typecheck:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    assert "python scripts/check_ruff_ratchet.py" in executable, (
        "The lint job must run the extended-ruff ratchet "
        "(python scripts/check_ruff_ratchet.py) so the rulesets are "
        "enforced in CI, not just at PR review time."
    )
