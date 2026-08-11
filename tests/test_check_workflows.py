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


_JOB_WITHOUT_TIMEOUT = """\
jobs:
  lint:
    runs-on: [self-hosted]
    timeout-minutes: 15
    steps:
      - run: true
  test:
    runs-on: [self-hosted]
    steps:
      - run: true
"""


def test_job_without_a_timeout_is_a_violation() -> None:
    """Issue #529: an unstated budget is GitHub's 360-minute default."""
    violations = check_workflows.check_timeouts(_JOB_WITHOUT_TIMEOUT, "ci.yml")

    assert len(violations) == 1
    assert "job 'test'" in violations[0]
    assert "360-minute" in violations[0]


def test_every_repository_job_states_a_timeout() -> None:
    """The live tree must stay covered: 360 minutes is never the intended budget."""
    violations, scanned = check_workflows.check(WORKFLOW_DIR)

    assert violations == []
    assert scanned > 0


def test_a_duplicate_key_suppresses_the_timeout_check_for_that_file() -> None:
    """Ordering rule: an ambiguous file is reported, not parsed further.

    ``yaml.safe_load`` would silently keep one of two colliding values, so any
    conclusion drawn past that point is arbitrary. The duplicate is the finding.
    """
    ambiguous = _ORPHANED_WITH.replace("  pr-size:\n", "  pr-size:\n    timeout-minutes: 5\n")
    violations = check_workflows.check_text(ambiguous, "pr-size.yml")

    assert any("duplicate key" in violation for violation in violations)


_PINNED_SERVICE_PORT = """\
jobs:
  test:
    runs-on: [self-hosted]
    timeout-minutes: 20
    services:
      postgres:
        image: postgres@sha256:abc
        ports:
          - 5432:5432
    steps:
      - run: true
"""


def test_fixed_host_port_on_a_service_is_a_violation() -> None:
    """Issue #532: a pinned host port is a collision waiting for a second runner."""
    violations = check_workflows.check_service_ports(_PINNED_SERVICE_PORT, "ci.yml")

    assert len(violations) == 1
    assert "pins host port '5432:5432'" in violations[0]
    assert "job.services.postgres.ports" in violations[0]


def test_container_port_alone_is_accepted() -> None:
    """Publishing only the container port is the shape that scales."""
    dynamic = _PINNED_SERVICE_PORT.replace("          - 5432:5432\n", "          - 5432\n")

    assert check_workflows.check_service_ports(dynamic, "ci.yml") == []


def test_no_repository_service_pins_a_host_port() -> None:
    """The live tree must stay collision-free, or the pool cannot grow."""
    violations, scanned = check_workflows.check(WORKFLOW_DIR)

    assert violations == []
    assert scanned > 0


def test_postgres_dsn_is_not_hardcoded_to_5432() -> None:
    """The DSN must follow the assigned port, not assume the canonical one.

    A DSN frozen at 5432 while the service publishes a random port connects to
    whatever else happens to hold 5432 on the host — or to nothing.
    """
    workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "host.docker.internal:5432" not in workflow
    assert "job.services.postgres.ports['5432']" in workflow


_DOCKER_WITHOUT_PREFLIGHT = """\
jobs:
  security:
    runs-on: [self-hosted]
    timeout-minutes: 15
    steps:
      - name: Check out repository
        uses: actions/checkout@sha
      - name: Scan
        run: docker run --rm scanner
"""


def test_docker_run_without_a_preflight_is_a_violation() -> None:
    """Issue #531: an unchecked daemon turns a scan into a silent stall."""
    violations = check_workflows.check_docker_preflight(_DOCKER_WITHOUT_PREFLIGHT, "ci.yml")

    assert len(violations) == 1
    assert "job 'security'" in violations[0]
    assert "docker info" in violations[0]


def test_preflight_without_timeout_does_not_count() -> None:
    """A bare `docker info` hangs exactly like the `docker run` it guards.

    This is the whole reason the check looks for `timeout` and not merely for the
    string `docker info`: an unwrapped guard is indistinguishable from no guard
    in the failure it is supposed to catch.
    """
    bare = _DOCKER_WITHOUT_PREFLIGHT.replace(
        "      - name: Scan\n",
        "      - name: Preflight\n        run: docker info >/dev/null\n      - name: Scan\n",
    )

    assert check_workflows.check_docker_preflight(bare, "ci.yml") != []


def test_timeout_wrapped_preflight_is_accepted() -> None:
    guarded = _DOCKER_WITHOUT_PREFLIGHT.replace(
        "      - name: Scan\n",
        "      - name: Preflight\n        run: timeout 30 docker info >/dev/null\n      - name: Scan\n",
    )

    assert check_workflows.check_docker_preflight(guarded, "ci.yml") == []


def test_preflight_after_the_docker_run_does_not_count() -> None:
    """Order matters: a guard that runs afterwards protects nothing."""
    late = _DOCKER_WITHOUT_PREFLIGHT + (
        "      - name: Preflight\n        run: timeout 30 docker info >/dev/null\n"
    )

    assert check_workflows.check_docker_preflight(late, "ci.yml") != []


def test_every_repository_docker_job_checks_the_daemon_first() -> None:
    """The live tree must stay guarded: this runner shares the host daemon."""
    violations, scanned = check_workflows.check(WORKFLOW_DIR)

    assert violations == []
    assert scanned > 0


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
