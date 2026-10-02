#!/usr/bin/env python3
# ci-pattern asset tests — parity between workflow fixture and policy (DysTelefonica/team-skills#132, PR 2/2)
"""Parity test: the fixture workflow and the policy must describe the same
required-jobs set. Fails when ``jobs − {aggregator}``, the aggregator's
``needs`` and the policy job set do not match. Stdlib only."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ASSET = Path(__file__).resolve().parent.parent
EXAMPLE_POLICY = ASSET / "required-jobs.policy.example.json"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ci-workflow.fixture.yml"

AGGREGATOR = "required"
POLICY_JOBS = ["lint", "compile", "smoke", "unit", "full"]

FIXTURE_TEXT = FIXTURE.read_text(encoding="utf-8")


def parse_jobs(text: str) -> dict:
    """Parse the fixture's ``jobs:`` block.

    Supports exactly the YAML subset the fixture uses: top-level ``jobs:``,
    two-space indented job keys and a flow-style ``needs: [a, b]`` list.
    """
    jobs: dict[str, dict] = {}
    in_jobs = False
    current: str | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            in_jobs = raw.rstrip() == "jobs:"
            current = None
            continue
        if not in_jobs:
            continue
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1]
            jobs[current] = {"needs": []}
        elif current and stripped.startswith("needs:"):
            inline = stripped.split(":", 1)[1].strip()
            jobs[current]["needs"] = [j.strip() for j in inline.strip("[]").split(",") if j.strip()]
    return jobs


def parity_mismatches(jobs: dict, policy_jobs: set[str]) -> list[str]:
    """Compare jobs − {aggregator}, the aggregator's needs and the policy set."""
    aggregator_jobs = [name for name, spec in jobs.items() if spec["needs"]]
    problems: list[str] = []
    if len(aggregator_jobs) != 1:
        return [f"expected exactly one aggregator job with needs, got {aggregator_jobs}"]
    aggregator = aggregator_jobs[0]
    deps = set(jobs[aggregator]["needs"])
    workflow_jobs = set(jobs) - {aggregator}
    for job in sorted(workflow_jobs - policy_jobs):
        problems.append(f"workflow job '{job}' is not in the policy")
    for job in sorted(policy_jobs - workflow_jobs):
        problems.append(f"policy job '{job}' is not defined in the workflow")
    for job in sorted(deps - policy_jobs):
        problems.append(f"aggregator needs '{job}' is not in the policy")
    for job in sorted(policy_jobs - deps):
        problems.append(f"policy job '{job}' is missing from the aggregator needs")
    return problems


class ParityTests(unittest.TestCase):
    """Workflow fixture and policy must describe the same required-jobs set."""

    def test_fixture_matches_example_policy(self) -> None:
        policy = json.loads(EXAMPLE_POLICY.read_text(encoding="utf-8"))
        jobs = parse_jobs(FIXTURE_TEXT)
        self.assertEqual(
            parity_mismatches(jobs, set(policy["required_jobs"])),
            [],
            "committed fixture and example policy drifted apart",
        )

    def test_parity_fails_when_a_job_is_missing_from_the_workflow(self) -> None:
        jobs = parse_jobs(FIXTURE_TEXT)
        del jobs["unit"]
        problems = parity_mismatches(jobs, set(POLICY_JOBS))
        self.assertIn("policy job 'unit' is not defined in the workflow", problems)

    def test_parity_fails_when_a_job_is_missing_from_the_policy(self) -> None:
        problems = parity_mismatches(parse_jobs(FIXTURE_TEXT), set(POLICY_JOBS) - {"smoke"})
        self.assertIn("workflow job 'smoke' is not in the policy", problems)

    def test_parity_fails_when_needs_miss_a_policy_job(self) -> None:
        jobs = parse_jobs(FIXTURE_TEXT)
        jobs[AGGREGATOR]["needs"] = ["lint", "compile", "smoke", "full"]
        problems = parity_mismatches(jobs, set(POLICY_JOBS))
        self.assertIn("policy job 'unit' is missing from the aggregator needs", problems)

    def test_parity_fails_when_needs_carry_an_unpolicyed_job(self) -> None:
        jobs = parse_jobs(FIXTURE_TEXT)
        jobs[AGGREGATOR]["needs"] = POLICY_JOBS + ["rogue"]
        problems = parity_mismatches(jobs, set(POLICY_JOBS))
        self.assertIn("aggregator needs 'rogue' is not in the policy", problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
