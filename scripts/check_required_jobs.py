"""Fail closed unless every CI job required for this event succeeded."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping

ALL_JOBS = frozenset(
    {
        "lint",
        "security",
        "security-deep",
        "mutation",
        "typecheck",
        "test",
        "integration",
        "issue-spec",
        "verify-fallback-ready",
        "build",
        "e2e",
    }
)
SKIPS_BY_EVENT = {
    "pull_request": frozenset({"security-deep", "mutation"}),
    "push": frozenset({"security-deep", "issue-spec", "mutation"}),
    "schedule": frozenset({"e2e", "issue-spec"}),
    "workflow_dispatch": frozenset({"issue-spec"}),
}


def _pin_output_encoding() -> None:
    """Make gate output independent from the runner locale."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def check_results(
    needs: Mapping[str, object], event_name: str, ref: str = ""
) -> list[str]:
    """Return policy violations for the serialized GitHub ``needs`` object."""
    violations: list[str] = []
    missing = sorted(ALL_JOBS - needs.keys())
    if missing:
        violations.append(f"missing jobs: {', '.join(missing)}")

    allowed_skips = SKIPS_BY_EVENT.get(event_name)
    if allowed_skips is None:
        violations.append(f"unsupported event: {event_name or '<empty>'}")
        allowed_skips = frozenset()

    is_tag_push = event_name == "push" and ref.startswith("refs/tags/")
    if is_tag_push:
        allowed_skips = frozenset({"issue-spec"})

    for job in sorted(ALL_JOBS & needs.keys()):
        payload = needs[job]
        if not isinstance(payload, Mapping):
            violations.append(f"{job}: malformed result payload")
            continue
        result = payload.get("result")
        if result == "success":
            continue
        if result == "skipped" and job in allowed_skips:
            continue
        violations.append(f"{job}: result={result!r}")
    return violations


def main() -> int:
    _pin_output_encoding()
    try:
        needs = json.loads(os.environ["CI_NEEDS_JSON"])
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL required jobs: invalid CI_NEEDS_JSON ({exc})", file=sys.stderr)
        return 1
    if not isinstance(needs, dict):
        print("FAIL required jobs: CI_NEEDS_JSON must be an object", file=sys.stderr)
        return 1

    violations = check_results(
        needs,
        os.environ.get("CI_EVENT_NAME", ""),
        os.environ.get("GITHUB_REF", ""),
    )
    for violation in violations:
        print(f"FAIL required jobs: {violation}", file=sys.stderr)
    if violations:
        return 1
    print("required jobs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
