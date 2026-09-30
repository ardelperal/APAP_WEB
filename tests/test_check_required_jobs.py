from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_required_jobs import (
    ALL_JOBS,
    GATE_SOURCE_FILES,
    JOB_DEPENDENCIES,
    NON_UI_PATH_PREFIXES,
    RequiredJobsReport,
    check_results,
    evaluate,
    format_report,
    ui_changed_for_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _needs(result: str = "success") -> dict[str, dict[str, str]]:
    return {job: {"result": result} for job in ALL_JOBS}


def _marker(needs: dict[str, dict], ui_changed: str) -> dict[str, dict]:
    """Attach a ui-detection output payload to a needs fixture."""
    needs["ui-detection"] = {"result": "success", "outputs": {"ui_changed": ui_changed}}
    return needs


def test_pull_request_accepts_only_the_two_deliberate_heavy_job_skips() -> None:
    needs = _needs()
    needs["security-deep"]["result"] = "skipped"
    needs["mutation"]["result"] = "skipped"

    assert check_results(needs, "pull_request") == []


def test_non_pr_events_skip_issue_spec_but_pull_requests_require_it() -> None:
    needs = _needs()
    needs["issue-spec"]["result"] = "skipped"

    assert check_results(needs, "workflow_dispatch") == []
    assert check_results(needs, "pull_request") == ["issue-spec: result='skipped'"]


def test_e2e_skip_on_pull_request_requires_no_ui_change_marker() -> None:
    """Issue #895: e2e ``skipped`` on a pull_request is acceptable ONLY when
    the run carries the no-UI-change marker (the ui-detection job reported
    ``ui_changed=false``). Without the marker, a skipped e2e violates the
    required policy — a UI change must never merge with untested UI.
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"
    _marker(needs, "false")
    assert check_results(needs, "pull_request") == []

    for marker in ("true", "", "maybe"):
        _marker(needs, marker)
        assert check_results(needs, "pull_request") == [
            f"e2e: result='skipped' without ui_changed='false' (got {marker!r})"
        ]


def test_e2e_skip_on_branch_push_requires_no_ui_change_marker() -> None:
    """Issue #895: the same marker contract applies to a branch push
    (staging), whose e2e runs only when the parent-commit diff touches a
    UI path.
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"
    _marker(needs, "false")
    assert check_results(needs, "push") == []

    _marker(needs, "true")
    assert check_results(needs, "push") == [
        "e2e: result='skipped' without ui_changed='false' (got 'true')"
    ]


def test_e2e_missing_marker_fails_closed() -> None:
    """A run whose ui-detection job never published ``ui_changed`` (absent
    job payload, absent outputs, non-string value) fails closed: the skip
    acceptance requires the marker to be exactly ``'false'``.
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"

    # ui-detection ran but published no outputs.
    needs["ui-detection"] = {"result": "success"}
    assert check_results(needs, "pull_request") == [
        "e2e: result='skipped' without ui_changed='false' (got '')"
    ]
    # Malformed output type.
    needs["ui-detection"] = {"result": "success", "outputs": {"ui_changed": 1}}
    assert check_results(needs, "pull_request") == [
        "e2e: result='skipped' without ui_changed='false' (got '')"
    ]


def test_e2e_skip_blocks_required_on_release_events_even_with_marker() -> None:
    """Issue #766: workflow_dispatch and tag push are release events where
    the e2e suite MUST terminate SUCCESS. The no-UI-change marker never
    exempts those events (issue #895).
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"
    _marker(needs, "false")

    assert check_results(needs, "workflow_dispatch") == ["e2e: result='skipped'"]
    assert check_results(needs, "push", "refs/tags/v1.2.3") == ["e2e: result='skipped'"]


def test_failed_or_cancelled_e2e_blocks_required_despite_marker() -> None:
    """Issue #895: a failed, cancelled or timed-out e2e run blocks the gate
    on every event, marker or no marker — acceptance criterion "Un E2E
    fallido, cancelado, omitido inesperadamente o sin pruebas bloquea".
    """
    for outcome in ("failure", "cancelled", "timed_out"):
        needs = _needs()
        needs["e2e"]["result"] = outcome
        _marker(needs, "false")
        assert check_results(needs, "pull_request") == [f"e2e: result={outcome!r}"]
        assert check_results(needs, "push") == [f"e2e: result={outcome!r}"]


def test_ui_detection_job_is_required_on_every_event() -> None:
    """Issue #895: the ui-detection job is the structural marker source.
    A run without it (or where it failed or was skipped) cannot carry a
    trustworthy marker and fails closed.
    """
    assert "ui-detection" in ALL_JOBS

    needs = _needs()
    needs.pop("ui-detection")
    assert check_results(needs, "pull_request") == ["missing jobs: ui-detection"]

    for outcome in ("failure", "skipped"):
        needs = _needs()
        needs["ui-detection"]["result"] = outcome
        assert check_results(needs, "pull_request") == [
            f"ui-detection: result={outcome!r}"
        ]


def test_non_ui_path_prefixes_pin_the_fail_closed_allowlist() -> None:
    """Issue #895 fix round 1 (JD-B-001): detection is INVERTED. The single
    source of truth now holds the NON-UI allowlist: ``ui_changed`` is true
    unless EVERY changed file matches it. ``app/**`` is deliberately NOT
    allowlisted (FastAPI renders Jinja from Python, so routes and
    _form_render affect the browser) and neither is ``tailwindcss/`` (the
    Tailwind source compiles into app/static/css/output.css).
    """
    directories = {p for p in NON_UI_PATH_PREFIXES if p.endswith("/")}
    root_files = {p for p in NON_UI_PATH_PREFIXES if not p.endswith("/")}

    # Conservative directory allowlist derived from the real tracked tree.
    assert {
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
    } <= directories
    # UI-relevant surfaces are never allowlisted.
    assert not any(p.startswith(("app/", "tailwindcss/")) for p in NON_UI_PATH_PREFIXES)
    # Root-level non-UI files are exact entries.
    assert {
        "AGENTS.md",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "uv.lock",
        "Dockerfile",
    } <= root_files


def test_ui_changed_for_paths_is_true_when_any_file_is_outside_the_allowlist() -> None:
    """Fail-closed inversion: a template change (or ANY file outside the
    allowlist) marks the revision UI-relevant, even mixed with docs edits.
    """
    assert ui_changed_for_paths(["app/templates/index.html"]) is True
    assert ui_changed_for_paths(["docs/x.md", "app/static/css/output.css"]) is True
    assert ui_changed_for_paths(["tailwindcss/styles/app.css"]) is True


def test_ui_changed_for_paths_is_false_when_every_file_is_in_the_allowlist() -> None:
    assert ui_changed_for_paths(["docs/x.md", "tests/test_x.py", "Makefile"]) is False
    assert ui_changed_for_paths(["scripts/check_rules.py", ".github/workflows/pr-name.yml"]) is False


def test_ui_changed_for_paths_is_true_when_the_allowlist_is_emptied() -> None:
    """Emptying the allowlist must force e2e to run for any change — the
    fail-closed direction of the inversion (JD-B-001 pin).
    """
    assert ui_changed_for_paths(["docs/x.md"], allowlist=()) is True
    assert ui_changed_for_paths(["README.md"], allowlist=()) is True


def test_root_file_entries_match_exactly_not_by_prefix() -> None:
    """A root-file entry (no trailing slash) matches exactly, so a new file
    like ``Makefile.bak`` is NOT silently treated as the allowlisted
    ``Makefile`` — fail-closed by default.
    """
    assert ui_changed_for_paths(["Makefile"]) is False
    assert ui_changed_for_paths(["Makefile.bak"]) is True


def test_gate_source_files_pay_the_e2e_toll() -> None:
    """Anti-self-exemption toll (JD-A-001 structural fix): the gate's own
    source cannot be edited without paying the e2e toll. Editing any gate
    file — even together with an obvious non-UI docs change — forces
    ``ui_changed=true``, so an allowlist edit can never reclassify future
    UI changes without e2e evidence.
    """
    assert set(GATE_SOURCE_FILES) == {
        "scripts/check_required_jobs.py",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
    }
    for gate_file in GATE_SOURCE_FILES:
        assert ui_changed_for_paths([gate_file]) is True
        # Gate-file edit + template change ⇒ e2e runs (trivially true under
        # the inversion, but pinned so the toll cannot regress to OR-less).
        assert ui_changed_for_paths([gate_file, "docs/x.md"]) is True
        # The toll must not be bypassable by allowlisting tricks either.
        assert ui_changed_for_paths([gate_file], allowlist=NON_UI_PATH_PREFIXES + (gate_file,)) is True


def test_two_merge_push_scenario_ui_change_in_the_first_commit_is_detected() -> None:
    """JD-B-002 pin: a push delivering two commits where only the FIRST one
    touches UI. Diffing against github.event.before yields the union of both
    commits, so the UI change is detected. The old parent-commit diff saw
    only the second commit and would have skipped e2e — that stale behavior
    is pinned here as the regression the event.before base prevents.
    """
    first_commit_files = ["app/templates/acogidas/form.html"]
    second_commit_files = ["docs/codebase/ci-cd.md"]
    union = first_commit_files + second_commit_files

    assert ui_changed_for_paths(union) is True
    # The old HEAD^ diff would only have seen the second commit.
    assert ui_changed_for_paths(second_commit_files) is False


def test_ui_changed_flag_reads_changed_paths_from_stdin() -> None:
    """The workflows classify the changed-file set through the single source
    of truth via ``--ui-changed`` (one path per line on stdin); the flag
    must work without the CI_NEEDS_JSON environment.
    """
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/check_required_jobs.py", "--ui-changed"],
        cwd=REPO_ROOT,
        input="docs/x.md\napp/templates/index.html\n",
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "true"


def test_print_ui_paths_flag_emits_the_non_ui_allowlist() -> None:
    """The workflows (ci.yml ui-detection, deploy.yml ui-e2e-gate) consume the
    single source of truth through ``--print-ui-paths`` (space-separated
    list; the flag name predates the fix round — it now emits the NON-UI
    allowlist); the flag must work without the CI_NEEDS_JSON environment.
    """
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/check_required_jobs.py", "--print-ui-paths"],
        cwd=REPO_ROOT,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == list(NON_UI_PATH_PREFIXES)


def test_schedule_event_is_unreachable_and_fails_closed() -> None:
    """Issue #780: the weekly cron trigger was removed from ci.yml.

    ``schedule`` is no longer a key in ``SKIPS_BY_EVENT``, so a stray
    ``schedule`` event (one should never reach this gate again) falls
    into the fail-closed "unsupported event" branch instead of silently
    being granted skips.
    """
    needs = _needs()

    violations = check_results(needs, "schedule")
    assert violations == ["unsupported event: schedule"]


def test_e2e_skip_blocks_required_on_workflow_dispatch_and_tag_push() -> None:
    """Issue #766: workflow_dispatch and tag push are release events where
    the e2e suite MUST terminate SUCCESS. A skipped e2e blocks the
    required gate.
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"

    assert check_results(needs, "workflow_dispatch") == ["e2e: result='skipped'"]
    assert check_results(needs, "push", "refs/tags/v1.2.3") == ["e2e: result='skipped'"]


def test_e2e_success_passes_required_on_workflow_dispatch_and_tag_push() -> None:
    """Issue #766: the release-gating happy path.
    """
    needs = _needs()
    assert check_results(needs, "workflow_dispatch") == []
    assert check_results(needs, "push", "refs/tags/v1.2.3") == []


def test_failed_optional_job_still_fails_when_it_runs() -> None:
    needs = _needs()
    needs["mutation"]["result"] = "failure"

    assert check_results(needs, "workflow_dispatch") == ["mutation: result='failure'"]


def test_missing_job_fails_closed() -> None:
    needs = _needs()
    needs.pop("security")

    assert check_results(needs, "pull_request") == ["missing jobs: security"]


def test_tag_push_accepts_the_weekly_deep_security_skip() -> None:
    """Issue #1046: a tag push accepts a skipped security-deep.

    Issue #780 made tag pushes release events where deep security and
    mutation had to run. #1046 moved the deep scan to a weekly schedule
    plus manual dispatch, so release tags no longer trigger it and its
    skip is now an accepted outcome of the checker. Issue #766 is
    unchanged: e2e and mutation must still terminate SUCCESS on a tag
    push — a skipped e2e or mutation remains a violation.
    """
    needs = _needs()
    needs["security-deep"]["result"] = "skipped"

    assert check_results(needs, "push", "refs/tags/v1.2.3") == []

    # Issue #766 unchanged: release events still require a real e2e run.
    needs["e2e"]["result"] = "skipped"
    assert check_results(needs, "push", "refs/tags/v1.2.3") == [
        "e2e: result='skipped'"
    ]

    # ...and a real mutation run.
    needs["e2e"]["result"] = "success"
    needs["mutation"]["result"] = "skipped"
    assert check_results(needs, "push", "refs/tags/v1.2.3") == [
        "mutation: result='skipped'"
    ]


def test_tag_push_still_skips_pr_only_issue_spec() -> None:
    needs = _needs()
    needs["issue-spec"]["result"] = "skipped"

    assert check_results(needs, "push", "refs/tags/v1.2.3") == []


def test_pr_size_is_a_required_job() -> None:
    """Issue #881: ALL_JOBS must list pr-size explicitly.

    The gate happened to fail closed today only because every other job's
    ``needs:`` transitively depends on ``pr-size`` in ci.yml — an
    unverified coupling. A future refactor that drops that transitive
    chain (e.g. a job gaining an independent trigger) would silently stop
    enforcing the 400-line budget, and this aggregator would never notice
    because it never checks pr-size's own result.
    """
    assert "pr-size" in ALL_JOBS


def test_missing_pr_size_fails_closed() -> None:
    needs = _needs()
    needs.pop("pr-size")

    assert check_results(needs, "pull_request") == ["missing jobs: pr-size"]


def test_skipped_pr_size_fails_closed_on_every_event() -> None:
    """pr-size has no ``if:`` guard in ci.yml — it always runs and always
    reports a definitive result (success/failure), even on non-PR events
    (see the empty-BASE_REF fallback that reports total=0 there). A
    skipped pr-size is therefore never legitimate, on any event.
    """
    needs = _needs()
    needs["pr-size"]["result"] = "skipped"

    assert check_results(needs, "pull_request") == ["pr-size: result='skipped'"]
    assert check_results(needs, "push") == ["pr-size: result='skipped'"]
    assert check_results(needs, "workflow_dispatch") == ["pr-size: result='skipped'"]


# --- issue #1118: surface root cause vs cascade skip ----------------------


def test_job_dependencies_match_ci_yml() -> None:
    """Issue #1118: ``JOB_DEPENDENCIES`` must mirror ci.yml ``needs:`` edges.

    Cascade attribution walks this DAG; a drift makes the output point at
    the wrong upstream. Pinned by parsing the workflow YAML directly.
    """
    import yaml

    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    with workflow_path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)

    expected: dict[str, tuple[str, ...]] = {}
    for job_id, job_data in (doc.get("jobs") or {}).items():
        if job_id not in ALL_JOBS:
            # ``required`` aggregator is the consumer of this checker,
            # not a tracked edge of the cascade DAG — skip it.
            continue
        needs = job_data.get("needs")
        if needs is None:
            expected[job_id] = ()
        elif isinstance(needs, str):
            expected[job_id] = (needs,)
        else:
            expected[job_id] = tuple(needs)

    assert set(JOB_DEPENDENCIES) == expected.keys()
    for job, edges in expected.items():
        assert JOB_DEPENDENCIES[job] == edges, (
            f"JOB_DEPENDENCIES drift for {job!r}: "
            f"script={JOB_DEPENDENCIES[job]!r}, ci.yml={edges!r}"
        )


def test_evaluate_groups_failures_as_root_causes() -> None:
    """Issue #1118: failures become ``root_causes``, not ``other_violations``."""
    needs = _needs()
    needs["lint"]["result"] = "failure"

    report = evaluate(needs, "pull_request")

    assert ("lint", "failure") in report.root_causes
    assert not report.other_violations


def test_evaluate_attributes_cascade_skips_to_closest_failing_upstream() -> None:
    """Issue #1118: cascade-skipped jobs attribute to the closest failing
    ancestor (BFS, fewest hops first)."""
    needs = _needs()
    needs["lint"]["result"] = "failure"
    needs["build"]["result"] = "skipped"
    needs["e2e"]["result"] = "skipped"

    report = evaluate(needs, "pull_request")
    cascade = dict(report.cascade_skips)

    assert cascade.get("build") == "lint"
    assert cascade.get("e2e") == "lint"
    assert not report.other_violations


def test_evaluate_does_not_invoke_cascade_without_failing_upstream() -> None:
    """Issue #1118: a skipped job without a failing upstream stays a violation.

    Regression guard: an allowed-skip denial (e.g. e2e on a release event)
    must still surface; cascade attribution must not silently swallow it.
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"

    report = evaluate(needs, "workflow_dispatch")

    assert not report.cascade_skips
    assert any("e2e" in line for line in report.other_violations)


def test_format_report_root_cause_then_consequences_no_json() -> None:
    """Issue #1118: hierarchical output — ROOT CAUSE first, then CONSEQUENCES,
    no raw JSON, unsupported event and missing jobs get their own sections."""
    needs = _needs()
    needs["lint"]["result"] = "failure"
    needs["build"]["result"] = "skipped"
    needs["e2e"]["result"] = "skipped"
    report = evaluate(needs, "pull_request")
    lines = format_report(report)
    text = "\n".join(lines)

    root_idx = next(i for i, line in enumerate(lines) if "ROOT CAUSE" in line)
    cascade_idx = next(i for i, line in enumerate(lines) if "CONSEQUENCES" in line)
    assert root_idx < cascade_idx, (
        f"ROOT CAUSE must precede CONSEQUENCES; lines={lines!r}"
    )
    assert any("lint: result='failure'" in line for line in lines)
    assert any("build (upstream: lint)" in line for line in lines)
    assert any("e2e (upstream: lint)" in line for line in lines)
    # No raw JSON payload (issue #1118 explicit constraint).
    assert "{" not in text and "}" not in text
    assert '"result"' not in text and '"skipped"' not in text

    # The other top-level sections render correctly when populated.
    unsupported_only = format_report(
        RequiredJobsReport(
            missing=(), root_causes=(), cascade_skips=(),
            other_violations=(), unsupported_event="schedule",
        )
    )
    assert any("UNSUPPORTED EVENT" in line and "schedule" in line for line in unsupported_only)

    missing_only = format_report(
        RequiredJobsReport(
            missing=("ui-detection",), root_causes=(), cascade_skips=(),
            other_violations=(), unsupported_event=None,
        )
    )
    assert any("MISSING JOBS" in line for line in missing_only)
    assert any("ui-detection" in line for line in missing_only)


def _run_check_required_jobs(
    needs: dict, *, event: str = "pull_request", ref: str = "refs/heads/feature"
) -> subprocess.CompletedProcess[str]:
    """Run ``scripts/check_required_jobs.py`` against a synthetic needs payload."""
    import json
    import os
    import sys

    env = {
        **os.environ,
        "CI_NEEDS_JSON": json.dumps(needs),
        "CI_EVENT_NAME": event,
        "GITHUB_REF": ref,
    }
    return subprocess.run(
        [sys.executable, "scripts/check_required_jobs.py"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_required_jobs_full_flow_1_failure_2_skips() -> None:
    """Issue #1118: end-to-end against the canonical fixture (1 failure +
    2 cascade skips). Exit code fail-loud, no raw JSON in the output."""
    needs = _needs()
    needs["lint"]["result"] = "failure"
    needs["build"]["result"] = "skipped"
    needs["e2e"]["result"] = "skipped"

    result = _run_check_required_jobs(needs)
    output = result.stderr

    assert result.returncode == 1, (
        f"exit code must be fail-loud; got {result.returncode}, stderr={output!r}"
    )
    root_lines = [line for line in output.splitlines() if "ROOT CAUSE" in line]
    assert len(root_lines) == 1
    assert any("lint: result='failure'" in line for line in output.splitlines())
    cascade_lines = [line for line in output.splitlines() if "CONSEQUENCES" in line]
    assert len(cascade_lines) == 1
    assert any("build (upstream: lint)" in line for line in output.splitlines())
    assert any("e2e (upstream: lint)" in line for line in output.splitlines())
    assert "{" not in output and "}" not in output
    assert '"result"' not in output and '"skipped"' not in output


def test_check_required_jobs_full_flow_happy_path_stays_clean() -> None:
    """Issue #1118 regression: a fully green needs payload exits 0 with
    only the OK marker and no FAIL sections."""
    result = _run_check_required_jobs(_needs())

    assert result.returncode == 0
    assert "required jobs: OK" in result.stdout
    assert "ROOT CAUSE" not in result.stderr
    assert "CONSEQUENCES" not in result.stderr
