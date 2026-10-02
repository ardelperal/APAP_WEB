#!/usr/bin/env python3
# ci-pattern asset tests — verdict, fail-closed and parity (DysTelefonica/team-skills#132)
"""Executable suite for the required-jobs aggregator.

Every failure case asserts a NON-ZERO exit; the pass cases assert exit 0.
Runs with the stdlib only, the same way CI invokes it:
``python3 personal/ardelperal/ci-pattern/assets/required-jobs/tests/test_required_jobs.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ASSET = Path(__file__).resolve().parent.parent
SCRIPT = ASSET / "check_required_jobs.py"
EXAMPLE_POLICY = ASSET / "required-jobs.policy.example.json"

POLICY_JOBS = ["lint", "compile", "smoke", "unit", "full"]


def run_gate(policy: dict, needs: dict | None = None, event: str = "pull_request",
             stdin_text: str | None = None, needs_file: str | None = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        policy_path = Path(tmp) / "policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        argv = [sys.executable, str(SCRIPT), "--policy", str(policy_path), "--event", event]
        if needs_file is not None:
            argv += ["--needs-file", needs_file]
        elif stdin_text is None and needs is not None:
            stdin_text = json.dumps(needs)
        return subprocess.run(argv, input=stdin_text, capture_output=True, text=True)


def base_policy() -> dict:
    return {
        "required_jobs": POLICY_JOBS,
        "events": {"pull_request": {"accepted_skips": ["full"]}, "push": {"accepted_skips": []}},
    }


def all_success(needs_overrides: dict | None = None) -> dict:
    needs = {job: "success" for job in POLICY_JOBS}
    needs.update(needs_overrides or {})
    return needs


class VerdictTests(unittest.TestCase):
    """Every doubt must be a non-zero exit; success or declared skips exit 0."""

    def test_failure_conclusion_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), all_success({"unit": "failure"}))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("root-cause failures", proc.stdout)
        self.assertIn("unit (failure)", proc.stdout)

    def test_cancelled_conclusion_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), all_success({"unit": "cancelled"}))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("unit (cancelled)", proc.stdout)

    def test_known_job_absent_from_needs_exits_nonzero(self) -> None:
        needs = all_success()
        del needs["smoke"]
        proc = run_gate(base_policy(), needs)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("required job 'smoke' is absent from needs", proc.stdout)

    def test_undeclared_skip_for_event_exits_nonzero(self) -> None:
        # 'unit' is skipped but only 'full' is declared as an accepted skip.
        proc = run_gate(base_policy(), all_success({"unit": "skipped"}))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("not declared for this event", proc.stdout)

    def test_undeclared_event_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), all_success(), event="workflow_dispatch")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("event 'workflow_dispatch' is not declared", proc.stdout)

    def test_unknown_needs_key_not_covered_by_policy_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), all_success({"surprise": "success"}))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("needs key 'surprise' is not covered by the policy", proc.stdout)

    def test_unreadable_needs_file_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), needs_file="/nonexistent/needs.json")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("unreadable needs input", proc.stderr)

    def test_malformed_needs_json_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), stdin_text="{not json")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("not valid JSON", proc.stderr)

    def test_empty_needs_input_exits_nonzero(self) -> None:
        proc = run_gate(base_policy(), stdin_text="   \n")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("needs input is empty", proc.stderr)

    def test_all_success_exits_zero(self) -> None:
        proc = run_gate(base_policy(), all_success())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("VERDICT: PASS", proc.stdout)

    def test_declared_skips_exit_zero(self) -> None:
        proc = run_gate(base_policy(), all_success({"full": "skipped"}))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("declared skips (accepted)", proc.stdout)

    def test_output_separates_root_cause_from_cascade_skips(self) -> None:
        needs = all_success({"unit": "failure", "full": "skipped"})
        # push declares no accepted skips, so full lands in the cascade section.
        proc = run_gate(base_policy(), needs, event="push")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        root = proc.stdout.index("root-cause failures")
        cascade = proc.stdout.index("not declared for this event")
        self.assertIn("unit (failure)", proc.stdout[root:cascade])
        self.assertIn("full (skipped)", proc.stdout[cascade:])


class ExamplePolicyTests(unittest.TestCase):
    """The shipped example policy must itself satisfy the gate's contract."""

    def test_example_policy_is_valid(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--policy", str(EXAMPLE_POLICY),
             "--event", "push", "--needs-file", str(EXAMPLE_POLICY)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)  # policy file is not a needs object: fail-closed
        self.assertIn("needs input must map", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
