"""Contract tests for issue specifications (issue #723)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_issue_specs  # noqa: E402


class RecordingSleep:
    """Injectable no-op sleep that records every injected delay."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


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


def test_repository_forms_implement_one_shared_required_contract() -> None:
    assert check_issue_specs.validate_forms() == []


def test_issue_spec_job_is_read_only_and_runs_for_pull_requests() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "issues: read" in workflow
    assert "pull-requests: read" in workflow
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
        "the issue contract requires all six canonical sections: "
        + "; ".join(check_issue_specs.REQUIRED_SECTIONS),
        "requires status:approved",
    ]


def test_issue_contract_failure_names_all_six_canonical_sections() -> None:
    """Issue #1217: the failure names the full six-section contract.

    An author who created the issue via `gh issue create --body` (bypassing
    the form templates, which expose the six fields) discovers the contract
    red, section by section, unless the failure message itself enumerates
    the six canonical sections.
    """
    issue = _issue(
        body=_body(**{"Plan de validación": "_No response_"}),
        labels=["type:feature", "status:approved"],
    )

    joined = "\n".join(check_issue_specs.issue_contract_errors(issue))

    assert "missing or empty section: Plan de validación" in joined
    for section in check_issue_specs.REQUIRED_SECTIONS:
        assert section in joined, f"the message must name the contract section: {section}"


def test_issue_contract_requires_exactly_one_supported_type() -> None:
    issue = _issue(labels=["type:bug", "type:feature", "status:approved"])

    assert check_issue_specs.issue_contract_errors(issue) == [
        "requires exactly one supported type:* label"
    ]


REPO = "ardelperal/APAP_WEB"


class StubClient:
    def __init__(
        self,
        issues: dict[int, dict[str, Any]],
        closing: tuple[int, ...] = (),
        labels: frozenset[str] = frozenset(),
    ) -> None:
        self.issues_by_number = issues
        self.links = check_issue_specs.PullRequestLinks(labels=labels, closing_issues=closing)
        self.requested: list[tuple[str, int]] = []
        self.pull_requests: list[tuple[str, int]] = []

    def issue(self, repository: str, number: int) -> dict[str, Any]:
        self.requested.append((repository, number))
        return self.issues_by_number[number]

    def pull_request_links(
        self, repository: str, number: int
    ) -> check_issue_specs.PullRequestLinks:
        self.pull_requests.append((repository, number))
        return self.links


def _event(head_ref: str, actor: str = "maintainer", number: int = 7) -> dict[str, Any]:
    return {
        "repository": {"full_name": REPO},
        "pull_request": {
            "number": number,
            "user": {"login": actor},
            "head": {"ref": head_ref},
            # Prose is deliberately hostile: the gate must never read it.
            "body": "Closes #999 and Fixes #998",
        },
    }


class SequencedLinksClient(StubClient):
    """Stub whose pull_request_links replays a queue of link snapshots.

    Models the closingIssuesReferences race (friction B11): GitHub populates
    the field seconds after PR creation, so the first query sees it absent
    and later queries see it present. The last snapshot repeats forever.
    """

    def __init__(
        self,
        issues: dict[int, dict[str, Any]],
        labels: frozenset[str] = frozenset(),
        sequence: tuple[check_issue_specs.PullRequestLinks, ...] = (),
    ) -> None:
        super().__init__(issues, labels=labels)
        if not sequence:
            raise ValueError("sequence must contain at least one snapshot")
        self._sequence = sequence

    def pull_request_links(
        self, repository: str, number: int
    ) -> check_issue_specs.PullRequestLinks:
        self.pull_requests.append((repository, number))
        return self._sequence[min(len(self.pull_requests) - 1, len(self._sequence) - 1)]


def _event_with_body(body: str, head_ref: str = "fix/42-some-slug") -> dict[str, Any]:
    event = _event(head_ref)
    event["pull_request"]["body"] = body
    return event


def test_branch_number_closing_reference_and_approved_issue_pass() -> None:
    client = StubClient({42: _issue()}, closing=(42,))

    assert check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client) == []
    assert client.requested == [(REPO, 42)]
    assert client.pull_requests == [(REPO, 7)]


def test_result_never_depends_on_the_pr_body() -> None:
    client = StubClient({42: _issue()}, closing=(42,))
    event = _event("fix/42-some-slug")
    event["pull_request"]["body"] = "no keywords here"

    assert check_issue_specs.validate_pr_event(event, client) == []
    assert client.requested == [(REPO, 42)]


def test_branch_without_issue_number_fails_with_the_expected_shape() -> None:
    violations = check_issue_specs.validate_pr_event(_event("fix/no-number"), StubClient({}))

    assert len(violations) == 1
    assert "<tipo>/<N>-<slug>" in violations[0]


