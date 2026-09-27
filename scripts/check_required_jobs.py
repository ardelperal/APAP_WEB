"""Fail closed unless every CI job required for this event succeeded.

This module is also the single source of truth for the UI surface used by
the issue #895 UI e2e gate: ``ci.yml``'s ``ui-detection`` job and
``deploy.yml``'s ``ui-e2e-gate`` job consume it through ``--print-ui-paths``
(the NON-UI allowlist) and ``--ui-changed`` (the fail-closed classifier) so
the three places cannot drift apart.

Issue #895 fix round 1 (JD-B-001): detection is INVERTED and fail-closed.
A revision is UI-relevant unless EVERY changed file is in the explicit
NON-UI allowlist below. The previous UI-path prefix list could never be
exhaustive — FastAPI renders Jinja templates from Python, so routes,
_form_render, and any future module under ``app/**`` all affect what the
browser loads — and a missed prefix silently skipped e2e. The allowlist
only has to be conservative in the safe direction: everything NOT listed
pays the e2e toll.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence

# Issue #895 fix round 1 (design D1, inverted): conservative allowlist of
# the NON-UI surface, derived from the real tracked tree. A changed file is
# non-UI only when it exactly equals a root-file entry or lives under a
# directory entry (trailing slash). Everything else — in particular ALL of
# app/** (routes, _form_render, templates, static) and tailwindcss/ (the
# Tailwind source that compiles into app/static/css/output.css) — is
# UI-relevant and forces e2e. Root-level build/tooling files (Makefile,
# pyproject.toml, Dockerfile, uv.lock) cannot change what the browser
# renders without an accompanying app/ or tailwindcss/ change, which the
# inversion would still catch.
NON_UI_PATH_PREFIXES: tuple[str, ...] = (
    # Directories (prefix match).
    ".atl/",
    ".codegraph/",
    ".github/",
    ".pi/",
    "coolify/",
    "docs/",
    "git-hooks/",
    "migration/",
    "odd/",
    "openspec/",
    "scripts/",
    "skills/",
    "tests/",
    # Root-level files (exact match, so "Makefile.bak" is NOT "Makefile").
    ".dockerignore",
    ".env.example",
    ".gitguardian.yml",
    ".gitignore",
    ".gitleaksignore",
    ".pre-commit-config.yaml",
    ".python-version",
    ".skills-fleet-manifest.json",
    "AGENTS.md",
    "CHANGELOG.md",
    "CODEOWNERS",
    "CONTRIBUTING.md",
    "docker-compose.yml",
    "DOCS.md",
    "Dockerfile",
    "env.example",
    "Makefile",
    "PLAN-E2E-COVERAGE.md",
    "pyproject.toml",
    "README.md",
    "SECURITY.md",
    "uv.lock",
)

#: Issue #895 fix round 1 (JD-A-001, anti-self-exemption toll): the gate's
#: own source cannot be edited without paying the e2e toll. These three
#: files DEFINE the detection, so a change to any of them forces
#: ``ui_changed=true`` — otherwise an allowlist edit could reclassify
#: future UI changes without e2e evidence.
GATE_SOURCE_FILES: tuple[str, ...] = (
    "scripts/check_required_jobs.py",
    ".github/workflows/ci.yml",
    ".github/workflows/deploy.yml",
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


def is_non_ui_path(path: str, allowlist: Sequence[str] = NON_UI_PATH_PREFIXES) -> bool:
    """Return True when ``path`` is inside the NON-UI allowlist.

    Directory entries (trailing slash) match by prefix; root-file entries
    match exactly, so ``Makefile.bak`` is not silently ``Makefile``.
    """
    for prefix in allowlist:
        if prefix.endswith("/"):
            if path.startswith(prefix):
                return True
        elif path == prefix:
            return True
    return False


def ui_changed_for_paths(
    paths: Sequence[str],
    allowlist: Sequence[str] = NON_UI_PATH_PREFIXES,
) -> bool:
    """Fail-closed classifier for the issue #895 UI e2e gate.

    Returns True (e2e must run) when ANY changed file is outside the NON-UI
    allowlist, or when any gate source file is present (anti-self-exemption
    toll). Only a changed set entirely inside the allowlist returns False.
    An empty changed set is a known no-op, not an unknown: it returns False.
    """
    for path in paths:
        if path in GATE_SOURCE_FILES:
            return True
        if not is_non_ui_path(path, allowlist):
            return True
    return False


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
    # Issue #895: the workflows consume the NON-UI allowlist through this
    # flag; it must work without the CI_NEEDS_JSON environment. The flag
    # name predates the fix round — it now prints the allowlist, not the
    # UI surface.
    if "--print-ui-paths" in args:
        print(" ".join(NON_UI_PATH_PREFIXES))
        return 0
    # Issue #895 fix round 1: the workflows classify the changed-file set
    # through this flag (one path per line on stdin) so the fail-closed
    # inversion and the gate toll live in the single source of truth too.
    if "--ui-changed" in args:
        paths = [line for line in sys.stdin.read().splitlines() if line.strip()]
        print("true" if ui_changed_for_paths(paths) else "false")
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
