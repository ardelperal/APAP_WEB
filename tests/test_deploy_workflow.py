"""Pin tests for the release e2e evidence flow in deploy.yml (issues #908, #1082).

Issue #908 anchored the production e2e validation
(docs/runbooks/e2e-production.md) into the release path. Issue #1082 replaced
the pre-deploy check of a global repository variable (which was circular: the
runbook validates production AFTER deploy) with per-revision evidence: after a
successful deploy the ``release-e2e-record`` job sets the commit status
``release/e2e-production`` to ``pending`` on the deployed SHA, and the operator
records the verdict on that same SHA. The workflow deliberately does NOT run
Playwright and holds no secret beyond the job token. These pins follow the
string-based assertion style of tests/test_ci_workflow.py.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
RECORD_JOB_NAME = "release-e2e-record"
STATUS_CONTEXT = "release/e2e-production"
#: The retired variable-based contract must not come back.
RETIRED_VARIABLE = "APAP_E2E_GATE_EVIDENCE"
RUNBOOK_PATH = "docs/runbooks/e2e-production.md"


def _job_sections(workflow: str) -> dict[str, str]:
    """Return each top-level job's text without adding a YAML test dependency."""
    jobs = workflow[workflow.index("\njobs:\n") :]
    marks = [
        (match.group(1), match.start())
        for match in re.finditer(r"^  ([a-z][a-z0-9-]+):$", jobs, flags=re.MULTILINE)
    ]
    sections: dict[str, str] = {}
    for index, (name, start) in enumerate(marks):
        end = marks[index + 1][1] if index + 1 < len(marks) else len(jobs)
        sections[name] = jobs[start:end]
    return sections


def _record_section() -> str:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    return _job_sections(workflow)[RECORD_JOB_NAME]


def _ui_gate_section() -> str:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    return _job_sections(workflow)["ui-e2e-gate"]


def test_pre_deploy_variable_gate_is_gone_and_deploy_no_longer_needs_it() -> None:
    """Issue #1082: the variable-based gate blocked every deploy and, once
    filled, approved every later release. It must not exist anymore.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    sections = _job_sections(workflow)

    assert "release-e2e-gate" not in sections
    assert RETIRED_VARIABLE not in workflow
    assert "needs: [evidence, ui-e2e-gate]" in sections["deploy"]


def test_release_e2e_record_runs_after_a_successful_deploy_only() -> None:
    """The record job needs deploy and runs only when deploy succeeded, so a
    failed or skipped deploy never opens an e2e validation window.
    """
    section = _record_section()

    assert "needs: [deploy]" in section
    assert "needs.deploy.result == 'success'" in section


def test_release_e2e_record_sets_pending_status_on_the_deployed_sha() -> None:
    section = _record_section()

    assert STATUS_CONTEXT in section
    assert 'state: "pending"' in section
    assert "statuses/${GITHUB_SHA}" in section
    assert RUNBOOK_PATH in section


def test_release_e2e_record_has_least_privilege_and_no_secrets() -> None:
    """Epic #909: no secret, no Playwright, no deploy-host access; the job
    writes a commit status and reads contents, nothing else.
    """
    section = _record_section()

    assert "statuses: write" in section
    assert "contents: read" in section
    assert "packages:" not in section
    assert "id-token:" not in section
    assert "secrets." not in section
    assert "github.token" in section
    assert "playwright" not in section.lower()
    assert "docker" not in section.lower()


def test_release_e2e_record_pins_any_action_by_sha() -> None:
    section = _record_section()

    for match in re.finditer(r"^\s*(?:- )?uses:\s*(\S+)", section, flags=re.MULTILINE):
        assert re.search(r"@[0-9a-f]{40}$", match.group(1)), match.group(1)


# --- issue #895 fix round 1: UI e2e gate -------------------------------------


def test_ui_e2e_gate_classifies_through_the_fail_closed_checker() -> None:
    """Issue #895 fix round 1 (JD-B-001): the deploy gate must classify the
    changed-file set with the same fail-closed inversion as ci.yml —
    ui_changed=true by default, and false only when the checker's
    ``--ui-changed`` classifier proves every changed file is inside the
    NON-UI allowlist printed by ``--print-ui-paths``.
    """
    section = _ui_gate_section()

    assert "scripts/check_required_jobs.py --print-ui-paths" in section
    assert "scripts/check_required_jobs.py --ui-changed" in section
    assert "ui_changed=true" in section, "the gate must default to ui_changed=true (fail-closed)"
    assert "assuming UI changed (fail-closed)" in section


def test_ui_e2e_gate_push_diff_uses_event_before_with_parent_fallback() -> None:
    """JD-B-002 (deploy half): deploy runs on every push to main, so the
    revision delta against what is deployed is github.event.before..HEAD —
    not HEAD^, which only covers the last commit of a multi-commit push.
    """
    section = _ui_gate_section()

    assert "EVENT_BEFORE: ${{ github.event.before }}" in section
    assert "0000000000000000000000000000000000000000" in section
    assert "git diff --name-only" in section


def test_ui_e2e_gate_pays_the_gate_file_toll() -> None:
    """Anti-self-exemption toll (JD-A-001, deploy half): editing any of the
    gate's own source files forces ui_changed=true in deploy.yml too — the
    two workflow consumers cannot drift on this contract.
    """
    section = _ui_gate_section()

    toll_pattern = (
        "scripts/check_required_jobs.py|.github/workflows/ci.yml|.github/workflows/deploy.yml"
    )
    assert toll_pattern in section, (
        "the ui-e2e-gate step must force ui_changed=true when any gate "
        "source file changes (anti-self-exemption toll)"
    )


def test_ui_e2e_gate_check_runs_query_is_scoped_to_latest_github_actions_runs() -> None:
    """F4 (JD-B-006 + JD-A-002): the check-runs query must use filter=latest
    (one entry per check name/app, not the full history of runs) and scope
    the e2e selection to checks reported by the github-actions app, so a
    third-party check named 'e2e' cannot satisfy the gate.
    """
    section = _ui_gate_section()

    assert "check-runs?per_page=100&filter=latest" in section
    assert section.count('.app.slug == "github-actions"') >= 3, (
        "every e2e check-run selection (presence, completion, conclusion) "
        "must be scoped to the github-actions app"
    )
    # Accepted fail-closed limitation, documented where it binds.
    assert "page-1" in section or "first page" in section


def test_ui_e2e_gate_tree_mismatch_error_documents_the_recovery_path() -> None:
    """F5 (JD-A-003): the HEAD^2 tree-mismatch fail-closed error must tell
    the operator how to recover: update the branch, let ci.yml run green on
    the updated branch, then re-merge — dispatching ci.yml on the existing
    merge commit does NOT satisfy this gate.
    """
    section = _ui_gate_section()

    assert "main moved" in section
    assert "update the branch" in section
    assert "re-merge" in section
    assert "does NOT satisfy" in section
