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
from dataclasses import dataclass
from types import MappingProxyType

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

#: Issue #1118: DAG mirroring ci.yml ``needs:`` edges. Pinned by
#: test_job_dependencies_match_ci_yml.
JOB_DEPENDENCIES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "pr-size": (),
        "issue-spec": ("pr-size",),
        "lint": ("pr-size",),
        "security": ("pr-size", "lint"),
        "security-deep": ("pr-size",),
        "mutation": ("pr-size",),
        "typecheck": ("pr-size",),
        "test": ("pr-size", "lint"),
        "integration": ("pr-size", "lint"),
        "verify-fallback-ready": ("pr-size", "integration"),
        "build": ("pr-size", "test", "integration", "verify-fallback-ready"),
        "e2e": ("build", "ui-detection"),
        "ui-detection": (),
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
    """Return policy violations for the serialized GitHub ``needs`` object.

    Backward-compatible flat list over :func:`evaluate`. Root causes come
    first, then cascade skips (issue #1118 attribution), then other
    violations.
    """
    report = evaluate(needs, event_name, ref)
    lines: list[str] = []
    if report.unsupported_event is not None:
        lines.append(f"unsupported event: {report.unsupported_event}")
    for job, result in report.root_causes:
        lines.append(f"{job}: result={result!r}")
    for job, upstream in report.cascade_skips:
        lines.append(f"{job}: result='skipped' (upstream: {upstream})")
    lines.extend(report.other_violations)
    for job in report.missing:
        lines.append(f"missing jobs: {job}")
    return lines


@dataclass(frozen=True)
class RequiredJobsReport:
    """Structured evaluation of a CI needs payload (issue #1118).

    Buckets the outcome for hierarchical output: missing jobs, root
    causes, cascade skips (attributed to the closest failing
    ancestor) and other policy violations (allowed-skip denials).
    """

    missing: tuple[str, ...]
    root_causes: tuple[tuple[str, str], ...]
    cascade_skips: tuple[tuple[str, str], ...]
    other_violations: tuple[str, ...]
    unsupported_event: str | None = None

    @property
    def is_clean(self) -> bool:
        return not (
            self.missing
            or self.root_causes
            or self.cascade_skips
            or self.other_violations
            or self.unsupported_event is not None
        )


def _failing_set(needs: Mapping[str, object]) -> set[str]:
    """Jobs whose result is anything other than success or skipped."""
    failing: set[str] = set()
    for job, payload in needs.items():
        if not isinstance(payload, Mapping):
            failing.add(job)
            continue
        result = payload.get("result")
        if result not in (None, "success", "skipped"):
            failing.add(job)
    return failing


def _closest_failing_upstream(job: str, failing: set[str]) -> str | None:
    """Return the closest failing ancestor of ``job`` (BFS through DAG)."""
    queue: list[str] = list(JOB_DEPENDENCIES.get(job, ()))
    seen: set[str] = set(queue)
    while queue:
        candidate = queue.pop(0)
        if candidate in failing:
            return candidate
        for parent in JOB_DEPENDENCIES.get(candidate, ()):
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)
    return None


def evaluate(
    needs: Mapping[str, object], event_name: str, ref: str = ""
) -> RequiredJobsReport:
    """Return the structured evaluation of the serialized ``needs`` object.

    See :class:`RequiredJobsReport` for the bucket semantics.
    """
    present = ALL_JOBS & set(needs)
    missing_jobs = sorted(ALL_JOBS - present)
    failing = _failing_set(needs)

    unsupported: str | None = None
    allowed_skips: frozenset[str] = frozenset()
    is_tag_push = event_name == "push" and ref.startswith("refs/tags/")
    if event_name not in SKIPS_BY_EVENT:
        unsupported = event_name or "<empty>"
    elif is_tag_push:
        # Issue #766 + #1046: e2e/mutation must still terminate SUCCESS
        # on a tag push; security-deep moved to weekly+manual so its
        # skip is accepted.
        allowed_skips = frozenset({"issue-spec", "security-deep"})
    else:
        allowed_skips = SKIPS_BY_EVENT[event_name]

    root_causes: list[tuple[str, str]] = []
    cascade_skips: list[tuple[str, str]] = []
    other_violations: list[str] = []

    for job in sorted(present):
        payload = needs[job]
        if not isinstance(payload, Mapping):
            root_causes.append((job, "malformed"))
            continue
        result = payload.get("result")
        if result == "success":
            continue
        if result != "skipped":
            # failure / cancelled / timed_out → root cause.
            root_causes.append((job, str(result)))
            continue
        upstream = _closest_failing_upstream(job, failing)
        if upstream is not None:
            # Issue #1118: cascade attribution wins over the allowed-skip
            # and e2e-marker branches because the actual reason GitHub
            # Actions skipped the job is the upstream failure.
            cascade_skips.append((job, upstream))
            continue
        if job in allowed_skips:
            # Issue #895: a skipped e2e on pull_request / branch push is
            # only a policy pass when the run carries the no-UI-change
            # marker. On release events the marker never exempts a skip.
            if (
                job == "e2e"
                and event_name in E2E_MARKER_EXEMPT_EVENTS
                and not is_tag_push
            ):
                marker = _ui_changed_marker(needs)
                if marker != "false":
                    other_violations.append(
                        f"{job}: result='skipped' without "
                        f"ui_changed='false' (got {marker!r})"
                    )
            continue
        other_violations.append(f"{job}: result={result!r}")

    return RequiredJobsReport(
        missing=tuple(missing_jobs),
        root_causes=tuple(root_causes),
        cascade_skips=tuple(cascade_skips),
        other_violations=tuple(other_violations),
        unsupported_event=unsupported,
    )


def format_report(report: RequiredJobsReport) -> list[str]:
    """Return the hierarchical output lines for ``report`` (issue #1118)."""
    lines: list[str] = []
    if report.unsupported_event is not None:
        lines.append(f"UNSUPPORTED EVENT: {report.unsupported_event}")
    if report.missing:
        lines.append("MISSING JOBS:")
        for job in report.missing:
            lines.append(f"  - {job}")
    if report.root_causes:
        lines.append("ROOT CAUSE:")
        for job, result in report.root_causes:
            lines.append(f"  - {job}: result={result!r}")
    if report.cascade_skips:
        lines.append("CONSEQUENCES (cascade skipped):")
        for job, upstream in report.cascade_skips:
            lines.append(f"  - {job} (upstream: {upstream})")
    if report.other_violations:
        lines.append("VIOLATIONS:")
        for line in report.other_violations:
            lines.append(f"  - {line}")
    return lines


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

    report = evaluate(
        needs,
        os.environ.get("CI_EVENT_NAME", ""),
        os.environ.get("GITHUB_REF", ""),
    )
    for line in format_report(report):
        print(f"FAIL required jobs: {line}", file=sys.stderr)
    if not report.is_clean:
        return 1
    print("required jobs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