def test_exempt_heads_skip_the_issue_contract() -> None:
    client = StubClient({})

    for head in ("archive/old-work", "main", "skill-fleet/apap"):
        assert check_issue_specs.validate_pr_event(_event(head), client) == []
    assert client.requested == []
    assert client.pull_requests == []


def test_dependabot_pr_is_the_only_automated_exemption() -> None:
    client = StubClient({})
    event = _event("dependabot/pip/foo-1.2", actor="dependabot[bot]")

    assert check_issue_specs.validate_pr_event(event, client) == []
    assert client.pull_requests == []


def test_chain_partial_with_closing_reference_to_branch_issue_fails() -> None:
    client = StubClient({42: _issue()}, closing=(42,), labels=frozenset({"chain:partial"}))

    violations = check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client)

    assert len(violations) == 1
    assert "chain:partial" in violations[0]
    assert "#42" in violations[0]
    assert "would close" in violations[0]


def test_premature_close_failure_names_body_and_title() -> None:
    """Issue #1216: the premature-close failure names body AND title.

    #1138's TITLE contained a closing keyword and the chain tip's issue was
    closed by the intermediate leg: closing keywords in either location
    create real closingIssuesReferences, so the failure message must name
    both as locations to clean.
    """
    client = StubClient({42: _issue()}, closing=(42,), labels=frozenset({"chain:partial"}))

    violations = check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client)

    assert "body" in violations[0]
    assert "title" in violations[0]


def test_chain_partial_without_closing_reference_passes() -> None:
    client = StubClient({42: _issue()}, closing=(), labels=frozenset({"chain:partial"}))

    assert check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client) == []


def test_missing_closing_reference_without_chain_partial_fails() -> None:
    client = StubClient({42: _issue()}, closing=())

    violations = check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client)

    assert len(violations) == 1
    assert "Closes #42" in violations[0]
    assert "chain:partial" in violations[0]


def test_closing_reference_to_a_different_issue_does_not_satisfy_the_branch_issue() -> None:
    client = StubClient({42: _issue(), 41: _issue()}, closing=(41,))

    violations = check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client)

    assert len(violations) == 1
    assert "Closes #42" in violations[0]


def test_other_closing_reference_must_be_an_approved_issue() -> None:
    other = _issue(labels=["type:feature"])
    client = StubClient({42: _issue(), 41: other}, closing=(42, 41))

    violations = check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client)

    assert violations == ["#41: requires status:approved"]


def test_closed_approved_other_issue_keeps_the_historical_exemption() -> None:
    legacy = _issue(body="### Evidencia\n\nold", labels=["status:approved"])
    legacy["state"] = "closed"
    client = StubClient({42: _issue(), 41: legacy}, closing=(42, 41))

    assert check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client) == []


def test_branch_issue_must_be_open_and_have_a_complete_spec() -> None:
    closed = _issue(labels=["type:feature"])
    closed["state"] = "closed"
    client = StubClient({42: closed}, closing=(42,))

    violations = check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client)

    assert violations == ["#42: the branch issue must be open", "#42: requires status:approved"]


def test_branch_issue_that_is_a_pull_request_fails() -> None:
    pull = _issue()
    pull["pull_request"] = {"url": "x"}
    client = StubClient({42: pull}, closing=(42,))

    assert check_issue_specs.validate_pr_event(_event("fix/42-some-slug"), client) == [
        "#42: reference resolves to a pull request"
    ]


def test_event_without_repository_or_pr_number_fails_closed() -> None:
    event = _event("fix/42-some-slug")
    del event["pull_request"]["number"]

    assert check_issue_specs.validate_pr_event(event, StubClient({})) == [
        "event does not identify the pull request number"
    ]
    assert check_issue_specs.validate_pr_event({}, StubClient({})) == [
        "event does not identify repository.full_name"
    ]


def test_graphql_payload_is_reduced_to_labels_and_same_repository_closing_issues() -> None:
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "labels": {"nodes": [{"name": "chain:partial"}, {"name": "ci"}]},
                    "closingIssuesReferences": {
                        "nodes": [
                            {"number": 42, "repository": {"nameWithOwner": "ArdelPerAl/apap_web"}},
                            {"number": 9, "repository": {"nameWithOwner": "other/project"}},
                        ]
                    },
                }
            }
        }
    }

    links = check_issue_specs.parse_pull_request_links(payload, REPO, 7)

    assert links.labels == frozenset({"chain:partial", "ci"})
    assert links.closing_issues == (42,)


def test_graphql_errors_or_missing_pull_request_raise_a_readable_api_error() -> None:
    for payload in ({"errors": [{"message": "denied"}]}, {"data": {"repository": None}}, []):
        with pytest.raises(check_issue_specs.GitHubApiError):
            check_issue_specs.parse_pull_request_links(payload, REPO, 7)


def test_unreadable_branch_issue_is_a_readable_violation_not_a_traceback() -> None:
    violations = check_issue_specs.validate_pr_event(
        _event("fix/4706-some-slug"), FailingClient()
    )

    assert len(violations) == 1
    assert violations[0].startswith("#4706: cannot read the issue")


