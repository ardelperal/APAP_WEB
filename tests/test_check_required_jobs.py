from __future__ import annotations

from pathlib import Path

from scripts.check_required_jobs import ALL_JOBS, UI_PATH_PREFIXES, check_results

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


def test_ui_path_prefixes_pin_the_derived_ui_surface() -> None:
    """Issue #895 (design D1): the UI surface single source of truth lives in
    scripts/check_required_jobs.py. It is derived from the repository layout:
    Jinja2 HTML under app/templates/, browser-loaded CSS/JS under app/static/
    (css/output.css is compiled from tailwindcss/styles), and the Tailwind
    source styles under tailwindcss/. Backend modules, migration/, tests/
    and docs/ are deliberately NOT part of the surface.
    """
    assert set(UI_PATH_PREFIXES) == {"app/templates/", "app/static/", "tailwindcss/"}
    assert all(prefix.endswith("/") for prefix in UI_PATH_PREFIXES)


def test_print_ui_paths_flag_emits_the_workflow_consumable_list() -> None:
    """The workflows (ci.yml ui-detection, deploy.yml ui-e2e-gate) consume the
    single source of truth through ``--print-ui-paths`` (space-separated
    prefixes); the flag must work without the CI_NEEDS_JSON environment.
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
    assert result.stdout.split() == list(UI_PATH_PREFIXES)


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


def test_tag_push_requires_deep_security_and_mutation() -> None:
    needs = _needs()
    needs["security-deep"]["result"] = "skipped"

    assert check_results(needs, "push", "refs/tags/v1.2.3") == [
        "security-deep: result='skipped'"
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
