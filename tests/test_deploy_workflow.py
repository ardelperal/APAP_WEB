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
from typing import Any

from tests import _workflow_yaml

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


def _gate_section() -> str:
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    return _job_sections(workflow)["release-e2e-gate"]


def test_release_e2e_gate_blocks_deploy_and_no_longer_reads_the_variable() -> None:
    """Issue #1082: the gate exists again, but on the previous revision's
    per-SHA verdict; the retired global variable must not come back.
    """
    workflow = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    sections = _job_sections(workflow)

    assert "release-e2e-gate" in sections
    assert RETIRED_VARIABLE not in workflow
    assert "needs: [evidence, release-e2e-gate, ui-e2e-gate]" in sections["deploy"]


def test_release_e2e_gate_evaluates_the_previous_deployed_revision() -> None:
    """Issue #1221: the gate resolves the revision ACTUALLY serving traffic.

    The old heuristic picked `[0].head_sha` from the Actions runs search
    index — a non-transactional index that already selected the
    third-most-recent revision in silence (run 37028750019 verified
    `460c56f1` while production served `9816c974`). The serving revision
    comes from the same health endpoint the deploy itself verifies against
    (`vars.APAP_DEPLOY_HEALTH_URL` → `/healthz` → `.revision`), so the gate
    can never verify a revision that is not serving production.
    """
    section = _gate_section()

    assert (
        "actions/workflows/deploy.yml/runs" not in section
    ), "the Actions runs index is not a source of truth for what is deployed (issue #1221)"
    assert "APAP_DEPLOY_HEALTH_URL" in section
    assert ".revision" in section, "the serving revision is read from the health payload"
    assert "commits/${prev_sha}/status" in section
    assert "python scripts/check_release_evidence.py --sha" in section


def test_release_e2e_gate_fails_closed_when_health_endpoint_is_unusable() -> None:
    """Issue #1221: an unusable health endpoint fails the gate, never falls
    back to the runs index and never passes in silence."""
    section = _gate_section()

    assert "::error::" in section
    assert "exit 1" in section


def test_release_e2e_gate_bootstrap_escape_is_the_unconfigured_health_url() -> None:
    """Issue #1221: the only notice-only escape is a not-configured health
    URL (first-deploy bootstrap); once configured, the gate is strict."""
    section = _gate_section()

    assert "first deploy" in section, "no previous deploy must pass explicitly"
    first_output = _gate_text_output_position(section)
    assert first_output < section.index("first deploy"), "the output is written before any early exit"


def _gate_text_output_position(section: str) -> int:
    return section.index('echo "previous_sha=${prev_sha}" >> "$GITHUB_OUTPUT"')


def test_release_e2e_gate_requires_both_release_contexts_of_the_previous_sha() -> None:
    """Issue #1131: smoke AND e2e must be valid on the previous revision, and
    the gate exposes that SHA so the record job can select the e2e range.
    """
    job = _deploy_job(_GATE_JOB)
    text = _workflow_yaml.runs_text(job)

    assert "release/smoke-production" in text
    assert "release/e2e-production" in text
    assert '--context "$context"' in text
    assert 'exit "$failed"' in text, "a refusal in either context must fail the gate"
    assert job["outputs"] == {"previous_sha": "${{ steps.gate.outputs.previous_sha }}"}
    gate_step = _workflow_yaml.find_step(job, "verdicts")
    assert gate_step["id"] == "gate"
    first_output = text.index('echo "previous_sha=${prev_sha}" >> "$GITHUB_OUTPUT"')
    assert first_output < text.index("first deploy"), "the output is written before any early exit"


def test_release_e2e_gate_fails_closed_on_api_errors() -> None:
    """Issue #1221: every unusable input fails the gate loudly: an
    unreachable health endpoint, a payload without a revision, and a failed
    verdict query."""
    section = _gate_section()

    assert "::error::" in section
    assert "exit 1" in section
    assert '!= "200"' in section, "a failed verdict query must fail the gate"
    assert "refusing to guess the serving revision" in section


def test_release_e2e_gate_has_least_privilege_pinned_actions_and_no_gh() -> None:
    section = _gate_section()

    assert "statuses: read" in section
    # Issue #1221: the gate no longer consults the Actions API at all.
    assert "actions: read" not in section
    assert "contents: read" in section
    assert ": write" not in section
    assert "secrets." not in section
    assert "timeout-minutes:" in section
    assert not re.search(r"^\s*gh\s", section, flags=re.MULTILINE)
    assert "gh api" not in re.sub(r"#.*", "", section)
    for match in re.finditer(r"^\s*(?:- )?uses:\s*(\S+)", section, flags=re.MULTILINE):
        assert re.search(r"@[0-9a-f]{40}$", match.group(1)), match.group(1)


