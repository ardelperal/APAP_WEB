"""Fail closed unless every CI job required for this event succeeded.

This module is also the single source of truth for the UI surface used by
the issue #895 UI e2e gate: ``ci.yml``'s ``ui-detection`` job and
``deploy.yml``'s ``ui-e2e-gate`` job consume ``UI_PATH_PREFIXES`` through
``--print-ui-paths`` so the three places cannot drift apart.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence

# Issue #895 (design D1): conservative prefix list of the UI surface,
# derived from the repository layout — Jinja2 HTML templates are served
# from app/templates/ (app/main.py renders them; app/modules/ contains no
# templates), the browser loads CSS/JS from app/static/ (css/output.css is
# compiled from tailwindcss/styles/app.css by the Makefile), and the
# Tailwind source styles/build inputs live under tailwindcss/. Backend
# modules, migration/, tests/ and docs/ are deliberately excluded: they
# cannot change what the browser renders.
UI_PATH_PREFIXES: tuple[str, ...] = (
    "app/templates/",
    "app/static/",
    "tailwindcss/",
)

ALL_JOBS = frozenset(
    {
        "pr-size",
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
        # Issue #895: the ui-detection job publishes the ui_changed marker
        # the e2e skip acceptance below relies on; without the job in needs
        # the marker is untrustworthy and the gate fails closed.
        "ui-detection",
    }
)
SKIPS_BY_EVENT = {
    "pull_request": frozenset({"security-deep", "mutation", "e2e"}),
    "push": frozenset({"security-deep", "issue-spec", "mutation", "e2e"}),
    # Workflow dispatch and tag pushes are release events (issue #766).
    # The e2e suite must terminate SUCCESS on those events; a skipped
    # or failed e2e blocks the required gate.
    "workflow_dispatch": frozenset({"issue-spec"}),
}

#: Issue #895: events where a skipped ``e2e`` is acceptable only when the
#: run carries the no-UI-change marker (``ui-detection`` published
#: ``ui_changed=false``). Tag pushes are carved out separately below: on a
#: release event the e2e suite must terminate SUCCESS regardless of marker.
E2E_MARKER_EXEMPT_EVENTS = frozenset({"pull_request", "push"})


def _ui_changed_marker(needs: Mapping[str, object]) -> str:
    """Return the published ``ui_changed`` value, or """" when untrustworthy."""
    payload = needs.get("ui-detection")
    if not isinstance(payload, Mapping):
        return ""
    outputs = payload.get("outputs")
    if not isinstance(outputs, Mapping):
        return ""
    marker = outputs.get("ui_changed")
    return marker if isinstance(marker, str) else ""


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
            # Issue #895: a skipped e2e is only a policy pass when the run
            # carries the no-UI-change marker. On release events (tag push,
            # workflow_dispatch) the marker never exempts a skip.
            if (
                job == "e2e"
                and event_name in E2E_MARKER_EXEMPT_EVENTS
                and not is_tag_push
            ):
                marker = _ui_changed_marker(needs)
                if marker != "false":
                    violations.append(
                        f"e2e: result='skipped' without ui_changed='false' "
                        f"(got {marker!r})"
                    )
                    continue
            continue
        violations.append(f"{job}: result={result!r}")
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    # Issue #895: the workflows consume the UI surface list through this
    # flag; it must work without the CI_NEEDS_JSON environment.
    if "--print-ui-paths" in args:
        print(" ".join(UI_PATH_PREFIXES))
        return 0
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