def test_unreadable_pull_request_links_fail_loud() -> None:
    class NoLinks(StubClient):
        def pull_request_links(
            self, repository: str, number: int
        ) -> check_issue_specs.PullRequestLinks:
            raise check_issue_specs.GitHubApiError("graphql", f"{repository}#{number}", "403")

    violations = check_issue_specs.validate_pr_event(
        _event("fix/42-some-slug"), NoLinks({42: _issue()})
    )

    assert len(violations) == 1
    assert "cannot read the pull request" in violations[0]


def test_body_declares_closing_keyword_matches_verbatim_numbers_only() -> None:
    assert check_issue_specs.body_declares_closing_keyword("Closes #42", 42)
    assert check_issue_specs.body_declares_closing_keyword("closes #42.", 42)
    assert check_issue_specs.body_declares_closing_keyword("Closes #999 and Fixes #42", 42)
    assert not check_issue_specs.body_declares_closing_keyword("Fixes #1421", 42)
    assert not check_issue_specs.body_declares_closing_keyword("Refs #42", 42)
    assert not check_issue_specs.body_declares_closing_keyword("no keywords here", 42)


def test_late_registered_closing_reference_passes_after_retry() -> None:
    absent = check_issue_specs.PullRequestLinks(labels=frozenset(), closing_issues=())
    present = check_issue_specs.PullRequestLinks(labels=frozenset(), closing_issues=(42,))
    client = SequencedLinksClient({42: _issue()}, sequence=(absent, present))
    sleep = RecordingSleep()

    violations = check_issue_specs.validate_pr_event(
        _event_with_body("Closes #42"), client, retry_delays=(0.0,), sleep=sleep
    )

    assert violations == []
    assert client.pull_requests == [(REPO, 7), (REPO, 7)]
    assert sleep.delays == [0.0]


def test_never_registered_closing_reference_fails_after_full_backoff() -> None:
    absent = check_issue_specs.PullRequestLinks(labels=frozenset(), closing_issues=())
    client = SequencedLinksClient({42: _issue()}, sequence=(absent,))
    sleep = RecordingSleep()

    violations = check_issue_specs.validate_pr_event(
        _event_with_body("Fixes #42"), client, retry_delays=(0.0, 0.0, 0.0), sleep=sleep
    )

    assert len(violations) == 1
    assert "Closes #42" in violations[0]
    assert "chain:partial" in violations[0]
    assert len(client.pull_requests) == 4  # initial query + one per injected delay
    assert sleep.delays == [0.0, 0.0, 0.0]


def test_absent_closing_reference_without_body_keyword_fails_without_retry() -> None:
    absent = check_issue_specs.PullRequestLinks(labels=frozenset(), closing_issues=())
    client = SequencedLinksClient({42: _issue()}, sequence=(absent,))
    sleep = RecordingSleep()

    violations = check_issue_specs.validate_pr_event(
        _event_with_body("no keywords here"), client, retry_delays=(0.0, 0.0), sleep=sleep
    )

    assert len(violations) == 1
    assert "Closes #42" in violations[0]
    assert len(client.pull_requests) == 1  # genuine failure: no retries
    assert sleep.delays == []


def test_chain_partial_with_absent_reference_is_never_retried() -> None:
    absent = check_issue_specs.PullRequestLinks(
        labels=frozenset({"chain:partial"}), closing_issues=()
    )
    client = SequencedLinksClient(
        {42: _issue()}, labels=frozenset({"chain:partial"}), sequence=(absent,)
    )
    sleep = RecordingSleep()

    assert check_issue_specs.validate_pr_event(
        _event_with_body("Closes #42"), client, retry_delays=(0.0,), sleep=sleep
    ) == []
    assert len(client.pull_requests) == 1  # chain:partial escape stays retry-free
    assert sleep.delays == []


def test_closing_retry_delays_default_and_env_override() -> None:
    assert check_issue_specs.closing_retry_delays({}) == (30.0, 60.0, 90.0)
    assert check_issue_specs.closing_retry_delays(
        {check_issue_specs._CLOSING_RETRY_ENV: "5,10"}
    ) == (5.0, 10.0)


def test_closing_retry_delays_fail_loud_on_malformed_env() -> None:
    for raw in ("soon", "-1", "30,"):
        with pytest.raises(ValueError):
            check_issue_specs.closing_retry_delays(
                {check_issue_specs._CLOSING_RETRY_ENV: raw}
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


class FailingClient(StubClient):
    def __init__(self) -> None:
        super().__init__({})

    def issue(self, repository: str, number: int) -> dict[str, Any]:
        raise check_issue_specs.GitHubApiError(
            "read", f"/repos/{repository}/issues/{number}", OSError("HTTP Error 404: Not Found")
        )
