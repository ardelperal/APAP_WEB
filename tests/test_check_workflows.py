"""Tests for the workflow-file gate (issue #523).

The regression that motivated the gate: `pr-size.yml` gained a second `with:`
key in one step, GitHub recorded a `startup_failure`, and the check disappeared
from the pull request rollup instead of turning red.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_workflows  # noqa: E402

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW_PATH = WORKFLOW_DIR / "ci.yml"

_ORPHANED_WITH = """\
name: pr-size
on:
  pull_request:
    branches: [main]
jobs:
  pr-size:
    runs-on: [self-hosted]
    steps:
      - name: Check out repository
        uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09

      - name: Set up Python
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.12.11"
        with:
          fetch-depth: 0
"""


def test_duplicate_key_in_one_step_is_a_violation() -> None:
    """The exact shape that broke pr-size: a step left holding two ``with:``."""
    violations = check_workflows.check_text(_ORPHANED_WITH, "pr-size.yml")

    assert len(violations) == 1
    assert "duplicate key 'with'" in violations[0]
    assert "pr-size.yml:16" in violations[0]


def test_repaired_step_is_accepted() -> None:
    """Moving ``fetch-depth`` back onto its own step clears the violation."""
    repaired = _ORPHANED_WITH.replace(
        '        with:\n          python-version: "3.12.11"\n        with:\n'
        "          fetch-depth: 0\n",
        '        with:\n          python-version: "3.12.11"\n',
    ).replace(
        "        uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09\n",
        "        uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09\n"
        "        with:\n          fetch-depth: 0\n",
    )

    assert check_workflows.check_text(repaired, "pr-size.yml") == []


def test_repeated_keys_across_sibling_list_items_are_not_duplicates() -> None:
    """Every step declares ``name``/``uses``; only a collision inside one counts."""
    text = """\
jobs:
  lint:
    steps:
      - name: One
        uses: actions/checkout@sha
      - name: Two
        uses: actions/setup-python@sha
"""

    assert check_workflows.check_text(text, "ci.yml") == []


def test_shell_script_inside_a_block_scalar_is_not_scanned_for_keys() -> None:
    """A ``run: |`` body is opaque text, not a mapping."""
    text = """\
jobs:
  lint:
    steps:
      - name: Compute
        run: |
          echo "total: 1"
          echo "total: 2"
"""

    assert check_workflows.check_text(text, "ci.yml") == []


def test_repository_workflows_are_all_parseable() -> None:
    """The live tree must stay clean, or a required check can vanish unnoticed."""
    violations, scanned = check_workflows.check(WORKFLOW_DIR)

    assert violations == []
    assert scanned > 0


def test_gate_fails_when_it_scanned_nothing(tmp_path: Path) -> None:
    """Liveness (Hard Rule 18, #519): an empty scan is a failure, never a silent pass."""
    assert check_workflows.main([str(tmp_path)]) == 1


def test_gate_fails_on_a_missing_workflow_directory(tmp_path: Path) -> None:
    assert check_workflows.main([str(tmp_path / "absent")]) == 1


def test_ci_workflow_lint_job_runs_workflow_gate() -> None:
    """Issue #523 — removing this step is a blocked change.

    Every other gate in the lint job protects application code. This one
    protects the gates themselves: without it, a malformed workflow removes
    its own check from the rollup and the branch reads green.
    """
    workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    lint_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_start : workflow.index("\n  security:")]

    assert "python scripts/check_workflows.py" in lint_job
