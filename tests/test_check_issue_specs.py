"""Contract tests for issue specifications (issue #723)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_issue_specs  # noqa: E402


def _body(**overrides: str) -> str:
    answers = {heading: f"Answer for {heading}." for heading in check_issue_specs.REQUIRED_SECTIONS}
    answers.update(overrides)
    return "\n\n".join(f"### {heading}\n\n{answer}" for heading, answer in answers.items())


def _issue(body: str | None = None, labels: list[str] | None = None) -> dict[str, Any]:
    return {
        "number": 42,
        "html_url": "https://github.com/ardelperal/APAP_WEB/issues/42",
        "state": "open",
        "title": "Example issue",
        "body": _body() if body is None else body,
        "labels": [{"name": label} for label in (labels or ["type:feature", "status:approved"])],
    }


class StubClient:
    def __init__(self, issues: dict[int, dict[str, Any]]) -> None:
        self.issues_by_number = issues
        self.requested: list[tuple[str, int]] = []

    def issue(self, repository: str, number: int) -> dict[str, Any]:
        self.requested.append((repository, number))
        return self.issues_by_number[number]


def _event(body: str, actor: str = "maintainer") -> dict[str, Any]:
    return {
        "repository": {"full_name": "ardelperal/APAP_WEB"},
        "pull_request": {"body": body, "user": {"login": actor}},
    }


def test_repository_forms_implement_one_shared_required_contract() -> None:
    assert check_issue_specs.validate_forms() == []


def test_issue_spec_job_is_read_only_and_runs_for_pull_requests() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "issues: read" in workflow
    assert "issue-spec:" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "persist-credentials: false" in workflow
    assert 'python scripts/check_issue_specs.py pr-event "$GITHUB_EVENT_PATH"' in workflow


def test_local_and_ci_gates_validate_the_versioned_forms() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "check-issue-specs:" in makefile
    assert "check-issue-specs typecheck" in makefile
    assert "python scripts/check_issue_specs.py forms" in workflow


def test_form_validator_fails_when_a_required_control_becomes_optional(tmp_path: Path) -> None:
    source = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
    for filename in (*check_issue_specs.EXPECTED_FORMS, "config.yml"):
        (tmp_path / filename).write_text((source / filename).read_text(), encoding="utf-8")
    path = tmp_path / "feature_request.yml"
    form = yaml.safe_load(path.read_text())
    form["body"][0]["validations"]["required"] = False
    path.write_text(yaml.safe_dump(form, allow_unicode=True), encoding="utf-8")

    violations = check_issue_specs.validate_forms(tmp_path)

    assert violations == [
        "feature_request.yml: 'Problema y contexto' must be required"
    ]


def test_form_validator_fails_closed_on_an_empty_directory(tmp_path: Path) -> None:
    violations = check_issue_specs.validate_forms(tmp_path)

    assert violations == [
        "missing issue form: bug_report.yml",
        "missing issue form: documentation.yml",
        "missing issue form: feature_request.yml",
        "missing issue form: maintenance.yml",
        "missing issue form: refactor.yml",
        "missing issue form config.yml",
    ]


def test_form_validator_reports_malformed_yaml(tmp_path: Path) -> None:
    source = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
    for filename in (*check_issue_specs.EXPECTED_FORMS, "config.yml"):
        (tmp_path / filename).write_text((source / filename).read_text(), encoding="utf-8")
    (tmp_path / "feature_request.yml").write_text("body: [", encoding="utf-8")

    violations = check_issue_specs.validate_forms(tmp_path)

    assert len(violations) == 1
    assert violations[0].startswith(f"{tmp_path}/feature_request.yml: invalid issue form:")


def test_issue_contract_rejects_empty_section_and_missing_approval() -> None:
    issue = _issue(
        body=_body(**{"Plan de validación": "_No response_"}),
        labels=["type:feature"],
    )

    assert check_issue_specs.issue_contract_errors(issue) == [
        "missing or empty section: Plan de validación",
        "requires status:approved",
    ]


def test_issue_contract_requires_exactly_one_supported_type() -> None:
    issue = _issue(labels=["type:bug", "type:feature", "status:approved"])

    assert check_issue_specs.issue_contract_errors(issue) == [
        "requires exactly one supported type:* label"
    ]


def test_pr_event_validates_every_same_repository_closing_reference() -> None:
    client = StubClient({41: _issue(), 42: _issue()})
    event = _event(
        "Closes #42\nFixes https://github.com/ardelperal/APAP_WEB/issues/41\n"
        "Closes https://github.com/other/project/issues/9"
    )

    assert check_issue_specs.validate_pr_event(event, client) == []
    assert client.requested == [("ardelperal/APAP_WEB", 41), ("ardelperal/APAP_WEB", 42)]


def test_human_pr_without_closing_issue_fails_closed() -> None:
    assert check_issue_specs.validate_pr_event(_event("Refs #42"), StubClient({})) == [
        "PR body must close at least one approved issue"
    ]


def test_dependabot_pr_is_the_only_automated_exemption() -> None:
    assert (
        check_issue_specs.validate_pr_event(
            _event("", actor="dependabot[bot]"), StubClient({})
        )
        == []
    )


def test_baseline_contains_no_body_and_binds_to_body_hash(tmp_path: Path) -> None:
    issue = _issue(body="### Evidencia\n\nVerified by audit.")
    output = tmp_path / "baseline.jsonl"

    check_issue_specs.write_baseline(
        [issue], output, "ardelperal/APAP_WEB", cutoff=722, as_of="2026-09-09"
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0] == {
        "as_of": "2026-09-09",
        "cutoff_issue": 722,
        "issue_count": 1,
        "kind": "metadata",
        "repository": "ardelperal/APAP_WEB",
        "schema_version": 1,
    }
    assert "body" not in rows[1]
    assert rows[1]["body_sha256"] == check_issue_specs.hashlib.sha256(
        issue["body"].encode()
    ).hexdigest()
    assert rows[1]["canonical_sections"]["Evidencia verificable"] == "absent"
    assert rows[1]["semantic_signals"]["evidence"] == "detected"
    assert rows[1]["workflow_ready"] is False


def test_checked_in_baseline_covers_exactly_the_pre_contract_history() -> None:
    path = REPO_ROOT / "docs" / "quality" / "issue-spec-baseline.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["repository"] == "ardelperal/APAP_WEB"
    assert rows[0]["cutoff_issue"] == 722
    assert rows[0]["issue_count"] == 308
    assert len(rows[1:]) == 308
    assert [row["number"] for row in rows[1:]] == sorted(
        {row["number"] for row in rows[1:]}
    )
    assert all("body" not in row for row in rows[1:])


# --- Issue #952: closing-reference parsing ---------------------------------


def _closing(body: str) -> list[int]:
    return check_issue_specs.extract_closing_issue_numbers(body, "ardelperal/APAP_WEB")


def test_keyword_at_line_end_does_not_reach_a_number_on_the_next_line() -> None:
    # PR #951: "... alias fix" followed by "4706 passed" was read as "fix #4706".
    assert _closing("# before the PLR0402 alias fix\n4706 passed, 1 failed") == []


def test_a_bare_number_without_hash_is_not_a_reference() -> None:
    assert _closing("Fixes 12 flaky tests") == []


def test_references_inside_fenced_code_blocks_do_not_count() -> None:
    # PR #931: a chain diagram in a code block closed #913 prematurely.
    body = "Refs #945\n\n```\nmain\n └─ next (2c, Closes #945)\n```\n"
    assert _closing(body) == []


def test_references_inside_inline_code_do_not_count() -> None:
    assert _closing("Use `Closes #945` only in the final slice.") == []


def test_documented_github_forms_are_still_detected() -> None:
    body = (
        "Closes #12\n"
        "Fixes: #13\n"
        "resolves ardelperal/APAP_WEB#14\n"
        "Closes https://github.com/ardelperal/APAP_WEB/issues/15\n"
        "Closes other/project#99\n"
    )
    assert _closing(body) == [12, 13, 14, 15]


class FailingClient:
    def issue(self, repository: str, number: int) -> dict[str, Any]:
        raise check_issue_specs.GitHubApiError(
            "read", f"/repos/{repository}/issues/{number}", OSError("HTTP Error 404: Not Found")
        )


def test_unreadable_issue_is_a_readable_violation_not_a_traceback() -> None:
    violations = check_issue_specs.validate_pr_event(_event("Closes #4706"), FailingClient())

    assert len(violations) == 1
    assert violations[0].startswith("#4706: cannot read the issue")
