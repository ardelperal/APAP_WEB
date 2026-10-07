"""Behaviour tests for the CI gate policy (issue #1168).

``.github/ci-gate-policy.json`` declares, per gate, whether it is
``enforcing`` (a failing gate fails the job) or ``dormant`` (the gate still
runs, its findings stay visible in the log, but exit 0). The file exists so
gates without real-defect evidence (epic #1065, handoff §8 criterion 5) can
be put to sleep explicitly — and re-armed by a one-line data change — instead
of being deleted.

Three layers are pinned here:

1. Schema — the policy file must parse and satisfy the declared contract;
   a malformed policy fails loud (never silently enforced or skipped).
2. Behaviour — ``scripts/preflight.py::run_gate_with_policy`` always
   executes the gate (no silent skip / no false-green), prints its
   findings, and applies the enforcement verdict.
3. Drift guard — every gate named in the policy must be wired to a real
   ci.yml step via ``run-gate``; a policy entry naming a gate that no
   step executes fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import preflight
from tests import _workflow_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
POLICY_PATH = REPO_ROOT / ".github" / "ci-gate-policy.json"


def _policy() -> dict[str, Any]:
    """Parse the repo policy file's gate map as JSON."""
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))["gates"]


def _write_policy(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "ci-gate-policy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


#: Exit code the fake failing gate command propagates (any non-zero works).
#: Named so the comparisons below are not flagged as magic values (PLR2004).
GATE_FAILURE_EXIT = 3

FAILING_COMMAND = [
    sys.executable,
    "-c",
    f"print('FINDING: offender'); raise SystemExit({GATE_FAILURE_EXIT})",
]
PASSING_COMMAND = [sys.executable, "-c", "print('FINDING: clean')"]


# --- 1. schema --------------------------------------------------------------


def test_gate_policy_file_exists_and_declares_both_dormant_gates() -> None:
    policy = preflight.load_gate_policy(POLICY_PATH)

    assert set(policy) == {"check_crap", "check_mutation_sites"}
    for gate in policy.values():
        assert gate["enforcement"] == "dormant"
        assert isinstance(gate["reason"], str) and gate["reason"].strip()
        assert isinstance(gate.get("dormant_since"), str) and gate["dormant_since"].strip()


@pytest.mark.parametrize(
    ("data", "why"),
    [
        ({"gates": {"g": {"enforcement": "sleeping"}}}, "enforcement outside the enum"),
        ({"gates": {"g": {}}}, "missing enforcement"),
        ({"gates": {"g": {"enforcement": "dormant", "reason": ""}}}, "empty reason for dormant"),
        (
            {"gates": {"g": {"enforcement": "dormant", "reason": "  "}}},
            "whitespace-only reason for dormant",
        ),
        (
            {"gates": {"g": {"enforcement": "dormant", "reason": "x", "notes": "y"}}},
            "key outside the allowed set",
        ),
        ({"gates": []}, "gates must be an object"),
        (["gates"], "top level must be an object"),
    ],
)
def test_gate_policy_rejects_invalid_documents(tmp_path: Path, data: Any, why: str) -> None:
    with pytest.raises(preflight.GatePolicyError):
        preflight.load_gate_policy(_write_policy(tmp_path, data))


def test_gate_policy_rejects_unparseable_json(tmp_path: Path) -> None:
    path = tmp_path / "ci-gate-policy.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(preflight.GatePolicyError):
        preflight.load_gate_policy(path)


def test_missing_policy_file_defaults_to_empty_enforcing_map(tmp_path: Path) -> None:
    """Default-deny: no policy means every gate enforces, nothing is skipped."""
    assert preflight.load_gate_policy(tmp_path / "absent.json") == {}


# --- 2. behaviour -----------------------------------------------------------


def test_enforcing_gate_failure_propagates(tmp_path: Path) -> None:
    policy_path = _write_policy(
        tmp_path, {"gates": {"g": {"enforcement": "enforcing"}}}
    )

    assert preflight.run_gate_with_policy("g", FAILING_COMMAND, policy_path) == GATE_FAILURE_EXIT


def test_dormant_gate_always_runs_and_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A failing gate under dormant policy must still execute and be visible."""
    policy_path = _write_policy(
        tmp_path,
        {"gates": {"g": {"enforcement": "dormant", "reason": "no real defect caught"}}},
    )

    assert preflight.run_gate_with_policy("g", FAILING_COMMAND, policy_path) == 0
    captured = capsys.readouterr()
    assert "FINDING: offender" in captured.out, "findings must stay visible in the log"
    assert "DORMANT" in captured.out


def test_dormant_gate_passing_command_returns_zero(tmp_path: Path) -> None:
    policy_path = _write_policy(
        tmp_path,
        {"gates": {"g": {"enforcement": "dormant", "reason": "no real defect caught"}}},
    )

    assert preflight.run_gate_with_policy("g", PASSING_COMMAND, policy_path) == 0


def test_unlisted_gate_enforces_even_with_policy_present(tmp_path: Path) -> None:
    """Default-deny: only gates listed as dormant are put to sleep."""
    policy_path = _write_policy(
        tmp_path,
        {"gates": {"other": {"enforcement": "dormant", "reason": "unrelated"}}},
    )

    assert preflight.run_gate_with_policy("g", FAILING_COMMAND, policy_path) == GATE_FAILURE_EXIT


def test_invalid_policy_fails_loud_never_green(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path, {"gates": {"g": {"enforcement": "nonsense"}}})

    with pytest.raises(preflight.GatePolicyError):
        preflight.run_gate_with_policy("g", PASSING_COMMAND, policy_path)


def test_run_gate_cli_maps_invalid_policy_to_loud_exit_code(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path, {"gates": {"g": {}}})

    code = preflight.main(
        [
            "--policy",
            str(policy_path),
            "run-gate",
            "g",
            "--",
            sys.executable,
            "-c",
            "print('x')",
        ]
    )

    assert code == preflight.EXIT_POLICY


# --- 3. drift guard ---------------------------------------------------------


def _all_workflow_runs() -> list[str]:
    """Every ``run:`` text of every job of ci.yml, in order."""
    doc = _workflow_yaml.load(WORKFLOW_PATH)
    runs: list[str] = []
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        runs.extend(str(step.get("run", "")) for step in _workflow_yaml.steps(job))
    return runs


@pytest.mark.parametrize("gate_name", sorted(_policy()) if POLICY_PATH.is_file() else [])
def test_policy_gate_is_wired_to_a_real_ci_step(gate_name: str) -> None:
    """A policy entry naming a gate no step executes must fail (IDEA T3)."""
    wired = [run for run in _all_workflow_runs() if f"run-gate {gate_name} --" in run]

    assert wired, (
        f"policy gate {gate_name!r} is not wired to any ci.yml step; "
        "either wire it with 'preflight.py run-gate <gate> -- <command>' or "
        "remove the policy entry"
    )
    assert any(f"python scripts/{gate_name}.py" in run for run in wired), (
        f"the step wired to {gate_name!r} must still run the gate script itself"
    )


def test_dormant_gates_are_routed_through_the_policy_runner() -> None:
    lint_runs = _workflow_yaml.runs_text(
        _workflow_yaml.job(_workflow_yaml.load(WORKFLOW_PATH), "lint")
    )
    test_runs = _workflow_yaml.runs_text(
        _workflow_yaml.job(_workflow_yaml.load(WORKFLOW_PATH), "test")
    )

    assert (
        "preflight.py run-gate check_mutation_sites -- python scripts/check_mutation_sites.py"
        in lint_runs
    )
    assert "preflight.py run-gate check_crap -- python scripts/check_crap.py" in test_runs
    # The gates must run, never be skipped: the raw script invocation stays
    # visible in each step's command.
    assert "python scripts/check_mutation_sites.py" in lint_runs
    assert "python scripts/check_crap.py" in test_runs
    assert "python scripts/check_crap.py" not in lint_runs