def test_release_e2e_record_runs_after_a_successful_deploy_only() -> None:
    """The record job needs deploy and runs only when deploy succeeded, so a
    failed or skipped deploy never opens an e2e validation window.
    """
    section = _record_section()

    assert "needs: [release-e2e-gate, deploy]" in section
    assert "needs.deploy.result == 'success'" in section


def test_release_e2e_record_sets_pending_status_on_the_deployed_sha() -> None:
    section = _record_section()

    assert f'context: "{STATUS_CONTEXT}"' in section
    assert "state=pending" in section
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


# --- issue #1131: production smoke and the range-based e2e decision -----------

_GATE_JOB = "release-e2e-gate"
_SMOKE_JOB = "production-smoke"
_SMOKE_CONTEXT = "release/smoke-production"
#: GitHub rejects a commit-status description longer than this.
_DESCRIPTION_LIMIT = 140
#: success/failure of the smoke plus pending/not-required of the record job.
_DESCRIPTION_COUNT = 4
_PINNED_ACTION = re.compile(r"@[0-9a-f]{40}$")


def _deploy_job(job_id: str) -> dict[str, Any]:
    return _workflow_yaml.job(_workflow_yaml.load(DEPLOY_WORKFLOW_PATH), job_id)


def _assert_pinned_and_gh_free(job: dict[str, Any]) -> None:
    for step in _workflow_yaml.steps(job):
        if "uses" in step:
            assert _PINNED_ACTION.search(str(step["uses"])), step["uses"]
        assert not re.search(r"(^|\s)gh\s", str(step.get("run", "")), flags=re.MULTILINE)


def _description_literals(run_text: str) -> list[str]:
    """Every ``description="..."`` assignment of a run script (shell-expanded)."""
    return re.findall(r'description="([^"]+)"', run_text)


def test_production_smoke_runs_after_a_successful_deploy_on_a_hosted_runner() -> None:
    job = _deploy_job(_SMOKE_JOB)

    assert _workflow_yaml.needs(job) == ["deploy"]
    assert job["if"] == "needs.deploy.result == 'success'"
    assert job["runs-on"] == "ubuntu-24.04", "hosted runner: no deploy-host access"
    assert "timeout-minutes" in job


def test_production_smoke_has_least_privilege_and_no_secrets() -> None:
    job = _deploy_job(_SMOKE_JOB)
    text = _workflow_yaml.job_text(job)

    assert _workflow_yaml.permissions(job) == {"contents": "read", "statuses": "write"}
    assert "secrets." not in text
    assert "docker" not in text.lower()
    assert "playwright" not in text.lower()
    _assert_pinned_and_gh_free(job)


def test_production_smoke_runs_the_script_against_the_variable_derived_url() -> None:
    job = _deploy_job(_SMOKE_JOB)
    run = _workflow_yaml.find_step(job, "smoke")

    assert run["env"]["DEPLOY_HEALTH_URL"] == "${{ vars.APAP_DEPLOY_HEALTH_URL }}"
    assert (
        'python scripts/production_smoke.py --health-url "$DEPLOY_HEALTH_URL"'
        ' --revision "$GITHUB_SHA"'
    ) in run["run"]
    assert "continue-on-error" not in run, "a failed smoke must fail the job"


def test_production_smoke_always_records_its_status_on_the_deployed_sha() -> None:
    job = _deploy_job(_SMOKE_JOB)
    record = _workflow_yaml.find_step(job, "Record release/smoke-production")
    text = str(record["run"])

    assert record["if"] == "always()"
    assert record["env"]["JOB_STATUS"] == "${{ job.status }}"
    assert '"$JOB_STATUS" = "success"' in text
    assert f'context: "{_SMOKE_CONTEXT}"' in text
    assert "statuses/${GITHUB_SHA}" in text
    assert "actions/runs/${GITHUB_RUN_ID}" in text, "target_url must be this run"
    assert 'if [ "$code" != "201" ]' in text
    smoke = _workflow_yaml.steps(job).index(_workflow_yaml.find_step(job, "smoke"))
    assert smoke < _workflow_yaml.steps(job).index(record), "record runs after the smoke"


def test_commit_status_descriptions_fit_the_github_limit() -> None:
    """A description over 140 characters makes the statuses API answer 422."""
    sha8 = "12345678"
    pieces: list[str] = []
    for job_id, step_name in ((_SMOKE_JOB, "Record release"), ("release-e2e-record", "Decide")):
        step = _workflow_yaml.find_step(_deploy_job(job_id), step_name)
        pieces += _description_literals(str(step["run"]))
    assert len(pieces) == _DESCRIPTION_COUNT, pieces
    for text in pieces:
        expanded = text.replace("${GITHUB_SHA:0:8}", sha8).replace("${PREVIOUS_SHA:0:8}", sha8)
        assert len(expanded) <= _DESCRIPTION_LIMIT, expanded


