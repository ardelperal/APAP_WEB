from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_required_jobs import (
    ALL_JOBS,
    DOCS_ONLY_HEAVY_JOBS,
    GATE_SOURCE_DIRS,
    GATE_SOURCE_FILES,
    JOB_DEPENDENCIES,
    NON_UI_PATH_PREFIXES,
    RequiredJobsReport,
    check_results,
    docs_changed_for_paths,
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
            "e2e: result='skipped' without ui_changed='false' "
            f"or docs_changed='true' (got ui_changed={marker!r}, docs_changed='')"
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
        "e2e: result='skipped' without ui_changed='false' "
        "or docs_changed='true' (got ui_changed='true', docs_changed='')"
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
        "e2e: result='skipped' without ui_changed='false' "
        "or docs_changed='true' (got ui_changed='', docs_changed='')"
    ]
    # Malformed output type.
    needs["ui-detection"] = {"result": "success", "outputs": {"ui_changed": 1}}
    assert check_results(needs, "pull_request") == [
        "e2e: result='skipped' without ui_changed='false' "
        "or docs_changed='true' (got ui_changed='', docs_changed='')"
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


def test_gate_source_dirs_pay_the_e2e_toll() -> None:
    """Issue #1095 (slice 1): the fail-closed CI browser gate's own suite
    cannot be edited without paying the e2e toll.

    Mirrors :func:`test_gate_source_files_pay_the_e2e_toll` for
    directories: any file under ``tests/e2e_ci/`` forces
    ``ui_changed=true`` even though ``tests/`` is in the
    :data:`NON_UI_PATH_PREFIXES` allowlist, otherwise the gate could
    silently rot (a PR that only touches ``tests/e2e_ci/`` would skip
    the e2e job today).
    """
    # The GATE_SOURCE_DIRS toll is the one introduced for issue #1095
    # and must keep ``tests/e2e_ci/`` (with the trailing slash the
    # prefix-match idiom requires) as a directory prefix entry.
    assert GATE_SOURCE_DIRS == ("tests/e2e_ci/",)

    # Any file under the toll-listed directory forces the e2e job
    # to run; we sample three representative paths (a new test, a
    # change to the conftest, and a changes to the shared helpers).
    for toll_path in (
        "tests/e2e_ci/test_new_thing.py",
        "tests/e2e_ci/conftest.py",
        "tests/e2e_ci/_crud_helpers.py",
    ):
        assert ui_changed_for_paths([toll_path]) is True, (
            f"{toll_path!r} is under GATE_SOURCE_DIRS and must pay the "
            f"e2e toll."
        )
        # Toll + docs change (trivially true under the inversion,
        # pinned so the toll cannot regress to OR-less — mirrors the
        # file toll's transitive-test above).
        assert ui_changed_for_paths([toll_path, "docs/x.md"]) is True
        # The toll must not be bypassable by allowlisting tricks either;
        # even when the explicit directory is added to the allowlist,
        # the GATE_SOURCE_DIRS branch fires first.
        assert (
            ui_changed_for_paths(
                [toll_path],
                allowlist=NON_UI_PATH_PREFIXES + ("tests/e2e_ci/",),
            )
            is True
        )


def test_gate_source_dirs_does_not_match_outside_the_directory() -> None:
    """The :data:`GATE_SOURCE_DIRS` prefix check fires only for paths
    INSIDE the listed directories. A sibling like ``tests/test_x.py``
    or ``tests/e2e_x.py`` stays under the regular :data:`NON_UI_PATH_PREFIXES`
    rules and is not pulled into the toll. Pins the prefix-match idiom
    so the toll cannot regress to substring/contains matching.
    """
    assert ui_changed_for_paths(["tests/test_x.py"]) is False
    assert ui_changed_for_paths(["tests/e2e_external/foo.py"]) is False
    # A file whose name literally starts with the directory prefix but
    # lives elsewhere (e.g. ``tests/e2e_ci_x/test.py``) is NOT under
    # the toll — the check is prefix-on-``tests/e2e_ci/``.
    assert ui_changed_for_paths(["tests/e2e_ci_x/test.py"]) is False


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


# ---------------------------------------------------------------------------
# Issue #1196: docs-only fast lane — fail-closed classifier.
# ---------------------------------------------------------------------------


def test_docs_changed_for_paths_true_for_pure_documentation_diffs() -> None:
    """Issue #1196: docs-only holds only when EVERY changed file is prose:
    everything under docs/, root-level *.md files, *.md under skills/."""
    assert docs_changed_for_paths(["docs/architecture/foo.md"]) is True
    assert docs_changed_for_paths(["README.md", "CHANGELOG.md"]) is True
    assert docs_changed_for_paths(["skills/apap-architecture/SKILL.md"]) is True
    assert docs_changed_for_paths(
        ["docs/runbooks/e2e-production.md", "CONTRIBUTING.md"]
    ) is True


def test_docs_changed_for_paths_is_false_when_any_code_file_is_present() -> None:
    """Mixed PRs (docs + anything else) run the heavy jobs: the detection is
    strict ALL-files-are-docs."""
    assert docs_changed_for_paths(["docs/x.md", "app/main.py"]) is False
    assert docs_changed_for_paths(["README.md", "Makefile"]) is False
    assert docs_changed_for_paths(["docs/x.md", "tests/test_ci_workflow.py"]) is False
    assert docs_changed_for_paths(["docs/x.md", ".github/workflows/ci.yml"]) is False


def test_docs_changed_for_paths_never_classifies_gate_sources_as_docs() -> None:
    """Anti-self-exemption toll (mirrors issue #895): the gate's own sources
    can never ride the docs-only lane, even defensively."""
    assert docs_changed_for_paths(["scripts/check_required_jobs.py"]) is False
    assert docs_changed_for_paths(["docs/x.md", ".github/workflows/deploy.yml"]) is False


def test_docs_changed_for_paths_excludes_github_markdown() -> None:
    """``.github/**`` is code-adjacent: workflow markdown never counts as docs."""
    assert docs_changed_for_paths([".github/pull_request_template.md"]) is False
    assert docs_changed_for_paths([".github/workflows/notes.md"]) is False


def test_docs_changed_for_paths_requires_markdown_under_skills() -> None:
    """Only *.md under skills/ counts; skill assets are not prose."""
    assert docs_changed_for_paths(["skills/apap-security/data.json"]) is False


def test_docs_changed_for_paths_scopes_root_markdown_to_the_root() -> None:
    """Nested non-docs markdown is code-adjacent, not documentation."""
    assert docs_changed_for_paths(["app/README.md"]) is False


def test_docs_changed_for_paths_empty_diff_runs_heavy_jobs() -> None:
    """Fail-closed: an empty changed set is a known no-op, not a docs-only
    diff — the heavy jobs must run."""
    assert docs_changed_for_paths([]) is False


def test_docs_only_heavy_jobs_pin_the_skip_set() -> None:
    """The heavy set is exactly the jobs the docs-only lane may skip."""
    assert DOCS_ONLY_HEAVY_JOBS == frozenset(
        {"typecheck", "test", "integration", "verify-fallback-ready", "build"}
    )


# ---------------------------------------------------------------------------
# Issue #1196: docs-only fast lane — skip acceptance in ``evaluate``.
# ---------------------------------------------------------------------------


def _docs_marker(
    needs: dict[str, dict], docs_changed: str, ui_changed: str = "false"
) -> dict[str, dict]:
    """Attach a ui-detection output payload carrying both markers."""
    needs["ui-detection"] = {
        "result": "success",
        "outputs": {"ui_changed": ui_changed, "docs_changed": docs_changed},
    }
    return needs


def test_docs_only_pull_request_accepts_the_documented_heavy_job_skips() -> None:
    """Issue #1196: on a docs-only PR the heavy jobs (and e2e) skip with the
    ``docs_changed='true'`` marker and the aggregator stays green."""
    needs = _needs()
    _docs_marker(needs, "true")
    for job in ("typecheck", "test", "integration", "verify-fallback-ready", "build", "e2e"):
        needs[job]["result"] = "skipped"

    report = evaluate(needs, "pull_request")

    assert report.is_clean, report


def test_heavy_job_skip_without_docs_marker_fails_closed() -> None:
    """A skipped heavy job without the marker stays a violation with its
    documented skip reason named."""
    needs = _needs()
    _docs_marker(needs, "false")
    needs["test"]["result"] = "skipped"

    report = evaluate(needs, "pull_request")

    assert any(
        "test" in line and "docs_changed" in line
        for line in report.other_violations
    ), report.other_violations


def test_docs_marker_does_not_accept_heavy_skips_on_release_events() -> None:
    """Release events (workflow_dispatch / tag push) must terminate the heavy
    jobs SUCCESS; the docs marker never exempts them there."""
    needs = _needs()
    _docs_marker(needs, "true")
    needs["test"]["result"] = "skipped"

    report = evaluate(needs, "workflow_dispatch")

    assert not report.is_clean
    assert report.other_violations


def test_e2e_skip_on_docs_only_pr_accepted_even_with_ui_changed_true() -> None:
    """Issue #1196: on a docs-only PR the e2e skip is accepted through the
    docs marker even when ui_changed is not 'false'."""
    needs = _needs()
    _docs_marker(needs, "true", ui_changed="true")
    needs["e2e"]["result"] = "skipped"

    report = evaluate(needs, "pull_request")

    assert report.is_clean, report


def test_docs_only_pr_with_missing_job_still_fails_closed() -> None:
    """The marker accepts documented skips, never absent jobs."""
    needs = _needs()
    _docs_marker(needs, "true")
    for job in ("typecheck", "test", "integration", "verify-fallback-ready", "build"):
        needs[job]["result"] = "skipped"
    del needs["build"]

    report = evaluate(needs, "pull_request")

    assert "build" in report.missing
    assert not report.is_clean


def test_docs_changed_flag_reads_changed_paths_from_stdin() -> None:
    """The workflow classifies the changed-file set through ``--docs-changed``
    (one path per line on stdin), mirroring ``--ui-changed``."""
    import subprocess
    import sys

    pure = subprocess.run(
        [sys.executable, "scripts/check_required_jobs.py", "--docs-changed"],
        cwd=REPO_ROOT,
        input="docs/x.md\nREADME.md\nskills/foo/SKILL.md\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert pure.returncode == 0
    assert pure.stdout.strip() == "true"

    mixed = subprocess.run(
        [sys.executable, "scripts/check_required_jobs.py", "--docs-changed"],
        cwd=REPO_ROOT,
        input="docs/x.md\napp/main.py\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert mixed.returncode == 0
    assert mixed.stdout.strip() == "false"
