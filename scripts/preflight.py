"""Canonical local preflight: run exactly what the ci.yml ``lint`` job runs.

Issue #1119 closed a Local-vs-CI parity gap: ``ruff check`` alone does not
cover the extended rulesets that ``scripts/check_ruff_ratchet.py`` applies
in CI, and many other gates were CI-only. ``make verify`` is a hand-curated
subset that can drift from the ``lint`` job.

This script reads ``.github/workflows/ci.yml`` at runtime, extracts the
``lint`` job's ``run:`` steps in order and executes them sequentially
against the local working tree, each with ``bash -e`` like the GitHub
runner does when a workflow sets no ``defaults.run.shell``. A step added
to ci.yml is picked up automatically. It does not run pytest, mypy or the
CI-only jobs.

Usage::

    python scripts/preflight.py [--list]

Exit code is 0 when every step passes, 1 when any step fails, 2 when the
workflow is missing, malformed, has no ``lint`` job or holds a step that
bash cannot run faithfully (a GitHub ``${{ }}`` expression).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml


class WorkflowError(Exception):
    """The workflow cannot be turned into a faithful list of lint steps."""


def lint_steps_from_ci(workflow_path: Path) -> list[tuple[str, str]]:
    """Parse ci.yml and return the ``lint`` job's ``(step_name, run_command)`` tuples.

    Setup-only steps (``uses:``) are skipped: the repo is already checked
    out and Python already installed on a workstation. Raises
    ``WorkflowError`` for malformed YAML, a missing ``lint`` job or a
    ``run:`` text with a GitHub expression, which bash cannot evaluate.
    """
    try:
        doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        message = f"{workflow_path} is not valid YAML: {exc}"
        raise WorkflowError(message) from exc
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    lint_job = jobs.get("lint") if isinstance(jobs, dict) else None
    if not isinstance(lint_job, dict):
        message = f"{workflow_path} has no 'lint' job; is this the right workflow file?"
        raise WorkflowError(message)

    result: list[tuple[str, str]] = []
    for step in lint_job.get("steps") or []:
        if not isinstance(step, dict) or not step.get("run"):
            continue
        name = str(step.get("name", "<unnamed>")).strip()
        command = str(step["run"])
        if "${{" in command:
            message = (
                f"step '{name}' uses a GitHub expression (${{{{ }}}}) that bash "
                "cannot evaluate; preflight refuses to run it unfaithfully"
            )
            raise WorkflowError(message)
        result.append((name, command))
    return result


def run(steps: list[tuple[str, str]], root: Path) -> int:
    """Run each step sequentially with PASS/FAIL output.

    Returns 0 when every step exits 0, 1 when any step exits non-zero.
    The aggregated exit code is the single signal a pre-push wrapper needs;
    each step's per-line outcome is what triage reads.
    """
    failures: list[str] = []
    total = len(steps)
    # Prepend the directory of the running Python to PATH so ``bash -c``
    # can resolve ``python`` against the active interpreter. CI has
    # ``python`` on PATH via the setup-python action; locally ``uv sync``
    # drops it under ``.venv/bin/`` and a bare ``bash`` subshell does
    # not see it. Mirroring the interpreter's directory makes the two
    # invocations resolve identically.
    #
    # We deliberately do NOT ``.resolve()`` the path: uv installs ``python``
    # as a symlink to its managed CPython, and ``resolve()`` follows the
    # link to a directory that does not contain ``ruff`` / ``mypy`` (the
    # scripts call them as modules, but a CI parity ``bash -c python ...``
    # loses them when the resolved directory is ahead on PATH). Using the
    # symlink's parent keeps ``.venv/bin/`` on PATH where every dev
    # dependency lives.
    env = os.environ.copy()
    python_bin_dir = str(Path(sys.executable).parent)
    env["PATH"] = python_bin_dir + os.pathsep + env.get("PATH", "")
    for index, (name, command) in enumerate(steps, start=1):
        print(f"[{index}/{total}] {name}")
        # ``bash -e``: the GitHub runner default when ci.yml sets no
        # ``defaults.run.shell``; a failing command aborts the step.
        proc = subprocess.run(  # noqa: S603 - ci.yml content, not user input
            ["bash", "-e", "-c", command],  # noqa: S607 - PATH-resolved binary
            cwd=str(root),
            env=env,
            check=False,
        )
        if proc.returncode == 0:
            print(f"PASS {name}")
        else:
            print(f"FAIL {name} (exit {proc.returncode})")
            failures.append(name)
    print()
    if failures:
        print(f"preflight: FAILED ({len(failures)}/{total} steps)")
        for name in failures:
            print(f"  - {name}")
        return 1
    print(f"preflight: PASSED ({total}/{total} steps)")
    return 0


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workflow",
        type=Path,
        default=Path(".github/workflows/ci.yml"),
        help="Path to the ci workflow YAML (default: .github/workflows/ci.yml)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(),
        help="Working directory to run the steps in (default: current directory)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the steps that would run, without running them",
    )
    args = parser.parse_args(argv)

    workflow = args.workflow.resolve()
    if not workflow.is_file():
        print(f"preflight: workflow file not found: {workflow}", file=sys.stderr)
        return 2

    root = args.root.resolve()
    try:
        steps = lint_steps_from_ci(workflow)
    except WorkflowError as exc:
        print(f"preflight: {exc}", file=sys.stderr)
        return 2
    print(f"preflight: {len(steps)} steps from {workflow}")
    if args.list:
        for name, _command in steps:
            print(f"  - {name}")
        return 0
    print(f"  root: {root}")
    print()
    return run(steps, root)


if __name__ == "__main__":
    raise SystemExit(main())