def test_release_e2e_record_decides_with_the_range_selector_on_full_history() -> None:
    job = _deploy_job("release-e2e-record")
    checkout = _workflow_yaml.find_step(job, "Check out")
    decide = _workflow_yaml.find_step(job, "Decide")
    text = str(decide["run"])

    assert checkout["with"]["fetch-depth"] == 0
    assert decide["env"]["PREVIOUS_SHA"] == "${{ needs.release-e2e-gate.outputs.previous_sha }}"
    assert (
        'python scripts/check_release_e2e_required.py --base "$PREVIOUS_SHA" --head "$GITHUB_SHA"'
    ) in text


def test_release_e2e_record_maps_selector_exit_codes_fail_closed() -> None:
    text = str(_workflow_yaml.find_step(_deploy_job("release-e2e-record"), "Decide")["run"])

    assert "0) required=false" in text
    assert "10) required=true" in text
    assert "*)" in text and "cannot decide" in text, "any other exit code fails the job"
    assert 'if [ -n "$PREVIOUS_SHA" ]' in text and "first deploy" in text
    assert "state=pending" in text and "state=success" in text
    assert "not-required: no e2e-sensitive path changed since ${PREVIOUS_SHA:0:8}" in text
    assert "awaiting runbook validation: e2e-sensitive paths changed" in text


def test_release_e2e_record_keeps_least_privilege_pinned_actions_and_no_gh() -> None:
    job = _deploy_job("release-e2e-record")

    assert _workflow_yaml.permissions(job) == {"contents": "read", "statuses": "write"}
    assert "secrets." not in _workflow_yaml.job_text(job)
    _assert_pinned_and_gh_free(job)


def test_deploy_still_needs_the_gate_and_the_gate_is_read_only() -> None:
    deploy = _deploy_job("deploy")

    assert _workflow_yaml.needs(deploy) == ["evidence", "release-e2e-gate", "ui-e2e-gate"]
    assert _SMOKE_JOB not in _workflow_yaml.needs(deploy), "the smoke runs after deploy, not before"
    assert set(_workflow_yaml.permissions(_deploy_job(_GATE_JOB)).values()) == {"read"}


def test_deploy_installs_cosign_with_a_direct_pinned_download_not_the_installer() -> None:
    """Issue #1222: sigstore/cosign-installer renders its download URL with
    ``envsubst`` (gettext-base), which the fleet's pool runners do not ship —
    run 37037386528 died with exit 127 (``envsubst: command not found``).
    The job must install cosign via a direct pinned download with sha256
    verification (the actionlint pattern), self-sufficient on any runner.
    """
    deploy_job = _deploy_job("deploy")
    run_scripts = [str(step.get("run", "")) for step in _workflow_yaml.steps(deploy_job)]

    assert not any("cosign-installer" in script for script in run_scripts), (
        "the third-party installer pulls in envsubst (gettext-base)"
    )
    assert not any("envsubst" in script for script in run_scripts), (
        "envsubst must not be a deploy dependency"
    )

    install = _workflow_yaml.find_step(deploy_job, "Install Cosign")
    assert install.get("uses") is None, "cosign comes from a run step, not an action"
    env = install.get("env") or {}
    assert env.get("COSIGN_VERSION") == "v3.1.3"
    run = str(install.get("run", ""))
    assert "https://github.com/sigstore/cosign/releases/download/" in run
    assert "sha256sum --check --strict" in run, "the binary must be checksum-verified"


def test_deploy_preflight_fails_loud_naming_missing_host_tools() -> None:
    """Issue #1222: a missing host tool must fail loud naming the tool and
    the Debian package that provides it, before the job starts real work —
    never again an opaque exit 127 deep inside third-party tooling.
    """
    deploy_job = _deploy_job("deploy")
    preflight = _workflow_yaml.find_step(deploy_job, "Preflight")
    run = str(preflight.get("run", ""))

    # The preflight must gate every host tool the deploy job actually needs:
    # docker + buildx (image build/publish/promote), jq (metadata parsing),
    # curl (cosign download). cosign, python and trivy are self-provisioned
    # (downloaded in-job, composite action, container image respectively).
    for tool, package in (
        ("docker", "docker.io"),
        ("jq", "jq"),
        ("curl", "curl"),
    ):
        assert f"check {tool} {package}" in run
    assert "docker buildx version" in run, "the buildx plugin is checked separately"
    assert "docker-buildx-plugin" in run
    assert "::error::MISSING TOOL:" in run
    assert "exit 1" in run or "exit \"$missing\"" in run, "missing tool must fail the job"

    # And it must run before the first tool use (the Docker daemon check).
    names = [str(step.get("name", "")) for step in _workflow_yaml.steps(deploy_job)]
    assert names.index(str(preflight["name"])) < names.index("Check Docker daemon")
