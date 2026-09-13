from __future__ import annotations

from scripts.check_required_jobs import ALL_JOBS, check_results


def _needs(result: str = "success") -> dict[str, dict[str, str]]:
    return {job: {"result": result} for job in ALL_JOBS}


def test_pull_request_accepts_only_the_two_deliberate_scheduled_skips() -> None:
    needs = _needs()
    needs["security-deep"]["result"] = "skipped"
    needs["mutation"]["result"] = "skipped"

    assert check_results(needs, "pull_request") == []


def test_non_pr_events_skip_issue_spec_but_pull_requests_require_it() -> None:
    needs = _needs()
    needs["issue-spec"]["result"] = "skipped"

    assert check_results(needs, "workflow_dispatch") == []
    assert check_results(needs, "pull_request") == ["issue-spec: result='skipped'"]


def test_e2e_skip_is_allowed_on_pull_request() -> None:
    """E2E requires Postgres + MinIO + Chromium; the Docker pull for those
    images flakes intermittently on the hosted runner. Run only on
    release events (schedule / tag push / workflow_dispatch) per
    AGENTS §PR_DISCIPLINE so PRs are not blocked by infrastructure
    flakes. A skipped e2e job on a PR is therefore NOT a policy
    violation.
    """
    needs = _needs()
    needs["e2e"]["result"] = "skipped"

    assert check_results(needs, "pull_request") == []
    assert check_results(needs, "push") == []
    assert check_results(needs, "workflow_dispatch") == []


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
