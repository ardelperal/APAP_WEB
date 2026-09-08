from __future__ import annotations

from scripts.check_required_jobs import ALL_JOBS, check_results


def _needs(result: str = "success") -> dict[str, dict[str, str]]:
    return {job: {"result": result} for job in ALL_JOBS}


def test_pull_request_accepts_only_the_two_deliberate_scheduled_skips() -> None:
    needs = _needs()
    needs["security-deep"]["result"] = "skipped"
    needs["mutation"]["result"] = "skipped"

    assert check_results(needs, "pull_request") == []


def test_required_job_skip_fails_closed() -> None:
    needs = _needs()
    needs["e2e"]["result"] = "skipped"

    assert check_results(needs, "pull_request") == ["e2e: result='skipped'"]


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
