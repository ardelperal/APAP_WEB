"""Canonical local preflight: run exactly what the ci.yml ``lint`` job runs.

Issue #1119 closed a Local-vs-CI parity gap: ``ruff check`` alone does not
cover the extended rulesets that ``scripts/check_ruff_ratchet.py`` applies
in CI, and many other gates were CI-only. ``make verify`` is a hand-curated
subset that can drift from the ``lint`` job.

This script reads ``.github/workflows/ci.yml`` at runtime, extracts the
``lint`` job's ``run:`` steps in order and executes them sequentially
against the local working tree, each with ``bash -e`` like the GitHub
runner does when a workflow sets no ``defaults.run.shell``. A step added
to ci.yml is picked up automatically. Step-level ``working-directory``
and ``env`` are honored; ``shell``, ``if`` and any other non-cosmetic
attribute are printed as visible warnings instead of being silently
ignored, and a ``lint`` job that yields zero ``run:`` steps fails loud
(parser drift must never print ``PASSED (0/0 steps)``) — issue #1187.
It does not run pytest, mypy or the CI-only jobs.

It also exposes the gate-policy runner the ci.yml steps use (issue #1168)::

    python scripts/preflight.py run-gate GATE -- COMMAND [ARGS...]

The runner reads ``.github/ci-gate-policy.json`` and applies the gate's
declared ``enforcement``: ``dormant`` means the gate still executes and
its findings stay visible in the log, but exit 0 (no real-defect evidence,
re-armable by a one-line data change); ``enforcing``, an unlisted gate, or
a missing policy means the gate's exit code propagates (default-deny). An
INVALID policy fails loud with exit code 3 — never a silent green.

Usage::

    python scripts/preflight.py [--list]
    python scripts/preflight.py run-gate GATE -- COMMAND [ARGS...]

Exit code is 0 when every step passes, 1 when any step fails, 2 when the
workflow is missing, malformed, has no ``lint`` job or holds a step that
bash cannot run faithfully (a GitHub ``${{ }}`` expression), and 3 when
the gate policy file exists but does not satisfy its schema.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Same code the module documents for an unusable workflow: the environment, not a lint step, is at fault.
EXIT_ENVIRONMENT = 2
#: The gate policy file exists but violates its schema: the wiring is
#: broken, so the step must fail instead of guessing an enforcement state.
EXIT_POLICY = 3

#: Location of the declarative gate policy, relative to the repo root.
GATE_POLICY_PATH = Path(".github") / "ci-gate-policy.json"
#: Keys a single gate entry may declare (issue #1168 schema contract).
ALLOWED_GATE_KEYS = frozenset({"enforcement", "reason", "dormant_since"})
VALID_ENFORCEMENT = frozenset({"dormant", "enforcing"})


class WorkflowError(Exception):
    """The workflow cannot be turned into a faithful list of lint steps."""


class GatePolicyError(Exception):
    """The gate policy file exists but does not satisfy its schema."""


@dataclass(frozen=True)
class Step:
    """One lint step extracted from ci.yml, with what preflight can faithfully run.

    Local hardening (issue #1187, preflight slice): ``working-directory``
    and step-level ``env`` are cheap to honor and are honored; ``shell``
    and ``if`` cannot be reproduced by the ``bash -e`` runner model, so
    they are carried in ``ignored`` (attribute, reason) pairs that callers
    must print as visible warnings — never dropped silently. Any other
    non-cosmetic attribute is warned the same way, so a future ci.yml
    attribute cannot silently drift from CI semantics again.
    """

    name: str
    command: str
    env: dict[str, str] = field(default_factory=dict)
    working_directory: str | None = None
    ignored: tuple[tuple[str, str], ...] = ()


def _attributes_we_cannot_run(step: dict[str, object]) -> list[tuple[str, str]]:
    """Return the step attributes preflight cannot faithfully reproduce.

    Decision (documented, issue #1187): ``shell`` and ``if`` change how or
    whether a command runs under the GitHub runner but are not cheap to
    honor locally (we always use ``bash -e`` and never evaluate
    conditions), so they are warned. ``continue-on-error`` would flip the
    pass/fail contract, so it is warned too. ``id`` and
    ``timeout-minutes`` are cosmetic or not-yet-implemented followups and
    stay silent; everything else unknown is warned to keep the
    silent-ignore defect class closed.
    """
    known_silent = {"name", "id", "uses", "run", "timeout-minutes",
                    "working-directory", "env"}
    reasons = {
        "shell": "steps run with 'bash -e' regardless of this setting",
        "if": "the condition is not evaluated; the step always runs",
        "continue-on-error": "the step's failure is fatal here while CI would tolerate it",
    }
    found: list[tuple[str, str]] = []
    for attribute in sorted(step):
        if attribute in known_silent or attribute in reasons:
            if attribute in reasons:
                found.append((attribute, reasons[attribute]))
            continue
        found.append((attribute, "is not honored by the local preflight"))
    return found


def _step_env(step_name: str, raw_env: object) -> dict[str, str]:
    """Validate and coerce a step's ``env:`` block (issue #1187).

    Raises ``WorkflowError`` for a non-mapping block or a GitHub
    expression, which bash cannot evaluate.
    """
    if raw_env is None:
        return {}
    if not isinstance(raw_env, dict):
        message = f"step '{step_name}': env must be a mapping of names to values"
        raise WorkflowError(message)
    result: dict[str, str] = {}
    for var, value in raw_env.items():
        text = str(value)
        if "${{" in text:
            message = (
                f"step '{step_name}': env var {var!r} uses a GitHub expression "
                "(${{{ }}}) that bash cannot evaluate; preflight refuses "
                "to run it unfaithfully"
            )
            raise WorkflowError(message)
        result[str(var)] = text
    return result


def _step_working_directory(step_name: str, raw_wd: object) -> str | None:
    """Validate a step's ``working-directory:`` (issue #1187)."""
    if raw_wd is None:
        return None
    working_directory = str(raw_wd)
    if "${{" in working_directory:
        message = (
            f"step '{step_name}': working-directory uses a GitHub expression "
            "(${{{ }}}) that bash cannot evaluate; preflight refuses "
            "to run it unfaithfully"
        )
        raise WorkflowError(message)
    return working_directory


def lint_steps_from_ci(workflow_path: Path) -> list[Step]:
    """Parse ci.yml and return the ``lint`` job's steps in order.

    Setup-only steps (``uses:``) are skipped: the repo is already checked
    out and Python already installed on a workstation. ``working-directory``
    and step-level ``env`` are honored; ``shell``/``if``/unknown attributes
    are carried as warnings on each :class:`Step`. Raises
    ``WorkflowError`` for malformed YAML, a missing ``lint`` job, zero
    ``run:`` steps (parser drift must fail loud, never print
    ``PASSED (0/0 steps)`` — issue #1187) or a ``run:``/``env:``/
    ``working-directory:`` text with a GitHub expression, which bash
    cannot evaluate.
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

    result: list[Step] = []
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
        step_env = _step_env(name, step.get("env"))
        working_directory = _step_working_directory(name, step.get("working-directory"))
        result.append(
            Step(
                name=name,
                command=command,
                env=step_env,
                working_directory=working_directory,
                ignored=tuple(_attributes_we_cannot_run(step)),
            )
        )
    if not result:
        message = (
            f"{workflow_path}: 0 steps extracted from the 'lint' job — parser drift "
            "or an empty job; refusing to report PASSED (0/0 steps)"
        )
        raise WorkflowError(message)
    return result


def run(steps: list[Step], root: Path) -> int:
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
    for index, step in enumerate(steps, start=1):
        name = step.name
        print(f"[{index}/{total}] {name}")
        step_env = env
        if step.env:
            step_env = {**env, **step.env}
        cwd = root
        if step.working_directory:
            candidate = Path(step.working_directory)
            cwd = candidate if candidate.is_absolute() else root / candidate
        # ``bash -e``: the GitHub runner default when ci.yml sets no
        # ``defaults.run.shell``; a failing command aborts the step.
        try:
            proc = subprocess.run(  # noqa: S603 - ci.yml content, not user input
                ["bash", "-e", "-c", step.command],  # noqa: S607 - PATH-resolved binary
                cwd=str(cwd),
                env=step_env,
                check=False,
            )
        except OSError as error:
            # The step never ran (bash missing from PATH, permission or resource
            # error): an environment problem, not a red step. Say so and stop
            # with the same exit code as an unusable workflow instead of a
            # traceback that looks like a gate failure.
            print(
                f"preflight: could not start bash for step {name!r}: {error}",
                file=sys.stderr,
            )
            return EXIT_ENVIRONMENT
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


def _validate_gate_entry(gate_name: str, gate: object) -> dict[str, object]:
    """Validate a single gate entry against the schema (issue #1168).

    Raises ``GatePolicyError`` on any violation; returns the entry
    unchanged when it satisfies the schema.
    """
    if not isinstance(gate, dict):
        message = f"gate {gate_name!r} must be an object"
        raise GatePolicyError(message)
    unknown = sorted(set(gate) - ALLOWED_GATE_KEYS)
    if unknown:
        message = f"gate {gate_name!r} has unknown keys: {unknown}"
        raise GatePolicyError(message)
    enforcement = gate.get("enforcement")
    if enforcement not in VALID_ENFORCEMENT:
        allowed = sorted(VALID_ENFORCEMENT)
        message = f"gate {gate_name!r}: enforcement must be one of {allowed}"
        raise GatePolicyError(message)
    if enforcement == "dormant":
        reason = gate.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            message = f"gate {gate_name!r}: dormant requires a non-empty reason"
            raise GatePolicyError(message)
    dormant_since = gate.get("dormant_since")
    if dormant_since is not None and (
        not isinstance(dormant_since, str) or not dormant_since.strip()
    ):
        message = f"gate {gate_name!r}: dormant_since must be a non-empty string"
        raise GatePolicyError(message)
    return gate


def load_gate_policy(policy_path: Path) -> dict[str, dict[str, object]]:
    """Load and validate the CI gate policy (issue #1168).

    A missing file is an empty policy: default-deny, every gate enforces.
    A present but invalid file (bad JSON, unknown keys, ``enforcement``
    outside {dormant, enforcing}, or a dormant gate without a non-empty
    reason) raises ``GatePolicyError`` so callers fail loud instead of
    silently enforcing or skipping a gate.
    """
    if not policy_path.is_file():
        return {}
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        message = f"cannot parse JSON: {exc}"
        raise GatePolicyError(message) from exc
    if not isinstance(data, dict) or not isinstance(data.get("gates"), dict):
        message = "top level must be an object with a 'gates' object"
        raise GatePolicyError(message)

    validated: dict[str, dict[str, object]] = {}
    for gate_name, gate in data["gates"].items():
        validated[gate_name] = _validate_gate_entry(gate_name, gate)
    return validated


def run_gate_with_policy(gate_name: str, command: list[str], policy_path: Path) -> int:
    """Run ``command`` for ``gate_name`` and apply the declared enforcement.

    The gate ALWAYS executes — dormant never skips it and never hides its
    findings (no false-green): the command's output is re-printed so the
    step log always shows the gate's results, then the policy decides the
    exit code. ``dormant`` returns 0; ``enforcing``, an unlisted gate or a
    missing policy returns the gate's own exit code. An invalid policy
    raises ``GatePolicyError``.
    """
    policy = load_gate_policy(policy_path)
    gate = policy.get(gate_name, {})
    enforcement = str(gate.get("enforcement", "enforcing"))
    try:
        proc = subprocess.run(  # noqa: S603 - ci.yml-wired gate command, not user input
            command,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except OSError as error:
        # The gate never ran (interpreter missing from PATH, permission or
        # resource error): an environment problem, not a green gate.
        print(f"gate-policy: could not start gate {gate_name!r}: {error}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    if proc.stdout:
        sys.stdout.write(proc.stdout)
        sys.stdout.flush()
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()
    if enforcement == "dormant":
        reason = gate.get("reason", "")
        print(
            f"gate-policy: {gate_name!r} is DORMANT per {policy_path.name} — findings "
            "above are informational (exit suppressed); re-arm by setting enforcement "
            f'to "enforcing". Reason: {reason}'
        )
        return 0
    return proc.returncode


def _run_gate_main(argv: list[str], policy_override: Path | None) -> int:
    """CLI for ``preflight.py run-gate GATE -- COMMAND...`` (issue #1168)."""
    # Minimum argv: ["run-gate", GATE, "--", COMMAND...]. Named so the
    # comparison is not a magic value (PLR2004).
    run_gate_min_args = 4
    if len(argv) < run_gate_min_args or argv[2] != "--":
        print("usage: preflight.py run-gate GATE -- COMMAND [ARGS...]", file=sys.stderr)
        return EXIT_ENVIRONMENT
    gate_name, command = argv[1], argv[3:]
    policy_path = policy_override or (
        Path(__file__).resolve().parents[1] / GATE_POLICY_PATH
    )
    try:
        return run_gate_with_policy(gate_name, command, policy_path)
    except GatePolicyError as exc:
        print(f"preflight: invalid gate policy ({policy_path}): {exc}", file=sys.stderr)
        return EXIT_POLICY


def _dispatch_run_gate(args_list: list[str]) -> int | None:
    """Handle ``--policy`` and ``run-gate`` pre-dispatch (issue #1168).

    Returns ``None`` when ``args_list`` is not a run-gate invocation and
    normal argparse parsing should proceed; otherwise the exit code.
    """
    policy_override: Path | None = None
    if "--policy" in args_list:
        index = args_list.index("--policy")
        if index + 1 >= len(args_list):
            print("preflight: --policy requires a path argument", file=sys.stderr)
            return EXIT_ENVIRONMENT
        policy_override = Path(args_list[index + 1])
        del args_list[index : index + 2]
    if args_list and args_list[0] == "run-gate":
        return _run_gate_main(args_list, policy_override)
    if policy_override is not None:
        print("preflight: --policy is only valid together with run-gate", file=sys.stderr)
        return EXIT_ENVIRONMENT
    return None


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def _report_step_attributes(steps: list[Step]) -> None:
    """Print honored attributes and ignored-attribute warnings per step (issue #1187)."""
    for step in steps:
        honored = []
        if step.working_directory:
            honored.append(f"working-directory '{step.working_directory}'")
        if step.env:
            honored.append(f"{len(step.env)} env var(s)")
        if honored:
            print(f"preflight: step {step.name!r}: honoring {' and '.join(honored)}")
        for attribute, reason in step.ignored:
            print(
                f"preflight: WARNING step {step.name!r}: attribute {attribute!r} "
                f"{reason}"
            )


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args_list = list(sys.argv[1:] if argv is None else argv)
    dispatched = _dispatch_run_gate(args_list)
    if dispatched is not None:
        return dispatched

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
    args = parser.parse_args(args_list)

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
    _report_step_attributes(steps)
    if args.list:
        for step in steps:
            print(f"  - {step.name}")
        return 0
    print(f"  root: {root}")
    print()
    return run(steps, root)


if __name__ == "__main__":
    raise SystemExit(main())
