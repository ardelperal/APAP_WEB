# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_ci_workflow.py
"""Wiring pin for the CI workflow (Hard Rule 4).

A gate that exists only as a script is a gate nobody runs. These tests parse the workflow and
fail when a step is deleted, when a gate is neutered, or when a pin goes floating. They are the
reason a silent revert cannot pass review.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import shlex
import sys
from pathlib import Path

import pytest
import yaml

#: Every gate CI must execute, represented by a stable identity rather than text snippets.
REQUIRED_GATE_IDENTITIES = (
    "branch_name",
    "pr_size",
    "adoption",
    "format",
    "lint",
    "typecheck",
    "test",
    "quality",
    "mutation",
    "dependency_scan",
    "secret_scan",
    "dockerfile_scan",
)

#: Gates CI runs that `make verify` deliberately does not (Hard Rule 19).
#: Each needs something a developer workstation does not have: the pull-request
#: payload, a weekly time budget, or a Docker daemon. Listing them here is what
#: turns an absence into a recorded decision — anything NOT in this tuple must
#: be reachable from `make verify`.
VERIFY_EXCLUSIONS = {
    "branch_name": "requires the pull-request head ref supplied by CI",
    "pr_size": "requires the pull-request merge base and body supplied by CI",
    "mutation": "runs on the weekly schedule because a full mutation session is too slow",
    "dependency_scan": "requires network access to the vulnerability advisory database",
    "secret_scan": "requires a Docker daemon and the pinned gitleaks image",
    "dockerfile_scan": "requires a Docker daemon and the pinned trivy image",
}

#: The four code gates, in the order they must run. Deduplication moves code, which changes
#: complexity, which changes CRAP — so the sequence is part of the contract, not a preference.
REQUIRED_GATE_ORDER = ("layers", "complexity", "crap", "mutation_sites", "dry")

_SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


def _logical_shell_lines(block: str) -> list[str]:
    logical: list[str] = []
    pending = ""
    for raw in block.splitlines():
        line = raw.strip()
        if pending:
            line = f"{pending} {line}"
        if line.endswith("\\"):
            pending = line.removesuffix("\\").rstrip()
            continue
        logical.append(line)
        pending = ""
    if pending:
        logical.append(pending)
    return logical


def _gate_identity(command: str) -> str | None:
    """Return the gate actually executed by one shell command, never text it prints."""
    stripped = command.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None

    tokens[0] = tokens[0].lstrip("@-")
    if Path(tokens[0]).name == "env":
        tokens = tokens[1:]
    while tokens and "=" in tokens[0] and not tokens[0].startswith(("/", "./")):
        name, _, _ = tokens[0].partition("=")
        if not name.replace("_", "").isalnum():
            break
        tokens = tokens[1:]
    if not tokens:
        return None

    executable = Path(tokens[0]).name
    if executable in {"echo", "printf"}:
        return None

    args = tokens[1:]
    if executable.startswith("python"):
        if len(args) >= 2 and args[0] == "-m":
            executable, args = args[1], args[2:]
        elif args:
            executable, args = Path(args[0]).name, args[1:]

    if executable == "ruff" and args[:2] == ["format", "--check"]:
        return "format"
    if executable == "ruff" and args[:1] == ["check"]:
        return "lint"
    if executable == "mypy":
        return "typecheck"
    if executable == "pytest":
        return "test"
    if executable == "check_adoption.py":
        return "adoption"
    if executable == "quality_report.py":
        return "quality"
    if executable == "check_mutation.py":
        return "mutation"
    if executable == "check_pr_size.py":
        return "pr_size"
    if executable == "check_branch_name.py":
        return "branch_name"
    if executable == "pip-audit":
        return "dependency_scan"
    if executable == "docker" and args[:1] == ["run"]:
        index = 1
        options_with_values = {"-v", "--volume", "-w", "--workdir", "--name", "--env", "-e"}
        while index < len(args) and args[index].startswith("-"):
            option = args[index].partition("=")[0]
            index += 1
            if option in options_with_values and "=" not in args[index - 1]:
                index += 1
        container_args = args[index + 1 :] if index < len(args) else []
        if container_args[:1] == ["dir"]:
            return "secret_scan"
        if container_args[:1] == ["config"]:
            return "dockerfile_scan"
    return None


def _workflow_gate_identities(steps: list[dict]) -> list[str]:
    identities: list[str] = []
    for step in steps:
        for command in _logical_shell_lines(step.get("run", "")):
            identity = _gate_identity(command)
            if identity and identity not in identities:
                identities.append(identity)
    return identities


def _find_workflow() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".github" / "workflows" / "ci.yml"
        if candidate.is_file():
            return candidate
    # Fallback: the skill's own asset layout, so the template is self-testing.
    candidate = here.parent.parent / "ci.yml"
    if candidate.is_file():
        return candidate
    raise AssertionError("ci.yml not found")


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(_find_workflow().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(workflow: dict) -> list[dict]:
    collected: list[dict] = []
    for job in workflow["jobs"].values():
        collected.extend(job.get("steps", []))
    return collected


@pytest.fixture(scope="module")
def run_blocks(steps: list[dict]) -> list[str]:
    return [step["run"] for step in steps if "run" in step]


@pytest.mark.parametrize("identity", REQUIRED_GATE_IDENTITIES)
def test_gate_is_wired(steps: list[dict], identity: str) -> None:
    assert identity in _workflow_gate_identities(steps), (
        f"no CI step executes gate '{identity}'"
    )


def test_no_step_swallows_its_exit_code(steps: list[dict]) -> None:
    """Hard Rule 1: a gate that cannot fail is not a gate."""
    offenders = [
        step.get("name", "<unnamed>") for step in steps if step.get("continue-on-error")
    ]
    assert not offenders, f"continue-on-error found on: {offenders}"


def test_no_run_block_forces_success(run_blocks: list[str]) -> None:
    """Hard Rule 1, the other half: `|| true` neuters a scanner while it still looks green."""
    offenders = [block for block in run_blocks if "|| true" in block]
    assert not offenders, f"'|| true' found in: {offenders}"


def test_ci_supplies_and_records_explicit_policy_time(run_blocks: list[str]) -> None:
    joined = "\n".join(run_blocks)
    assert "POLICY_DATE=" in joined
    assert 'quality_report.py --policy-date "$POLICY_DATE"' in joined
    assert (
        'check_mutation.py mutation-session.sqlite --policy-date "$POLICY_DATE"'
        in joined
    )


def test_every_action_is_pinned_to_a_sha(steps: list[dict]) -> None:
    """Hard Rule 15: a floating tag turns a green gate red with no code change."""
    unpinned = []
    for step in steps:
        uses = step.get("uses")
        if not uses:
            continue
        _, _, ref = uses.partition("@")
        if not _SHA_PIN.match(ref):
            unpinned.append(uses)
    assert not unpinned, f"actions not pinned to a 40-character SHA: {unpinned}"


def test_gate_order_is_pinned_in_code() -> None:
    """Hard Rule 13: the order lives in quality_report.GATES, and this is what pins it.

    Keeping the four code gates inside one script rather than four YAML steps is deliberate: a
    reviewer can reorder two YAML steps without noticing, and the resulting verdict would depend
    on the order in which someone happened to fix things.
    """
    scripts = Path(__file__).resolve().parent.parent / "scripts" / "quality_report.py"
    if str(scripts.parent) not in sys.path:
        sys.path.insert(0, str(scripts.parent))
    spec = importlib.util.spec_from_file_location("quality_report", scripts)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert tuple(name for name, _, _ in module.GATES) == REQUIRED_GATE_ORDER


def test_no_job_runs_on_a_floating_runner(workflow: dict) -> None:
    """Hard Rule 15: `ubuntu-latest` is a different machine from one month to the next."""
    floating = [
        f"{name}: {job['runs-on']}"
        for name, job in workflow["jobs"].items()
        if str(job.get("runs-on", "")).endswith("-latest")
    ]
    assert not floating, f"jobs on a floating runner label: {floating}"


# --- Set-level parity: scripts <-> ci.yml <-> make verify (Hard Rule 19) ---
#
# Every test above pins ONE gate to ONE step. That catches a deletion and
# nothing else: a gate script written and never wired passes, because the
# hardcoded entry for it was never added either. The three tests below pin the
# SETS, which is the only assertion that survives someone adding gate number
# eighteen.


def _find_makefile() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "Makefile"
        if candidate.is_file():
            return candidate
    # Fallback: the skill's own asset layout, so the template is self-testing.
    candidate = here.parent.parent / "Makefile"
    if candidate.is_file():
        return candidate
    raise AssertionError("Makefile not found")


def _parse_makefile(path: Path) -> dict[str, tuple[list[str], list[str]]]:
    """Parse a Makefile into ``{target: (prerequisites, recipe lines)}``.

    Deliberately minimal — enough to walk the ``verify`` dependency graph.
    Backslash continuations are joined first so a wrapped prerequisite list
    reads as one logical line; comments, ``.PHONY`` and variable assignments
    are skipped.
    """
    logical: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if logical and logical[-1].endswith("\\"):
            logical[-1] = logical[-1].removesuffix("\\").rstrip() + " " + line.strip()
        else:
            logical.append(line)

    targets: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    for line in logical:
        if line.startswith("\t"):
            if current is not None:
                targets[current][1].append(line.strip())
            continue
        stripped = line.strip()
        head = stripped.partition(":")[0]
        if (
            not stripped
            or stripped.startswith(("#", "."))
            or ":" not in stripped
            or " " in head
        ):
            current = None
            continue
        current = head.strip()
        targets[current] = (stripped.partition(":")[2].split(), [])
    return targets


def _verify_gate_identities(path: Path) -> list[str]:
    """Return executable gate identities reachable from ``make verify`` in execution order."""
    targets = _parse_makefile(path)
    assert "verify" in targets, f"{path} defines no `verify` target (Hard Rule 19)"

    seen: set[str] = set()
    collected: list[str] = []

    def walk(name: str) -> None:
        if name in seen or name not in targets:
            return
        seen.add(name)
        prerequisites, recipe = targets[name]
        for prerequisite in prerequisites:
            walk(prerequisite)
        collected.extend(recipe)

    walk("verify")
    commands = "\n".join(collected)
    for variable, expansion in (
        ("$(PYTHON)", "python"),
        ("$(RUFF)", "python -m ruff"),
        ("$(MYPY)", "python -m mypy"),
        ("$(PYTEST)", "python -m pytest"),
        ("$(PACKAGE)", "app"),
    ):
        commands = commands.replace(variable, expansion)
    return [
        identity
        for command in _logical_shell_lines(commands)
        if (identity := _gate_identity(command)) is not None
    ]


@pytest.fixture(scope="module")
def verify_gate_identities() -> list[str]:
    return _verify_gate_identities(_find_makefile())


def test_make_verify_runs_every_local_gate(verify_gate_identities: list[str]) -> None:
    """Hard Rule 19: one command must prove the complete portable local boundary.

    Without this, the gate list lives only in ci.yml, `make verify` silently
        becomes an undocumented subset of it, and a green local run stops meaning
        anything. The subset always drifts downward, because nothing measures it.

    Anything CI runs that a workstation genuinely cannot must be recorded in
    VERIFY_EXCLUSIONS — an absence that is written down is a decision, and an
    absence that is not is a hole.
    """
    expected = [
        gate for gate in REQUIRED_GATE_IDENTITIES if gate not in VERIFY_EXCLUSIONS
    ]
    assert verify_gate_identities == expected, (
        f"CI's portable gate order is {expected}, but `make verify` executes "
        f"{verify_gate_identities}. Add each missing target and preserve CI order "
        "(Hard Rules 13 and 19)."
    )


def test_make_verify_excludes_what_a_workstation_cannot_run(
    verify_gate_identities: list[str],
) -> None:
    """The exclusions are a design decision, so they are pinned like any other.

    Folding the weekly mutation session or the Docker scanners into ``verify``
    would make the local gate slow, Linux-only, or impossible without a daemon
    — and a gate people stop running is worse than one that never existed. If
    one of them ever becomes cheap enough to include, deleting its entry from
    VERIFY_EXCLUSIONS is the deliberate act that records the change.
    """
    leaked = [
        identity for identity in VERIFY_EXCLUSIONS if identity in verify_gate_identities
    ]
    assert not leaked, (
        f"`make verify` runs {leaked}, which VERIFY_EXCLUSIONS declares out of scope. "
        "Either remove it from verify or remove it from the exclusion list — silently "
        "disagreeing with the declared contract is the drift Hard Rule 19 exists to stop."
    )


def test_every_gate_script_on_disk_is_wired_in_ci(steps: list[dict]) -> None:
    """Hard Rule 4, at the level of the set rather than one gate at a time.

    REQUIRED_GATE_IDENTITIES catches a gate being deleted from ci.yml. It cannot catch
    a gate that was written and never wired, because whoever forgot the CI step
    also forgot to add the entry here. Walking `scripts/` closes that: the gate
    exists on disk, so it must run somewhere, or be deleted.
    """
    scripts_dir = _find_makefile().parent / "scripts"
    if not scripts_dir.is_dir():
        pytest.skip("no scripts/ directory in this layout")

    direct_scripts = {
        "adoption": "check_adoption.py",
        "branch_name": "check_branch_name.py",
        "mutation": "check_mutation.py",
        "pr_size": "check_pr_size.py",
    }
    wired = {
        direct_scripts[identity]
        for identity in _workflow_gate_identities(steps)
        if identity in direct_scripts
    }

    # The structural gates count as wired through the aggregator. Read the
    # literal registry without importing executable code or mutating sys.path.
    aggregator = scripts_dir / "quality_report.py"
    if aggregator.is_file():
        tree = ast.parse(aggregator.read_text(encoding="utf-8"), filename=str(aggregator))
        gates = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "GATES"
        )
        wired.update(script for _, script, _ in gates)

    unwired = sorted(
        path.name for path in scripts_dir.glob("check_*.py") if path.name not in wired
    )
    assert not unwired, (
        f"these gate scripts exist but no CI step runs them: {unwired}. A gate that "
        "runs nowhere is a false guarantee — wire it into ci.yml or delete it "
        "(Decision Gate: 'Gate runs locally but not in CI')."
    )


def test_workflow_comments_and_echo_do_not_count_as_wiring() -> None:
    steps = [
        {
            "run": "# python scripts/check_pr_size.py\n"
            "echo python scripts/check_branch_name.py\n"
            "echo 'ruff check .'"
        }
    ]

    assert _workflow_gate_identities(steps) == []


def test_scanner_subcommand_words_outside_docker_run_do_not_count() -> None:
    steps = [
        {
            "run": "docker echo dir .\n"
            "docker inspect config\n"
            "echo docker run scanner-image dir ."
        }
    ]

    assert _workflow_gate_identities(steps) == []


def test_environment_prefix_preserves_executable_identity() -> None:
    assert (
        _gate_identity(
            "POLICY_DATE=2026-08-12 python scripts/quality_report.py "
            '--policy-date "$POLICY_DATE"'
        )
        == "quality"
    )


def test_ci_gate_order_matches_declared_order(steps: list[dict]) -> None:
    assert _workflow_gate_identities(steps) == list(REQUIRED_GATE_IDENTITIES)


def test_make_comments_and_echo_do_not_count_as_wiring(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "verify: fake\n"
        "\t@echo 'python scripts/quality_report.py'\n"
        "\t# python scripts/check_branch_name.py\n"
        "fake:\n"
        "\t@echo ruff check .\n",
        encoding="utf-8",
    )

    assert _verify_gate_identities(makefile) == []


def test_every_verify_exclusion_has_a_reason_and_ci_counterpart(
    steps: list[dict],
) -> None:
    ci_gates = set(_workflow_gate_identities(steps))
    assert all(reason.strip() for reason in VERIFY_EXCLUSIONS.values())
    assert set(VERIFY_EXCLUSIONS) <= ci_gates
