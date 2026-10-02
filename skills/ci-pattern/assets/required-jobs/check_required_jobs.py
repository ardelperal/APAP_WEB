#!/usr/bin/env python3
# ci-pattern asset — fail-closed required-jobs aggregator (DysTelefonica/team-skills#132)
"""Aggregator gate over a serialized GitHub Actions ``needs`` object.

Reads ``toJSON(needs)`` — one key per dependency job, value = its conclusion —
plus a policy file that owns every job name, event name and accepted skip.
The script hardcodes none of them: replacing the policy retargets the gate,
so the same asset serves any consumer.

Fail-closed contract: any doubt exits non-zero. That includes unreadable or
malformed input, an undeclared event, a policy job absent from ``needs``, a
``needs`` key the policy does not cover (the workflow grew, the policy did
not), an undeclared skip, and any conclusion that is not ``success`` or a
declared skip.

Output separates root-cause failures (``failure``/``cancelled``) from skips,
so a downstream cascade skip is never mistaken for the cause.

Exit codes:
    0  every job succeeded or was a declared skip for the event
    1  fail-closed: root-cause failure, policy violation, or doubt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SUCCESS = "success"
SKIPPED = "skipped"
ROOT_CAUSE_CONCLUSIONS = ("failure", "cancelled")

POLICY_KEYS = frozenset({"required_jobs", "events"})
EVENT_KEYS = frozenset({"accepted_skips"})


class GateError(Exception):
    """A condition the gate refuses to interpret; maps to exit 1."""


def load_policy(path: str) -> dict:
    """Load and validate the policy file; every structural doubt raises."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise GateError(f"unreadable policy file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GateError(f"policy file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != set(POLICY_KEYS):
        raise GateError(f"policy must be an object with exactly {sorted(POLICY_KEYS)}")
    jobs = data["required_jobs"]
    if not isinstance(jobs, list) or not jobs or not all(isinstance(j, str) and j for j in jobs):
        raise GateError("required_jobs must be a non-empty list of non-empty strings")
    if len(set(jobs)) != len(jobs):
        raise GateError("required_jobs contains duplicate job names")
    events = data["events"]
    if not isinstance(events, dict):
        raise GateError("events must be an object")
    known = set(jobs)
    for event, spec in events.items():
        if not isinstance(spec, dict) or set(spec) - EVENT_KEYS:
            raise GateError(f"event '{event}' must be an object with keys {sorted(EVENT_KEYS)}")
        skips = spec.get("accepted_skips", [])
        if not isinstance(skips, list) or not all(isinstance(s, str) and s for s in skips):
            raise GateError(f"event '{event}': accepted_skips must be a list of job names")
        unknown = set(skips) - known
        if unknown:
            raise GateError(
                f"event '{event}': accepted skips outside required_jobs: {sorted(unknown)}"
            )
    return data


def load_needs(path: str | None) -> dict:
    """Load the serialized needs object from a file or stdin."""
    try:
        if path is None:
            if sys.stdin.isatty():
                raise GateError("no input: pipe the needs JSON or pass --needs-file")
            raw = sys.stdin.read()
        else:
            raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"unreadable needs input: {exc}") from exc
    if not raw.strip():
        raise GateError("needs input is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"needs input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise GateError("needs input must be a non-empty object of job -> conclusion")
    for job, conclusion in data.items():
        if not isinstance(job, str) or not job or not isinstance(conclusion, str):
            raise GateError("needs input must map non-empty job names to string conclusions")
    return data


def evaluate(needs: dict, policy: dict, event: str) -> dict:
    """Compare the needs object against the policy and return the verdict."""
    required = policy["required_jobs"]
    violations: list[str] = []
    if event not in policy["events"]:
        violations.append(f"event '{event}' is not declared in the policy")
        accepted: set[str] = set()
    else:
        accepted = set(policy["events"][event]["accepted_skips"])

    # S3 rule: a needs key the policy does not cover means the workflow grew
    # without updating the policy; fail-closed instead of silently ignoring it.
    for job in sorted(set(needs) - set(required)):
        violations.append(f"needs key '{job}' is not covered by the policy")
    for job in required:
        if job not in needs:
            violations.append(f"required job '{job}' is absent from needs")

    root_causes: list[str] = []
    undeclared_skips: list[str] = []
    declared_skips: list[str] = []
    for job, conclusion in sorted(needs.items()):
        if conclusion == SUCCESS:
            continue
        if conclusion == SKIPPED:
            if job in accepted:
                declared_skips.append(job)
            else:
                undeclared_skips.append(job)
        elif conclusion in ROOT_CAUSE_CONCLUSIONS:
            root_causes.append(f"{job} ({conclusion})")
        else:
            violations.append(f"job '{job}' has unknown conclusion '{conclusion}'")
    return {
        "event": event,
        "root_causes": root_causes,
        "undeclared_skips": undeclared_skips,
        "declared_skips": declared_skips,
        "violations": violations,
        "passed": not (root_causes or undeclared_skips or violations),
    }


def render(report: dict) -> str:
    """Human-readable verdict; root causes first, cascade skips after."""
    lines = [f"VERDICT: {'PASS' if report['passed'] else 'FAIL'} (event: {report['event']})"]
    if report["root_causes"]:
        lines.append("root-cause failures (fix these first):")
        lines += [f"  {item}" for item in report["root_causes"]]
    if report["undeclared_skips"]:
        lines.append("skips in cascade, not declared for this event (consequences, not causes):")
        lines += [f"  {job} (skipped)" for job in report["undeclared_skips"]]
    if report["violations"]:
        lines.append("policy violations:")
        lines += [f"  {item}" for item in report["violations"]]
    if report["declared_skips"]:
        lines.append("declared skips (accepted):")
        lines += [f"  {job} (skipped)" for job in report["declared_skips"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fail-closed required-jobs aggregator")
    parser.add_argument("--policy", required=True, help="path to the required-jobs policy JSON")
    parser.add_argument("--event", required=True, help="current event name (github.event_name)")
    parser.add_argument(
        "--needs-file",
        default=None,
        help="path to the serialized needs JSON (default: read stdin)",
    )
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        needs = load_needs(args.needs_file)
        report = evaluate(needs, policy, args.event)
    except GateError as exc:
        print(f"FAIL fail-closed: {exc}", file=sys.stderr)
        return 1
    print(render(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
