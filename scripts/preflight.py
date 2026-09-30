"""Canonical local preflight: run exactly what the ci.yml ``lint`` job runs.

Issue #1119 closed a Local-vs-CI parity gap: ``ruff check`` alone does not
cover the extended rulesets (``S``, ``ERA``, ``ARG``, ``FAST``, ``N``,
``C901``, ``PLR``, ``SIM``, ``RET``, ``TRY``, ``PTH``) that
``scripts/check_ruff_ratchet.py`` applies in CI, and the only other
eighteen gates (``check_rules``, ``check_docstring_balance``,
``check_alantyle``, ``check_module_size``, ``check_route_size``,
``check_layers``, ``check_test_classification``, ``check_slice_completeness``,
``check_migration_boundaries``, ``check_docstring_coverage``,
``check_complexity``, ``check_ruff_ratchet``, ``check_vulture_guard``,
``check_jscpd``, ``check_mutation_sites``, ``check_import_cycles``,
``check_workflows``, ``check_issue_specs forms``) were CI-only.
Contributors running ``make verify`` ran most of them, but ``make verify``
is also a hand-curated subset that can drift.

This script reads ``.github/workflows/ci.yml`` at runtime, extracts the
``lint`` job's ``run:`` steps in order, and executes them sequentially
against the local working tree. Adding a step to ci.yml is picked up
automatically; hardcoding or dropping a step inside this file is detected
by ``tests/test_preflight.py::test_preflight_runs_exactly_lint_job_run_steps``.

Usage::

    python scripts/preflight.py

Exit code is 0 when every step passes, 1 when any step fails, 2 when the
workflow file is missing or malformed.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml


def lint_steps_from_ci(workflow_path: Path) -> list[tuple[str, str]]:
    """Parse ci.yml and return the ``lint`` job's ``(step_name, run_command)`` tuples.

    Setup-only steps (``uses:`` like ``actions/checkout``) are filtered out:
    the preflight runs on a workstation where the repo is already checked
    out and Python is already installed through ``uv sync``.

    Mirrors the ``True`` -> ``"on"`` normalization that
    ``tests/_workflow_yaml.load`` applies, so a YAML 1.1 boolean quirk
    cannot make the parser disagree with the test's own walk.
    """
    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise SystemExit(  # noqa: TRY003 — operator-facing diagnostic
            f"preflight: {workflow_path} is not a YAML mapping "
            f"(got {type(doc).__name__})"
        )
    if True in doc:
        doc["on"] = doc.pop(True)

    try:
        lint_job = doc["jobs"]["lint"]
    except KeyError as exc:
        raise SystemExit(  # noqa: TRY003 — operator-facing diagnostic
            f"preflight: {workflow_path} has no 'lint' job; "
            "is this the right workflow file?"
        ) from exc

    steps = lint_job.get("steps") or []
    result: list[tuple[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if not run:
            # ``uses:`` steps (checkout, setup-python) are CI-only.
            continue
        name = str(step.get("name", "<unnamed>")).strip()
        result.append((name, str(run)))
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
        # ``bash -c`` preserves the glob expansion (e.g.
        # ``openspec/changes/*/specs/``) the way the GitHub-hosted runner
        # does — same shell, same expansion, same exit-code semantics.
        # ``command`` is parsed from a YAML file we control, not from user
        # input, so ``bash -c`` is not a shell-injection surface here.
        proc = subprocess.run(  # noqa: S602,S603 - ci.yml content; PATH-resolved binary
            ["bash", "-c", command],  # noqa: S607 - PATH-resolved binary
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


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    workflow = args.workflow.resolve()
    if not workflow.is_file():
        print(f"preflight: workflow file not found: {workflow}", file=sys.stderr)
        return 2

    root = args.root.resolve()
    steps = lint_steps_from_ci(workflow)
    print(f"preflight: {len(steps)} steps from {workflow}")
    print(f"  root: {root}")
    print()
    return run(steps, root)


if __name__ == "__main__":
    raise SystemExit(main())
